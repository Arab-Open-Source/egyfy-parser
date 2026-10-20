"""Document storage, option validation, and page recognition."""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from indra_ocr.document import Converter
from indra_ocr.models import model_dir
from indra_ocr.pipeline import OrtOCR

from .errors import DocumentExpired, InvalidDocument, InvalidOptions, PageOutOfRange
from .markup import clean_markdown, markdown_to_html

logger = logging.getLogger(__name__)

MODES = ("auto", "ocr", "text")
TIMING_KEYS = (
    "render_ms",
    "text_ms",
    "det_ms",
    "rec_ms",
    "ocr_ms",
    "math_ms",
    "order_ms",
    "total_ms",
)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
MAX_OPEN_DOCUMENTS = 5
MAX_CACHED_PAGES = 200
MAX_PAGE_LIMIT = 500
MIN_DPI = 50.0
MAX_DPI = 600.0
_JPEG_QUALITY = 82
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return default


def _as_box(values: Any) -> list[float]:
    box = [round(float(value), 1) for value in list(values or [])[:4]]
    return box + [0.0] * (4 - len(box))


def decode_image(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise InvalidDocument("The file is neither a PDF nor a readable image.")
    return image


@dataclass(frozen=True, slots=True)
class PageOptions:
    mode: str = "auto"
    pdf_order: bool = True
    image_ocr: bool = True
    math: bool = False
    furniture: bool = False
    clean: bool = True
    dpi: float = 200.0
    max_pages: int = 20

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any] | None,
        *,
        default_dpi: float = 200.0,
        default_max_pages: int = 20,
    ) -> PageOptions:
        raw = values or {}
        mode = str(raw.get("mode") or "auto").strip().lower()
        if mode not in MODES:
            raise InvalidOptions("Reading mode must be auto, ocr, or text.")

        try:
            dpi = float(raw.get("dpi", default_dpi))
        except (TypeError, ValueError) as exc:
            raise InvalidOptions("Render DPI must be a number.") from exc
        if not math.isfinite(dpi) or not MIN_DPI <= dpi <= MAX_DPI:
            raise InvalidOptions(
                f"Render DPI must be between {MIN_DPI:.0f} and {MAX_DPI:.0f}."
            )

        raw_max_pages = raw.get("max_pages", default_max_pages)
        if raw_max_pages in (None, ""):
            raw_max_pages = default_max_pages
        try:
            max_pages = int(raw_max_pages)
        except (TypeError, ValueError) as exc:
            raise InvalidOptions("Page limit must be a whole number.") from exc
        if not 0 <= max_pages <= MAX_PAGE_LIMIT:
            raise InvalidOptions(
                f"Page limit must be between 0 and {MAX_PAGE_LIMIT} (0 means all pages)."
            )

        return cls(
            mode=mode,
            pdf_order=_as_bool(raw.get("pdf_order"), True),
            image_ocr=_as_bool(raw.get("image_ocr"), True),
            math=_as_bool(raw.get("math"), False),
            furniture=_as_bool(raw.get("furniture"), False),
            clean=_as_bool(raw.get("clean"), True),
            dpi=dpi,
            max_pages=max_pages,
        )

    def cache_key(self) -> str:
        # Presentation and page selection do not change the parsed page itself.
        parsed_fields = {
            "mode": self.mode,
            "pdf_order": self.pdf_order,
            "image_ocr": self.image_ocr,
            "math": self.math,
            "furniture": self.furniture,
            "dpi": self.dpi,
        }
        return json.dumps(parsed_fields, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "pdf_order": self.pdf_order,
            "image_ocr": self.image_ocr,
            "math": self.math,
            "furniture": self.furniture,
            "clean": self.clean,
            "dpi": self.dpi,
            "max_pages": self.max_pages,
        }


@dataclass(slots=True)
class Document:
    id: str
    name: str
    kind: str
    page_count: int
    data: bytes | None = None
    path: Path | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "pages": self.page_count,
        }


class Engine:
    """Keeps a small LRU set of documents and parsed pages."""

    def __init__(
        self,
        model_path: str | Path | None,
        threads: int,
        dpi: float,
        max_pages: int,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.threads = threads
        self.default_dpi = dpi
        self.default_max_pages = max_pages

        self._workdir = tempfile.TemporaryDirectory(prefix="egyfy-parser-")
        self._lock = threading.RLock()
        self._models: dict[tuple[bool, bool], OrtOCR] = {}
        self._documents: OrderedDict[str, Document] = OrderedDict()
        self._pages: OrderedDict[tuple[str, int, str], dict[str, Any]] = OrderedDict()

        if self.model_path is None and os.environ.get("INDRA_OCR_MODEL_DIR"):
            self.model_path = Path(os.environ["INDRA_OCR_MODEL_DIR"])

        logger.info("Preparing OCR models")
        self._get_ocr(math=False, furniture=False)

    @property
    def defaults(self) -> dict[str, Any]:
        return PageOptions(
            dpi=self.default_dpi,
            max_pages=self.default_max_pages,
        ).to_dict()

    def close(self) -> None:
        with self._lock:
            self._documents.clear()
            self._pages.clear()
            self._models.clear()
            self._workdir.cleanup()

    def parse_options(self, values: Mapping[str, Any] | None) -> PageOptions:
        return PageOptions.from_mapping(
            values,
            default_dpi=self.default_dpi,
            default_max_pages=self.default_max_pages,
        )

    def _get_ocr(self, math: bool, furniture: bool) -> OrtOCR:
        key = (math, furniture)
        with self._lock:
            model = self._models.get(key)
            if model is None:
                onnx_dir = model_dir(self.model_path, math=math)
                model = OrtOCR(
                    onnx_dir,
                    threads=self.threads,
                    rec_int8=False,
                    math=math,
                    furniture=furniture,
                )
                model(np.full((200, 200), 255, dtype=np.uint8))
                self._models[key] = model
            return model

    def _inspect_upload(self, data: bytes) -> tuple[str, int]:
        if not data:
            raise InvalidDocument("The uploaded file is empty.")

        if data[:5] == b"%PDF-":
            import pypdfium2 as pdfium

            try:
                pdf = pdfium.PdfDocument(data)
                page_count = len(pdf)
                pdf.close()
            except Exception as exc:
                raise InvalidDocument("The PDF could not be opened.") from exc
            if page_count < 1:
                raise InvalidDocument("The PDF does not contain any pages.")
            return "pdf", page_count

        decode_image(data)
        return "image", 1

    @staticmethod
    def _clean_name(name: str, kind: str) -> str:
        name = re.split(r"[\\/]", (name or "").strip())[-1][:180]
        if name:
            return name
        return "document.pdf" if kind == "pdf" else "image.png"

    def upload(self, data: bytes, name: str) -> dict[str, Any]:
        kind, page_count = self._inspect_upload(data)
        document_id = uuid.uuid4().hex[:12]
        stored_name = self._clean_name(name, kind)

        pdf_path = None
        if kind == "pdf":
            pdf_path = Path(self._workdir.name) / f"{document_id}.pdf"
            try:
                pdf_path.write_bytes(data)
            except OSError as exc:
                raise InvalidDocument("The PDF could not be stored.") from exc

        document = Document(
            id=document_id,
            name=stored_name,
            kind=kind,
            page_count=page_count,
            data=None if kind == "pdf" else data,
            path=pdf_path,
        )

        with self._lock:
            self._documents[document_id] = document
            self._documents.move_to_end(document_id)
            while len(self._documents) > MAX_OPEN_DOCUMENTS:
                self._evict_oldest_document()

        return document.to_public_dict()

    def _evict_oldest_document(self) -> None:
        _, document = self._documents.popitem(last=False)
        if document.path is not None:
            document.path.unlink(missing_ok=True)
        stale = [key for key in self._pages if key[0] == document.id]
        for key in stale:
            self._pages.pop(key, None)

    def _document(self, document_id: str) -> Document:
        document = self._documents.get(document_id)
        if document is None:
            raise DocumentExpired(
                "This document is no longer available. Upload it again."
            )
        self._documents.move_to_end(document_id)
        return document

    def read_page(
        self,
        document_id: str,
        index: int,
        options: PageOptions | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed_options = (
            options if isinstance(options, PageOptions) else self.parse_options(options)
        )
        with self._lock:
            return self._read_page_locked(document_id, index, parsed_options)

    def read_pages(
        self,
        document_id: str,
        options: PageOptions,
        only: Sequence[int] | None = None,
    ) -> tuple[Document, list[int], list[dict[str, Any]]]:
        with self._lock:
            document = self._document(document_id)

            if only is None:
                total = (
                    document.page_count
                    if options.max_pages == 0
                    else min(document.page_count, options.max_pages)
                )
                indices = list(range(total))
            else:
                indices = []
                seen: set[int] = set()
                for value in only:
                    index = int(value)
                    if 0 <= index < document.page_count and index not in seen:
                        seen.add(index)
                        indices.append(index)
                indices.sort()

            if not indices:
                raise PageOutOfRange("No valid pages were selected for export.")

            pages = [
                self._read_page_locked(document_id, index, options)
                for index in indices
            ]
            return document, indices, pages

    def _read_page_locked(
        self, document_id: str, index: int, options: PageOptions
    ) -> dict[str, Any]:
        document = self._document(document_id)
        if not 0 <= index < document.page_count:
            raise PageOutOfRange("Page number is outside the document.")

        key = (document_id, index, options.cache_key())
        cached = self._pages.get(key)
        if cached is not None:
            self._pages.move_to_end(key)
            return cached

        result = self._parse_page(document, index, options)
        self._pages[key] = result
        self._pages.move_to_end(key)
        while len(self._pages) > MAX_CACHED_PAGES:
            self._pages.popitem(last=False)
        return result

    def _parse_page(
        self, document: Document, index: int, options: PageOptions
    ) -> dict[str, Any]:
        ocr = self._get_ocr(options.math, options.furniture)
        converter = Converter(
            ocr,
            dpi=options.dpi,
            mode=options.mode,
            pdf_order=options.pdf_order,
            image_ocr=options.image_ocr,
        )

        render_ms = 0.0
        if document.kind == "pdf":
            if document.path is None:
                raise InvalidDocument("The PDF is no longer available on disk.")

            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(document.path))
            try:
                pdf_page = pdf[index]
                started = time.perf_counter()
                bitmap = pdf_page.render(
                    scale=converter.page_scale(pdf_page), grayscale=True
                )
                gray = bitmap.to_numpy()
                render_ms = 1000 * (time.perf_counter() - started)
                page = converter.pdf_page(str(document.path), pdf, index)
            finally:
                pdf.close()
            if gray.ndim == 3:
                gray = gray[..., 0]
            gray = np.ascontiguousarray(gray)
        else:
            if document.data is None:
                raise InvalidDocument("The image data is no longer available.")
            gray = decode_image(document.data)
            page = ocr(gray)

        # Line boxes refer to the upright page, so mirror the model's rotation
        # in the preview before drawing them.
        if page.rotation:
            gray = np.ascontiguousarray(np.rot90(gray, -(page.rotation // 90)))

        page_height, page_width = gray.shape
        preview_scale = min(1.0, MAX_IMAGE_SIDE / max(page_height, page_width))
        preview = (
            cv2.resize(
                gray,
                None,
                fx=preview_scale,
                fy=preview_scale,
                interpolation=cv2.INTER_AREA,
            )
            if preview_scale < 1
            else gray
        )
        encoded, jpeg = cv2.imencode(
            ".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        )
        if not encoded:
            raise RuntimeError("The page preview could not be encoded.")

        timings = {key: 0.0 for key in TIMING_KEYS}
        timings["render_ms"] = round(render_ms, 1)
        for key, value in (page.timings or {}).items():
            timings[key] = round(float(value), 1)

        markdown = page.markdown if page.markdown is not None else page.text or ""
        cleaned = clean_markdown(markdown)
        preview_html = markdown_to_html(markdown)
        preview_clean_html = (
            preview_html if cleaned == markdown else markdown_to_html(cleaned)
        )

        return {
            "page": index + 1,
            "w": preview.shape[1],
            "h": preview.shape[0],
            "width": page_width,
            "height": page_height,
            "scale": round(preview_scale, 6),
            "img": "data:image/jpeg;base64,"
            + base64.b64encode(jpeg.tobytes()).decode("ascii"),
            "lines": [
                {
                    "box": _as_box(line.box),
                    "text": line.text,
                    "conf": round(float(line.conf), 4),
                }
                for line in page.lines
            ],
            "blocks": [
                {
                    "label": block.get("label", ""),
                    "box": _as_box(block.get("bbox")),
                    "text": block.get("text", ""),
                }
                for block in page.blocks
            ],
            "markdown": markdown,
            "clean_markdown": cleaned,
            "preview": preview_html,
            "preview_clean": preview_clean_html,
            "text": page.text or "",
            "source": page.source,
            "note": page.note or "",
            "rotation": int(page.rotation or 0),
            "skew": float(page.skew or 0.0),
            "timings": timings,
        }

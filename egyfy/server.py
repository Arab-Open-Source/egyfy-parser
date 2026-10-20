"""HTTP server and request routing for EgyFy Parser."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from indra_ocr import __version__ as ENGINE_VERSION

from . import APP_NAME, APP_VERSION
from .engine import (
    MAX_PAGE_LIMIT,
    MAX_UPLOAD_BYTES,
    MODES,
    Engine,
)
from .errors import ParserError, RequestTooLarge
from .exporters import EXPORT_FORMATS, ExportResult, export_document

logger = logging.getLogger(__name__)


def content_disposition(filename: str) -> str:
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "export"
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def create_handler(engine: Engine, static_dir: Path):
    static_root = static_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = f"EgyFyParser/{APP_VERSION}"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("%s %s", self.address_string(), fmt % args)

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str = "application/json; charset=utf-8",
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body)

        def _static(self, relative_path: str) -> None:
            try:
                target = (static_root / relative_path).resolve()
                if not target.is_relative_to(static_root) or not target.is_file():
                    raise FileNotFoundError(relative_path)
                content_type = (
                    mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                )
                if content_type.startswith("text/") or content_type in (
                    "application/javascript",
                    "application/json",
                    "image/svg+xml",
                ):
                    content_type += "; charset=utf-8"
                self._send(200, target.read_bytes(), content_type)
            except (FileNotFoundError, IsADirectoryError, OSError):
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def _read_body(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Invalid Content-Length header.") from exc
            if length < 0:
                raise ValueError("Invalid Content-Length header.")
            if length > MAX_UPLOAD_BYTES:
                raise RequestTooLarge(
                    "The file is larger than the 200 MB upload limit."
                )
            return self.rfile.read(length) if length else b""

        @staticmethod
        def _read_json(body: bytes) -> dict[str, Any]:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("The request body is not valid JSON.") from exc
            if not isinstance(payload, dict):
                raise ValueError("The JSON body must be an object.")
            return payload

        @staticmethod
        def _require_id(payload: dict[str, Any]) -> str:
            document_id = payload.get("id")
            if not isinstance(document_id, str) or not document_id:
                raise ValueError("A document id is required.")
            return document_id

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/") :])
            elif path == "/api/info":
                self._json(
                    200,
                    {
                        "app": APP_NAME,
                        "version": APP_VERSION,
                        "engine_version": ENGINE_VERSION,
                        "defaults": engine.defaults,
                        "modes": list(MODES),
                        "formats": list(EXPORT_FORMATS),
                        "max_upload": MAX_UPLOAD_BYTES,
                        "max_page_limit": MAX_PAGE_LIMIT,
                    },
                )
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def _upload(self, body: bytes) -> None:
            query = parse_qs(urlparse(self.path).query)
            name = (query.get("name") or ["document"])[0]
            self._json(200, engine.upload(body, name))

        def _page(self, body: bytes) -> None:
            payload = self._read_json(body)
            document_id = self._require_id(payload)
            try:
                index = int(payload.get("n"))
            except (TypeError, ValueError) as exc:
                raise ValueError("A page number is required.") from exc
            options = engine.parse_options(payload.get("opts") or {})
            self._json(200, engine.read_page(document_id, index, options))

        def _export(self, body: bytes) -> None:
            payload = self._read_json(body)
            document_id = self._require_id(payload)
            export_format = str(payload.get("format") or "md")
            options = engine.parse_options(payload.get("opts") or {})

            pages = payload.get("pages")
            only: list[int] | None = None
            if pages is not None:
                if not isinstance(pages, list):
                    raise ValueError("The pages field must be a list.")
                if len(pages) > MAX_PAGE_LIMIT:
                    raise ValueError("Too many pages were requested.")
                try:
                    only = [int(value) for value in pages]
                except (TypeError, ValueError) as exc:
                    raise ValueError("Page numbers must be integers.") from exc

            result: ExportResult = export_document(
                engine, document_id, export_format, options, only
            )
            self._send(
                200,
                result.data,
                result.content_type,
                {"Content-Disposition": content_disposition(result.filename)},
            )

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = self._read_body()
                if path == "/api/upload":
                    self._upload(body)
                elif path == "/api/page":
                    self._page(body)
                elif path == "/api/export":
                    self._export(body)
                else:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
            except RequestTooLarge as exc:
                self._json(413, {"error": str(exc)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except ParserError as exc:
                self._json(400, {"error": str(exc)})
            except Exception:
                logger.exception("Unhandled request error")
                self._json(
                    500,
                    {"error": "The server could not complete the request."},
                )

    return Handler

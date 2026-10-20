"""Export the parsed pages in the formats offered by the web interface."""

from __future__ import annotations

import csv
import html
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from string import Template
from typing import Any, Sequence

from indra_ocr import __version__ as ENGINE_VERSION

from .engine import Document, Engine, PageOptions
from .markup import (
    BLOCK_LABELS,
    clean_line,
    clean_markdown,
    extract_tables,
    markdown_to_html,
)

EXPORT_FORMATS = ("md", "txt", "csv", "json", "html", "tables", "zip")

LINE_CSV_HEADER = ["Page", "Line", "Text", "Confidence", "x0", "y0", "x1", "y1"]
BLOCK_CSV_HEADER = ["Page", "Type", "Text", "x0", "y0", "x1", "y1"]

_TABLE_PACKAGE_README = Template(
    """EgyFy Parser — tables package
============================

lines.csv    Every recognized line: page, line number, text,
             confidence, and bounding box.
blocks.csv   Layout blocks: page, type, text, and bounding box.
tables/      Each detected table as its own CSV file ($count total).

Coordinates are in pixels of the rendered page before the on-screen preview
was downscaled. CSV files use UTF-8 with a BOM so they open directly in
Excel and Google Sheets.
"""
)

_EXPORT_PACKAGE_README = Template(
    """EgyFy Parser — export package
============================

$name.md       Markdown with page separators.
$name.txt      Plain text.
$name.csv      Recognized lines and their bounding boxes.
$name.json     Complete data, including layout blocks and timings.
$name.html     Standalone, print-ready HTML.
tables/        Detected tables as CSV files ($count total).

This file was generated locally by EgyFy Parser using Indra OCR $engine.
"""
)

_HTML_TEMPLATE = Template(
    """<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f6f6f3;color:#1a1c18;font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.document{max-width:820px;margin:0 auto;padding:56px 28px 64px}
header{border-bottom:1px solid #dcdcd3;padding-bottom:24px}
.eyebrow{margin:0 0 8px;font:600 10.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:#7d8278}
h1{margin:0 0 18px;font-size:30px;line-height:1.25;letter-spacing:-.02em;font-weight:650}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin:0;font-size:12px;color:#6a6f66}
.meta div{display:flex;gap:6px}
.meta dt{color:#8b9086}
.meta dd{margin:0;color:#3f443d}
section.page{padding:30px 0 18px;border-bottom:1px solid #e3e3db}
section.page:last-of-type{border-bottom:0}
.page-label{margin:0 0 16px;font:600 10px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:#8b9086}
.page-body{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;font-size:16px;line-height:1.75}
.page-body h1,.page-body h2,.page-body h3,.page-body h4,.page-body h5,.page-body h6{margin:1.4em 0 .5em;line-height:1.35;font-family:inherit;font-weight:650}
.page-body h2{font-size:22px}
.page-body h3{font-size:18px}
.page-body h4,.page-body h5,.page-body h6{font-size:16px}
.page-body p{margin:.7em 0}
.page-body ul,.page-body ol{padding-inline-start:1.5em;margin:.7em 0}
.page-body li{margin:.25em 0}
.page-body table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13.5px}
.page-body td,.page-body th{border:1px solid #d3d6cc;padding:6px 10px;vertical-align:top;text-align:start}
.page-body th{background:#efefe9;font-weight:600}
.page-body code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:#ecece5;border-radius:4px;padding:1px 5px}
.page-body code.math{color:#1f6b4f;direction:ltr;unicode-bidi:embed;display:inline-block}
.page-body blockquote{margin:1em 0;padding:.4em 1em;border-inline-start:3px solid #1f6b4f;color:#4f554c}
.page-body hr{border:0;border-top:1px solid #e3e3db;margin:1.6em 0}
.page-body a{color:#1f6b4f}
.page-body img{max-width:100%;height:auto}
.page-error{margin:0;padding:12px 14px;border:1px solid #f3c7c1;border-radius:6px;background:#fef3f2;color:#9f2c22;font-family:inherit;font-size:14px}
footer{margin-top:36px;padding-top:16px;border-top:1px solid #e3e3db;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:11.5px;color:#8b9086}
@media print{body{background:#fff}.document{padding:0;max-width:none}section.page{break-inside:auto}.page-label{color:#555}}
</style>
</head>
<body>
<main class="document">
<header>
<p class="eyebrow">EgyFy Parser export</p>
<h1>$title</h1>
<dl class="meta">
<div><dt>Pages</dt><dd>$pages</dd></div>
<div><dt>Exported</dt><dd>$date</dd></div>
<div><dt>Engine</dt><dd>Indra OCR $engine</dd></div>
</dl>
</header>
$body
<footer><span>Processed locally with EgyFy Parser</span><span>$source_name</span></footer>
</main>
</body>
</html>
"""
)


@dataclass(frozen=True, slots=True)
class ExportResult:
    filename: str
    content_type: str
    data: bytes


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[\\/:*?\"<>|]+", "-", Path(name).stem).strip(" .-")
    return stem or "document"


def _page_suffix(indices: Sequence[int]) -> str:
    return f"-p{indices[0] + 1}" if len(indices) == 1 else ""


def _box_values(box: Any) -> list[float]:
    values = [round(float(value), 1) for value in list(box or [])[:4]]
    return values + [0.0] * (4 - len(values))


def _csv_bytes(rows: Sequence[Sequence[Any]]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _line_rows(
    indices: Sequence[int], pages: Sequence[dict[str, Any]], clean: bool
) -> list[list[Any]]:
    rows: list[list[Any]] = [LINE_CSV_HEADER]
    for index, page in zip(indices, pages):
        for number, line in enumerate(page["lines"], 1):
            text = line["text"]
            if clean:
                cleaned = clean_line(text)
                if cleaned is None:
                    continue
                text = cleaned
            rows.append(
                [
                    index + 1,
                    number,
                    text,
                    line.get("conf", ""),
                    *_box_values(line.get("box")),
                ]
            )
    return rows


def _block_rows(
    indices: Sequence[int], pages: Sequence[dict[str, Any]], clean: bool
) -> list[list[Any]]:
    rows: list[list[Any]] = [BLOCK_CSV_HEADER]
    for index, page in zip(indices, pages):
        for block in page["blocks"]:
            text = block.get("text", "")
            if clean:
                kept = [
                    cleaned
                    for line in text.split("\n")
                    if (cleaned := clean_line(line)) is not None
                ]
                text = "\n".join(kept)
            label = BLOCK_LABELS.get(block.get("label", ""), block.get("label", ""))
            rows.append(
                [
                    index + 1,
                    label,
                    text,
                    *_box_values(block.get("box")),
                ]
            )
    return rows


def _table_files(
    indices: Sequence[int], pages: Sequence[dict[str, Any]], clean: bool
) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for index, page in zip(indices, pages):
        tables = extract_tables(page.get("markdown") or "", clean)
        for number, table in enumerate(tables, 1):
            name = f"tables/table-p{index + 1}-{number}.csv"
            files.append((name, _csv_bytes(table)))
    return files


def _markdown_body(
    indices: Sequence[int], pages: Sequence[dict[str, Any]], options: PageOptions
) -> str:
    chunks = []
    for index, page in zip(indices, pages):
        if page["source"] == "error":
            markdown = f"> This page could not be read: {page['note']}"
        else:
            markdown = (
                page["clean_markdown"] if options.clean else page["markdown"]
            )
        chunks.append(f"<!-- page {index + 1} -->\n{markdown}")
    return "\n\n".join(chunks) + "\n"


def _text_body(
    pages: Sequence[dict[str, Any]], options: PageOptions
) -> str:
    chunks = []
    for page in pages:
        text = page["text"]
        if page["source"] == "error":
            text = f"[This page could not be read: {page['note']}]"
        elif options.clean:
            text = clean_markdown(text)
        chunks.append(text)
    return "\n\n".join(chunks) + "\n"


def _json_body(
    document: Document,
    indices: Sequence[int],
    pages: Sequence[dict[str, Any]],
    options: PageOptions,
) -> bytes:
    payload = {
        "app": "egyfy-parser",
        "engine": f"indra-ocr {ENGINE_VERSION}",
        "file": document.name,
        "exported": datetime.now().astimezone().isoformat(timespec="seconds"),
        "options": options.to_dict(),
        "pages": [
            {
                "page": index + 1,
                "width": page["width"],
                "height": page["height"],
                "source": page["source"],
                "rotation": page["rotation"],
                "skew": page["skew"],
                "note": page["note"],
                "lines": page["lines"],
                "blocks": page["blocks"],
                "markdown": page["markdown"],
                "text": page["text"],
                "timings": page["timings"],
            }
            for index, page in zip(indices, pages)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _html_body(
    document: Document,
    indices: Sequence[int],
    pages: Sequence[dict[str, Any]],
    options: PageOptions,
) -> bytes:
    sections = []
    for index, page in zip(indices, pages):
        if page["source"] == "error":
            inner = (
                '<p class="page-error" dir="auto">This page could not be read: '
                f'{html.escape(page["note"])}</p>'
            )
        else:
            markdown = (
                page["clean_markdown"] if options.clean else page["markdown"]
            )
            inner = markdown_to_html(markdown)
        sections.append(
            f'<section class="page"><p class="page-label">Page {index + 1}</p>'
            f'<div class="page-body">{inner}</div></section>'
        )

    title = html.escape(_safe_stem(document.name))
    body = _HTML_TEMPLATE.substitute(
        title=title,
        pages=len(pages),
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        engine=ENGINE_VERSION,
        body="\n".join(sections),
        source_name=html.escape(document.name),
    )
    return body.encode("utf-8")


def _tables_package(
    indices: Sequence[int], pages: Sequence[dict[str, Any]], options: PageOptions
) -> bytes:
    buffer = BytesIO()
    table_files = _table_files(indices, pages, options.clean)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "lines.csv", _csv_bytes(_line_rows(indices, pages, options.clean))
        )
        archive.writestr(
            "blocks.csv", _csv_bytes(_block_rows(indices, pages, options.clean))
        )
        for name, content in table_files:
            archive.writestr(name, content)
        archive.writestr(
            "README.txt",
            _TABLE_PACKAGE_README.substitute(count=len(table_files)).encode("utf-8"),
        )
    return buffer.getvalue()


def _complete_package(
    document: Document,
    indices: Sequence[int],
    pages: Sequence[dict[str, Any]],
    options: PageOptions,
) -> bytes:
    stem = _safe_stem(document.name)
    table_files = _table_files(indices, pages, options.clean)
    files = {
        f"{stem}.md": _markdown_body(indices, pages, options).encode("utf-8"),
        f"{stem}.txt": _text_body(pages, options).encode("utf-8"),
        f"{stem}.csv": _csv_bytes(_line_rows(indices, pages, options.clean)),
        f"{stem}.json": _json_body(document, indices, pages, options),
        f"{stem}.html": _html_body(document, indices, pages, options),
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        for name, content in table_files:
            archive.writestr(name, content)
        archive.writestr(
            "README.txt",
            _EXPORT_PACKAGE_README.substitute(
                name=stem,
                count=len(table_files),
                engine=ENGINE_VERSION,
            ).encode("utf-8"),
        )
    return buffer.getvalue()


def export_document(
    engine: Engine,
    document_id: str,
    export_format: str,
    options: PageOptions,
    only: Sequence[int] | None = None,
) -> ExportResult:
    export_format = export_format.strip().lower()
    if export_format not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {export_format}")

    document, indices, pages = engine.read_pages(document_id, options, only)
    stem = _safe_stem(document.name)
    suffix = _page_suffix(indices) if only is not None else ""

    if export_format == "md":
        return ExportResult(
            f"{stem}{suffix}.md",
            "text/markdown; charset=utf-8",
            _markdown_body(indices, pages, options).encode("utf-8"),
        )
    if export_format == "txt":
        return ExportResult(
            f"{stem}{suffix}.txt",
            "text/plain; charset=utf-8",
            _text_body(pages, options).encode("utf-8"),
        )
    if export_format == "csv":
        return ExportResult(
            f"{stem}{suffix}.csv",
            "text/csv; charset=utf-8",
            _csv_bytes(_line_rows(indices, pages, options.clean)),
        )
    if export_format == "json":
        return ExportResult(
            f"{stem}{suffix}.json",
            "application/json; charset=utf-8",
            _json_body(document, indices, pages, options),
        )
    if export_format == "html":
        return ExportResult(
            f"{stem}{suffix}.html",
            "text/html; charset=utf-8",
            _html_body(document, indices, pages, options),
        )
    if export_format == "tables":
        return ExportResult(
            f"{stem}{suffix}-tables.zip",
            "application/zip",
            _tables_package(indices, pages, options),
        )
    return ExportResult(
        f"{stem}{suffix}.zip",
        "application/zip",
        _complete_package(document, indices, pages, options),
    )

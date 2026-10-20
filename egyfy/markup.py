"""Cleanup and rendering for the Markdown produced by the OCR model."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

BLOCK_LABELS = {
    "Text": "Text",
    "Section-Header": "Section header",
    "Page-Header": "Page header",
    "Page-Footer": "Page footer",
    "List-Group": "List",
    "Table": "Table",
    "Caption": "Caption",
    "Footnote": "Footnote",
    "Table-Of-Contents": "Contents",
    "Form": "Form",
}

_MARKER_LABELS = (
    r"Page-Header|Page-Footer|Section-Header|List-Group|Table-Of-Contents|"
    r"Caption|Footnote|Form|Text|Table"
)
_MARKER_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s*)?\|?\s*(?:[Il|]\s+)?(?:{_MARKER_LABELS})\s*$"
)
_CELL_MARKER_RE = re.compile(
    rf"^\s*\|?\s*(?:[Il|]\s+)?(?:{_MARKER_LABELS})\s*$"
)
_LONE_PIPE_RE = re.compile(r"^(\s*)\|((?![^\n]*\|).*)$")
_CELL_LINE_RE = re.compile(
    r"(<(?:td|th)\b[^>]*>)([\s\S]*?)(</(?:td|th)>)", re.IGNORECASE
)

_RAW_TAG_RE = re.compile(r"^\s*</?(?:table|thead|tbody|tr|td|th)\b", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[-*•▪◦]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])\s+(.*)$"
)
_HORIZONTAL_RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")


def _strip_cell_pipes(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("|"):
        text = text[1:].lstrip()
    if text.endswith("|"):
        text = text[:-1].rstrip()
    return text


def _strip_line_pipes(line: str) -> str:
    text = line.strip()
    if text.startswith("|") and text.endswith("|") and text.count("|") == 2:
        return text[1:-1].strip()
    match = _LONE_PIPE_RE.match(line)
    if not match:
        return line
    return match.group(1) + match.group(2).lstrip()


def _clean_cell_line(match: re.Match[str]) -> str:
    return match.group(1) + _strip_cell_pipes(match.group(2)) + match.group(3)


def clean_line(line: str) -> str | None:
    """Remove a layout marker or a table-cell pipe from one line.

    Returns None when the line only carries a model layout label.
    """
    text = _strip_line_pipes(line)
    if _MARKER_RE.match(text):
        return None
    if "<td" in text or "<th" in text:
        text = _CELL_LINE_RE.sub(_clean_cell_line, text)
    return text


def clean_markdown(markdown: str) -> str:
    """Drop layout-marker lines, strip boundary pipes, and collapse blank runs."""
    lines = []
    for line in (markdown or "").split("\n"):
        cleaned = clean_line(line)
        if cleaned is not None:
            lines.append(cleaned)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "col",
        "colgroup",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)
_VOID_TAGS = frozenset({"br", "col", "hr"})
_SUPPRESSED_TAGS = frozenset(
    {
        "embed",
        "form",
        "iframe",
        "math",
        "noscript",
        "object",
        "script",
        "style",
        "svg",
        "template",
    }
)
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "code": {"class"},
    "col": {"span"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
}
_COMMON_ATTRS = frozenset({"class", "dir"})
_NUMERIC_ATTRS = frozenset({"colspan", "rowspan", "span"})
_SAFE_URL_RE = re.compile(r"^(?:https?:|mailto:)", re.IGNORECASE)


class _HTMLSanitizer(HTMLParser):
    """Rebuild a fragment using a small allowlist of document tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SUPPRESSED_TAGS:
            self._suppressed += 1
            return
        if self._suppressed or tag not in _ALLOWED_TAGS:
            return

        allowed = _ALLOWED_ATTRS.get(tag, frozenset()) | _COMMON_ATTRS
        rendered = [f"<{tag}"]
        for name, value in attrs:
            if value is None or name not in allowed:
                continue
            if name in _NUMERIC_ATTRS and not value.isdigit():
                continue
            if name == "href" and not _SAFE_URL_RE.match(value.strip()):
                continue
            rendered.append(f' {name}="{html.escape(value, quote=True)}"')
        rendered.append(">")
        self.parts.append("".join(rendered))

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _SUPPRESSED_TAGS or self._suppressed:
            return
        self.handle_starttag(tag, attrs)
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SUPPRESSED_TAGS:
            self._suppressed = max(0, self._suppressed - 1)
        elif not self._suppressed and tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._suppressed:
            self.parts.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        return


def _sanitize_html(fragment: str) -> str:
    parser = _HTMLSanitizer()
    try:
        parser.feed(fragment)
        parser.close()
    except Exception:
        return html.escape(fragment)
    return "".join(parser.parts)


def _inline_markdown(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\$\$([^$]+)\$\$", r'<code class="math">\1</code>', text)
    text = re.sub(r"\$([^$\n]+)\$", r'<code class="math">\1</code>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?:[^)\s]+)\)", r'<a href="\2">\1</a>', text
    )
    return text


def markdown_to_html(markdown: str) -> str:
    """Render the small Markdown subset emitted by Indra for the preview panes."""
    output: list[str] = []
    paragraph: list[str] = []
    active_list: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            output.append(
                '<p dir="auto">' + _inline_markdown(" ".join(paragraph)) + "</p>"
            )
            paragraph.clear()

    def flush_list() -> None:
        nonlocal active_list
        if active_list:
            output.append(f"</{active_list}>")
            active_list = None

    for raw_line in (markdown or "").split("\n"):
        line = raw_line.rstrip()

        if _RAW_TAG_RE.match(line):
            flush_paragraph()
            flush_list()
            line = re.sub(
                r"<(td|th)\b", r'<\1 dir="auto"', line, flags=re.IGNORECASE
            )
            output.append(line)
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = min(len(heading.group(1)), 6)
            output.append(
                f'<h{level} dir="auto">{_inline_markdown(heading.group(2))}</h{level}>'
            )
            continue

        if _HORIZONTAL_RULE_RE.match(line):
            flush_paragraph()
            flush_list()
            output.append("<hr>")
            continue

        item = _LIST_ITEM_RE.match(line)
        if item:
            flush_paragraph()
            if active_list != "ul":
                flush_list()
                output.append("<ul>")
                active_list = "ul"
            output.append(f'<li dir="auto">{_inline_markdown(item.group(1))}</li>')
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            continue

        paragraph.append(line.strip())

    flush_paragraph()
    flush_list()
    return _sanitize_html("\n".join(output))


class _TableExtractor(HTMLParser):
    """Collect every HTML table as a list of rows and string cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self.tables.append([])
            self._depth += 1
            return
        if not self._depth:
            return
        if tag == "tr":
            self._row = []
            self.tables[-1].append(self._row)
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._depth:
                self._depth -= 1
            return
        if not self._depth:
            return
        if tag in ("td", "th") and self._cell is not None:
            if self._row is None:
                self._row = []
                self.tables[-1].append(self._row)
            self._row.append("".join(self._cell).strip())
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def extract_tables(markdown: str, clean: bool = False) -> list[list[list[str]]]:
    """Return all non-empty tables in the Markdown.

    With ``clean`` enabled, cell pipes and layout-marker cells are removed and
    fully empty rows are discarded.
    """
    parser = _TableExtractor()
    try:
        parser.feed(markdown or "")
    except Exception:  # HTMLParser can raise on severely malformed model output.
        pass

    tables: list[list[list[str]]] = []
    for table in parser.tables:
        rows: list[list[str]] = []
        for row in table:
            cells = [
                _strip_cell_pipes(cell) if clean else cell.strip() for cell in row
            ]
            if clean:
                cells = ["" if _CELL_MARKER_RE.match(cell) else cell for cell in cells]
                if not any(cells):
                    continue
            rows.append(cells)
        if rows and any(any(cell for cell in row) for row in rows):
            tables.append(rows)
    return tables


__all__ = [
    "BLOCK_LABELS",
    "clean_line",
    "clean_markdown",
    "extract_tables",
    "markdown_to_html",
]

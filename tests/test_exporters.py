import json
import unittest
import zipfile
from io import BytesIO

from egyfy.engine import Document, PageOptions
from egyfy.exporters import export_document


def make_page(number=1):
    return {
        "page": number,
        "w": 800,
        "h": 1000,
        "width": 800,
        "height": 1000,
        "scale": 1.0,
        "img": "data:image/jpeg;base64,",
        "lines": [
            {"box": [10.0, 20.0, 100.0, 40.0], "text": "Hello", "conf": 0.99}
        ],
        "blocks": [
            {
                "label": "Text",
                "box": [10.0, 20.0, 100.0, 40.0],
                "text": "Hello",
            }
        ],
        "markdown": (
            "Hello\n\n<table><tr><td>| A |</td><td>1</td></tr></table>"
        ),
        "clean_markdown": "Hello",
        "preview": "<p>Hello</p>",
        "preview_clean": "<p>Hello</p>",
        "text": "Hello",
        "source": "text",
        "note": "",
        "rotation": 0,
        "skew": 0.0,
        "timings": {"text_ms": 1.0, "total_ms": 2.0},
    }


class FakeEngine:
    def __init__(self, document, pages):
        self.document = document
        self.pages = pages

    def read_pages(self, document_id, options, only=None):
        indices = list(range(len(self.pages))) if only is None else list(only)
        return self.document, indices, [self.pages[index] for index in indices]


def make_engine(name="report.pdf", page_count=1):
    document = Document(
        id="doc-1",
        name=name,
        kind="pdf",
        page_count=page_count,
    )
    return FakeEngine(document, [make_page(index + 1) for index in range(page_count)])


class ExportNamingTests(unittest.TestCase):
    def test_full_document_has_no_page_suffix(self):
        result = export_document(
            make_engine(page_count=2), "doc-1", "md", PageOptions()
        )
        self.assertEqual(result.filename, "report.md")

    def test_single_page_export_is_labelled(self):
        engine = make_engine(page_count=2)
        first = export_document(engine, "doc-1", "md", PageOptions(), [0])
        second = export_document(engine, "doc-1", "json", PageOptions(), [1])
        self.assertEqual(first.filename, "report-p1.md")
        self.assertEqual(second.filename, "report-p2.json")

    def test_unsafe_characters_are_replaced(self):
        engine = make_engine(name="Q3: report?.pdf")
        result = export_document(engine, "doc-1", "txt", PageOptions())
        self.assertEqual(result.filename, "Q3- report.txt")

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            export_document(make_engine(), "doc-1", "docx", PageOptions())


class ExportContentTests(unittest.TestCase):
    def test_markdown_includes_page_separator(self):
        result = export_document(
            make_engine(page_count=2), "doc-1", "md", PageOptions()
        )
        body = result.data.decode("utf-8")
        self.assertIn("<!-- page 1 -->", body)
        self.assertIn("<!-- page 2 -->", body)
        self.assertNotIn("Page-Header", body)

    def test_clean_option_controls_markdown_output(self):
        engine = make_engine()
        engine.pages[0]["markdown"] = "| Page-Header\nHello"
        engine.pages[0]["clean_markdown"] = "Hello"

        raw = export_document(engine, "doc-1", "md", PageOptions(clean=False))
        clean = export_document(engine, "doc-1", "md", PageOptions(clean=True))

        self.assertIn("Page-Header", raw.data.decode("utf-8"))
        self.assertNotIn("Page-Header", clean.data.decode("utf-8"))

    def test_csv_is_excel_friendly(self):
        result = export_document(make_engine(), "doc-1", "csv", PageOptions())
        self.assertTrue(result.data.startswith(b"\xef\xbb\xbf"))
        rows = result.data.decode("utf-8-sig").splitlines()
        self.assertEqual(rows[0], "Page,Line,Text,Confidence,x0,y0,x1,y1")
        self.assertIn("1,1,Hello,0.99,10.0,20.0,100.0,40.0", rows[1])

    def test_json_includes_options_and_pages(self):
        payload = json.loads(
            export_document(make_engine(), "doc-1", "json", PageOptions()).data
        )
        self.assertEqual(payload["file"], "report.pdf")
        self.assertEqual(payload["options"]["mode"], "auto")
        self.assertEqual(len(payload["pages"]), 1)
        self.assertEqual(payload["pages"][0]["lines"][0]["text"], "Hello")

    def test_html_escapes_the_document_name(self):
        engine = make_engine(name="Q3 & Q4.pdf")
        body = export_document(engine, "doc-1", "html", PageOptions()).data.decode()
        self.assertIn("<title>Q3 &amp; Q4</title>", body)
        self.assertIn('class="page-body"', body)

    def test_complete_package_contains_every_format(self):
        result = export_document(make_engine(), "doc-1", "zip", PageOptions())
        with zipfile.ZipFile(BytesIO(result.data)) as archive:
            names = set(archive.namelist())
        self.assertTrue(
            {"report.md", "report.txt", "report.csv", "report.json", "report.html"}
            <= names
        )
        self.assertIn("tables/table-p1-1.csv", names)

    def test_tables_package_contains_lines_blocks_and_tables(self):
        result = export_document(make_engine(), "doc-1", "tables", PageOptions())
        self.assertTrue(result.filename.endswith("-tables.zip"))
        with zipfile.ZipFile(BytesIO(result.data)) as archive:
            names = set(archive.namelist())
        self.assertTrue(
            {"lines.csv", "blocks.csv", "tables/table-p1-1.csv"} <= names
        )


if __name__ == "__main__":
    unittest.main()

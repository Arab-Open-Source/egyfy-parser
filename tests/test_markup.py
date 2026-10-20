import unittest

from egyfy.markup import (
    clean_line,
    clean_markdown,
    extract_tables,
    markdown_to_html,
)


class CleanMarkdownTests(unittest.TestCase):
    def test_layout_markers_are_removed(self):
        source = "| Page-Header\n\nSection-Header\n| A paragraph\n|Text\n"
        self.assertEqual(clean_markdown(source), "A paragraph")

    def test_blank_runs_are_collapsed(self):
        source = "First\n\n\n\nSecond\n\n\nThird"
        self.assertEqual(clean_markdown(source), "First\n\nSecond\n\nThird")

    def test_pipe_wrapped_lines_keep_their_text(self):
        self.assertEqual(clean_line("| value |"), "value")
        self.assertEqual(clean_line("| value"), "value")

    def test_cell_boundary_pipes_are_removed(self):
        self.assertEqual(clean_line("<td>| value |</td>"), "<td>value</td>")

    def test_marker_line_returns_none(self):
        self.assertIsNone(clean_line("Page-Footer"))
        self.assertIsNone(clean_line("## Section-Header"))

    def test_ordinary_table_pipes_are_preserved(self):
        line = "| a | b |"
        self.assertEqual(clean_markdown(line), line)


class TableExtractionTests(unittest.TestCase):
    def test_tables_are_collected(self):
        markdown = (
            "<table><tr><th>Name</th><th>Value</th></tr>"
            "<tr><td>A</td><td>1</td></tr></table>"
        )
        self.assertEqual(
            extract_tables(markdown),
            [[["Name", "Value"], ["A", "1"]]],
        )

    def test_clean_mode_drops_markers_and_empty_rows(self):
        markdown = (
            "<table><tr><td>| Name |</td><td>Table</td></tr>"
            "<tr><td></td><td></td></tr></table>"
        )
        self.assertEqual(extract_tables(markdown, clean=True), [[["Name", ""]]])

    def test_empty_tables_are_ignored(self):
        self.assertEqual(extract_tables("<table><tr><td></td></tr></table>"), [])


class MarkdownRenderingTests(unittest.TestCase):
    def test_headings_paragraphs_and_lists(self):
        html = markdown_to_html("# Title\n\nText\n\n- one\n- two")
        self.assertIn("<h1 dir=\"auto\">Title</h1>", html)
        self.assertIn("<p dir=\"auto\">Text</p>", html)
        self.assertEqual(html.count("<li dir=\"auto\">"), 2)

    def test_inline_formatting_and_math(self):
        html = markdown_to_html("**bold** and $x + 1$ and `code`")
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn('<code class="math">x + 1</code>', html)
        self.assertIn("<code>code</code>", html)

    def test_model_text_is_escaped(self):
        html = markdown_to_html("A < B & C")
        self.assertIn("A &lt; B &amp; C", html)
        self.assertNotIn("<script", html)

    def test_raw_table_scripts_and_handlers_are_removed(self):
        markdown = (
            '<table onmouseover="steal()"><script>alert(1)</script>'
            "<tr><td>| A |</td></tr></table>"
        )
        html = markdown_to_html(clean_markdown(markdown))
        self.assertNotIn("<script", html)
        self.assertNotIn("onmouseover", html)
        self.assertIn('<td dir="auto">A</td>', html)

    def test_embedded_documents_and_event_handlers_are_removed(self):
        markdown = (
            '<table><tr><td colspan="2">'
            '<iframe srcdoc="<script>alert(1)</script>"></iframe>'
            '<img src="x" onerror="alert(1)">'
            "</td></tr></table>"
        )
        html = markdown_to_html(markdown)
        self.assertNotIn("<iframe", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("srcdoc", html)
        self.assertNotIn("onerror", html)
        self.assertIn('colspan="2"', html)

    def test_suppressed_elements_do_not_leak_their_contents(self):
        markdown = (
            "<table><tr><td><script>alert(1)</script>Safe text</td></tr></table>"
        )
        html = markdown_to_html(markdown)
        self.assertNotIn("alert(1)", html)
        self.assertNotIn("<script", html)
        self.assertIn("Safe text", html)

    def test_safe_links_are_kept_and_javascript_urls_are_dropped(self):
        safe = markdown_to_html("[site](https://example.com/a?b=1&c=2)")
        unsafe = markdown_to_html(
            '<table><tr><td><a href="javascript:alert(1)">x</a></td></tr></table>'
        )
        self.assertIn('href="https://example.com/a?b=1&amp;c=2"', safe)
        self.assertNotIn("javascript:", unsafe)


if __name__ == "__main__":
    unittest.main()

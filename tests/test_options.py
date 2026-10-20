import unittest

from egyfy.engine import PageOptions
from egyfy.errors import InvalidOptions


class PageOptionsTests(unittest.TestCase):
    def test_defaults(self):
        options = PageOptions.from_mapping(None)
        self.assertEqual(options.mode, "auto")
        self.assertEqual(options.dpi, 200.0)
        self.assertTrue(options.clean)
        self.assertTrue(options.pdf_order)

    def test_string_values_are_normalized(self):
        options = PageOptions.from_mapping(
            {
                "mode": "OCR",
                "dpi": "300",
                "max_pages": "4",
                "clean": "false",
                "math": "true",
            }
        )
        self.assertEqual(options.mode, "ocr")
        self.assertEqual(options.dpi, 300.0)
        self.assertEqual(options.max_pages, 4)
        self.assertFalse(options.clean)
        self.assertTrue(options.math)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(InvalidOptions):
            PageOptions.from_mapping({"mode": "scan"})

    def test_dpi_outside_range_is_rejected(self):
        with self.assertRaises(InvalidOptions):
            PageOptions.from_mapping({"dpi": 20})

    def test_page_limit_outside_range_is_rejected(self):
        with self.assertRaises(InvalidOptions):
            PageOptions.from_mapping({"max_pages": 501})

    def test_presentation_fields_do_not_change_cache_key(self):
        first = PageOptions.from_mapping({"clean": True, "max_pages": 5})
        second = PageOptions.from_mapping({"clean": False, "max_pages": 50})
        self.assertEqual(first.cache_key(), second.cache_key())

    def test_parsing_fields_change_cache_key(self):
        first = PageOptions.from_mapping({"mode": "auto"})
        second = PageOptions.from_mapping({"mode": "ocr"})
        self.assertNotEqual(first.cache_key(), second.cache_key())


if __name__ == "__main__":
    unittest.main()

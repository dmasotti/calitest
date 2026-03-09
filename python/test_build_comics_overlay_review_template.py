import unittest

from scripts.build_comics_overlay_review import HTML_TEMPLATE, select_image_entries


class BuildComicsOverlayReviewTemplateTest(unittest.TestCase):
    def test_template_contains_thumbnail_strip_and_hooks(self):
        self.assertIn('id="thumbs"', HTML_TEMPLATE)
        self.assertIn("function renderThumbs()", HTML_TEMPLATE)
        self.assertIn("thumb.className = 'thumb-item'", HTML_TEMPLATE)
        self.assertIn("thumb.addEventListener('click'", HTML_TEMPLATE)
        self.assertIn("const mapCoord = (v, axisMax)", HTML_TEMPLATE)
        self.assertIn("p.source_page || (idx + 1)", HTML_TEMPLATE)

    def test_select_image_entries_uses_selected_source_pages_only(self):
        extracted = ["/tmp/p1.jpg", "/tmp/p2.jpg", "/tmp/p3.jpg", "/tmp/p4.jpg"]
        entries = select_image_entries(extracted, [2, 4])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["path"], "/tmp/p2.jpg")
        self.assertEqual(entries[0]["source_page"], 2)
        self.assertEqual(entries[1]["path"], "/tmp/p4.jpg")
        self.assertEqual(entries[1]["source_page"], 4)


if __name__ == "__main__":
    unittest.main()

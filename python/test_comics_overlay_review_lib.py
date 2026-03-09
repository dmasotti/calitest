import unittest

from scripts.comics_overlay_review_lib import build_review_payload


class ComicsOverlayReviewLibTest(unittest.TestCase):
    def test_build_review_payload_merges_pipelines_and_images(self):
        image_files = ["images/page_0001.jpg", "images/page_0002.jpg"]
        pipelines = {
            "heuristic-ocr": {
                "pages": [
                    {
                        "page": 0,
                        "panels": [
                            {
                                "corners": {"x1": 0, "y1": 0, "x2": 100, "y2": 0, "x3": 100, "y3": 200, "x4": 0, "y4": 200},
                                "balloons": [{"x1": 10, "y1": 20, "x2": 30, "y2": 40, "text": "ciao"}],
                            }
                        ],
                    }
                ]
            },
            "vlm-openai": {
                "pages": [
                    {
                        "page": 0,
                        "panels": [
                            {
                                "corners": {"x1": 5, "y1": 5, "x2": 95, "y2": 5, "x3": 95, "y3": 195, "x4": 5, "y4": 195},
                                "balloons": [],
                            }
                        ],
                    }
                ]
            },
        }

        payload = build_review_payload(image_files=image_files, pipeline_results=pipelines)

        self.assertEqual(payload["total_pages"], 2)
        self.assertEqual(payload["pipelines"], ["heuristic-ocr", "vlm-openai"])
        self.assertEqual(payload["pages"][0]["image"], "images/page_0001.jpg")
        self.assertEqual(payload["pages"][1]["image"], "images/page_0002.jpg")
        self.assertEqual(len(payload["pages"][0]["by_pipeline"]["heuristic-ocr"]["panels"]), 1)
        self.assertEqual(len(payload["pages"][0]["by_pipeline"]["heuristic-ocr"]["balloons"]), 1)
        self.assertEqual(len(payload["pages"][0]["by_pipeline"]["vlm-openai"]["panels"]), 1)

    def test_build_review_payload_handles_missing_page_data(self):
        image_files = ["images/page_0001.jpg"]
        pipelines = {
            "heuristic-ocr": {"pages": []},
        }
        payload = build_review_payload(image_files=image_files, pipeline_results=pipelines)
        self.assertEqual(payload["total_pages"], 1)
        self.assertEqual(payload["pages"][0]["by_pipeline"]["heuristic-ocr"]["panels"], [])
        self.assertEqual(payload["pages"][0]["by_pipeline"]["heuristic-ocr"]["balloons"], [])

    def test_build_review_payload_supports_page_level_balloons_and_xywh_fallback(self):
        image_files = ["images/page_0001.jpg"]
        pipelines = {
            "vlm-openai": {
                "pages": [
                    {
                        "page": 0,
                        "panels": [
                            {
                                "corners": {"x1": 0, "y1": 0, "x2": 100, "y2": 0, "x3": 100, "y3": 100, "x4": 0, "y4": 100},
                                "balloons": [{"x": 10, "y": 20, "width": 30, "height": 40, "text": "legacy"}],
                            }
                        ],
                        "balloons": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "text": "page-level"}],
                    }
                ]
            }
        }
        payload = build_review_payload(image_files=image_files, pipeline_results=pipelines)
        balloons = payload["pages"][0]["by_pipeline"]["vlm-openai"]["balloons"]
        self.assertEqual(len(balloons), 2)
        legacy = [b for b in balloons if b.get("text") == "legacy"][0]
        self.assertEqual(legacy["x1"], 10)
        self.assertEqual(legacy["y1"], 20)
        self.assertEqual(legacy["x2"], 40)
        self.assertEqual(legacy["y2"], 60)

    def test_build_review_payload_supports_legacy_panel_xywh(self):
        image_files = ["images/page_0001.jpg"]
        pipelines = {
            "legacy": {
                "pages": [
                    {
                        "page": 0,
                        "panels": [
                            {"x": 10, "y": 20, "width": 30, "height": 40, "balloons": []}
                        ],
                    }
                ]
            }
        }
        payload = build_review_payload(image_files=image_files, pipeline_results=pipelines)
        panel = payload["pages"][0]["by_pipeline"]["legacy"]["panels"][0]
        self.assertEqual(panel["x1"], 10)
        self.assertEqual(panel["y1"], 20)
        self.assertEqual(panel["x2"], 40)
        self.assertEqual(panel["y2"], 20)
        self.assertEqual(panel["x3"], 40)
        self.assertEqual(panel["y3"], 60)


if __name__ == "__main__":
    unittest.main()

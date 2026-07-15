import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_past_exam_pdfs as importer


class FakePage:
    width = 400
    height = 600
    rects = []
    lines = []
    curves = []

    def __init__(self, images, words):
        self.images = images
        self._words = words

    def extract_words(self):
        return self._words


class QuestionVisualBboxTests(unittest.TestCase):
    def test_includes_left_side_label_and_superscript(self):
        page = FakePage(
            images=[{"x0": 100, "top": 200, "x1": 300, "bottom": 400}],
            words=[
                {"x0": 60, "top": 250, "x1": 96, "bottom": 266, "text": "Tc-MIBI"},
                {"x0": 50, "top": 252, "x1": 60, "bottom": 260, "text": "99m"},
                {"x0": 10, "top": 250, "x1": 40, "bottom": 266, "text": "unrelated"},
                {"x0": 60, "top": 150, "x1": 96, "bottom": 166, "text": "choice"},
                {"x0": 150, "top": 404, "x1": 210, "bottom": 420, "text": "caption"},
            ],
        )
        position = {"top": 100, "end_top": 500}

        self.assertEqual(importer.question_visual_bbox(page, position), (42, 192, 308, 428))

    def test_does_not_expand_without_a_label_touching_the_image_edge(self):
        page = FakePage(
            images=[{"x0": 100, "top": 200, "x1": 300, "bottom": 400}],
            words=[
                {"x0": 50, "top": 250, "x1": 70, "bottom": 266, "text": "detached"},
            ],
        )
        position = {"top": 100, "end_top": 500}

        self.assertEqual(importer.question_visual_bbox(page, position), (92, 192, 308, 408))


if __name__ == "__main__":
    unittest.main()

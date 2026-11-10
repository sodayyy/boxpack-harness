# -*- coding: utf-8 -*-
"""专项测试：MES空间切分与Beam结果的几何不变量。"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mes_beam import Space, _prune_spaces, beam_pack  # noqa: E402


class MesBeamTests(unittest.TestCase):
    def test_toy_exact_fill(self):
        items = [{"serial": f"I{i}", "dims": (2, 2, 2)} for i in range(8)]
        result = beam_pack(items, (4, 4, 4), beam_width=4, space_cap=20)
        self.assertEqual(result["placed"], 8)
        self.assertEqual(result["used_volume"], 64)
        self.assertEqual(result["skipped"], 0)

    def test_no_overlap(self):
        items = [
            {"serial": "A", "dims": (3, 2, 2)},
            {"serial": "B", "dims": (2, 3, 2)},
            {"serial": "C", "dims": (1, 1, 4)},
        ]
        result = beam_pack(items, (4, 4, 4), beam_width=8, space_cap=30)
        boxes = result["boxes"]
        for a, b in itertools.combinations(boxes, 2):
            overlap = (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
                       a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
                       a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"])
            self.assertFalse(overlap)

    def test_prune_contains(self):
        spaces = [Space(0, 0, 0, 10, 10, 10), Space(1, 1, 1, 2, 2, 2)]
        self.assertEqual(len(_prune_spaces(spaces)), 1)


if __name__ == "__main__":
    unittest.main()

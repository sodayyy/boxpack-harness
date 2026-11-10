# -*- coding: utf-8 -*-
"""专项测试：MES空间切分与Beam结果的几何不变量。"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mes_beam import (  # noqa: E402
    Space, _check_space_invariants, _prune_spaces, _remaining_spaces,
    _subtract_space, beam_pack,
)
from experiments.exact_l0 import solve_exact  # noqa: E402


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

    def test_subtract_internal_box_invariants(self):
        space = Space(0, 0, 0, 10, 10, 10)
        box = {"x": 2, "y": 3, "z": 4, "l": 3, "w": 2, "h": 1}
        spaces = _subtract_space(space, box)
        self.assertTrue(spaces)
        self.assertEqual(_check_space_invariants(spaces, [box], (10, 10, 10)), [])

    def test_subtract_full_space(self):
        space = Space(0, 0, 0, 4, 4, 4)
        box = {"x": 0, "y": 0, "z": 0, "l": 4, "w": 4, "h": 4}
        self.assertEqual(_subtract_space(space, box), [])

    def test_remaining_spaces_are_disjoint_from_boxes(self):
        spaces = [Space(0, 0, 0, 8, 8, 8)]
        boxes = []
        for serial, box in enumerate((
            {"serial": "A", "x": 0, "y": 0, "z": 0, "l": 4, "w": 4, "h": 4},
            {"serial": "B", "x": 4, "y": 0, "z": 0, "l": 4, "w": 4, "h": 4},
        )):
            boxes.append(box)
            spaces = _remaining_spaces(spaces, box)
            self.assertEqual(_check_space_invariants(spaces, boxes, (8, 8, 8)), [])

    def test_exact_referee_matches_toy_optimum(self):
        items = [{"serial": f"I{i}", "dims": (2, 2, 2)} for i in range(8)]
        result = solve_exact(items, (4, 4, 4), time_limit=10)
        self.assertEqual(result.status, "optimal")
        self.assertEqual(result.placed, 8)
        self.assertEqual(result.used_volume, 64)

    def test_exact_referee_exposes_b2_gap(self):
        items = [
            {"serial": "R0", "dims": (1, 3, 1)},
            {"serial": "R1", "dims": (4, 3, 1)},
            {"serial": "R2", "dims": (1, 4, 3)},
        ]
        items.sort(key=lambda it: (-it["dims"][0] * it["dims"][1] * it["dims"][2],
                                   it["serial"]))
        exact = solve_exact(items, (4, 4, 4), time_limit=5, node_limit=2_000_000)
        b2 = beam_pack(items, (4, 4, 4), beam_width=8, space_cap=80)
        self.assertEqual(exact.status, "optimal")
        self.assertEqual(exact.placed, 3)
        self.assertEqual(exact.used_volume, 27)
        self.assertEqual(b2["placed"], 2)
        self.assertLess(b2["placed"], exact.placed)


if __name__ == "__main__":
    unittest.main()

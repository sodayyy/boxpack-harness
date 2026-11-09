# -*- coding: utf-8 -*-
"""平台候选诊断的针对性回归，不依赖大算例。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_analysis import enumerate_slots, select_nonoverlapping


def host():
    return SimpleNamespace(L=4, W=4, H=5, h_eff=5,
                           own=np.full((5, 4, 4), -1, dtype=int),
                           kinds=["standard", "oriented"], boxes=[])


class PlatformTests(unittest.TestCase):
    def test_floor_candidates(self):
        self.assertEqual(len(enumerate_slots(host(), (2, 2, 2))), 9)

    def test_obstacle_above_empty_base_rejected(self):
        tr = host()
        tr.own[1, 0, 0] = 1
        self.assertNotIn((0, 0, 0, 2, 2, 2), enumerate_slots(tr, (2, 2, 2)))

    def test_top_contact_rejected(self):
        tr = host()
        tr.own[2, 0, 0] = 1
        self.assertNotIn((0, 0, 0, 2, 2, 2), enumerate_slots(tr, (2, 2, 2)))

    def test_only_standard_support(self):
        tr = host()
        tr.own[0] = 0
        tr.boxes = [dict(z=0, h=1)]
        self.assertIn((0, 0, 1, 2, 2, 2), enumerate_slots(tr, (2, 2, 2)))
        tr.own[0] = 1
        self.assertEqual(enumerate_slots(tr, (2, 2, 2)), [])

    def test_partial_support_rejected(self):
        tr = host()
        tr.own[0, 0, 0] = 0
        tr.boxes = [dict(z=0, h=1)]
        self.assertNotIn((0, 0, 1, 2, 2, 2), enumerate_slots(tr, (2, 2, 2)))

    def test_height_bounds(self):
        self.assertEqual(enumerate_slots(host(), (2, 2, 6)), [])

    def test_greedy_rejects_overlap_and_contact(self):
        a = (0, 0, 0, 2, 2, 2)
        overlap = (1, 0, 0, 2, 2, 2)
        touching = (0, 0, 2, 2, 2, 2)
        separate = (2, 0, 0, 2, 2, 2)
        self.assertEqual(select_nonoverlapping([a, overlap, touching, separate]),
                         [a, separate])

    def test_multiple_heights_with_gap(self):
        a = (0, 0, 0, 2, 2, 2)
        b = (0, 0, 3, 2, 2, 2)
        self.assertEqual(len(select_nonoverlapping([a, b])), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

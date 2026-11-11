"""Exact fixed-layout parameter thresholds and cross-referee regression."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.parameter_envelope import exact_thresholds, accepts, canonical_digest, check_parameter_fleet
from src.constraints import load_catalog, load_trucks, check_fleet
import json


def fixture(partial=False):
    base_l = 50 if partial else 100
    catalog = dict(a=dict(dims=(base_l, 100, 10), kind="standard", weight=10, qty=1),
                   b=dict(dims=(100, 100, 10), kind="standard", weight=20, qty=1))
    trucks = dict(test=dict(dims=(100, 100, 40), cap_weight=100, cost=1))
    boxes = [dict(serial=name + "-000", name=name, kind=s["kind"], weight=s["weight"],
                  x=0, y=0, z=i*10, l=s["dims"][0], w=100, h=10) for i, (name, s) in enumerate(catalog.items())]
    return [dict(truck_type="test", boxes=boxes)], trucks, catalog


class ParameterEnvelopeTests(unittest.TestCase):
    def test_exact_thresholds_and_inclusive_boundaries(self):
        fleet, trucks, catalog = fixture()
        t = exact_thresholds(fleet, trucks, catalog)
        self.assertEqual((t["alpha_max"], t["pressure_min"], t["clearance_max"]), ("1", "20", "20"))
        for a, p, d, expected in (("1", "20", "20", True), ("1", "19999/1000", "20", False),
                                   ("1", "20", "21", False), ("0", "21", "0", True)):
            self.assertEqual(accepts(t, a, p, d), expected)
            self.assertEqual(not check_parameter_fleet(fleet, trucks, catalog, a, p, d), expected)

    def test_partial_support_exact_half_not_rounded(self):
        fleet, trucks, catalog = fixture(partial=True)
        t = exact_thresholds(fleet, trucks, catalog)
        self.assertEqual(t["alpha_max"], "1/2")
        self.assertEqual(t["pressure_min"], "40")
        self.assertTrue(accepts(t, "1/2", "40", "20"))
        self.assertFalse(accepts(t, "501/1000", "40", "20"))
        self.assertFalse(check_parameter_fleet(fleet, trucks, catalog, "1/2", "40", "20"))
        self.assertTrue(check_parameter_fleet(fleet, trucks, catalog, "501/1000", "40", "20"))

    def test_duplicate_floating_overlap_and_metadata_rejected(self):
        fleet, trucks, catalog = fixture()
        for mode in ("duplicate", "floating", "overlap", "kind"):
            bad = copy.deepcopy(fleet)
            if mode == "duplicate":
                bad[0]["boxes"][1]["serial"] = "a-000"
            elif mode == "floating":
                bad[0]["boxes"][1]["z"] = 11
            elif mode == "overlap":
                bad[0]["boxes"][1]["z"] = 9
            else:
                bad[0]["boxes"][1]["kind"] = "fragile"
            with self.assertRaises(ValueError, msg=mode):
                exact_thresholds(bad, trucks, catalog)

    def test_digest_order_invariant_but_pose_and_identity_preserved(self):
        fleet, _, _ = fixture()
        reversed_boxes = copy.deepcopy(fleet)
        reversed_boxes[0]["boxes"].reverse()
        self.assertEqual(canonical_digest(fleet), canonical_digest(reversed_boxes))
        reversed_boxes[0]["boxes"][0]["x"] += 1
        self.assertNotEqual(canonical_digest(fleet), canonical_digest(reversed_boxes))

    def test_bad_parameters_rejected(self):
        fleet, trucks, catalog = fixture()
        t = exact_thresholds(fleet, trucks, catalog)
        for a, p, d in ((True, 20, 0), ("NaN", 20, 0), (2, 20, 0), (0, -1, 0), (0, 20, -1)):
            with self.assertRaises(ValueError):
                accepts(t, a, p, d)
            with self.assertRaises(ValueError):
                check_parameter_fleet(fleet, trucks, catalog, a, p, d)

    def test_original_rules_unchanged_real_witness(self):
        data = json.loads((ROOT / "experiments/results/block_search_L4_v1/blocks_L4_024.json").read_text(encoding="utf-8"))
        trucks = load_trucks(ROOT / "data/trucks.csv")
        catalog = load_catalog(ROOT / "data/items.csv")
        t = exact_thresholds(data["fleet"], trucks, catalog)
        self.assertEqual((t["alpha_max"], t["pressure_min"], t["clearance_max"]), ("1", "2540/7", "10"))
        self.assertEqual(check_parameter_fleet(data["fleet"], trucks, catalog, "0", "500", "3"),
                         check_fleet(data["fleet"], trucks, catalog, pressure_model="chain_area_v1"))
        self.assertFalse(check_parameter_fleet(data["fleet"], trucks, catalog, "1", "2540/7", "10"))
        self.assertTrue(check_parameter_fleet(data["fleet"], trucks, catalog, "1", "362", "10"))
        self.assertTrue(check_parameter_fleet(data["fleet"], trucks, catalog, "1", "500", "11"))


if __name__ == "__main__":
    unittest.main()

"""Regression and independent cross-checks for the versioned chain EP."""
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constrained_ep import ChainTruck, vertical_load_state, pack_fixed_fleet
from src.constraints import audit_load_chain, check_all
from src.pack_lib import TruckType


def meta(name, dims, weight=1, kind="standard"):
    return dict(name=name, serial=name + "-000", dims=dims, weight=weight, kind=kind)


class ChainEPTests(unittest.TestCase):
    def test_three_level_load_reaches_bottom(self):
        tr = ChainTruck(TruckType("test", (10, 10, 20), 100, 1), clearance=0)
        a, b, c = [meta(name, (10, 10, 5), weight) for name, weight in (("a", 1), ("b", 3), ("c", 3))]
        tr.put(a, 0, 0, 0, 10, 10, 5)
        tr.put(b, 0, 0, 5, 10, 10, 5)
        self.assertFalse(tr.feasible(0, 0, 10, 10, 10, 5, "standard", 3))
        with self.assertRaises(ValueError):
            tr.put(c, 0, 0, 10, 10, 10, 5)
        self.assertEqual(len(tr.boxes), 2)
        self.assertFalse(audit_load_chain(tr.boxes)["errors"])

    def test_partial_contact_normalizes_entire_load(self):
        boxes = [dict(meta("base", (5, 10, 5)), x=0, y=0, z=0, l=5, w=10, h=5),
                 dict(meta("upper", (10, 10, 5), 2), x=0, y=0, z=5, l=10, w=10, h=5)]
        state = vertical_load_state(boxes)
        self.assertIsNotNone(state)
        self.assertEqual(state["total_load_kg"][0], 3)
        self.assertEqual(state["floor_reaction_kg"], 3)
        audit = audit_load_chain(boxes)
        self.assertFalse(audit["errors"])
        self.assertEqual(audit["transfers"][0]["load_kg"], 2)

    def test_new_support_under_old_overhang_checked(self):
        tr = ChainTruck(TruckType("test", (20, 10, 20), 100, 1), level=2, clearance=0)
        tr.put(meta("left", (10, 10, 5)), 0, 0, 0, 10, 10, 5)
        tr.put(meta("bridge", (20, 10, 5)), 0, 0, 5, 20, 10, 5)
        self.assertFalse(tr.feasible(10, 0, 0, 10, 10, 5, "fragile", 1))
        self.assertTrue(tr.feasible(10, 0, 0, 10, 10, 5, "standard", 1))

    def test_support_ratio_is_explicit_not_environment_global(self):
        tr = ChainTruck(TruckType("test", (20, 10, 20), 100, 1), level=2,
                        clearance=0, support_ratio=0.75)
        tr.put(meta("base", (5, 10, 5)), 0, 0, 0, 5, 10, 5)
        self.assertFalse(tr.feasible(0, 0, 5, 10, 10, 5, "standard", 1))
        tr.support_ratio = 0
        self.assertTrue(tr.feasible(0, 0, 5, 10, 10, 5, "standard", 1))

    def test_independent_random_vertical_chain_crosscheck(self):
        rng = random.Random(4103)
        for _ in range(100):
            boxes = []
            z = 0
            for index in range(rng.randint(1, 8)):
                l, w, h = rng.randint(4, 15), rng.randint(4, 15), rng.randint(1, 5)
                boxes.append(dict(meta(str(index), (l, w, h), rng.randint(0, 5)),
                                  x=0, y=0, z=z, l=l, w=w, h=h))
                z += h
            solver = vertical_load_state(boxes)
            audit = audit_load_chain(boxes)
            self.assertEqual(solver is not None, not audit["errors"])
            if solver is not None:
                self.assertAlmostEqual(solver["floor_reaction_kg"], audit["total_weight_kg"])

    def test_fixed_fleet_never_opens_extra_vehicle(self):
        specs = [TruckType("small", (10, 10, 13), 100, 1)]
        items = [meta("a", (10, 10, 10)), meta("b", (10, 10, 10))]
        fleet, rest = pack_fixed_fleet(items, specs)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(len(rest), 1)
        catalog = {i["name"]: dict(dims=i["dims"], kind=i["kind"], weight=i["weight"], qty=1) for i in items}
        self.assertFalse(check_all(fleet[0]["boxes"], dict(dims=specs[0].dims, cap_weight=100),
                                   catalog, pressure_model="chain_area_v1", strict_ids=True))


if __name__ == "__main__":
    unittest.main()

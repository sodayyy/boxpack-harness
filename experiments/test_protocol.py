"""Protocol regressions: catalog tampering, identity, reflections and load chain."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import (audit_load_chain, check_all, check_fleet,
                             load_catalog, load_trucks)
from src.solution_io import (export_solution, read_solution, read_solution_csv,
                             fleet_metrics, reflect_box)
from src.pack_lib import TRUCKS, lower_bound

CAT = load_catalog(ROOT / "data/items.csv")
SPECS = load_trucks(ROOT / "data/trucks.csv")


def box(serial="G1-000", x=0, y=0, z=0, weight=12, l=60, w=40, h=30):
    return dict(serial=serial, name="G1", kind="standard", weight=weight,
                x=x, y=y, z=z, l=l, w=w, h=h)


class ProtocolTests(unittest.TestCase):
    def test_catalog_tampering(self):
        for key, value in (("weight", 0), ("kind", "fragile")):
            b = box()
            b[key] = value
            self.assertTrue(any(e.startswith("C3 ") for e in
                                check_all([b], SPECS["车型1"], CAT)))

    def test_cross_truck_duplicate(self):
        fleet = [dict(truck_type="车型1", boxes=[box()]) for _ in range(2)]
        self.assertTrue(any("重复身份" in e for e in
                            check_fleet(fleet, SPECS, CAT, require_complete=False)))

    def test_malformed_fleet_rejected(self):
        for fleet in (None, {}, [{}], [dict(truck_type=[], boxes=[])],
                      [dict(truck_type="车型1", boxes=None)]):
            self.assertTrue(check_fleet(fleet, SPECS, CAT))
        self.assertTrue(check_fleet([], SPECS, CAT))
        self.assertTrue(check_fleet([dict(truck_type="unknown", boxes=[])], SPECS, CAT))

    def test_identity_type_and_range(self):
        for serial in ("G2-000", "G1-080", "arbitrary", [], None, 0):
            self.assertTrue(check_all([box(serial)], SPECS["车型1"], CAT,
                                      strict_ids=True))

    def test_malformed_geometry(self):
        for key, value in (("x", float("nan")), ("l", 0), ("x", "0")):
            b = box()
            b[key] = value
            self.assertTrue(check_all([b], SPECS["车型1"], CAT))
        self.assertTrue(check_all([{}], SPECS["车型1"], CAT))

    def test_guesser_input_conversion(self):
        from itertools import product
        from experiments.prepare_guesser_inputs import convert, validate_conversion
        for dims in ((7, 5, 3), (4, 4, 2), (3, 3, 3)):
            for flags in product((0, 1), repeat=3):
                inst = dict(pid="synthetic", box=(20, 20, 20),
                            types=[dict(t=1, dims=dims, flags=flags, qty=2)])
                if not any(flags):
                    with self.assertRaises(ValueError):
                        convert(inst)
                else:
                    converted = convert(inst)
                    validate_conversion(inst, converted)
                    self.assertEqual(converted["small_items"][0]["quantity"], 2)

    def test_saved_l0_layout_verifier(self):
        from experiments.verify_mes_result import verify
        items = [dict(serial="G1-000", name="G1", allowed=[(60, 40, 30)])]
        valid = dict(boxes=[box()], placed=1, used_volume=72000,
                     isd=72000 / 1000000, n=1, rest=0)
        self.assertFalse(verify(valid, (100, 100, 100), items))
        for field, value in (("serial", []), ("x", float("nan")),
                             ("l", float("inf")), ("z", "0"),
                             ("weight", 0)):
            candidate = copy.deepcopy(valid)
            candidate["boxes"][0][field] = value
            if field == "weight":
                # L0 benchmark has no weight restriction; do not invent one.
                self.assertFalse(verify(candidate, (100, 100, 100), items))
            else:
                self.assertTrue(verify(candidate, (100, 100, 100), items))
        for field, value in (("isd", float("nan")), ("used_volume", 1),
                             ("placed", 0), ("n", 2), ("rest", 1)):
            candidate = copy.deepcopy(valid)
            candidate[field] = value
            self.assertTrue(verify(candidate, (100, 100, 100), items))
        for change in ({"serial": "unknown"}, {"name": "G2"},
                       {"l": 40, "w": 60}, {"x": -1}, {"h": 0}):
            candidate = copy.deepcopy(valid)
            candidate["boxes"][0].update(change)
            self.assertTrue(verify(candidate, (100, 100, 100), items))
        candidate = copy.deepcopy(valid)
        candidate["boxes"].append(box())
        self.assertTrue(verify(candidate, (100, 100, 100), items))
        self.assertTrue(verify({"boxes": [{}]}, (100, 100, 100), items))

    def test_coordinate_both_axes_and_roundtrip(self):
        b = box(x=13, y=17, z=19)
        reflected = reflect_box(b, SPECS["车型1"]["dims"])
        self.assertEqual((reflected["x"], reflected["y"], reflected["z"]), (347, 153, 19))
        self.assertEqual(reflect_box(reflected, SPECS["车型1"]["dims"]), b)
        fleet = [dict(truck_type="车型1", boxes=[b])]
        with tempfile.TemporaryDirectory() as td:
            jp, cp = Path(td) / "s.json", Path(td) / "s.csv"
            export_solution(fleet, jp, cp, SPECS, level=0)
            self.assertEqual(read_solution(jp, SPECS), fleet)
            self.assertEqual(read_solution_csv(cp, SPECS), fleet)
            self.assertFalse(check_fleet(read_solution(jp, SPECS), SPECS, CAT,
                                         level=0, require_complete=False))

    def test_metrics_are_not_completion(self):
        fleet = [dict(truck_type="车型1", boxes=[box()])]
        m = fleet_metrics(fleet, SPECS, CAT)
        self.assertAlmostEqual(m["nominal_space_util"], 72000 / 19404000)
        self.assertAlmostEqual(m["effective_space_util"], 72000 / 19139400)
        self.assertAlmostEqual(m["shipment_completion"], 72000 / 28735000)
        self.assertNotEqual(m["shipment_completion"], m["nominal_space_util"])
        self.assertEqual([lower_bound(s)[0] for s in TRUCKS], [2, 1])

    def test_chain_propagates_all_levels(self):
        bs = [box(f"S-{i}", z=i * 30, l=100, w=100, weight=w)
              for i, w in enumerate((10, 20, 30))]
        a = audit_load_chain(bs)
        self.assertFalse(a["errors"])
        self.assertEqual(a["total_load"]["S-0"], 60)
        self.assertEqual(a["top_pressure"]["S-0"], 50)
        self.assertEqual(a["floor_reactions"]["S-0"], 60)
        self.assertAlmostEqual(a["conservation_residual_kg"], 0)

    def test_partial_support_does_not_lose_weight(self):
        bs = [box("base", l=50, w=100, weight=10),
              box("top", z=30, l=100, w=100, weight=40)]
        a = audit_load_chain(bs)
        self.assertEqual(a["transfers"][0]["load_kg"], 40)
        self.assertEqual(a["floor_reactions"]["base"], 50)
        self.assertFalse(a["errors"])  # vertical-only, not a claim of moment balance

    def test_multisupport_split_and_overload(self):
        bs = [box("left", l=25, w=100, weight=10),
              box("right", x=25, l=75, w=100, weight=10),
              box("top", z=30, l=100, w=100, weight=600)]
        a = audit_load_chain(bs)
        self.assertEqual(a["floor_reactions"], {"left": 160.0, "right": 460.0})
        self.assertAlmostEqual(a["conservation_residual_kg"], 0)
        self.assertEqual(len([e for e in a["errors"] if e.startswith("C9 ")]), 2)

    def test_floating_chain_fails_conservation(self):
        a = audit_load_chain([box(z=10)])
        self.assertTrue(any(e.startswith("A3 ") for e in a["errors"]))
        self.assertNotEqual(a["conservation_residual_kg"], 0)

    def test_fragile_real_coordinates(self):
        base = box(x=0.5, y=0.5, l=70, w=50)
        catalog = dict(CAT, B=dict(dims=(70, 50, 30), kind="standard", weight=12, qty=1))
        base["name"] = "B"
        fragile = dict(serial="G3-000", name="G3", kind="fragile", weight=15,
                       x=0.5, y=0.5, z=30, l=70, w=50, h=40)
        self.assertFalse(check_all([base, fragile], SPECS["车型1"], catalog))


if __name__ == "__main__":
    unittest.main(verbosity=2)

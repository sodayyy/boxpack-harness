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

    def test_guesser_output_identity_adapter(self):
        from experiments.adapt_guesser_output import adapt
        from experiments.verify_mes_result import verify
        inst = dict(pid="synthetic", box=(20, 20, 20), types=[
            dict(t=1, dims=(4, 3, 2), flags=(0, 0, 1), qty=1),
            dict(t=2, dims=(5, 3, 2), flags=(0, 0, 1), qty=1),
        ])
        payload = {"large_object": {"measurement": dict(zip("xyz", inst["box"]))},
                   "small_items": [
            {"measurement": {"x": 3, "y": 4, "z": 2},
             "position": {"x": 0, "y": 0, "z": 0}},
            {"measurement": {"x": 5, "y": 3, "z": 2},
             "position": {"x": 3, "y": 0, "z": 0}},
        ]}
        adapted = adapt(inst, payload)
        self.assertEqual([b["name"] for b in adapted["boxes"]], ["T1", "T2"])
        items = [{"serial": "T1-000", "name": "T1", "allowed": [(3, 4, 2), (4, 3, 2)]},
                 {"serial": "T2-000", "name": "T2", "allowed": [(5, 3, 2)]}]
        self.assertFalse(verify(adapted, inst["box"], items))
        ambiguous = dict(inst, types=[
            dict(t=1, dims=(4, 3, 2), flags=(0, 0, 1), qty=1),
            dict(t=2, dims=(4, 3, 2), flags=(0, 0, 1), qty=1),
        ])
        candidate = copy.deepcopy(payload)
        candidate["small_items"] = candidate["small_items"][:1]
        with self.assertRaisesRegex(ValueError, "ambiguous source type assignment"):
            adapt(ambiguous, candidate)

    def test_guesser_rejects_bad_geometry_and_overquantity(self):
        from experiments.adapt_guesser_output import adapt
        inst = dict(pid="one", box=(20, 20, 20), types=[
            dict(t=1, dims=(4, 3, 2), flags=(0, 0, 1), qty=1)])
        valid = {"large_object": {"measurement": {"x": 20, "y": 20, "z": 20}},
                 "small_items": [{"measurement": {"x": 4, "y": 3, "z": 2},
                                  "position": {"x": 0, "y": 0, "z": 0}}]}
        too_many = copy.deepcopy(valid)
        too_many["small_items"] *= 2
        with self.assertRaisesRegex(ValueError, "exceeds source type quantities"):
            adapt(inst, too_many)
        for section, key, value in [("measurement", "x", 0),
                                    ("measurement", "x", -4),
                                    ("measurement", "z", 3),
                                    ("position", "x", -1),
                                    ("position", "x", float("nan")),
                                    ("position", "x", float("inf")),
                                    ("position", "x", True),
                                    ("position", "x", "0")]:
            bad = copy.deepcopy(valid)
            bad["small_items"][0][section][key] = value
            with self.subTest(section=section, key=key, value=value):
                with self.assertRaises(ValueError):
                    adapt(inst, bad)
        for bad in ({}, {"small_items": None},
                    dict(valid, small_items=[{}])):
            with self.assertRaises(ValueError):
                adapt(inst, bad)
        bad = copy.deepcopy(valid)
        del bad["small_items"][0]["position"]["z"]
        with self.assertRaisesRegex(ValueError, "missing coordinate"):
            adapt(inst, bad)

    def test_guesser_binds_full_input_and_container(self):
        from experiments.adapt_guesser_output import adapt, validate_input
        from experiments.prepare_guesser_inputs import convert
        inst = dict(pid="one", box=(20, 20, 20), types=[
            dict(t=1, dims=(4, 3, 2), flags=(0, 0, 1), qty=1)])
        source = convert(inst)
        validate_input(inst, source)
        for section in ("quantity", "profit", "orientation", "container"):
            bad = copy.deepcopy(source)
            if section == "container":
                bad["large_object"]["measurement"]["x"] = 21
            elif section == "orientation":
                bad["small_items"][0]["constraint"]["orientation"]["xyz"] = False
            else:
                bad["small_items"][0][section] += 1
            with self.assertRaisesRegex(ValueError, "canonical source instance"):
                validate_input(inst, bad)
        bad = copy.deepcopy(source)
        bad["small_items"][0]["quantity"] = True
        with self.assertRaisesRegex(ValueError, "canonical source instance"):
            validate_input(inst, bad)
        empty = {"large_object": {"measurement": {"x": 20, "y": 20, "z": 20}},
                 "small_items": []}
        self.assertEqual(adapt(inst, empty)["placed"], 0)
        for bad in (dict(empty, large_object={}),
                    dict(empty, large_object={"measurement": {"x": 21, "y": 20, "z": 20}}),
                    dict(empty, appendix={"pid": "wrong"}),
                    dict(empty, appendix=[])):
            with self.assertRaises(ValueError):
                adapt(inst, bad)

    def test_guesser_matching_against_exhaustive_oracle(self):
        from itertools import product
        import random
        from experiments.adapt_guesser_output import _solve_type_assignment
        rng = random.Random(20261110)
        for trial in range(250):
            n, m = rng.randint(0, 6), rng.randint(1, 4)
            dims = [(i + 1, 1, 1) for i in range(n)]
            candidates = [[t for t in range(m) if rng.random() < 0.55] for _ in dims]
            capacities = [rng.randint(0, 3) for _ in range(m)]
            descriptors = [dict(quantity=capacities[t],
                                allowed={dims[i] for i in range(n) if t in candidates[i]})
                           for t in range(m)]
            boxes = [dict(l=d[0], w=d[1], h=d[2]) for d in dims]
            solutions = []
            for assignment in product(*candidates):
                if all(assignment.count(t) <= capacities[t] for t in range(m)):
                    solutions.append(assignment)
                    if len(solutions) == 2:
                        break
            with self.subTest(trial=trial):
                if len(solutions) == 1:
                    self.assertEqual(_solve_type_assignment(boxes, descriptors), solutions[0])
                else:
                    pattern = "ambiguous" if solutions else "no legal source type|exceeds"
                    with self.assertRaisesRegex(ValueError, pattern):
                        _solve_type_assignment(boxes, descriptors)

    def test_guesser_matching_not_limited_by_python_recursion(self):
        from experiments.adapt_guesser_output import _solve_type_assignment
        boxes = [dict(l=4, w=3, h=2) for _ in range(1500)]
        descriptors = [dict(quantity=1500, allowed={(4, 3, 2)})]
        self.assertEqual(_solve_type_assignment(boxes, descriptors), (0,) * 1500)

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

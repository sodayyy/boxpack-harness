"""Restricted-block construction checks, accepted by the external referee."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.block_search import make_blocks, pack_blocks
from src.constraints import load_catalog, load_trucks, check_fleet
from src.pack_lib import expand_items, TRUCKS


class BlockSearchTests(unittest.TestCase):
    def test_full_catalog_conserved_in_both_recipes_and_heights(self):
        items = expand_items()
        for height in (217, 247):
            for capped in (False, True):
                blocks = make_blocks(items, height, capped)
                serials = [p[0]["serial"] for b in blocks for p in b["parts"]]
                self.assertEqual(sorted(serials), sorted(it["serial"] for it in items))
                self.assertTrue(all(b["h"] <= height for b in blocks))

    def test_capped_blocks_individually_accepted_by_independent_referee(self):
        from src.constraints import check_all
        catalog = load_catalog(ROOT / "data/items.csv")
        for height in (217, 247):
            for block in make_blocks(expand_items(), height):
                boxes = [dict(serial=it["serial"], name=it["name"], kind=it["kind"],
                              weight=it["weight"], x=x, y=y, z=z, l=l, w=w, h=h)
                         for it, x, y, z, l, w, h in block["parts"]]
                errors = check_all(boxes, dict(dims=(block["l"], block["w"], height + 3),
                                               cap_weight=10000), catalog,
                                   level=4, pressure_model="chain_area_v1", strict_ids=True)
                self.assertFalse(errors, (height, block["id"], errors))

    def test_partial_fleet_has_no_duplicates_and_no_extra_vehicle(self):
        catalog = load_catalog(ROOT / "data/items.csv")
        trucks = load_trucks(ROOT / "data/trucks.csv")
        # A small real subset keeps this a fast regression, not a 300-item run.
        items = [it for it in expand_items() if it["name"] == "G3"]
        fleet, rest, stats = pack_blocks(items, [TRUCKS[0]], order="area")
        placed = [b["serial"] for tr in fleet for b in tr["boxes"]]
        self.assertLessEqual(len(fleet), 1)
        self.assertEqual(sorted(placed + [it["serial"] for it in rest]),
                         sorted(it["serial"] for it in items))
        self.assertFalse(check_fleet(fleet, trucks, catalog, level=4,
                                    pressure_model="chain_area_v1", require_complete=False))
        self.assertEqual(stats["placed_blocks"], len(placed))

    def test_reproducible_and_does_not_mutate_inputs(self):
        import copy
        items = expand_items()[:6]
        before = copy.deepcopy(items)
        a = pack_blocks(items, [TRUCKS[1]], rotation="wide")
        b = pack_blocks(items, [TRUCKS[1]], rotation="wide")
        self.assertEqual(a, b)
        self.assertEqual(items, before)

    def test_bad_configuration_and_duplicate_identity_rejected(self):
        items = expand_items()[:2]
        with self.assertRaises(ValueError):
            make_blocks([items[0], items[0]], 247)
        with self.assertRaises(ValueError):
            pack_blocks(items, [TRUCKS[1]], order="unknown")
        with self.assertRaises(ValueError):
            pack_blocks(items, TRUCKS)
        with self.assertRaises(ValueError):
            make_blocks(items, 0)


if __name__ == "__main__":
    unittest.main()

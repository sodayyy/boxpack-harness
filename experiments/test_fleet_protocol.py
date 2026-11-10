"""Objective independence and evidence tampering regression tests."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.bench_constrained_fleet import candidate_combinations, select_objectives
from experiments.verify_constrained_fleet import objective_summary, single_summary, verify_bundle
from src.pack_lib import TruckType


class FleetProtocolTests(unittest.TestCase):
    def test_cost_domain_includes_more_vehicles(self):
        trucks = [TruckType("cheap", (10, 10, 13), 100, 2),
                  TruckType("dear", (30, 10, 13), 100, 10)]
        combos = list(candidate_combinations(3000, 1, trucks, 1, 10))
        self.assertIn((3, 0), combos)
        self.assertIn((0, 1), combos)
        self.assertNotIn((1, 0), combos)

    def test_p1_p2_are_separate_and_partial_excluded(self):
        rows = [dict(label="two", complete=True, errors=[], vehicles=2, cost=14),
                dict(label="three", complete=True, errors=[], vehicles=3, cost=12),
                dict(label="partial", complete=False, errors=[], vehicles=1, cost=1),
                dict(label="illegal", complete=True, errors=["bad"], vehicles=1, cost=1)]
        for rank in (select_objectives, objective_summary):
            self.assertEqual(rank(rows)["P1"]["label"], "two")
            self.assertEqual(rank(rows)["P2"]["label"], "three")

    def test_single_selects_volume_not_count(self):
        rows = [dict(label="many", vehicle_order=["small"], errors=[], used_volume_cm3=100,
                     placed=20, rest_serials=[], item_order="height"),
                dict(label="volume", vehicle_order=["small"], errors=[], used_volume_cm3=200,
                     placed=10, rest_serials=[], item_order="volume")]
        result = single_summary(rows, {"small": dict(dims=(10, 10, 10))})
        self.assertEqual(result["small"]["label"], "volume")

    def test_missing_run_rejected_even_with_updated_hash(self):
        source = ROOT / "experiments/results/chain_single_L4_v1"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            shutil.copytree(source, target)
            manifest_path = target / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["runs"].pop()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            # The matrix check must reject this without relying on hash failure.
            import hashlib
            hash_path = target / "sha256.json"
            hashes = json.loads(hash_path.read_text(encoding="utf-8"))
            hashes["files"]["manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            hash_path.write_text(json.dumps(hashes), encoding="utf-8")
            result = verify_bundle(target)
            self.assertFalse(result["passed"])
            self.assertTrue(any("missing, duplicate" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()

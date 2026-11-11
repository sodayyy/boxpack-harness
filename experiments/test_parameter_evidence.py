"""R7 evidence regression: reject semantic corruption even after rehashing."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_parameter_envelope import verify_bundle
import experiments.verify_parameter_envelope as verifier
from unittest.mock import patch

EVIDENCE = ROOT / "experiments/results/parameter_envelope_R7_v1"


class ParameterEvidenceTests(unittest.TestCase):
    def test_real_complete_bundle(self):
        result = verify_bundle(EVIDENCE)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual((result["grid_points"], result["unique_layouts"], result["boundary_checks"]), (720, 21, 84))
        self.assertEqual(result["monotonicity_checks"], 11160)
        self.assertEqual(result["status_counts"], {
            "no_saved_witness_not_infeasible": 594,
            "verified_upper_bounds_not_global_optimum": 54,
            "witness_and_lower_bounds": 72,
        })

    def assert_corruption_rejected(self, name, mutate, message):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "bundle"
            shutil.copytree(EVIDENCE, directory)
            path = directory / name
            obj = json.loads(path.read_text(encoding="utf-8"))
            mutate(obj)
            path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            hash_path = directory / "sha256.json"
            hashes = json.loads(hash_path.read_text(encoding="utf-8"))
            hashes["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
            hash_path.write_text(json.dumps(hashes), encoding="utf-8")
            result = verify_bundle(directory)
            self.assertFalse(result["passed"])
            self.assertTrue(any(message in error for error in result["errors"]), result["errors"])
            self.assertFalse(any("hash mismatch" in error for error in result["errors"]), result["errors"])

    def test_truncated_grid_rejected_after_rehash(self):
        self.assert_corruption_rejected("grid.json", lambda obj: obj["rows"].pop(), "truncated grid")

    def test_wrong_parameter_rejected_after_rehash(self):
        self.assert_corruption_rejected("grid.json", lambda obj: obj["rows"][0].update(alpha="1/3"), "grid rank/status mismatch")

    def test_uncovered_is_not_infeasible_after_rehash(self):
        self.assert_corruption_rejected("grid.json", lambda obj: obj["rows"][0].update(status="proven_infeasible"), "grid rank/status mismatch")

    def test_false_threshold_rejected_after_rehash(self):
        self.assert_corruption_rejected("thresholds.json", lambda obj: obj["candidates"][0]["threshold"].update(pressure_min="300"), "thresholds/deduplication")

    def test_catalog_checkout_newlines_only_and_real_change_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            alternate_root = Path(temp)
            (alternate_root / "data").mkdir()
            (alternate_root / "experiments/results").mkdir(parents=True)
            # Bind source evidence read-only without copying/changing original files.
            (alternate_root / "experiments/results/block_search_L4_v1").mkdir()
            for name in ("manifest.json", "sha256.json"):
                shutil.copyfile(ROOT / "experiments/results/block_search_L4_v1" / name,
                                alternate_root / "experiments/results/block_search_L4_v1" / name)
            for name in ("items.csv", "trucks.csv"):
                source = (ROOT / "data" / name).read_bytes().replace(b"\r\n", b"\n")
                (alternate_root / "data" / name).write_bytes(source)
            with patch.object(verifier, "ROOT", alternate_root):
                result = verify_bundle(EVIDENCE)
                self.assertTrue(result["passed"], result["errors"])
                path = alternate_root / "data/items.csv"
                original = path.read_text(encoding="utf-8")
                self.assertIn("12", original)
                path.write_text(original.replace("12", "13", 1), encoding="utf-8")
                result = verify_bundle(EVIDENCE)
                self.assertFalse(result["passed"])
                self.assertIn("catalog mismatch: data/items.csv", result["errors"])


if __name__ == "__main__":
    unittest.main()

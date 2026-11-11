"""R6 real evidence, exact witness checks and corruption regression tests."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_block_search import verify_bundle, expected_plan
from experiments.verify_witness_exact import verify
from experiments.summarize_block_search import build_summary

EVIDENCE = ROOT / "experiments/results/block_search_L4_v1"
WITNESS = ROOT / "experiments/results/r6_block_witnesses_v1/one_large.json"


class BlockEvidenceTests(unittest.TestCase):
    def test_full_real_matrix(self):
        self.assertEqual(len(expected_plan()), 96)
        result = verify_bundle(EVIDENCE)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["runs"], 96)
        self.assertEqual(result["complete_runs"], 44)

    def test_missing_run_rejected_even_after_manifest_rehash(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "bundle"
            shutil.copytree(EVIDENCE, directory)
            path = directory / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["runs"].pop()
            path.write_text(json.dumps(manifest), encoding="utf-8")
            hashes = json.loads((directory / "sha256.json").read_text(encoding="utf-8"))
            hashes["files"]["manifest.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
            (directory / "sha256.json").write_text(json.dumps(hashes), encoding="utf-8")
            self.assertFalse(verify_bundle(directory)["passed"])

    def test_exact_arithmetic_real_witness_and_corruptions(self):
        result = verify(WITNESS)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["exact_floor_reaction_kg"], "4110")
        self.assertEqual(result["exact_max_top_pressure_kg_m2"], "2540/7")
        self.assertEqual(result["exact_min_support_ratio"], "1")
        original = json.loads(WITNESS.read_text(encoding="utf-8"))
        mutations = []
        duplicate = copy.deepcopy(original)
        duplicate["fleet"][0]["boxes"][1]["serial"] = duplicate["fleet"][0]["boxes"][0]["serial"]
        mutations.append(duplicate)
        bad_orientation = copy.deepcopy(original)
        box = next(b for b in bad_orientation["fleet"][0]["boxes"] if b["kind"] == "oriented")
        box["l"], box["h"] = box["h"], box["l"]
        mutations.append(bad_orientation)
        floating = copy.deepcopy(original)
        floating["fleet"][0]["boxes"][0]["z"] += 1
        mutations.append(floating)
        with tempfile.TemporaryDirectory() as temp:
            for i, obj in enumerate(mutations):
                path = Path(temp) / f"corrupt_{i}.json"
                path.write_text(json.dumps(obj), encoding="utf-8")
                self.assertFalse(verify(path)["passed"])

    def test_separate_objective_lower_bounds_match_verified_witness(self):
        summary = build_summary(EVIDENCE)
        p1, p2 = summary["certificates"]["P1"], summary["certificates"]["P2"]
        self.assertTrue(p1["proven_optimal"])
        self.assertTrue(p2["proven_optimal"])
        self.assertEqual((p1["lower_bound"], p1["upper_bound"]), (1, 1))
        self.assertEqual((p2["lower_bound"], p2["upper_bound"]), (700, 700))
        self.assertEqual([r["combination"] for r in p2["all_strictly_cheaper_fleets"]], [[0, 0], [1, 0]])


if __name__ == "__main__":
    unittest.main()

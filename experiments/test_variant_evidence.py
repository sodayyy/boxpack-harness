"""R8 evidence checks reject semantic changes even with updated hashes."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_variant_study import verify_bundle

EVIDENCE = ROOT / "experiments/results/quantity_variants_R8_v1"


class VariantEvidenceTests(unittest.TestCase):
    def test_real_complete_matrix(self):
        result = verify_bundle(EVIDENCE)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual((result["runs"], result["cases"]), (288, 12))

    def assert_rejected(self, name, mutate, message):
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
            self.assertTrue(any(message in e for e in result["errors"]), result["errors"])
            self.assertFalse(any("hash mismatch" in e for e in result["errors"]), result["errors"])

    def test_missing_run_rejected_after_rehash(self):
        self.assert_rejected("manifest.json", lambda o: o["runs"].pop(), "incomplete matrix")

    def test_wrong_derived_catalog_rejected_after_rehash(self):
        self.assert_rejected("catalogs/fragile_0.json", lambda o: o["G3"].update(qty=1), "derived catalog mismatch")

    def test_duplicate_identity_rejected_after_rehash(self):
        def mutate(o):
            o["rest_serials"].append(o["fleet"][0]["boxes"][0]["serial"])
        self.assert_rejected("runs/variants_000.json", mutate, "identity conservation")

    def test_false_objective_rejected_after_rehash(self):
        self.assert_rejected("summary.json", lambda o: o["cases"]["base"]["P2"].update(upper_bound=450), "objective/lower-bound/summary")

    def test_protocol_change_rejected_after_rehash(self):
        self.assert_rejected("plan.json", lambda o: o.update(support_ratio=1), "fixed protocol/matrix")


if __name__ == "__main__":
    unittest.main()

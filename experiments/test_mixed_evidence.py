"""R9 semantic evidence regressions, including rehashed corruption."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.verify_mixed_study import verify_bundle
EVIDENCE = ROOT / "experiments/results/mixed_blocks_R9_v1"


class MixedEvidenceTests(unittest.TestCase):
    def test_real_complete_matrix(self):
        result = verify_bundle(EVIDENCE)
        self.assertTrue(result["passed"],result["errors"])
        self.assertEqual((result["runs"],result["cases"]),(288,6))

    def assert_rejected(self,name,mutate,message):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)/"bundle"
            shutil.copytree(EVIDENCE,d)
            p = d/name
            obj = json.loads(p.read_text(encoding="utf-8"))
            mutate(obj)
            p.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")
            hp = d/"sha256.json"
            hashes = json.loads(hp.read_text(encoding="utf-8"))
            hashes["files"][name] = hashlib.sha256(p.read_bytes()).hexdigest()
            hp.write_text(json.dumps(hashes),encoding="utf-8")
            result = verify_bundle(d)
            self.assertFalse(result["passed"])
            self.assertTrue(any(message in e for e in result["errors"]),result["errors"])
            self.assertFalse(any("hash mismatch" in e for e in result["errors"]),result["errors"])

    def test_missing_run_rejected_after_rehash(self):
        self.assert_rejected("manifest.json",lambda o:o["runs"].pop(),"incomplete matrix")

    def test_wrong_catalog_rejected_after_rehash(self):
        self.assert_rejected("catalogs/fragile_45.json",lambda o:o["G3"].update(qty=46),"derived catalog mismatch")

    def test_wrong_vehicle_order_rejected_after_rehash(self):
        self.assert_rejected("runs/mixed_000.json",lambda o:o["config"].update(vehicle_order=[0,0]),"run configuration mismatch")

    def test_stage_identity_rejected_after_rehash(self):
        self.assert_rejected("runs/mixed_000.json",lambda o:o["search"]["stages"][0]["input_serials"].pop(),"stage input/order mismatch")

    def test_false_cost_rejected_after_rehash(self):
        self.assert_rejected("runs/mixed_000.json",lambda o:o.update(cost=0),"metric mismatch")


if __name__ == "__main__":
    unittest.main()

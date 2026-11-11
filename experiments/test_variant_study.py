"""R8 quantities, restricted recipes, independent objectives and mixed bounds."""
from collections import Counter
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.constraints import load_catalog,load_trucks
from src.block_search import make_blocks
from experiments.variant_study import cases,derived_catalog,expand_catalog,planned_runs,totals,capacity_bounds,summarize
from experiments.verify_variant_study import expected_cases,expected_runs,independent_bounds


class VariantStudyTests(unittest.TestCase):
    def test_fixed_cases_and_matrix_independently_agree(self):
        self.assertEqual(cases(),expected_cases())
        self.assertEqual(planned_runs(),expected_runs())
        self.assertEqual(len(planned_runs()),288)
        self.assertEqual(len({c["id"] for c in cases()}),12)

    def test_quantity_scaling_and_zero_kinds_preserve_original(self):
        base=load_catalog(ROOT/"data/items.csv")
        original=copy.deepcopy(base)
        actual={c["id"]:totals(derived_catalog(base,c["quantities"])) for c in cases()}
        self.assertEqual([actual[k]["items"] for k in ("scale_1_2","base","scale_3_2","scale_2")],[150,300,450,600])
        self.assertEqual(actual["fragile_0"]["fragile_count"],0)
        self.assertEqual(actual["oriented_0"]["oriented_count"],0)
        self.assertEqual(base,original)
        self.assertEqual(actual["base"]["volume_cm3"],28735000)

    def test_all_derived_block_recipes_conserve_identities(self):
        base=load_catalog(ROOT/"data/items.csv")
        for c in cases():
            catalog=derived_catalog(base,c["quantities"])
            items=expand_catalog(catalog)
            for height in (217,247):
                blocks=make_blocks(items,height,capped=True)
                serials=[part[0]["serial"] for b in blocks for part in b["parts"]]
                self.assertEqual(Counter(serials),Counter(it["serial"] for it in items))
                self.assertEqual(len(serials),totals(catalog)["items"])

    def test_invalid_quantity_vectors_rejected(self):
        base=load_catalog(ROOT/"data/items.csv")
        for counts in ([0]*5,[1]*4,[True,1,1,1,1],[-1,1,1,1,1],[1.5,1,1,1,1]):
            with self.assertRaises(ValueError): derived_catalog(base,counts)

    def test_separate_objectives_not_lexicographic(self):
        cat=dict(a=dict(dims=(10,10,5),weight=1,kind="standard",qty=5))
        trucks=dict(s=dict(dims=(10,10,13),cap_weight=100,cost=100),l=dict(dims=(10,10,33),cap_weight=100,cost=1000))
        records=[dict(label="one_large",vehicles=1,cost=1000,complete=True,errors=[]),
                 dict(label="three_small",vehicles=3,cost=300,complete=True,errors=[]),
                 dict(label="partial",vehicles=1,cost=100,complete=False,errors=[])]
        result=summarize(records,cat,trucks)
        self.assertEqual(result["P1"]["witness"],"one_large")
        self.assertEqual(result["P2"]["witness"],"three_small")
        self.assertEqual((result["P1"]["lower_bound"],result["P2"]["lower_bound"]),(1,300))
        self.assertTrue(result["P1"]["proven_optimal"] and result["P2"]["proven_optimal"])
        self.assertEqual(summarize(records[2:],cat,trucks)["status"],"no_complete_witness_not_infeasible")

    def test_capacity_lower_bound_includes_mixed_unsearched_fleets(self):
        cat=dict(a=dict(dims=(10,10,5),weight=1,kind="standard",qty=8))
        trucks=dict(s=dict(dims=(10,10,13),cap_weight=100,cost=100),l=dict(dims=(10,10,33),cap_weight=100,cost=250))
        bounds=capacity_bounds(cat,trucks)
        self.assertEqual((bounds["P1"],bounds["P2"]),(2,350))
        self.assertEqual(bounds,independent_bounds(cat,trucks))
        base=load_catalog(ROOT/"data/items.csv")
        real=load_trucks(ROOT/"data/trucks.csv")
        for c in cases():
            catalog=derived_catalog(base,c["quantities"])
            self.assertEqual(capacity_bounds(catalog,real),independent_bounds(catalog,real))


if __name__=="__main__":
    unittest.main()

"""R9 construction and fixed matrix basics, before the first study run."""
from collections import Counter
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.constraints import load_catalog, load_trucks, check_fleet
from src.pack_lib import TruckType
from src.mixed_blocks import pack_mixed_blocks
from src.block_search import pack_blocks
from experiments.variant_study import derived_catalog, expand_catalog
from experiments.mixed_study import planned_runs, selected_cases, merged_summary
from experiments.verify_mixed_study import expected_runs, expected_cases


class MixedStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_catalog(ROOT/"data/items.csv")
        cls.trucks = load_trucks(ROOT/"data/trucks.csv")
        cls.specs = [TruckType(n,tuple(s["dims"]),s["cap_weight"],s["cost"]) for n,s in cls.trucks.items()]

    def test_fixed_protocol_independently_agrees(self):
        self.assertEqual(selected_cases(),expected_cases())
        self.assertEqual(planned_runs(),expected_runs())
        self.assertEqual(len(planned_runs()),288)

    def test_both_vehicle_orders_conserve_and_referee_accepts(self):
        cat = derived_catalog(self.base,[40,50,15,20,25])
        items = expand_catalog(cat)
        for specs in (self.specs,list(reversed(self.specs))):
            fleet,rest,stats = pack_mixed_blocks(items,specs)
            serials = [b["serial"] for tr in fleet for b in tr["boxes"]]+[b["serial"] for b in rest]
            self.assertEqual(Counter(serials),Counter(b["serial"] for b in items))
            self.assertFalse(check_fleet(fleet,self.trucks,cat,level=4,support_ratio=0,pressure_model="chain_area_v1",require_complete=not rest))
            self.assertEqual([s["truck_type"] for s in stats["stages"]],[s.name for s in specs])

    def test_reproducible_and_input_not_mutated(self):
        items = expand_catalog(derived_catalog(self.base,[8,10,3,4,5]))
        before = copy.deepcopy(items)
        a = pack_mixed_blocks(items,self.specs,axis="xy",rotation="wide")
        b = pack_mixed_blocks(items,self.specs,axis="xy",rotation="wide")
        self.assertEqual(a,b)
        self.assertEqual(items,before)
        self.assertIsNone(a[2]["stages"][1]["search"])

    def test_invalid_configurations_and_old_contract(self):
        items = expand_catalog(derived_catalog(self.base,[8,10,3,4,5]))
        for kwargs in ({"order":"bad"},{"axis":"bad"},{"rotation":"bad"},{"capped":1}):
            with self.assertRaises(ValueError):
                pack_mixed_blocks(items,self.specs,**kwargs)
        with self.assertRaises(ValueError):
            pack_mixed_blocks(items,[])
        with self.assertRaises(ValueError):
            pack_mixed_blocks(items+[items[0]],self.specs)
        with self.assertRaisesRegex(ValueError,"equal-height"):
            pack_blocks(items,self.specs)

    def test_separate_objective_merge_preserves_r8_alternative(self):
        cat = derived_catalog(self.base,[120,150,45,60,75])
        def r(label,vehicles,cost):
            return dict(label=label,vehicles=vehicles,cost=cost,complete=True,errors=[],config=dict(case="scale_3_2"))
        old = [r("two_large",2,1400),r("three_small",3,1350)]
        result = merged_summary([],old,{"scale_3_2":cat},self.trucks)["scale_3_2"]
        self.assertEqual((result["P1"]["upper_bound"],result["P2"]["upper_bound"]),(2,1350))
        result = merged_summary([r("mixed",2,1150)],old,{"scale_3_2":cat},self.trucks)["scale_3_2"]
        self.assertTrue(result["P1"]["proven_optimal"])
        self.assertTrue(result["P2"]["proven_optimal"])
        self.assertEqual(result["P2"]["source"],"R9")


if __name__ == "__main__":
    unittest.main()

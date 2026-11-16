"""Catch ignored pressure in recipes/insertion, and silent identity loss."""
from pathlib import Path
import sys
import unittest
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.block_search import make_blocks, pack_blocks
from src.constrained_ep import ChainTruck
from src.pack_lib import expand_items, TRUCKS
from src.constraints import audit_load_chain


class PressureSearchTests(unittest.TestCase):
    def test_recipe_shortens_g2_columns_at_350(self):
        blocks = make_blocks(expand_items(), 247, True, max_pressure=350)
        g2 = [b for b in blocks if any(p[0]['name'] == 'G2' for p in b['parts'])]
        self.assertEqual(max(sum(p[0]['name'] == 'G2' for p in b['parts']) for b in g2), 14)
        serials = [p[0]['serial'] for b in blocks for p in b['parts']]
        self.assertEqual(sorted(serials), sorted(it['serial'] for it in expand_items()))
        for block in blocks:
            boxes = [dict(serial=i['serial'], name=i['name'], kind=i['kind'], weight=i['weight'],
                          x=x, y=y, z=z, l=l, w=w, h=h)
                     for i,x,y,z,l,w,h in block['parts']]
            self.assertFalse(audit_load_chain(boxes, max_pressure=350)['errors'])

    def test_insertion_uses_requested_pressure_not_default(self):
        items = [i for i in expand_items() if i['name'] == 'G2'][:8]
        tr = ChainTruck(TRUCKS[1], support_ratio=1, max_pressure=300)
        for j, item in enumerate(items[:7]):
            tr.put(item, 0, 0, 25*j, 50, 35, 25)
        with self.assertRaises(ValueError):
            tr.put(items[7], 0, 0, 175, 50, 35, 25)
        self.assertEqual(len(tr.boxes), 7)

    def test_pack_threads_pressure_and_clearance(self):
        items = [i for i in expand_items() if i['name'] == 'G2'][:16]
        fleet, rest, stats = pack_blocks(items, [TRUCKS[1]], max_pressure=300,
                                         clearance=10, support_ratio=1)
        self.assertFalse(rest)
        boxes = fleet[0]['boxes']
        self.assertLessEqual(max(b['z']+b['h'] for b in boxes), 240)
        self.assertFalse(audit_load_chain(boxes, max_pressure=300)['errors'])
        self.assertEqual(len(boxes), 16)

    def test_zero_pressure_uses_ground_singletons(self):
        blocks = make_blocks(expand_items(), 247, True, max_pressure=0)
        self.assertTrue(all(len(b['parts']) == 1 for b in blocks))
        self.assertEqual(len(blocks), 300)

    def test_invalid_pressure_rejected(self):
        for p in (-1, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                make_blocks(expand_items(), 247, max_pressure=p)
            with self.assertRaises(ValueError):
                ChainTruck(TRUCKS[1], max_pressure=p)

    def test_fixed_grid_has_no_adaptive_expansion(self):
        from experiments.search_pressure350 import planned_runs
        plan = planned_runs()
        self.assertEqual(len(plan), 48)
        self.assertEqual(len({tuple(sorted(c.items())) for c in plan}), 48)

    def test_worker_marks_partial_without_global_infeasibility(self):
        from experiments.search_pressure350 import run_one
        from src.pack_lib import TruckType
        items = [i for i in expand_items() if i['name'] == 'G3'][:2]
        fleet, row = run_one(dict(capped=False, order='area', axis='yx', rotation='original'),
                             items=items, specs=[TruckType('tiny', (50,40,250),10000,700)])
        self.assertEqual(row['status'], 'partial')
        self.assertEqual(row['placed'], 1)
        self.assertEqual(len(row['rest_serials']), 1)
        self.assertEqual(len(fleet), 1)

    def test_snapshot_recipe_load_never_writes_inside_evidence(self):
        # A bytecode-writing loader contaminates the strict historical bundle.
        import shutil
        import tempfile
        from experiments import verify_pressure350
        self.assertTrue(callable(getattr(verify_pressure350, 'load_recipe_snapshot', None)),
                        'read-only snapshot loader not implemented')
        source = ROOT / 'experiments/results/block_search_L4_v1/snapshot/src/block_search.py'
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'snapshot.py'
            shutil.copyfile(source, path)
            before = {p.relative_to(d).as_posix(): p.read_bytes()
                      for p in Path(d).rglob('*') if p.is_file()}
            module = verify_pressure350.load_recipe_snapshot(path)
            blocks = module.make_blocks(expand_items(), 247, True)
            self.assertEqual(sum(len(b['parts']) for b in blocks), 300)
            after = {p.relative_to(d).as_posix(): p.read_bytes()
                     for p in Path(d).rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_exact_g2_threshold_inclusive(self):
        p = Fraction(2540, 7)
        at = make_blocks(expand_items(), 247, True, max_pressure=p)
        below = make_blocks(expand_items(), 247, True, max_pressure=p-Fraction(1,1000))
        count = lambda bs: max(sum(q[0]['name']=='G2' for q in b['parts']) for b in bs)
        self.assertEqual(count(at), 16)
        self.assertEqual(count(below), 14)


if __name__ == '__main__':
    unittest.main()

"""Behavior tests: prevent false optimality, stale reports and silent bad inputs."""
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ParameterTaskTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.parameter_task'),
                             'parameter task adapter is not implemented')
        return importlib.import_module('experiments.parameter_task')

    def task(self, **changes):
        return dict(alpha='1', pressure='500', clearance='3', **changes)

    def test_standard_closes_both_objectives(self):
        r = self.api().run_task(self.task())
        self.assertEqual(r['bounds'], {'vehicles': [1, 1], 'cost_yuan': [700, 700]})
        self.assertEqual(r['status'], 'optimal_certified')
        self.assertTrue(all(w['feasible'] for w in r['witnesses']))

    def test_350_preserves_unknown_not_infeasible(self):
        api = self.api()
        historical = [ROOT / 'experiments/results/r6_block_witnesses_v1' / f
                      for f in ('one_large.json', 'two_small.json')]
        r = api.run_task(dict(alpha='1', pressure='350', clearance='3'), witness_paths=historical)
        self.assertEqual(r['bounds'], {'vehicles': [1, 2], 'cost_yuan': [700, 900]})
        self.assertEqual(r['status'], 'bounded_unknown')
        self.assertEqual([w['feasible'] for w in r['witnesses']], [False, True])
        self.assertEqual(r['witnesses'][0]['threshold']['pressure_min'], '2540/7')
        self.assertFalse(r['new_search_performed'])

    def test_no_saved_witness_is_not_proof_of_infeasibility(self):
        r = self.api().run_task(dict(alpha='1', pressure='0', clearance='3'))
        self.assertEqual(r['bounds'], {'vehicles': [1, None], 'cost_yuan': [700, None]})
        self.assertEqual(r['status'], 'bounded_unknown')

    def test_exact_inclusive_boundary_and_below(self):
        api = self.api()
        historical = [ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json']
        equal = api.run_task(dict(alpha='1', pressure='2540/7', clearance='10'), witness_paths=historical)
        below = api.run_task(dict(alpha='1', pressure='2539999/7000', clearance='10'), witness_paths=historical)
        self.assertEqual(equal['status'], 'optimal_certified')
        self.assertFalse(below['witnesses'][0]['feasible'])
        self.assertEqual(below['status'], 'bounded_unknown')

    def test_default_pool_reuses_new_witness_without_search(self):
        r = self.api().run_task(dict(alpha='1', pressure='350', clearance='3'))
        self.assertEqual(r['status'], 'optimal_certified')
        self.assertEqual(r['bounds'], {'vehicles': [1, 1], 'cost_yuan': [700, 700]})
        self.assertEqual([w['feasible'] for w in r['witnesses'][:3]], [False, True, True])
        self.assertEqual(r['witnesses'][2]['threshold']['pressure_min'], '675/2')
        self.assertFalse(r['new_search_performed'])

    def test_new_default_inclusive_boundary_and_below(self):
        api = self.api()
        historical = [ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json',
                      ROOT / 'experiments/results/r6_block_witnesses_v1/two_small.json',
                      ROOT / 'experiments/results/pressure350_registered_v1/one_large.json']
        equal = api.run_task(dict(alpha='1', pressure='675/2', clearance='10'), witness_paths=historical)
        below = api.run_task(dict(alpha='1', pressure='337499/1000', clearance='10'), witness_paths=historical)
        self.assertEqual(equal['status'], 'optimal_certified')
        self.assertEqual(below['status'], 'bounded_unknown')
        self.assertEqual(below['bounds'], {'vehicles': [1, None], 'cost_yuan': [700, None]})

    def test_method_study_frontier_is_registered_and_boundary_exact(self):
        api = self.api()
        task = dict(alpha='1', pressure='1900/7', clearance='30')
        equal = api.run_task(task)
        self.assertEqual(equal['bounds'], {'vehicles':[1,1], 'cost_yuan':[700,700]})
        below = api.run_task(dict(alpha='1', pressure='271428/1000', clearance='30'))
        self.assertEqual(below['status'], 'bounded_unknown')
        self.assertEqual(below['bounds'], {'vehicles':[1,2], 'cost_yuan':[700,1150]})
        low = api.run_task(dict(alpha='1', pressure='250', clearance='3'))
        self.assertEqual(low['bounds'], {'vehicles':[1,2], 'cost_yuan':[700,900]})

    def test_historical_pool_report_not_current_for_default_pool(self):
        api = self.api()
        historical = [ROOT / 'experiments/results/r6_block_witnesses_v1' / f
                      for f in ('one_large.json', 'two_small.json')]
        task = dict(alpha='1', pressure='350', clearance='3')
        r = api.run_task(task, witness_paths=historical)
        self.assertFalse(api.is_current(r, task))
        self.assertTrue(api.is_current(r, task, witness_paths=historical))

    def test_changed_witness_invalidates_bound_report(self):
        api = self.api()
        source = ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json'
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'witness.json'
            path.write_bytes(source.read_bytes())
            r = api.run_task(self.task(), witness_paths=[path])
            self.assertTrue(api.is_current(r, self.task(), witness_paths=[path]))
            path.write_bytes(path.read_bytes() + b'\n')
            self.assertFalse(api.is_current(r, self.task(), witness_paths=[path]))

    def test_rule_metadata_cannot_bypass_supported_protocol(self):
        api = self.api()
        source = ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json'
        for ratio in (True, -1, 2, 'NaN'):
            record = json.loads(source.read_text(encoding='utf-8'))
            record['rules']['support_ratio'] = ratio
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'bad.json'
                path.write_text(json.dumps(record), encoding='utf-8')
                r = api.run_task(self.task(), witness_paths=[path])
            self.assertEqual(r['status'], 'execution_failed', ratio)
            self.assertIsNone(r['bounds']['vehicles'][1])

    def test_missing_fields_returns_question_without_execution(self):
        r = self.api().run_task({'pressure': '350'})
        self.assertEqual(r['status'], 'needs_input')
        self.assertEqual(set(r['missing_fields']), {'alpha', 'clearance'})
        self.assertNotIn('bounds', r)

    def test_invalid_values_rejected_without_bounds(self):
        api = self.api()
        for field, value in [('alpha', '2'), ('pressure', '-1'), ('clearance', '-1'),
                             ('pressure', 'NaN'), ('pressure', True), ('pressure', '350 Pa')]:
            t = self.task()
            t[field] = value
            r = api.run_task(t)
            self.assertEqual(r['status'], 'invalid_input', (field, value))
            self.assertNotIn('bounds', r)

    def test_unrecognized_fields_not_silently_ignored(self):
        t = self.task()
        t['pressure_unit'] = 'Pa'
        self.assertEqual(self.api().run_task(t)['status'], 'invalid_input')

    def test_changed_parameter_invalidates_current_binding(self):
        api = self.api()
        r = api.run_task(self.task())
        self.assertTrue(api.is_current(r, self.task()))
        self.assertFalse(api.is_current(r, dict(alpha='1', pressure='350', clearance='3')))
        self.assertFalse(api.is_current(r, {'pressure': '500'}))

    def test_missing_witness_is_execution_error_not_infeasible(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.api().run_task(self.task(), witness_paths=[Path(d) / 'missing.json'])
        self.assertEqual(r['status'], 'execution_failed')
        self.assertEqual(r['bounds'], {'vehicles': [1, None], 'cost_yuan': [700, None]})
        self.assertTrue(r['errors'])

    def test_damaged_layout_cannot_supply_upper_bound(self):
        source = ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json'
        record = json.loads(source.read_text(encoding='utf-8'))
        record['fleet'][0]['boxes'].pop()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.json'
            p.write_text(json.dumps(record), encoding='utf-8')
            r = self.api().run_task(self.task(), witness_paths=[p])
        self.assertEqual(r['status'], 'execution_failed')
        self.assertIsNone(r['bounds']['cost_yuan'][1])

    def test_unsupported_rule_is_rejected(self):
        source = ROOT / 'experiments/results/r6_block_witnesses_v1/one_large.json'
        record = json.loads(source.read_text(encoding='utf-8'))
        record['rules']['pressure_model'] = 'legacy_b1'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.json'
            p.write_text(json.dumps(record), encoding='utf-8')
            r = self.api().run_task(self.task(), witness_paths=[p])
        self.assertEqual(r['status'], 'execution_failed')
        self.assertIsNone(r['bounds']['cost_yuan'][1])

    def test_changed_data_invalidates_report(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'data').mkdir()
            for f in ['items.csv', 'trucks.csv']:
                (root / 'data' / f).write_bytes((ROOT / 'data' / f).read_bytes())
            r = api.run_task(self.task(), root=root)
            # Existing default witness paths resolve from the actual repository.
            self.assertEqual(r['status'], 'optimal_certified')
            (root / 'data/items.csv').write_bytes(b'changed catalog')
            self.assertFalse(api.is_current(r, self.task(), root=root))
            self.assertEqual(api.run_task(self.task(), root=root)['status'], 'execution_failed')


if __name__ == '__main__':
    unittest.main()

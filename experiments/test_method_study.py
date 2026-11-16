"""Behavior tests for equal-budget full-constraint study and independent ranking."""
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MethodStudyTests(unittest.TestCase):
    def api(self):
        return importlib.import_module('experiments.method_study')

    def test_quantity_variant_preserves_identity_and_types(self):
        items, catalog = self.api().scenario_items([1, 2, 1, 0, 0])
        self.assertEqual([i['serial'] for i in items], ['G1-000', 'G2-000', 'G2-001', 'G3-000'])
        self.assertEqual(catalog['G2']['qty'], 2)
        self.assertEqual(items[-1]['kind'], 'fragile')
        with self.assertRaises(ValueError):
            self.api().scenario_items([True, 0, 0, 0, 0])

    def test_capacity_bounds_and_cost_domain_not_lexicographic(self):
        api = self.api()
        items, _ = api.scenario_items([80, 100, 30, 40, 50])
        self.assertEqual(api.capacity_bounds(items, 3), {'vehicles': 1, 'cost': 700})
        self.assertIn([0, 0, 0], api.fleet_sequences(items, 3))
        items, _ = api.scenario_items([160, 200, 60, 80, 100])
        self.assertEqual(api.capacity_bounds(items, 3), {'vehicles': 2, 'cost': 1150})
        # 57.470 m3 cargo > 3 * 19.1394 m3 effective small capacity.
        self.assertNotIn([0, 0, 0], api.fleet_sequences(items, 3))
        self.assertIn([0, 1], api.fleet_sequences(items, 3))
        self.assertNotIn([1], api.fleet_sequences(items, 3))

    def test_partial_and_late_witnesses_never_enter_objective(self):
        rows = [dict(status='verified_complete', vehicles=2, cost=1400, accepted_at=2, id=0),
                dict(status='verified_complete', vehicles=3, cost=1350, accepted_at=5, id=1),
                dict(status='partial', vehicles=1, cost=700, accepted_at=1, id=2),
                dict(status='verified_complete', vehicles=1, cost=700, accepted_at=11, id=3)]
        result = self.api().rank(rows, 10)
        self.assertEqual(result['P1']['id'], 0)
        self.assertEqual(result['P2']['id'], 1)
        self.assertIsNone(self.api().rank(rows, 1)['P1'])

    def test_real_candidate_audited_and_missing_identity_rejected(self):
        api = self.api()
        task = dict(counts=[1,0,0,0,0], alpha='1', pressure='0', clearance=3)
        candidate = dict(method='block_capped', fleet=[1], config=dict(order='area',axis='yx',rotation='original'))
        payload = api.run_candidate(task, candidate)
        self.assertEqual(payload['status'], 'verified_complete')
        self.assertEqual(payload['threshold']['pressure_min'], '0')
        payload['fleet'][0]['boxes'][0]['serial'] = 'G1-999'
        with self.assertRaises(ValueError):
            api.audit_candidate(task, payload['fleet'], [])

    def test_verifier_rejects_missing_matrix_and_hash_tampering(self):
        import tempfile
        import json
        import hashlib
        verifier = importlib.import_module('experiments.verify_method_study')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'summary.json').write_text(json.dumps(dict(groups=[], group_count=0)))
            digest = hashlib.sha256((p/'summary.json').read_bytes()).hexdigest()
            (p/'sha256.json').write_text(json.dumps({'summary.json':digest}))
            result = verifier.verify(p)
            self.assertFalse(result['passed'])
            self.assertIn('matrix', result['errors'][0])
            (p/'summary.json').write_text('{}')
            result = verifier.verify(p)
            self.assertFalse(result['passed'])
            self.assertIn('hash', result['errors'][0])

    def test_envelope_separates_pool_upper_and_global_lower(self):
        verifier = importlib.import_module('experiments.verify_method_study')
        profiles = [dict(alpha_max='1',pressure_min='300',clearance_max='10',vehicles=2,cost=1400),
                    dict(alpha_max='1',pressure_min='250',clearance_max='3',vehicles=3,cost=1350)]
        result = verifier.envelope(profiles, '1', '300', 3, dict(vehicles=1,cost=700))
        self.assertEqual(result['vehicles'], [1,2])
        self.assertEqual(result['cost'], [700,1350])
        self.assertEqual(result['status'], 'bounds_gap')
        empty = verifier.envelope(profiles, '1', '200', 3, dict(vehicles=1,cost=700))
        self.assertEqual(empty['vehicles'], [1,None])
        self.assertEqual(empty['status'], 'pool_uncovered_not_infeasible')

    def test_partial_identity_conservation_is_checked(self):
        task = dict(counts=[1,0,0,0,0], alpha='1', pressure='0', clearance=3)
        with self.assertRaises(ValueError):
            self.api().audit_candidate(task, [], [])


if __name__ == '__main__':
    unittest.main()

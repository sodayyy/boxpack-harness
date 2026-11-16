"""Recheck saved witnesses for the original catalog; no new packing search.

Parameters are explicit rational strings: alpha (ratio), pressure (kg/m^2),
clearance (cm). Exact integer/rational checks govern feasibility; the legacy
floating referee is cross-checked, never silently allowed to overrule them.
"""
import argparse
import datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.parameter_envelope import fraction, exact_thresholds, accepts, check_parameter_fleet
from src.constraints import load_catalog, load_trucks
from src.solution_io import read_solution

FIELDS = ('alpha', 'pressure', 'clearance')
CATALOG_HASHES = {
    'data/items.csv': '1a7dc169daf5134ef20823e4361c30d7b4d3da263c01ac1eea4ea9657c21436f',
    'data/trucks.csv': '0419ec6ccb5f054d12660c45b32a549d58aeb39ea5528858ff2b324bc1a6f106',
}
DEFAULT_WITNESSES = [ROOT / 'experiments/results/r6_block_witnesses_v1' / f
                     for f in ('one_large.json', 'two_small.json')]
DEFAULT_WITNESSES.append(ROOT / 'experiments/results/pressure350_registered_v1/one_large.json')
DEFAULT_WITNESSES.extend(ROOT / 'experiments/results/method_frontier_registered_v1' / f'layout_{i:02d}.json'
                         for i in range(5))
SOURCE_FILES = [Path(__file__), ROOT / 'experiments/parameter_envelope.py',
                ROOT / 'src/constraints.py', ROOT / 'src/solution_io.py']


def normalize(task):
    if not isinstance(task, dict) or set(task) != set(FIELDS):
        raise ValueError('exactly alpha, pressure, clearance are required')
    a, p, d = (fraction(task[k]) for k in FIELDS)
    if not 0 <= a <= 1 or p < 0 or d < 0:
        raise ValueError('alpha must be in [0,1]; pressure and clearance nonnegative')
    return dict(zip(FIELDS, map(str, (a, p, d))))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binding(task, root, witness_paths):
    files = [root / p for p in CATALOG_HASHES] + list(witness_paths) + SOURCE_FILES
    return dict(parameters=normalize(task), rules='L4_chain_area_v1',
                files={str(p.resolve()): digest(p) for p in files})


def is_current(report, task, root=ROOT, witness_paths=None):
    """Match the requested pool (current default unless explicit), not approval.

    This is cache invalidation, not a report authenticity or proof validator.
    """
    try:
        paths = list(DEFAULT_WITNESSES) if witness_paths is None else [Path(p) for p in witness_paths]
        recorded = [str(Path(w['path']).resolve()) for w in report['witnesses']]
        return (recorded == [str(p.resolve()) for p in paths] and
                report['status'] in ('optimal_certified', 'bounded_unknown') and
                report['binding'] == binding(task, Path(root), paths))
    except (KeyError, ValueError, TypeError, OSError):
        return False


def run_task(task, root=ROOT, witness_paths=None):
    start = time.perf_counter()
    report = dict(schema_version=2, started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  mode='saved_witness_recheck', new_search_performed=False,
                  human_conclusion_confirmation='pending', errors=[], witnesses=[],
                  units=dict(alpha='ratio', pressure='kg/m^2', clearance='cm'),
                  python=sys.version, platform=platform.platform())
    if isinstance(task, dict) and not set(task) - set(FIELDS):
        missing = [k for k in FIELDS if k not in task or task[k] is None or task[k] == '']
        if missing:
            return dict(report, status='needs_input', missing_fields=missing)
    try:
        params = normalize(task)
    except (ValueError, TypeError) as exc:
        return dict(report, status='invalid_input', errors=[str(exc)])
    report['parameters'] = params
    root = Path(root)
    paths = DEFAULT_WITNESSES if witness_paths is None else [Path(p) for p in witness_paths]
    try:
        # Scope guard: lower bounds are for this catalog, not arbitrary inputs.
        for rel, expected in CATALOG_HASHES.items():
            actual = hashlib.sha256((root / rel).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            if actual != expected:
                raise ValueError('unsupported catalog bytes: ' + rel)
        catalog = load_catalog(root / 'data/items.csv')
        trucks = load_trucks(root / 'data/trucks.csv')
        volume = sum(s['dims'][0] * s['dims'][1] * s['dims'][2] * s['qty'] for s in catalog.values())
        # Nonempty cargo needs >=1 vehicle. Below 700 yuan, only zero vehicles
        # or a single 450-yuan small vehicle exist. Its NOMINAL volume already
        # falls short, hence the bound holds for all nonnegative clearances.
        small = trucks['车型1']
        small_volume = small['dims'][0] * small['dims'][1] * small['dims'][2]
        if not (volume > small_volume and small['cost'] == 450 and trucks['车型2']['cost'] == 700):
            raise ValueError('lower-bound assumptions do not hold')
        report['lower_bound_evidence'] = dict(cargo_volume_cm3=volume,
            single_small_nominal_volume_cm3=small_volume,
            cheaper_than_700_fleets='zero vehicles or one small vehicle; both excluded by volume',
            vehicle_lower=1, cost_lower_yuan=700)
        report['bounds'] = dict(vehicles=[1, None], cost_yuan=[700, None])
        if not paths:
            raise ValueError('at least one witness file is required')
        report['witness_pool'] = 'current_default' if witness_paths is None else 'explicit_selection'
        for path in paths:
            w = dict(path=str(path.resolve()), feasible=False)
            report['witnesses'].append(w)
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                rules = record.get('rules')
                if (not isinstance(rules, dict) or
                        set(rules) != {'level', 'support_ratio', 'pressure_model'} or
                        type(rules['level']) is not int or rules['level'] != 4 or
                        rules['pressure_model'] != 'chain_area_v1' or
                        not 0 <= fraction(rules['support_ratio']) <= 1):
                    raise ValueError('unsupported saved witness rule protocol')
                # The saved support ratio describes generation, not a waiver
                # or a feasibility result for this request. Recompute below.
                w['generation_rules'] = rules
                fleet = read_solution(path, trucks)
                threshold = exact_thresholds(fleet, trucks, catalog)
                w['threshold'] = threshold
                exact_ok = accepts(threshold, **params)
                errors = check_parameter_fleet(fleet, trucks, catalog, **params)
                w.update(exact_accepts=exact_ok, referee_errors=errors, sha256=digest(path))
                if exact_ok != (not errors):
                    raise ValueError('exact/float referee disagreement; no certificate issued')
                w['feasible'] = exact_ok
                w['status'] = 'verified_feasible' if exact_ok else 'fixed_layout_invalid'
                w['violated_parameters'] = [k for k, invalid in (
                    ('alpha', Fraction(params['alpha']) > Fraction(threshold['alpha_max'])),
                    ('pressure', Fraction(params['pressure']) < Fraction(threshold['pressure_min'])),
                    ('clearance', Fraction(params['clearance']) > Fraction(threshold['clearance_max']))) if invalid]
                if exact_ok:
                    for key, val in [('vehicles', threshold['vehicles']), ('cost_yuan', threshold['cost'])]:
                        old = report['bounds'][key][1]
                        report['bounds'][key][1] = val if old is None else min(old, val)
            except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
                w['status'] = 'execution_failed'
                w['error'] = str(exc)
                report['errors'].append(str(path) + ': ' + str(exc))
        if not report['errors']:
            report['binding'] = binding(params, root, paths)
        report['status'] = ('execution_failed' if report['errors'] else
                            'optimal_certified' if all(lo == hi for lo, hi in report['bounds'].values())
                            else 'bounded_unknown')
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        report['status'] = 'execution_failed'
        report['errors'].append(str(exc))
    report['elapsed_seconds'] = time.perf_counter() - start
    report['limits'] = ['Only the selected saved witnesses were rechecked.',
                        'No valid saved witness does not prove general infeasibility.',
                        'No moment balance, friction or transport dynamics certification.',
                        'No AI efficiency measurement; this program performs deterministic checks.']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in FIELDS:
        parser.add_argument('--' + field, required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.output.parent.is_dir() or args.output.exists():
        parser.error('output parent must exist and output file must be new')
    result = run_task({k: getattr(args, k) for k in FIELDS})
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'parameters', 'bounds') if k in result}, ensure_ascii=False))
    return 0 if result['status'] in ('optimal_certified', 'bounded_unknown') else 2


if __name__ == '__main__':
    raise SystemExit(main())

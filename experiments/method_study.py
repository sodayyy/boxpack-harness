"""Frozen, sequential equal-wall-budget full-constraint method comparison.

Development cases, not blind evaluation. Referees never call constructors.
Each accepted candidate includes full coordinates and exact threshold summary.
"""
import argparse
from collections import Counter
import datetime
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pack_lib import TYPES, TRUCKS
from src.constrained_ep import pack_fixed_fleet
from src.block_search import pack_blocks
from src.constraints import load_trucks, check_fleet, audit_load_chain
from src.solution_io import export_solution, read_solution, read_solution_csv
from experiments.bench_constrained_fleet import sort_items
from experiments.parameter_envelope import exact_thresholds, accepts, check_parameter_fleet

METHODS = ('ep_multistart', 'block_columns', 'block_capped')
BASE = [80, 100, 30, 40, 50]


def scenario_items(counts):
    if len(counts) != 5 or any(type(n) is not int or n < 0 for n in counts) or not sum(counts):
        raise ValueError('five nonnegative integer counts, nonempty cargo required')
    catalog = {t.name: dict(dims=t.dims, weight=t.weight, kind=t.kind, qty=n)
               for t, n in zip(TYPES, counts)}
    items = [dict(name=t.name, kind=t.kind, dims=t.dims, weight=t.weight, serial=f'{t.name}-{i:03d}')
             for t, n in zip(TYPES, counts) for i in range(n)]
    return items, catalog


def scenarios():
    rows = [dict(id='p_' + p.replace('.', '_'), counts=BASE, alpha='1', pressure=p, clearance=3)
            for p in ('250', '300', '317.5', '337.499', '337.5', '350', '500')]
    rows += [dict(id=f'd_{d}', counts=BASE, alpha='1', pressure='350', clearance=d) for d in (10, 11, 30)]
    rows += [dict(id='a_' + str(i), counts=BASE, alpha=a, pressure='350', clearance=3)
             for i, a in enumerate(('0', '3/4'))]
    for name, counts in [('scale_450', [120,150,45,60,75]), ('scale_600', [160,200,60,80,100]),
                         ('fragile_60', [80,100,60,40,50]), ('oriented_180', [80,100,30,80,100])]:
        rows.append(dict(id=name, counts=counts, alpha='1', pressure='500', clearance=3))
    return rows


def fleet_sequences(items, clearance):
    volume = sum(x['dims'][0]*x['dims'][1]*x['dims'][2] for x in items)
    weight = sum(x['weight'] for x in items)
    return [seq for seq in ([1], [0,0], [0,1], [1,0], [1,1], [0,0,0])
            if sum(TRUCKS[i].dims[0]*TRUCKS[i].dims[1]*max(0, TRUCKS[i].dims[2]-clearance) for i in seq) >= volume
            and sum(TRUCKS[i].cap_weight for i in seq) >= weight]


def capacity_bounds(items, clearance):
    # Each single item fits an available vehicle for our registered cases.
    # Enumerate all counts <= number of items: positive-cost minimizers have
    # <=n nonempty trucks, so this finite relaxation gives global lower bounds.
    volume = sum(x['dims'][0]*x['dims'][1]*x['dims'][2] for x in items)
    weight = sum(x['weight'] for x in items)
    capacities = [t.dims[0]*t.dims[1]*max(0, t.dims[2]-clearance) for t in TRUCKS]
    feasible = [(a+b, 450*a+700*b) for a in range(len(items)+1) for b in range(len(items)+1-a)
                if capacities[0]*a + capacities[1]*b >= volume
                and 6000*a+10000*b >= weight and a+b]
    if not feasible:
        raise ValueError('no capacity relaxation witness within n trucks')
    return dict(vehicles=min(n for n,c in feasible), cost=min(c for n,c in feasible))


def rank(rows, checkpoint):
    valid = [r for r in rows if r['status'] == 'verified_complete' and r['accepted_at'] <= checkpoint]
    return {goal: min(valid, key=lambda r: (r[key], r['id'])) if valid else None
            for goal, key in [('P1', 'vehicles'), ('P2', 'cost')]}


def audit_candidate(task, fleet, rest):
    items, catalog = scenario_items(task['counts'])
    trucks = load_trucks(ROOT/'data/trucks.csv')
    actual = [b['serial'] for t in fleet for b in t['boxes']]
    if Counter(actual + rest) != Counter(i['serial'] for i in items) or len(set(actual)) != len(actual):
        raise ValueError('placed/rest identity conservation failed')
    adjusted = {k: dict(v, dims=(*v['dims'][:2], v['dims'][2]+3-task['clearance'])) for k,v in trucks.items()}
    errors = check_fleet(fleet, adjusted, catalog, level=3, support_ratio=float(Fraction(task['alpha'])),
                         pressure_model='chain_area_v1', require_complete=not rest)
    for tr in fleet:
        errors += audit_load_chain(tr['boxes'], max_pressure=float(Fraction(task['pressure'])))['errors']
    if errors:
        raise ValueError('independent parameter referee: ' + str(errors))
    if rest:
        return None
    threshold = exact_thresholds(fleet, trucks, catalog)
    if not accepts(threshold, task['alpha'], task['pressure'], task['clearance']):
        raise ValueError('exact threshold rejected')
    if check_parameter_fleet(fleet, trucks, catalog, task['alpha'], task['pressure'], task['clearance']):
        raise ValueError('complete independent referee rejected')
    return threshold


def run_candidate(task, candidate):
    start = time.perf_counter()
    items, _ = scenario_items(task['counts'])
    specs = [TRUCKS[i] for i in candidate['fleet']]
    params = dict(clearance=task['clearance'], max_pressure=float(Fraction(task['pressure'])),
                  support_ratio=float(Fraction(task['alpha'])))
    if candidate['method'] == 'ep_multistart':
        fleet, rest = pack_fixed_fleet(sort_items(items, candidate['config']['order']), specs,
                                      ep_cap=1500, **params)
        stats = {}
    else:
        # Same sequential repacking semantics as the historical mixed-height
        # constructor. Also use for equal heights to avoid height-specific bias.
        fleet, rest, stages = [], items, []
        for spec in specs:
            if not rest:
                break
            part, rest, stage = pack_blocks(rest, [spec], capped=candidate['method']=='block_capped',
                                            **params, **candidate['config'])
            fleet.extend(part)
            stages.append(stage)
        stats = dict(stages=stages)
    search_seconds = time.perf_counter()-start
    serials = [it['serial'] for it in rest]
    threshold = audit_candidate(task, fleet, serials)
    return dict(status='partial' if rest else 'verified_complete', fleet=fleet, rest_serials=serials,
                placed=sum(len(t['boxes']) for t in fleet), vehicles=len(fleet),
                cost=sum(TRUCKS[i].cost for t in fleet for i in range(2) if TRUCKS[i].name == t['truck_type']),
                threshold=threshold, search_seconds=search_seconds, stats=stats)


def planned_candidates(task, method):
    items, _ = scenario_items(task['counts'])
    if method == 'ep_multistart':
        configs = [dict(order=o) for o in ('standard_first','volume','height','fragile_last','fragile_first')]
    elif method in METHODS:
        configs = [dict(order=o, axis=a, rotation=r) for o,a,r in itertools.product(
            ('area','long','volume','height'), ('yx','xy'), ('original','wide','long'))]
    else:
        raise ValueError('unknown method')
    return [dict(method=method, fleet=f, config=c) for c in configs for f in fleet_sequences(items, task['clearance'])]


def save(path, data):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def execute(protocol, out):
    if out.exists() or not out.parent.is_dir():
        raise ValueError('new output directory with existing parent required')
    out.mkdir()
    frozen = json.loads(protocol.read_text(encoding='utf-8'))
    save(out/'protocol.json', frozen)
    snapshot_files = ['src/pack_lib.py','src/constrained_ep.py','src/block_search.py',
                      'src/constraints.py','src/solution_io.py','experiments/method_study.py',
                      'experiments/bench_constrained_fleet.py','experiments/parameter_envelope.py',
                      'data/items.csv','data/trucks.csv']
    for rel in snapshot_files:
        target = out/'snapshot'/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/rel).read_bytes())
    save(out/'environment.json', dict(python=sys.version, platform=platform.platform(),
         utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), command=sys.argv))
    save(out/'scenarios.json', scenarios())
    all_groups = []
    for task in scenarios():
        items, _ = scenario_items(task['counts'])
        lower = capacity_bounds(items, task['clearance'])
        for method in METHODS:
            group = out/(task['id']+'__'+method)
            group.mkdir()
            plan = planned_candidates(task, method)
            save(group/'plan.json', dict(task=task, method=method, candidates=plan, lower=lower))
            records = []
            start = time.perf_counter()
            stop_reason = 'all_configurations_exhausted'
            for index, cand in enumerate(plan):
                remaining = 30-(time.perf_counter()-start)
                if remaining <= 0:
                    stop_reason = 'budget_exhausted'
                    break
                request, result = group/f'request_{index:03d}.json', group/f'candidate_{index:03d}.json'
                save(request, dict(task=task, candidate=cand))
                command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', str(request), '--output', str(result)]
                row = dict(id=index, candidate=cand)
                try:
                    proc = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          timeout=remaining, check=False)
                    (group/f'worker_{index:03d}.log').write_bytes(proc.stdout)
                    if proc.returncode:
                        raise ValueError('worker failed: '+proc.stdout.decode(errors='replace')[-2000:])
                    payload = json.loads(result.read_text(encoding='utf-8'))
                    row.update({k:v for k,v in payload.items() if k not in ('fleet','stats')})
                    row['file'] = result.name
                except subprocess.TimeoutExpired as exc:
                    (group/f'worker_{index:03d}.log').write_bytes(exc.stdout or b'')
                    row['status'] = 'timeout'
                    stop_reason = 'budget_exhausted'
                except (ValueError, OSError, KeyError) as exc:
                    row.update(status='execution_failed', error=str(exc))
                row['accepted_at'] = time.perf_counter()-start
                records.append(row)
                save(group/f'record_{index:03d}.json', row)
                if row['status'] == 'execution_failed':
                    stop_reason = 'execution_failure'
                    break
                best = rank(records, 30)
                if (best['P1'] is not None and best['P1']['vehicles'] == lower['vehicles'] and
                        best['P2']['cost'] == lower['cost']):
                    stop_reason = 'both_global_lower_bounds_attained'
                    break
            summary = dict(task=task, method=method, lower=lower, records=records, planned_count=len(plan),
                elapsed=time.perf_counter()-start, stop_reason=stop_reason,
                checkpoints={str(c):rank(records,c) for c in (10,30)})
            save(group/'summary.json', summary)
            all_groups.append(summary)
            print(json.dumps(dict(case=task['id'],method=method,runs=len(records),stop=stop_reason,
                  P1=None if summary['checkpoints']['30']['P1'] is None else summary['checkpoints']['30']['P1']['vehicles'],
                  P2=None if summary['checkpoints']['30']['P2'] is None else summary['checkpoints']['30']['P2']['cost'])), flush=True)
            if stop_reason == 'execution_failure':
                save(out/'failed.json', dict(groups=all_groups))
                return 1
    save(out/'summary.json', dict(groups=all_groups, group_count=len(all_groups)))
    save(out/'sha256.json', {p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in out.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol', type=Path)
    p.add_argument('--worker', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.worker:
        request = json.loads(a.worker.read_text(encoding='utf-8'))
        payload = run_candidate(**request)
        # JSON and CSV roundtrip, including partial candidates. Parent includes
        # this entire worker's imports, checks and serialization in its clock.
        trucks = load_trucks(ROOT/'data/trucks.csv')
        if payload['fleet']:
            jp, cp = a.output.with_suffix('.layout.json'), a.output.with_suffix('.csv')
            export_solution(payload['fleet'],jp,cp,trucks,level=4,
                            support_ratio=float(Fraction(request['task']['alpha'])),pressure_model='chain_area_v1')
            if read_solution(jp,trucks) != payload['fleet'] or read_solution_csv(cp,trucks) != payload['fleet']:
                raise ValueError('JSON/CSV readback mismatch')
        save(a.output,payload)
        return 0
    return execute(a.protocol.resolve(), a.output.resolve())


if __name__ == '__main__':
    raise SystemExit(main())

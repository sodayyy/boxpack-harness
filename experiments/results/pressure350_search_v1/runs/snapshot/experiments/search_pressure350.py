"""Fixed, budgeted original-catalog one-large pressure350 feasibility experiment.

Not a general optimizer or infeasibility prover. Independent acceptance is after
export/readback; pressure also participates in recipes and every insertion.
"""
import argparse
import datetime
import hashlib
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.block_search import pack_blocks
from src.pack_lib import expand_items, TRUCKS
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain
from src.solution_io import export_solution, read_solution, read_solution_csv
from experiments.parameter_envelope import exact_thresholds, accepts, check_parameter_fleet


def planned_runs():
    return [dict(capped=c, order=o, axis=a, rotation=r) for c,o,a,r in itertools.product(
        (False,True), ('area','long','volume','height'), ('yx','xy'), ('original','wide','long'))]


def run_one(config, items=None, specs=None):
    items = expand_items() if items is None else items
    specs = [TRUCKS[1]] if specs is None else specs
    start = time.perf_counter()
    fleet, rest, stats = pack_blocks(items, specs, max_pressure=350, clearance=3,
                                     support_ratio=1, **config)
    return fleet, dict(config=config, status='candidate_complete' if not rest else 'partial',
                       rest_serials=[i['serial'] for i in rest],
                       placed=sum(len(t['boxes']) for t in fleet),
                       search=stats, seconds=time.perf_counter()-start)


def save(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', type=int)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.worker is not None:
        fleet, row = run_one(planned_runs()[args.worker])
        save(out, dict(row, fleet=fleet))
        return 0
    if not out.parent.is_dir():
        parser.error('output parent must exist')
    out.mkdir(exist_ok=False)
    plan = planned_runs()
    save(out/'plan.json', dict(parameters=dict(alpha='1',pressure='350',clearance='3'),
         runs=plan, per_run_seconds=30, total_seconds=600,
         scope='known original instance; restricted constructive feasibility experiment',
         failure_means='unknown, not general infeasibility'))
    snapshot = out/'snapshot'
    snapshot.mkdir()
    for rel in ['src/block_search.py','src/constrained_ep.py','src/pack_lib.py',
                'src/constraints.py','src/solution_io.py','experiments/parameter_envelope.py',
                'experiments/search_pressure350.py','data/items.csv','data/trucks.csv']:
        p = snapshot/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT/rel).read_bytes())
    save(out/'environment.json',dict(python=sys.version, platform=platform.platform(),
         utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),command=sys.argv))
    catalog, trucks = load_catalog(ROOT/'data/items.csv'), load_trucks(ROOT/'data/trucks.csv')
    start = time.perf_counter()
    rows = []
    fatal = False
    for i, config in enumerate(plan):
        remaining = 600-(time.perf_counter()-start)
        row = dict(index=i,config=config)
        if remaining <= 0:
            row['status'] = 'not_run_budget'
            rows.append(row)
            continue
        raw = out/f'raw_{i:03d}.json'
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',str(i),'--output',str(raw)]
        try:
            p = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=min(30,remaining), check=False)
            (out/f'worker_{i:03d}.log').write_bytes(p.stdout)
            row['returncode'] = p.returncode
            if p.returncode:
                raise ValueError('worker execution failed')
            data = json.loads(raw.read_text(encoding='utf-8'))
            fleet = data.pop('fleet')
            row.update(data)
            placed = [b['serial'] for t in fleet for b in t['boxes']]
            expected = sorted(it['serial'] for it in expand_items())
            if sorted(placed+row['rest_serials']) != expected or len(set(placed)) != len(placed):
                raise ValueError('placed/rest identity conservation failed')
            errors = check_fleet(fleet,trucks,catalog,level=3,support_ratio=1,
                                  pressure_model='chain_area_v1',require_complete=not row['rest_serials'])
            for t in fleet:
                errors += audit_load_chain(t['boxes'],max_pressure=350)['errors']
            if errors:
                raise ValueError('partial/full external rejection: '+str(errors))
            row['external_errors'] = errors
            if not row['rest_serials']:
                jp,cp = out/f'witness_{i:03d}.json',out/f'witness_{i:03d}.csv'
                export_solution(fleet,jp,cp,trucks,level=4,support_ratio=1,pressure_model='chain_area_v1')
                reread = read_solution(jp,trucks)
                if reread != read_solution_csv(cp,trucks) or reread != fleet:
                    raise ValueError('coordinate readback mismatch')
                threshold = exact_thresholds(reread,trucks,catalog)
                if not accepts(threshold,'1','350','3') or check_parameter_fleet(reread,trucks,catalog,'1','350','3'):
                    raise ValueError('complete candidate failed exact/readback parameter check')
                row.update(status='verified_complete',threshold=threshold,witness=jp.name)
        except subprocess.TimeoutExpired:
            row['status'] = 'timeout'
        except (ValueError,KeyError,TypeError,OSError) as exc:
            row.update(status='execution_failed',error=str(exc))
            fatal = True
        rows.append(row)
        save(out/f'record_{i:03d}.json',row)
        print(json.dumps({k:row[k] for k in ('index','status','placed') if k in row}),flush=True)
        if fatal:
            break
    complete = [r for r in rows if r['status']=='verified_complete']
    summary = dict(status='execution_failed' if fatal else 'finished',runs=rows,
        planned_count=48,elapsed_seconds=time.perf_counter()-start,
        verified_complete=len(complete),
        bounds=dict(vehicles=[1,1] if complete else [1,2],cost_yuan=[700,700] if complete else [700,900]),
        bound_basis='existing original-catalog lower bounds and prior two-small witness; complete new one-large witness if any',
        no_infeasibility_proof=True)
    save(out/'summary.json',summary)
    hashes = {p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in out.rglob('*') if p.is_file()}
    save(out/'sha256.json',hashes)
    return 1 if fatal else 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Read-only comparison audit; never imports constructors or runner.

Project self-check, not independent third-party review. Reconstructs the fixed
matrix, capacity bounds, ranks, identities, geometry, loads and output readback.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain
from src.solution_io import read_solution, read_solution_csv
from experiments.parameter_envelope import exact_thresholds, accepts, check_parameter_fleet, canonical_digest


def expected_tasks():
    base = [80,100,30,40,50]
    tasks = [dict(id='p_'+p.replace('.','_'),counts=base,alpha='1',pressure=p,clearance=3)
             for p in ('250','300','317.5','337.499','337.5','350','500')]
    tasks += [dict(id=f'd_{d}',counts=base,alpha='1',pressure='350',clearance=d) for d in (10,11,30)]
    tasks += [dict(id=f'a_{i}',counts=base,alpha=a,pressure='350',clearance=3) for i,a in enumerate(('0','3/4'))]
    tasks += [dict(id=i,counts=q,alpha='1',pressure='500',clearance=3) for i,q in (
        ('scale_450',[120,150,45,60,75]),('scale_600',[160,200,60,80,100]),
        ('fragile_60',[80,100,60,40,50]),('oriented_180',[80,100,30,80,100]))]
    return tasks


def lower_bounds(cat, trucks, delta):
    volume = sum(math.prod(s['dims'])*s['qty'] for s in cat.values())
    weight = sum(s['weight']*s['qty'] for s in cat.values())
    capacities = [math.prod(t['dims'][:2])*max(0,t['dims'][2]-delta) for t in trucks.values()]
    # Sufficient bound from homogeneous solutions of the relaxation; not a
    # geometric feasibility assumption. Includes every improving cost fleet.
    needs = [max(math.ceil(Fraction(volume,c)), math.ceil(Fraction(weight,t['cap_weight'])))
             for c,t in zip(capacities,trucks.values())]
    limit = max(min(needs), min(n*t['cost'] for n,t in zip(needs,trucks.values()))//450)
    feasible = [(a+b,450*a+700*b) for a in range(limit+1) for b in range(limit+1-a)
                if a*capacities[0]+b*capacities[1] >= volume and a*6000+b*10000 >= weight]
    return dict(vehicles=min(x[0] for x in feasible),cost=min(x[1] for x in feasible))


def expected_plan(task,method,cat,trucks):
    volume = sum(math.prod(s['dims'])*s['qty'] for s in cat.values())
    weight = sum(s['weight']*s['qty'] for s in cat.values())
    specs = list(trucks.values())
    fleets = [seq for seq in ([1],[0,0],[0,1],[1,0],[1,1],[0,0,0]) if
        sum(math.prod(specs[i]['dims'][:2])*(specs[i]['dims'][2]-task['clearance']) for i in seq)>=volume
        and sum(specs[i]['cap_weight'] for i in seq)>=weight]
    configs = ([dict(order=o) for o in ('standard_first','volume','height','fragile_last','fragile_first')]
               if method=='ep_multistart' else
               [dict(order=o,axis=a,rotation=r) for o,a,r in itertools.product(
                   ('area','long','volume','height'),('yx','xy'),('original','wide','long'))])
    return [dict(method=method,fleet=f,config=c) for c in configs for f in fleets]


def envelope(profiles, alpha, pressure, clearance, lower):
    valid = [t for t in profiles if accepts(t,alpha,pressure,clearance)]
    vehicles = min((t['vehicles'] for t in valid), default=None)
    cost = min((t['cost'] for t in valid), default=None)
    status = ('pool_uncovered_not_infeasible' if not valid else 'optimal_certified'
              if vehicles==lower['vehicles'] and cost==lower['cost'] else 'bounds_gap')
    return dict(vehicles=[lower['vehicles'],vehicles],cost=[lower['cost'],cost],status=status)


def verify(directory):
    directory = Path(directory).resolve()
    result = dict(passed=False,errors=[],groups=[],verified_candidates=0,complete_candidates=0)
    try:
        read = lambda p: json.loads((directory/p).read_text(encoding='utf-8'))
        hashes = read('sha256.json')
        for name,digest in hashes.items():
            p = (directory/name).resolve()
            if not p.is_relative_to(directory) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                raise ValueError('hash mismatch: '+name)
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
        if actual != set(hashes)|{'sha256.json'}:
            raise ValueError('hash file set mismatch')
        summary = read('summary.json')
        keys = [(t['id'],m) for t in expected_tasks() for m in ('ep_multistart','block_columns','block_capped')]
        if summary['group_count'] != 48 or [(g['task']['id'],g['method']) for g in summary['groups']]!=keys:
            raise ValueError('fixed 48-group matrix missing/duplicate/mismatch')
        if read('scenarios.json') != expected_tasks():
            raise ValueError('scenario matrix mismatch')
        catalog = load_catalog(directory/'snapshot/data/items.csv')
        trucks = load_trucks(directory/'snapshot/data/trucks.csv')
        for rel in ('data/items.csv','data/trucks.csv'):
            if (directory/'snapshot'/rel).read_text(encoding='utf-8') != (ROOT/rel).read_text(encoding='utf-8'):
                raise ValueError('catalog source mismatch')
        for group,(taskid,method) in zip(summary['groups'],keys):
            task = next(t for t in expected_tasks() if t['id']==taskid)
            if group['task'] != task:
                raise ValueError('group scenario mismatch')
            cat = {n:dict(s,qty=q) for (n,s),q in zip(catalog.items(),task['counts'])}
            ids = Counter(f'{n}-{i:03d}' for n,s in cat.items() for i in range(s['qty']))
            path = taskid+'__'+method
            if read(path+'/summary.json') != group:
                raise ValueError('summary readback mismatch')
            plan = expected_plan(task,method,cat,trucks)
            lower = lower_bounds(cat,trucks,task['clearance'])
            if read(path+'/plan.json') != dict(task=task,method=method,candidates=plan,lower=lower):
                raise ValueError('candidate plan mismatch')
            records = group['records']
            if group['planned_count']!=len(plan) or group['lower']!=lower or not records:
                raise ValueError('counts/bounds mismatch')
            previous = 0
            for index,row in enumerate(records):
                if row['id']!=index or row['candidate']!=plan[index] or row['accepted_at']<previous:
                    raise ValueError('run identity/order/time mismatch')
                previous=row['accepted_at']
                if read(f'{path}/record_{index:03d}.json')!=row:
                    raise ValueError('record mismatch')
                if read(f'{path}/request_{index:03d}.json') != dict(task=task,candidate=plan[index]):
                    raise ValueError('worker request mismatch')
                if row['status']=='timeout':
                    if index!=len(records)-1 or row['accepted_at']<29:
                        raise ValueError('invalid timeout metadata')
                    continue
                if row['status'] not in ('partial','verified_complete'):
                    raise ValueError('unresolved execution failure')
                payload = read(path+'/'+row['file'])
                for key,val in payload.items():
                    if key not in ('fleet','stats') and row[key]!=val:
                        raise ValueError('candidate metadata differs')
                fleet,rest = payload['fleet'],payload['rest_serials']
                boxes = [b for tr in fleet for b in tr['boxes']]
                if Counter([b['serial'] for b in boxes]+rest)!=ids:
                    raise ValueError('identity conservation failed')
                allowed = Counter(list(trucks)[i] for i in plan[index]['fleet'])
                if Counter(tr['truck_type'] for tr in fleet)-allowed or any(not tr['boxes'] for tr in fleet):
                    raise ValueError('undeclared vehicle')
                expected_complete = not rest
                if (row['status']=='verified_complete')!=expected_complete:
                    raise ValueError('partial accepted as complete')
                if row['vehicles']!=len(fleet) or row['cost']!=sum(trucks[t['truck_type']]['cost'] for t in fleet) or row['placed']!=len(boxes):
                    raise ValueError('wrong objectives')
                adj = {n:dict(s,dims=(*s['dims'][:2],s['dims'][2]+3-task['clearance'])) for n,s in trucks.items()}
                errors = check_fleet(fleet,adj,cat,level=3,support_ratio=float(Fraction(task['alpha'])),
                                     pressure_model='chain_area_v1',require_complete=expected_complete)
                for tr in fleet:
                    errors+=audit_load_chain(tr['boxes'],max_pressure=float(Fraction(task['pressure'])))['errors']
                if errors:
                    raise ValueError('referee rejected: '+str(errors))
                if fleet:
                    jp=directory/path/row['file'].replace('.json','.layout.json')
                    cp=directory/path/row['file'].replace('.json','.csv')
                    if read_solution(jp,trucks)!=fleet or read_solution_csv(cp,trucks)!=fleet:
                        raise ValueError('layout coordinate readback mismatch')
                if expected_complete:
                    th=exact_thresholds(fleet,trucks,cat)
                    if th!=row['threshold'] or not accepts(th,task['alpha'],task['pressure'],task['clearance']):
                        raise ValueError('rational threshold mismatch')
                    if check_parameter_fleet(fleet,trucks,cat,task['alpha'],task['pressure'],task['clearance']):
                        raise ValueError('complete parameter referee mismatch')
                    result['complete_candidates']+=1
                result['verified_candidates']+=1
            for checkpoint in (10,30):
                valid=[r for r in records if r['status']=='verified_complete' and r['accepted_at']<=checkpoint]
                expected={g:min(valid,key=lambda r:(r[k],r['id'])) if valid else None for g,k in [('P1','vehicles'),('P2','cost')]}
                if group['checkpoints'][str(checkpoint)]!=expected:
                    raise ValueError('independent objective/checkpoint mismatch')
            best=group['checkpoints']['30']
            stop=group['stop_reason']
            if stop=='both_global_lower_bounds_attained':
                if best['P1'] is None or best['P1']['vehicles']!=lower['vehicles'] or best['P2']['cost']!=lower['cost']:
                    raise ValueError('unjustified early optimal stop')
            elif stop=='all_configurations_exhausted':
                if len(records)!=len(plan):
                    raise ValueError('incomplete plan not accounted for')
            elif stop=='budget_exhausted':
                if group['elapsed']<29:
                    raise ValueError('invalid budget stop')
            else:
                raise ValueError('unexpected stopping reason')
            result['groups'].append(dict(case=taskid,method=method,runs=len(records),
                complete=sum(r['status']=='verified_complete' for r in records),
                timeouts=sum(r['status']=='timeout' for r in records),
                P1=None if best['P1'] is None else best['P1']['vehicles'],
                P2=None if best['P2'] is None else best['P2']['cost']))
        result.update(passed=True,hashes=len(hashes),matrix_groups=48)
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        result['errors'].append(str(exc))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=verify(a.directory)
    with a.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='groups'},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)

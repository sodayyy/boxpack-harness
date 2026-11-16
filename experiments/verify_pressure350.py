"""Read-only recheck of a completed pressure350 fixed experiment, no search."""
import argparse
import hashlib
import types
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.constraints import load_catalog,load_trucks
from src.solution_io import read_solution,read_solution_csv
from experiments.parameter_envelope import exact_thresholds,accepts,check_parameter_fleet,canonical_digest
from src.block_search import make_blocks
from src.pack_lib import expand_items


def load_recipe_snapshot(path):
    """Execute our trusted historical source in memory without writing pyc."""
    path = Path(path)
    module = types.ModuleType('old_block_recipes')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def verify(directory):
    runs=Path(directory)
    hashes=json.loads((runs/'sha256.json').read_text())
    assert all(hashlib.sha256((runs/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
    summary=json.loads((runs/'summary.json').read_text())
    assert summary['status']=='finished' and len(summary['runs'])==48
    catalog=load_catalog(ROOT/'data/items.csv')
    trucks=load_trucks(ROOT/'data/trucks.csv')
    verified=[]
    layouts=set()
    for row in summary['runs']:
        if row['status']!='verified_complete':
            continue
        path=runs/row['witness']
        fleet=read_solution(path,trucks)
        assert fleet==read_solution_csv(path.with_suffix('.csv'),trucks)
        threshold=exact_thresholds(fleet,trucks,catalog)
        assert threshold==row['threshold'] and accepts(threshold,1,350,3)
        assert not check_parameter_fleet(fleet,trucks,catalog,1,350,3)
        verified.append(row['index'])
        layouts.add(canonical_digest(fleet))
    assert len(verified)==summary['verified_complete']
    boundaries=[]
    if verified:
        fleet=read_solution(runs/f'witness_{verified[0]:03d}.json',trucks)
        threshold=exact_thresholds(fleet,trucks,catalog)
        for a,p,d,want in [('1','675/2','10',True),('1','337499/1000','10',False),
                            ('1','350','10001/1000',False),('0','675/2','10',True)]:
            assert accepts(threshold,a,p,d)==want
            assert (not check_parameter_fleet(fleet,trucks,catalog,a,p,d))==want
            boundaries.append(dict(alpha=a,pressure=p,clearance=d,accepted=want))
    old=ROOT/'experiments/results/block_search_L4_v1/snapshot/src/block_search.py'
    module=load_recipe_snapshot(old)
    for height in (217,247):
        for cap in (False,True):
            assert make_blocks(expand_items(),height,cap)==module.make_blocks(expand_items(),height,cap)
    return dict(verified_complete=verified,unique_complete_layouts=len(layouts),
                hashed_files=len(hashes),boundary_checks=boundaries,
                default_recipe_comparisons=4,all_passed=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.directory)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2)
    print(json.dumps(result))

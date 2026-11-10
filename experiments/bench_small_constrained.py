"""Persist small finite-grid exact certificates and EP comparison, L0--L4."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.exact_constrained import solve
from src.constrained_ep import pack_fixed_fleet
from src.pack_lib import TruckType, apply_level
from src.constraints import check_all, check_fleet


def main():
    target = ROOT/"experiments/results/chain_small_exact_v1"
    if target.exists():
        raise SystemExit("preserve existing evidence")
    target.mkdir()
    hashes = {}

    def save(name, payload):
        path = target/name
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    cases = [("standard_stack_8", ["standard"]*8, 0.01, (2,2,19)),
             ("fragile_stack_2", ["fragile"]*2, 0.05, (2,2,7)),
             ("late_standard_support_2", ["fragile","standard"], 0.05, (2,2,7)),
             ("pressure_stack_2", ["standard"]*2, 1, (2,2,7))]
    rows = []
    for name,kinds,weight,dims in cases:
        items = [dict(name=f"T{i}",serial=f"T{i}-000",kind=kind,dims=(2,2,2),weight=weight)
                 for i,kind in enumerate(kinds)]
        catalog = {it["name"]:dict(kind=it["kind"],dims=it["dims"],weight=weight,qty=1) for it in items}
        spec = dict(dims=dims,cap_weight=100,cost=1)
        for level in range(5):
            result = solve(items,spec,catalog,level=level,time_limit=10,node_limit=1000000)
            errors = check_all(result["boxes"],spec,catalog,level=level,strict_ids=True,pressure_model="chain_area_v1")
            fleet,rest = pack_fixed_fleet(apply_level(items,level),[TruckType("test",dims,100,1)],level=level)
            ep_errors = check_fleet(fleet,{"test":spec},catalog,level=level,
                                    pressure_model="chain_area_v1",require_complete=not rest)
            volume = sum(b["l"]*b["w"]*b["h"] for tr in fleet for b in tr["boxes"])
            if errors or ep_errors or volume > result["volume_upper_bound"]:
                raise ValueError("reference comparison failed")
            rows.append(dict(case=name,items=items,spec=spec,level=level,exact=result,
                             ep_fleet=fleet,ep_unplaced=[it["serial"] for it in rest],ep_volume=volume,
                             errors=errors,ep_errors=ep_errors))
    for rel in ("experiments/exact_constrained.py","experiments/bench_small_constrained.py",
                "src/constrained_ep.py","src/constraints.py","src/pack_lib.py"):
        path = target/"snapshot"/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/rel).read_bytes())
        hashes[path.relative_to(target).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    save("results.json",dict(runs=rows,scope="finite_integer_grid_single_container_only",
                             optimal_runs=sum(r["exact"]["status"]=="optimal" for r in rows),
                             limitation="Includes one easy eight-item case, not broad 8--20 item scaling evidence; shares independent acceptance checker"))
    (target/"sha256.json").write_text(json.dumps(dict(files=hashes),indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(runs=len(rows),optimal=sum(r["exact"]["status"]=="optimal" for r in rows),
                          zero_violations=True),indent=2))


if __name__ == "__main__":
    main()

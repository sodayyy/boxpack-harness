"""Read-only R8 checks: independently fixed matrix, referee, bounds, CSV and hashes.

Does not import the solver or runner. Shares R7 exact arithmetic for full layouts;
this is project self-checking, not a third-party proof.
"""
import argparse
from collections import Counter
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import load_catalog, load_trucks, check_fleet
from experiments.parameter_envelope import exact_thresholds

SNAPSHOTS = ["src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/variant_study.py", "experiments/bench_variant_study.py",
             "experiments/verify_variant_study.py", "experiments/parameter_envelope.py",
             "data/items.csv", "data/trucks.csv", "docs/13-R8规模组成协议.md"]


def expected_cases():
    specs = [("base", "base", "1", [80,100,30,40,50]),
             ("scale_1_2", "scale", "1/2", [40,50,15,20,25]),
             ("scale_3_2", "scale", "3/2", [120,150,45,60,75]),
             ("scale_2", "scale", "2", [160,200,60,80,100]),
             ("fragile_0", "fragile", "0", [80,100,0,40,50]),
             ("fragile_15", "fragile", "1/2", [80,100,15,40,50]),
             ("fragile_45", "fragile", "3/2", [80,100,45,40,50]),
             ("fragile_60", "fragile", "2", [80,100,60,40,50]),
             ("oriented_0", "oriented", "0", [80,100,30,0,0]),
             ("oriented_1_2", "oriented", "1/2", [80,100,30,20,25]),
             ("oriented_3_2", "oriented", "3/2", [80,100,30,60,75]),
             ("oriented_2", "oriented", "2", [80,100,30,80,100])]
    return [dict(id=i, family=f, factor=x, quantities=q) for i,f,x,q in specs]


def expected_runs():
    return [dict(case=c["id"], combination=list(combo), capped=True, order=o, axis="yx", rotation="original")
            for c, combo, o in itertools.product(expected_cases(), ((1,0),(2,0),(3,0),(4,0),(0,1),(0,2)),
                                                  ("area","long","volume","height"))]


def independent_bounds(catalog, trucks):
    """Enumeration with a proven cost/count sufficient limit, not runner import."""
    volume = sum(math.prod(s["dims"]) * s["qty"] for s in catalog.values())
    weight = sum(s["weight"] * s["qty"] for s in catalog.values())
    specs = list(trucks.values())
    capacities = [s["dims"][0]*s["dims"][1]*(s["dims"][2]-3) for s in specs]
    need = [max((volume+v-1)//v, (weight+s["cap_weight"]-1)//s["cap_weight"]) for s,v in zip(specs,capacities)]
    limit = max(min(need), min(n*s["cost"] for n,s in zip(need,specs)) // min(s["cost"] for s in specs))
    feasible = []
    for a in range(limit+1):
        for b in range(limit+1-a):
            if a*capacities[0]+b*capacities[1] >= volume and a*specs[0]["cap_weight"]+b*specs[1]["cap_weight"] >= weight:
                feasible.append((a+b, a*specs[0]["cost"]+b*specs[1]["cost"]))
    return dict(P1=min(x[0] for x in feasible), P2=min(x[1] for x in feasible),
                scope="all_types_including_mixed_volume_weight_relaxation", enumeration_count_limit=limit)


def verify_bundle(directory):
    directory = Path(directory).resolve()
    errors, result = [], dict(directory=str(directory))
    try:
        read = lambda name: json.loads((directory/name).read_text(encoding="utf-8"))
        plan, manifest = read("plan.json"), read("manifest.json")
        expected = expected_runs()
        if plan != dict(schema="r8_quantity_variants_v1", cases=expected_cases(), runs=expected, planned_runs=288,
                        level=4, support_ratio=0, pressure_model="chain_area_v1", pressure=500, clearance=3,
                        scope="derived_quantity_development_not_holdout_or_causal"):
            raise ValueError("fixed protocol/matrix mismatch")
        records = manifest["runs"]
        if manifest["status"] != "complete" or manifest["planned_runs"] != 288 or len(records) != 288:
            raise ValueError("incomplete matrix")
        labels = [f"variants_{i:03d}" for i in range(288)]
        if Counter(r["label"] for r in records) != Counter(labels):
            raise ValueError("missing/duplicate/unexpected run")
        hashes = read("sha256.json")["files"]
        required = {"plan.json","manifest.json","environment.json","summary.json","catalogs.csv","runs.csv"} | {
            "snapshot/"+p for p in SNAPSHOTS} | {"catalogs/"+c["id"]+".json" for c in expected_cases()} | {
            "runs/"+label+".json" for label in labels}
        if set(hashes) != required:
            raise ValueError("hash file set mismatch")
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != required | {"sha256.json"}:
            raise ValueError("unexpected/missing files")
        for name,digest in hashes.items():
            p=(directory/name).resolve()
            if not p.is_relative_to(directory):
                raise ValueError("hash path escapes evidence")
            if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                raise ValueError("hash mismatch: "+name)
        for rel in ("data/items.csv","data/trucks.csv"):
            if (directory/"snapshot"/rel).read_text(encoding="utf-8") != (ROOT/rel).read_text(encoding="utf-8"):
                raise ValueError("original catalog mismatch: "+rel)
        base = load_catalog(directory/"snapshot/data/items.csv")
        trucks = load_trucks(directory/"snapshot/data/trucks.csv")
        catalogs = {}
        expected_catalog_csv=[]
        for c in expected_cases():
            cat = {n:dict(s, qty=q, dims=list(s["dims"])) for (n,s),q in zip(base.items(),c["quantities"])}
            if read("catalogs/"+c["id"]+".json") != cat:
                raise ValueError("derived catalog mismatch: "+c["id"])
            catalogs[c["id"]] = cat
            for name,s in cat.items():
                expected_catalog_csv.append([c["id"],name,str(s["qty"]),*[str(x) for x in s["dims"]],str(s["weight"]),s["kind"]])
        with (directory/"catalogs.csv").open(encoding="utf-8-sig",newline="") as f:
            csv_catalog=list(csv.reader(f))
        if csv_catalog != [["case","item","quantity","l_cm","w_cm","h_cm","weight_kg","kind"]]+expected_catalog_csv:
            raise ValueError("catalog CSV mismatch")
        lookup={r["label"]:r for r in records}
        checked=[]
        exact_count=0
        for label,config in zip(labels,expected):
            record=lookup[label]
            if record["file"] != "runs/"+label+".json":
                raise ValueError("wrong run path")
            row=read(record["file"])
            if row["label"] != label or row["config"] != config:
                raise ValueError("run configuration mismatch: "+label)
            cat=catalogs[config["case"]]
            identities={f"{n}-{i:03d}" for n,s in cat.items() for i in range(s["qty"])}
            fleet, rest = row["fleet"],row["rest_serials"]
            boxes=[b for tr in fleet for b in tr["boxes"]]
            if Counter([b["serial"] for b in boxes]+rest) != Counter(identities):
                raise ValueError("identity conservation failure: "+label)
            if type(row["complete"]) is not bool or row["complete"] != (not rest):
                raise ValueError("completeness mismatch: "+label)
            available=Counter({n:q for n,q in zip(trucks,config["combination"])})
            if Counter(tr["truck_type"] for tr in fleet)-available or any(not tr["boxes"] for tr in fleet):
                raise ValueError("undeclared/empty vehicle: "+label)
            validation=check_fleet(fleet,trucks,cat,level=4,support_ratio=0,pressure_model="chain_area_v1",require_complete=row["complete"])
            if validation or row["errors"] != validation:
                raise ValueError("referee errors: "+label+repr(validation))
            metrics=dict(vehicles=len(fleet),cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),placed=len(boxes),
                         used_volume_cm3=sum(b["l"]*b["w"]*b["h"] for b in boxes))
            if any(row[k]!=v for k,v in metrics.items()):
                raise ValueError("metric mismatch: "+label)
            for key in ("solve_cpu_seconds","solve_wall_seconds"):
                if isinstance(row[key],bool) or not isinstance(row[key],(int,float)) or not math.isfinite(row[key]) or row[key]<0:
                    raise ValueError("invalid timing")
            placements=row["search"]["placements"]
            if (Counter(s for p in placements for s in p["serials"])!=Counter(b["serial"] for b in boxes) or
                    row["search"]["placed_blocks"]!=len(placements) or
                    len({p["block_id"] for p in placements})!=len(placements)):
                raise ValueError("block statistics mismatch")
            # Final referee above checks box geometry; additionally validate saved floor claims.
            sequence=[n for n,q in zip(trucks,config["combination"]) for _ in range(q)]
            for i,a in enumerate(placements):
                k=a["vehicle_index"]
                if type(k) is not int or not 0<=k<len(sequence):
                    raise ValueError("bad block vehicle")
                dims=trucks[sequence[k]]["dims"]
                if min(a["x"],a["y"])<0 or min(a["l"],a["w"])<=0 or a["x"]+a["l"]>dims[0] or a["y"]+a["w"]>dims[1]:
                    raise ValueError("floor outside vehicle")
                for b in placements[:i]:
                    if k==b["vehicle_index"] and max(a["x"],b["x"])<min(a["x"]+a["l"],b["x"]+b["l"]) and max(a["y"],b["y"])<min(a["y"]+a["w"],b["y"]+b["w"]):
                        raise ValueError("floor overlap")
            exact=exact_thresholds(fleet,trucks,cat) if row["complete"] else None
            if row["exact_thresholds"] != exact:
                raise ValueError("exact arithmetic mismatch")
            exact_count += int(row["complete"])
            actual_record={k:v for k,v in row.items() if k not in ("fleet","search","exact_thresholds")}
            actual_record["file"]="runs/"+label+".json"
            if actual_record!=record:
                raise ValueError("row/manifest mismatch")
            checked.append(record)
        expected_summaries={}
        for name,cat in catalogs.items():
            valid=[r for r in checked if r["config"]["case"]==name and r["complete"] and not r["errors"]]
            totals=dict(items=sum(s["qty"] for s in cat.values()),volume_cm3=sum(math.prod(s["dims"])*s["qty"] for s in cat.values()),
                        weight_kg=sum(s["weight"]*s["qty"] for s in cat.values()),fragile_count=sum(s["qty"] for s in cat.values() if s["kind"]=="fragile"),
                        oriented_count=sum(s["qty"] for s in cat.values() if s["kind"]=="oriented"))
            bounds=independent_bounds(cat,trucks)
            s=dict(totals=totals,capacity_lower_bounds=bounds,complete_runs=len(valid),P1=None,P2=None,status="no_complete_witness_not_infeasible")
            if valid:
                for goal,first,second in (("P1","vehicles","cost"),("P2","cost","vehicles")):
                    r=min(valid,key=lambda x:(x[first],x[second],x["label"]))
                    s[goal]=dict(lower_bound=bounds[goal],upper_bound=r[first],witness=r["label"],proven_optimal=bounds[goal]==r[first])
                s["status"]="both_objectives_proven" if all(s[k]["proven_optimal"] for k in ("P1","P2")) else "verified_bounds_gap_remaining"
            expected_summaries[name]=s
        summary=dict(cases=expected_summaries,runs=288,complete_runs=sum(r["complete"] for r in checked),
                     no_failure_is_infeasibility=True,no_ai_efficiency_claim=True)
        if read("summary.json")!=summary:
            raise ValueError("objective/lower-bound/summary mismatch")
        with (directory/"runs.csv").open(encoding="utf-8-sig",newline="") as f:
            csv_rows=list(csv.DictReader(f))
        expected_csv=[]
        for r in checked:
            d=dict(label=r["label"],case=r["config"]["case"],small=r["config"]["combination"][0],large=r["config"]["combination"][1],order=r["config"]["order"],
                   **{k:r[k] for k in ("placed","vehicles","cost","complete","used_volume_cm3")})
            expected_csv.append({k:str(v) for k,v in d.items()})
        if csv_rows!=expected_csv:
            raise ValueError("run CSV/JSON mismatch")
        env=read("environment.json")
        if env["planned_runs"]!=288:
            raise ValueError("environment plan mismatch")
        result.update(runs=288,cases=12,complete_runs=exact_count,hashed_files=len(hashes),
                      objective_proven_counts={k:sum(bool(s[k] and s[k]["proven_optimal"]) for s in expected_summaries.values()) for k in ("P1","P2")},
                      cpu_seconds=sum(r["solve_cpu_seconds"] for r in checked))
    except (OSError,ValueError,KeyError,TypeError,IndexError,ZeroDivisionError) as exc:
        errors.append(str(exc))
    return dict(result,errors=errors,passed=not errors)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    result=verify_bundle(parser.parse_args().directory)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)

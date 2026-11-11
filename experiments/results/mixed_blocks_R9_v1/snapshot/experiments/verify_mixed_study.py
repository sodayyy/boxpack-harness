"""Read-only R9 matrix/stage/geometry/objective/hash self-check; no solver import."""
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
from experiments.verify_variant_study import verify_bundle as verify_r8, independent_bounds

SOURCE = "experiments/results/quantity_variants_R8_v1"
SNAPSHOTS = ["src/mixed_blocks.py", "src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/mixed_study.py", "experiments/bench_mixed_study.py", "experiments/verify_mixed_study.py",
             "experiments/variant_study.py", "experiments/verify_variant_study.py", "experiments/parameter_envelope.py",
             "data/items.csv", "data/trucks.csv", "docs/15-R9混合车队协议.md"]


def expected_cases():
    return [dict(id=i, family=f, factor=x, quantities=q) for i,f,x,q in [
        ("scale_3_2", "scale", "3/2", [120,150,45,60,75]),
        ("scale_2", "scale", "2", [160,200,60,80,100]),
        ("fragile_45", "fragile", "3/2", [80,100,45,40,50]),
        ("fragile_60", "fragile", "2", [80,100,60,40,50]),
        ("oriented_3_2", "oriented", "3/2", [80,100,30,60,75]),
        ("oriented_2", "oriented", "2", [80,100,30,80,100])]]


def expected_runs():
    return [dict(case=c["id"], vehicle_order=list(v), capped=True, order=o, axis=a, rotation=r)
        for c,v,o,a,r in itertools.product(expected_cases(), ((0,1),(1,0)),
            ("area","long","volume","height"), ("xy","yx"), ("original","wide","long"))]


def verify_bundle(directory):
    directory = Path(directory).resolve()
    result = dict(directory=str(directory))
    try:
        read = lambda n: json.loads((directory/n).read_text(encoding="utf-8"))
        plan = dict(schema="r9_mixed_blocks_v1", cases=expected_cases(), runs=expected_runs(), planned_runs=288,
                    level=4, support_ratio=0, pressure=500, clearance=3, pressure_model="chain_area_v1",
                    strategy="sequential_rebuild_remaining_v1", source=SOURCE)
        if read("plan.json") != plan:
            raise ValueError("fixed protocol/matrix mismatch")
        manifest = read("manifest.json")
        records = manifest["runs"]
        if manifest["status"] != "complete" or manifest["planned_runs"] != 288 or len(records) != 288:
            raise ValueError("incomplete matrix")
        labels = [f"mixed_{i:03d}" for i in range(288)]
        if Counter(r["label"] for r in records) != Counter(labels):
            raise ValueError("missing/duplicate run")
        required = {"plan.json","manifest.json","summary.json","environment.json","runs.csv"} | {
            "snapshot/"+s for s in SNAPSHOTS} | {"source/"+s for s in ("manifest.json","summary.json","sha256.json")} | {
            "catalogs/"+c["id"]+".json" for c in expected_cases()} | {"runs/"+s+".json" for s in labels}
        hashes = read("sha256.json")
        if hashes["algorithm"] != "SHA256" or set(hashes["files"]) != required:
            raise ValueError("hash file set mismatch")
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != required | {"sha256.json"}:
            raise ValueError("unexpected/missing evidence file")
        for n, digest in hashes["files"].items():
            p = (directory/n).resolve()
            if not p.is_relative_to(directory) or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                raise ValueError("hash mismatch: "+n)
        source_check = verify_r8(ROOT / SOURCE)
        if not source_check["passed"]:
            raise ValueError("source R8 invalid: "+repr(source_check["errors"]))
        for n in ("manifest.json","summary.json","sha256.json"):
            if (directory/"source"/n).read_bytes() != (ROOT/SOURCE/n).read_bytes():
                raise ValueError("source binding mismatch")
        for n in ("data/items.csv", "data/trucks.csv"):
            if (directory/"snapshot"/n).read_text(encoding="utf-8") != (ROOT/n).read_text(encoding="utf-8"):
                raise ValueError("original catalog mismatch")
        base, trucks = load_catalog(directory/"snapshot/data/items.csv"), load_trucks(directory/"snapshot/data/trucks.csv")
        names = list(trucks)
        catalogs = {}
        for c in expected_cases():
            cat = {n:dict(s, qty=q) for (n,s),q in zip(base.items(),c["quantities"])}
            if read("catalogs/"+c["id"]+".json") != {n:dict(s, dims=list(s["dims"])) for n,s in cat.items()}:
                raise ValueError("derived catalog mismatch")
            catalogs[c["id"]] = cat
        lookup = {r["label"]:r for r in records}
        checked = []
        for label, config in zip(labels, expected_runs()):
            record = lookup[label]
            if record["file"] != "runs/"+label+".json":
                raise ValueError("run path mismatch")
            row = read(record["file"])
            if row["label"] != label or row["config"] != config:
                raise ValueError("run configuration mismatch")
            cat = catalogs[config["case"]]
            identities = {f"{n}-{i:03d}" for n,s in cat.items() for i in range(s["qty"])}
            fleet, rest = row["fleet"], row["rest_serials"]
            boxes = [b for tr in fleet for b in tr["boxes"]]
            if Counter([b["serial"] for b in boxes]+rest) != Counter(identities):
                raise ValueError("identity conservation failure")
            if type(row["complete"]) is not bool or row["complete"] != (not rest):
                raise ValueError("completeness mismatch")
            if any(not tr["boxes"] for tr in fleet):
                raise ValueError("empty vehicle")
            errors = check_fleet(fleet,trucks,cat,level=4,support_ratio=0,pressure_model="chain_area_v1",require_complete=row["complete"])
            if errors or row["errors"] != errors:
                raise ValueError("referee errors: "+label+repr(errors))
            metrics = dict(vehicles=len(fleet), placed=len(boxes), cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
                           used_volume_cm3=sum(b["l"]*b["w"]*b["h"] for b in boxes))
            if any(row[k] != v for k,v in metrics.items()):
                raise ValueError("metric mismatch")
            for k in ("solve_cpu_seconds", "solve_wall_seconds"):
                if isinstance(row[k],bool) or not isinstance(row[k],(float,int)) or not math.isfinite(row[k]) or row[k]<0:
                    raise ValueError("invalid timing")
            search = row["search"]
            if search["strategy"] != "sequential_rebuild_remaining_v1" or len(search["stages"]) != 2:
                raise ValueError("stage strategy mismatch")
            before, fleet_index = identities, 0
            for k, stage in enumerate(search["stages"]):
                name = names[config["vehicle_order"][k]]
                if stage["vehicle_index"] != k or stage["truck_type"] != name or Counter(stage["input_serials"]) != Counter(before):
                    raise ValueError("stage input/order mismatch")
                placed = stage["placed_serials"]
                after = stage["rest_serials"]
                if Counter(placed+after) != Counter(before):
                    raise ValueError("stage identity conservation failure")
                if placed:
                    if fleet_index >= len(fleet) or fleet[fleet_index]["truck_type"] != name or Counter(placed) != Counter(b["serial"] for b in fleet[fleet_index]["boxes"]):
                        raise ValueError("stage/fleet allocation mismatch")
                    fleet_index += 1
                stats = stage["search"]
                if not before:
                    if stats is not None:
                        raise ValueError("nonempty search for empty stage")
                else:
                    placements = stats["placements"]
                    if stats["placed_blocks"] != len(placements) or Counter(s for p in placements for s in p["serials"]) != Counter(placed):
                        raise ValueError("block identity statistics mismatch")
                    if len({p["block_id"] for p in placements}) != len(placements) or stats["blocks"] < len(placements):
                        raise ValueError("block count mismatch")
                    dims = trucks[name]["dims"]
                    for i,a in enumerate(placements):
                        if a["vehicle_index"] != 0 or min(a["x"],a["y"])<0 or min(a["l"],a["w"])<=0 or a["x"]+a["l"]>dims[0] or a["y"]+a["w"]>dims[1]:
                            raise ValueError("floor outside vehicle")
                        for b in placements[:i]:
                            if max(a["x"],b["x"])<min(a["x"]+a["l"],b["x"]+b["l"]) and max(a["y"],b["y"])<min(a["y"]+a["w"],b["y"]+b["w"]):
                                raise ValueError("floor overlap")
                before = after
            if fleet_index != len(fleet) or Counter(before) != Counter(rest):
                raise ValueError("final stage/fleet mismatch")
            exact = exact_thresholds(fleet,trucks,cat) if row["complete"] else None
            if row["exact_thresholds"] != exact:
                raise ValueError("exact arithmetic mismatch")
            expected_record = {k:v for k,v in row.items() if k not in ("fleet","search","exact_thresholds")}
            expected_record["file"] = record["file"]
            if record != expected_record:
                raise ValueError("row/manifest mismatch")
            checked.append(record)
        source = read("source/manifest.json")["runs"]
        summaries = {}
        for name, cat in catalogs.items():
            valid = [dict(r, source="R8") for r in source if r["config"]["case"]==name and r["complete"] and not r["errors"]]
            valid += [dict(r, source="R9") for r in checked if r["config"]["case"]==name and r["complete"] and not r["errors"]]
            lower = independent_bounds(cat,trucks)
            t = dict(items=sum(s["qty"] for s in cat.values()), volume_cm3=sum(math.prod(s["dims"])*s["qty"] for s in cat.values()),
                     weight_kg=sum(s["weight"]*s["qty"] for s in cat.values()), fragile_count=sum(s["qty"] for s in cat.values() if s["kind"]=="fragile"),
                     oriented_count=sum(s["qty"] for s in cat.values() if s["kind"]=="oriented"))
            s = dict(totals=t,capacity_lower_bounds=lower,r9_complete_runs=sum(r["complete"] and not r["errors"] for r in checked if r["config"]["case"]==name))
            for goal,first,second in (("P1","vehicles","cost"),("P2","cost","vehicles")):
                r = min(valid,key=lambda r:(r[first],r[second],r["source"],r["label"]))
                s[goal] = dict(lower_bound=lower[goal],upper_bound=r[first],witness=r["label"],source=r["source"],proven_optimal=lower[goal]==r[first])
            summaries[name] = s
        summary = dict(cases=summaries,runs=288,complete_runs=sum(r["complete"] for r in checked),no_failure_is_infeasibility=True,no_ai_efficiency_claim=True)
        if read("summary.json") != summary:
            raise ValueError("objective/lower-bound/summary mismatch")
        with (directory/"runs.csv").open(encoding="utf-8-sig",newline="") as f:
            csv_rows = list(csv.DictReader(f))
        expected_csv = []
        for r in checked:
            d = dict(label=r["label"],**{k:r["config"][k] for k in ("case","order","axis","rotation")},
                     vehicle_order="-".join(map(str,r["config"]["vehicle_order"])),**{k:r[k] for k in ("placed","vehicles","cost","complete")})
            expected_csv.append({k:str(v) for k,v in d.items()})
        if csv_rows != expected_csv:
            raise ValueError("CSV/JSON mismatch")
        if read("environment.json")["planned_runs"] != 288:
            raise ValueError("environment mismatch")
        return dict(result,passed=True,errors=[],runs=288,cases=6,complete_runs=summary["complete_runs"],hashed_files=len(required),
                    objective_proven_counts={k:sum(s[k]["proven_optimal"] for s in summaries.values()) for k in ("P1","P2")},
                    cpu_seconds=sum(r["solve_cpu_seconds"] for r in checked))
    except (OSError,ValueError,KeyError,TypeError,IndexError,ZeroDivisionError) as exc:
        return dict(result,passed=False,errors=[str(exc)])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    result = verify_bundle(p.parse_args().directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["passed"] else 1)

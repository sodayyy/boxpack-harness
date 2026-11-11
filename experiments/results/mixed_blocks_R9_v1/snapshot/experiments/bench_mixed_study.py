"""Execute the frozen 288-run R9 sequential mixed-fleet matrix."""
import argparse
import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.mixed_blocks import pack_mixed_blocks
from src.pack_lib import TruckType
from src.constraints import load_catalog, load_trucks, check_fleet
from experiments.parameter_envelope import exact_thresholds
from experiments.variant_study import derived_catalog, expand_catalog
from experiments.mixed_study import selected_cases, planned_runs, merged_summary
from experiments.verify_variant_study import verify_bundle as verify_r8

SOURCE = "experiments/results/quantity_variants_R8_v1"
SNAPSHOTS = ["src/mixed_blocks.py", "src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/mixed_study.py", "experiments/bench_mixed_study.py", "experiments/verify_mixed_study.py",
             "experiments/variant_study.py", "experiments/verify_variant_study.py", "experiments/parameter_envelope.py",
             "data/items.csv", "data/trucks.csv", "docs/15-R9混合车队协议.md"]
FIELDS = ["label", "case", "vehicle_order", "order", "axis", "rotation", "placed", "vehicles", "cost", "complete"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    out = parser.parse_args().output_dir.resolve()
    if out.exists():
        parser.error("preserve evidence; use new output directory")
    source_check = verify_r8(ROOT / SOURCE)
    if not source_check["passed"]:
        raise ValueError(source_check["errors"])
    out.mkdir(parents=True)
    hashes = {}

    def save(name, obj):
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()

    plan = planned_runs()
    save("plan.json", dict(schema="r9_mixed_blocks_v1", cases=selected_cases(), runs=plan,
         planned_runs=288, level=4, support_ratio=0, pressure=500, clearance=3,
         pressure_model="chain_area_v1", strategy="sequential_rebuild_remaining_v1", source=SOURCE))
    for rel in SNAPSHOTS:
        p = out / "snapshot" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / rel).read_bytes())
        hashes["snapshot/" + rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ("manifest.json", "summary.json", "sha256.json"):
        p = out / "source" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / SOURCE / name).read_bytes())
        hashes["source/" + name] = hashlib.sha256(p.read_bytes()).hexdigest()
    base, trucks = load_catalog(ROOT / "data/items.csv"), load_trucks(ROOT / "data/trucks.csv")
    specs = [TruckType(n, tuple(s["dims"]), s["cap_weight"], s["cost"]) for n, s in trucks.items()]
    catalogs = {c["id"]: derived_catalog(base, c["quantities"]) for c in selected_cases()}
    for name, cat in catalogs.items():
        save("catalogs/" + name + ".json", cat)
    save("environment.json", dict(platform=platform.platform(), python=sys.version, command=sys.argv,
         process_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
         planned_runs=288, source_verification=source_check))
    records = []
    for i, config in enumerate(plan):
        cat = catalogs[config["case"]]
        gc.collect()
        wall, cpu = time.perf_counter(), time.process_time()
        fleet, rest, stats = pack_mixed_blocks(expand_catalog(cat), [specs[j] for j in config["vehicle_order"]],
            **{k: config[k] for k in ("capped", "order", "axis", "rotation")})
        cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
        errors = check_fleet(fleet, trucks, cat, level=4, support_ratio=0, pressure_model="chain_area_v1", require_complete=not rest)
        label = f"mixed_{i:03d}"
        row = dict(label=label, config=config, fleet=fleet, rest_serials=[b["serial"] for b in rest],
            complete=not rest, errors=errors, vehicles=len(fleet), placed=sum(len(tr["boxes"]) for tr in fleet),
            cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
            used_volume_cm3=sum(b["l"]*b["w"]*b["h"] for tr in fleet for b in tr["boxes"]),
            solve_cpu_seconds=cpu, solve_wall_seconds=wall, search=stats,
            exact_thresholds=exact_thresholds(fleet, trucks, cat) if not rest and not errors else None)
        save("runs/" + label + ".json", row)
        record = {k:v for k,v in row.items() if k not in ("fleet", "search", "exact_thresholds")}
        record["file"] = "runs/" + label + ".json"
        records.append(record)
        save("manifest.json", dict(status="in_progress", planned_runs=288, runs=records))
        print(json.dumps({k:row[k] for k in ("label", "placed", "complete", "errors", "solve_cpu_seconds")}), flush=True)
        if errors:
            raise ValueError("referee rejected candidate; preserve evidence")
    source_records = json.loads((ROOT / SOURCE / "manifest.json").read_text(encoding="utf-8"))["runs"]
    save("summary.json", dict(cases=merged_summary(records, source_records, catalogs, trucks), runs=288,
         complete_runs=sum(r["complete"] for r in records), no_failure_is_infeasibility=True, no_ai_efficiency_claim=True))
    p = out / "runs.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in records:
            w.writerow(dict(label=r["label"], **{k:r["config"][k] for k in ("case", "order", "axis", "rotation")},
                vehicle_order="-".join(map(str, r["config"]["vehicle_order"])),
                **{k:r[k] for k in ("placed", "vehicles", "cost", "complete")}))
    hashes["runs.csv"] = hashlib.sha256(p.read_bytes()).hexdigest()
    save("manifest.json", dict(status="complete", planned_runs=288, runs=records))
    (out / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=hashes), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(completed_runs=288, complete_witnesses=sum(r["complete"] for r in records))), flush=True)


if __name__ == "__main__":
    main()

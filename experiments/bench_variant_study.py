"""Execute the preregistered R8 12-catalog x 6-fleet x 4-order matrix."""
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
from src.block_search import pack_blocks
from src.pack_lib import TruckType
from src.constraints import load_catalog, load_trucks, check_fleet
from experiments.parameter_envelope import exact_thresholds
from experiments.variant_study import cases, derived_catalog, expand_catalog, planned_runs, summarize

SNAPSHOTS = ["src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/variant_study.py", "experiments/bench_variant_study.py",
             "experiments/verify_variant_study.py", "experiments/parameter_envelope.py",
             "data/items.csv", "data/trucks.csv", "docs/13-R8规模组成协议.md"]
FIELDS = ["label", "case", "small", "large", "order", "placed", "vehicles", "cost", "complete", "used_volume_cm3"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists():
        parser.error("preserve evidence; use a new output directory")
    out.mkdir(parents=True)
    hashes = {}

    def save(name, obj):
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()

    plan = planned_runs()
    save("plan.json", dict(schema="r8_quantity_variants_v1", cases=cases(), runs=plan,
                           planned_runs=288, level=4, support_ratio=0, pressure_model="chain_area_v1",
                           pressure=500, clearance=3, scope="derived_quantity_development_not_holdout_or_causal"))
    for rel in SNAPSHOTS:
        p = out / "snapshot" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / rel).read_bytes())
        hashes["snapshot/" + rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    base = load_catalog(ROOT / "data/items.csv")
    trucks = load_trucks(ROOT / "data/trucks.csv")
    specs = [TruckType(name, tuple(s["dims"]), s["cap_weight"], s["cost"]) for name, s in trucks.items()]
    catalogs = {c["id"]: derived_catalog(base, c["quantities"]) for c in cases()}
    for name, cat in catalogs.items():
        save("catalogs/" + name + ".json", cat)
    catalog_csv = out / "catalogs.csv"
    with catalog_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "item", "quantity", "l_cm", "w_cm", "h_cm", "weight_kg", "kind"])
        for name, cat in catalogs.items():
            for item, s in cat.items():
                writer.writerow([name, item, s["qty"], *s["dims"], s["weight"], s["kind"]])
    hashes["catalogs.csv"] = hashlib.sha256(catalog_csv.read_bytes()).hexdigest()
    save("environment.json", dict(platform=platform.platform(), python=sys.version, command=sys.argv,
                                  planned_runs=len(plan), process_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                                  note="constructive configuration budgets, not equal CPU trials"))
    records = []
    for i, config in enumerate(plan):
        cat = catalogs[config["case"]]
        items = expand_catalog(cat)
        fleet_specs = [s for n, s in zip(config["combination"], specs) for _ in range(n)]
        gc.collect()
        wall, cpu = time.perf_counter(), time.process_time()
        fleet, rest, stats = pack_blocks(items, fleet_specs, **{k: config[k] for k in ("capped", "order", "axis", "rotation")})
        cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
        errors = check_fleet(fleet, trucks, cat, level=4, support_ratio=0, pressure_model="chain_area_v1", require_complete=not rest)
        label = f"variants_{i:03d}"
        row = dict(label=label, config=config, fleet=fleet, rest_serials=[b["serial"] for b in rest], complete=not rest,
                   errors=errors, vehicles=len(fleet), cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
                   placed=sum(len(tr["boxes"]) for tr in fleet),
                   used_volume_cm3=sum(b["l"]*b["w"]*b["h"] for tr in fleet for b in tr["boxes"]),
                   solve_cpu_seconds=cpu, solve_wall_seconds=wall, search=stats,
                   exact_thresholds=exact_thresholds(fleet, trucks, cat) if not rest and not errors else None)
        save("runs/" + label + ".json", row)
        record = {k: v for k, v in row.items() if k not in ("fleet", "search", "exact_thresholds")}
        record["file"] = "runs/" + label + ".json"
        records.append(record)
        save("manifest.json", dict(status="in_progress", planned_runs=288, runs=records))
        print(json.dumps({k: row[k] for k in ("label", "config", "placed", "complete", "errors", "solve_cpu_seconds")}), flush=True)
        if errors:
            raise ValueError("independent referee rejected candidate; preserve failed evidence")
    summaries = {name: summarize([r for r in records if r["config"]["case"] == name], cat, trucks)
                 for name, cat in catalogs.items()}
    save("summary.json", dict(cases=summaries, runs=len(records), complete_runs=sum(r["complete"] for r in records),
                              no_failure_is_infeasibility=True, no_ai_efficiency_claim=True))
    grid_path = out / "runs.csv"
    with grid_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(dict(label=r["label"], case=r["config"]["case"], small=r["config"]["combination"][0],
                                 large=r["config"]["combination"][1], order=r["config"]["order"],
                                 **{k: r[k] for k in ("placed", "vehicles", "cost", "complete", "used_volume_cm3")}))
    hashes["runs.csv"] = hashlib.sha256(grid_path.read_bytes()).hexdigest()
    save("manifest.json", dict(status="complete", planned_runs=288, runs=records))
    (out / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=hashes), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"completed_runs": len(records), "complete_witnesses": sum(r["complete"] for r in records)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

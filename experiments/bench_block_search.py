"""R6 predeclared bounded block-construction development matrix, never a blind test."""
import argparse
import gc
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.block_search import pack_blocks
from src.pack_lib import TRUCKS, expand_items
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain
from experiments.bench_constrained_fleet import select_objectives

SNAPSHOTS = ["src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/bench_block_search.py", "experiments/bench_constrained_fleet.py",
             "experiments/verify_block_search.py", "experiments/verify_constrained_fleet.py",
             "data/items.csv", "data/trucks.csv"]


def planned_runs():
    return [dict(combination=list(combo), capped=capped, order=order, axis=axis, rotation=rotation)
            for combo, capped, order, axis, rotation in itertools.product(
                ((0, 1), (2, 0)), (False, True), ("area", "long", "volume", "height"),
                ("yx", "xy"), ("original", "wide", "long"))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if directory.exists():
        parser.error("preserve existing evidence; use a new directory")
    directory.mkdir(parents=True)
    hashes = {}

    def save(name, obj):
        path = directory / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    for rel in SNAPSHOTS:
        dest = directory / "snapshot" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / rel).read_bytes())
        hashes[dest.relative_to(directory).as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
    plan = planned_runs()
    # This file is emitted before the first packing run; no adaptive stop on success.
    save("plan.json", {"schema": "r6_blocks_v1", "runs": plan,
                       "budget": "96 fixed constructive configurations; no random/adaptive trials",
                       "purpose": "development_on_known_original_instance_not_holdout",
                       "level": 4, "pressure_model": "chain_area_v1", "support_ratio": 0,
                       "note": "restricted block recipes; failures never certify original infeasibility"})
    save("environment.json", {"platform": platform.platform(), "python": sys.version,
                              "command": sys.argv, "source_total_volume_cm3": 28735000,
                              "source_total_weight_kg": 4110, "planned_count": len(plan)})
    items = expand_items()
    catalog = load_catalog(ROOT / "data/items.csv")
    trucks = load_trucks(ROOT / "data/trucks.csv")
    records = []
    for index, config in enumerate(plan):
        specs = [tr for qty, tr in zip(config["combination"], TRUCKS) for _ in range(qty)]
        gc.collect()
        wall, cpu = time.perf_counter(), time.process_time()
        fleet, rest, stats = pack_blocks(items, specs, **{k: config[k] for k in ("capped", "order", "axis", "rotation")})
        cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
        errors = check_fleet(fleet, trucks, catalog, level=4, support_ratio=0,
                             pressure_model="chain_area_v1", require_complete=not rest)
        label = f"blocks_L4_{index:03d}"
        row = dict(label=label, config=config, level=4, pressure_model="chain_area_v1", support_ratio=0,
                   fleet=fleet, rest_serials=[it["serial"] for it in rest], complete=not rest,
                   vehicles=len(fleet), cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
                   placed=sum(len(tr["boxes"]) for tr in fleet),
                   used_volume_cm3=sum(b["l"] * b["w"] * b["h"] for tr in fleet for b in tr["boxes"]),
                   errors=errors, solve_cpu_seconds=cpu, solve_wall_seconds=wall,
                   chain_audits=[audit_load_chain(tr["boxes"]) for tr in fleet], search=stats)
        save(label + ".json", row)
        record = {k: v for k, v in row.items() if k not in ("fleet", "chain_audits", "search")}
        record["file"] = label + ".json"
        records.append(record)
        save("manifest.json", dict(status="in_progress", planned_count=len(plan), runs=records))
        print(json.dumps({k: row[k] for k in ("label", "config", "placed", "complete", "errors", "solve_wall_seconds")}), flush=True)
        if errors:
            raise RuntimeError("independent verifier rejected a generated solution")
    save("manifest.json", dict(status="verified", planned_count=len(plan), runs=records,
                               independent_objectives=select_objectives(records)))
    (directory / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=hashes), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

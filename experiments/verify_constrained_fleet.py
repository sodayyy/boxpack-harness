"""Read back fixed-fleet evidence without running the packing algorithm.

Rebuild the full declared experiment matrix, hash required files, recheck each
layout against the CSV catalogs and recompute objective summaries. Historical
v1 bundles are accepted under their fixed five-order protocol only.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain

ORDERS = ["volume", "height", "fragile_last", "fragile_first", "standard_first"]
SNAPSHOTS = ["src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/bench_constrained_fleet.py", "data/items.csv", "data/trucks.csv"]


def expected_plan(scope, trucks):
    """Independent enumeration of the recorded v1 finite domain."""
    names = list(trucks)
    if len(names) != 2:
        raise ValueError("v1 requires the two original truck types")
    combos = [(1, 0), (0, 1)]
    if scope == "fleet":
        combos = []
        for combo in itertools.product(range(4), repeat=2):
            n = sum(combo)
            cost = sum(q * trucks[name]["cost"] for q, name in zip(combo, names))
            capacity = sum(q * math.prod((*trucks[name]["dims"][:2], trucks[name]["dims"][2] - 3))
                           for q, name in zip(combo, names))
            weight = sum(q * trucks[name]["cap_weight"] for q, name in zip(combo, names))
            if n and (n <= 3 or cost <= 1400) and capacity >= 28735000 and weight >= 4110:
                combos.append(combo)
    elif scope != "single":
        raise ValueError("unknown scope")
    plan = []
    for combo in combos:
        available = [name for q, name in zip(combo, names) for _ in range(q)]
        sequences = [available]
        if available[::-1] != available:
            sequences.append(available[::-1])
        for sequence in sequences:
            for order in ORDERS:
                plan.append((list(combo), sequence, order))
    return plan


def objective_summary(records):
    feasible = [r for r in records if r["complete"] and not r["errors"]]
    if not feasible:
        return {"P1": None, "P2": None}
    p1 = min(feasible, key=lambda r: (r["vehicles"], r["cost"], r["label"]))
    p2 = min(feasible, key=lambda r: (r["cost"], r["vehicles"], r["label"]))
    status = "best_verified_heuristic_not_global_optimum"
    return {"P1": dict(objective="vehicles", value=p1["vehicles"], label=p1["label"],
                       cost=p1["cost"], status=status),
            "P2": dict(objective="cost", value=p2["cost"], label=p2["label"],
                       vehicles=p2["vehicles"], status=status)}


def single_summary(records, trucks):
    best = {}
    for name, spec in trucks.items():
        candidates = [r for r in records if r["vehicle_order"] == [name] and not r["errors"]]
        if not candidates:
            continue
        row = min(candidates, key=lambda r: (-r["used_volume_cm3"], r["label"]))
        l, w, h = spec["dims"]
        best[name] = {key: row[key] for key in ("label", "item_order", "placed", "used_volume_cm3", "rest_serials")}
        best[name].update(nominal_space_util=row["used_volume_cm3"] / (l*w*h),
                          effective_space_util=row["used_volume_cm3"] / (l*w*(h-3)),
                          shipment_completion=row["used_volume_cm3"] / 28735000,
                          status="best_of_five_orders_not_proven_maximum")
    return best


def verify_bundle(directory):
    directory = Path(directory)
    errors = []
    try:
        read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
        manifest, env, hashes = read("manifest.json"), read("environment.json"), read("sha256.json")["files"]
        trucks = load_trucks(directory / "snapshot/data/trucks.csv")
        catalog = load_catalog(directory / "snapshot/data/items.csv")
        if (directory / "snapshot/data/items.csv").read_text(encoding="utf-8") != (ROOT / "data/items.csv").read_text(encoding="utf-8"):
            errors.append("item source differs from original catalog")
        if (directory / "snapshot/data/trucks.csv").read_text(encoding="utf-8") != (ROOT / "data/trucks.csv").read_text(encoding="utf-8"):
            errors.append("truck source differs from original catalog")
        scope, level = env["scope"], env["level"]
        if type(level) is not int or level not in range(5) or env["pressure_model"] != "chain_area_v1" or env["support_ratio"] != 0:
            raise ValueError("unsupported protocol")
        if env["source_total_volume_cm3"] != 28735000 or env["source_total_weight_kg"] != 4110:
            errors.append("wrong source totals")
        plan = expected_plan(scope, trucks)
        expected_labels = [f"{scope}_L{level}_{i:03d}" for i in range(len(plan))]
        records = manifest["runs"]
        if manifest["status"] != "verified" or manifest["planned_count"] != len(plan) or env["planned_count"] != len(plan):
            errors.append("incomplete or mismatched declared plan")
        if Counter(r["label"] for r in records) != Counter(expected_labels):
            raise ValueError("missing, duplicate or unexpected run labels")
        required = {"manifest.json", "environment.json"} | {f"snapshot/{p}" for p in SNAPSHOTS} | {label + ".json" for label in expected_labels}
        if set(hashes) != required:
            errors.append("hash manifest does not match full required file set")
        for name, digest in hashes.items():
            path = directory / name
            if path.resolve().is_relative_to(directory.resolve()) is False:
                raise ValueError("hash path escapes bundle")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append("hash mismatch: " + name)
        identities = {f"{name}-{i:03d}" for name, spec in catalog.items() for i in range(spec["qty"])}
        checked = []
        lookup = {r["label"]: r for r in records}
        for label, (combo, sequence, order) in zip(expected_labels, plan):
            record = lookup[label]
            if record["file"] != label + ".json":
                raise ValueError("unexpected run filename")
            row = read(record["file"])
            if row["combination"] != combo or row["vehicle_order"] != sequence or row["item_order"] != order:
                errors.append(label + ": configuration differs from plan")
            if row["level"] != level or row["pressure_model"] != "chain_area_v1":
                errors.append(label + ": constraint protocol mismatch")
            fleet = row["fleet"]
            boxes = [b for tr in fleet for b in tr["boxes"]]
            remaining = row["rest_serials"]
            packed = [b["serial"] for b in boxes]
            if Counter(packed + remaining) != Counter(identities) or type(row["complete"]) is not bool or row["complete"] != (not remaining):
                errors.append(label + ": item identity conservation/completeness failed")
            available = Counter(sequence)
            used = Counter(tr["truck_type"] for tr in fleet)
            if used - available or any(not tr["boxes"] for tr in fleet):
                errors.append(label + ": invalid fixed fleet use")
            validation = check_fleet(fleet, trucks, catalog, level=level, support_ratio=0,
                                     pressure_model="chain_area_v1", require_complete=row["complete"])
            if validation or row["errors"] != validation:
                errors.append(label + ": layout rejected: " + repr(validation))
            recomputed = dict(vehicles=len(fleet), cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
                              placed=len(boxes), used_volume_cm3=sum(b["l"]*b["w"]*b["h"] for b in boxes))
            if any(row[k] != v for k, v in recomputed.items()):
                errors.append(label + ": saved metrics mismatch")
            audits = [audit_load_chain(tr["boxes"]) for tr in fleet] if level >= 4 else []
            if row["chain_audits"] != audits:
                errors.append(label + ": chain audit mismatch")
            duration = row["solve_wall_seconds"]
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                errors.append(label + ": invalid timing")
            actual_record = {k: v for k, v in row.items() if k not in ("fleet", "chain_audits")}
            actual_record["file"] = label + ".json"
            if actual_record != record:
                errors.append(label + ": manifest/layout mismatch")
            checked.append(actual_record)
        objectives = objective_summary(checked) if scope == "fleet" else None
        if manifest["independent_objectives"] != objectives:
            errors.append("objective summary differs from independently recomputed rankings")
        result = dict(directory=str(directory), scope=scope, level=level, runs=len(checked),
                      complete_runs=sum(r["complete"] for r in checked), hashed_files=len(hashes),
                      independent_objectives=objectives,
                      best_single=single_summary(checked, trucks) if scope == "single" else None)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"bundle read failed: {exc}")
        result = dict(directory=str(directory))
    return dict(result, errors=errors, passed=not errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = verify_bundle(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

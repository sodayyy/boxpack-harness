"""Read-only, independent matrix/layout/metric checks for R6 block evidence."""
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
from experiments.verify_constrained_fleet import objective_summary

SNAPSHOTS = ["src/block_search.py", "src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py",
             "experiments/bench_block_search.py", "experiments/bench_constrained_fleet.py",
             "experiments/verify_block_search.py", "experiments/verify_constrained_fleet.py",
             "data/items.csv", "data/trucks.csv"]


def expected_plan():
    return [dict(combination=list(combo), capped=cap, order=order, axis=axis, rotation=rotation)
            for combo, cap, order, axis, rotation in itertools.product(
                ((0, 1), (2, 0)), (False, True), ("area", "long", "volume", "height"),
                ("yx", "xy"), ("original", "wide", "long"))]


def verify_bundle(directory):
    directory = Path(directory).resolve()
    errors = []
    result = dict(directory=str(directory))
    try:
        read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
        plan, env, manifest = read("plan.json"), read("environment.json"), read("manifest.json")
        hashes = read("sha256.json")["files"]
        expected = expected_plan()
        if (plan["schema"] != "r6_blocks_v1" or plan["runs"] != expected or
                type(plan["level"]) is not int or plan["level"] != 4 or
                plan["pressure_model"] != "chain_area_v1" or plan["support_ratio"] != 0):
            errors.append("declared plan/protocol differs from fixed v1 matrix")
        labels = [f"blocks_L4_{i:03d}" for i in range(len(expected))]
        if (manifest["status"] != "verified" or manifest["planned_count"] != len(expected) or
                env["planned_count"] != len(expected)):
            errors.append("incomplete declared plan")
        records = manifest["runs"]
        if Counter(r["label"] for r in records) != Counter(labels):
            raise ValueError("missing, duplicate or unexpected run labels")
        required = {"plan.json", "environment.json", "manifest.json"} | {f"snapshot/{p}" for p in SNAPSHOTS} | {s + ".json" for s in labels}
        if set(hashes) != required:
            errors.append("hash file set differs from the complete matrix")
        actual_files = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual_files != required | {"sha256.json"}:
            errors.append("missing or unexpected bundle files")
        for name, digest in hashes.items():
            path = directory / name
            if not path.resolve().is_relative_to(directory):
                raise ValueError("hash path escapes bundle")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append("hash mismatch: " + name)
        for rel in ("data/items.csv", "data/trucks.csv"):
            # Catalog checkout line endings may differ; evidence bytes stay hashed.
            if (directory / "snapshot" / rel).read_text(encoding="utf-8") != (ROOT / rel).read_text(encoding="utf-8"):
                errors.append("source differs from original catalog: " + rel)
        catalog = load_catalog(directory / "snapshot/data/items.csv")
        trucks = load_trucks(directory / "snapshot/data/trucks.csv")
        if env["source_total_volume_cm3"] != 28735000 or env["source_total_weight_kg"] != 4110:
            errors.append("source totals mismatch")
        identities = {f"{name}-{i:03d}" for name, spec in catalog.items() for i in range(spec["qty"])}
        lookup = {r["label"]: r for r in records}
        checked = []
        for label, config in zip(labels, expected):
            record = lookup[label]
            if record["file"] != label + ".json":
                raise ValueError("unexpected run filename")
            row = read(record["file"])
            if (row["config"] != config or type(row["level"]) is not int or row["level"] != 4 or
                    row["support_ratio"] != 0 or row["pressure_model"] != "chain_area_v1"):
                errors.append(label + ": configuration mismatch")
            fleet, remaining = row["fleet"], row["rest_serials"]
            boxes = [b for tr in fleet for b in tr["boxes"]]
            packed = [b["serial"] for b in boxes]
            if (Counter(packed + remaining) != Counter(identities) or
                    type(row["complete"]) is not bool or row["complete"] != (not remaining)):
                errors.append(label + ": identity conservation/completeness failed")
            names = list(trucks)
            available = Counter({name: qty for name, qty in zip(names, config["combination"])})
            if Counter(tr["truck_type"] for tr in fleet) - available or any(not tr["boxes"] for tr in fleet):
                errors.append(label + ": undeclared or empty vehicle")
            validation = check_fleet(fleet, trucks, catalog, level=4, support_ratio=0,
                                     pressure_model="chain_area_v1", require_complete=row["complete"])
            if validation or row["errors"] != validation:
                errors.append(label + ": independent layout errors " + repr(validation))
            metrics = dict(vehicles=len(fleet), cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet),
                           placed=len(boxes), used_volume_cm3=sum(b["l"] * b["w"] * b["h"] for b in boxes))
            if any(row[k] != v for k, v in metrics.items()):
                errors.append(label + ": metric mismatch")
            if row["chain_audits"] != [audit_load_chain(tr["boxes"]) for tr in fleet]:
                errors.append(label + ": chain audit mismatch")
            for key in ("solve_cpu_seconds", "solve_wall_seconds"):
                t = row[key]
                if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                    errors.append(label + ": invalid timing")
            # Placement statistics must identify exactly the saved boxes, with
            # disjoint whole-block floor footprints. Referee above checks contents.
            placements = row["search"]["placements"]
            if (Counter(s for p in placements for s in p["serials"]) != Counter(packed) or
                    row["search"]["placed_blocks"] != len(placements) or
                    len({p["block_id"] for p in placements}) != len(placements)):
                errors.append(label + ": block-placement identities mismatch")
            for i, a in enumerate(placements):
                idx = a["vehicle_index"]
                sequence = [name for name, qty in zip(names, config["combination"]) for _ in range(qty)]
                if type(idx) is not int or not 0 <= idx < len(sequence):
                    raise ValueError("invalid block vehicle index")
                dims = trucks[sequence[idx]]["dims"]
                if (min(a["x"], a["y"]) < 0 or min(a["l"], a["w"]) <= 0 or
                        a["x"] + a["l"] > dims[0] or a["y"] + a["w"] > dims[1]):
                    errors.append(label + ": block footprint outside truck")
                for b in placements[:i]:
                    if (idx == b["vehicle_index"] and
                            max(a["x"], b["x"]) < min(a["x"] + a["l"], b["x"] + b["l"]) and
                            max(a["y"], b["y"]) < min(a["y"] + a["w"], b["y"] + b["w"])):
                        errors.append(label + ": overlapping block footprints")
            actual_record = {k: v for k, v in row.items() if k not in ("fleet", "chain_audits", "search")}
            actual_record["file"] = label + ".json"
            if actual_record != record:
                errors.append(label + ": manifest/row mismatch")
            checked.append(actual_record)
        objectives = objective_summary(checked)
        if manifest["independent_objectives"] != objectives:
            errors.append("objective ranking mismatch")
        best = {}
        for combo in ((0, 1), (2, 0)):
            candidates = [r for r in checked if r["config"]["combination"] == list(combo)]
            row = min(candidates, key=lambda r: (-r["used_volume_cm3"], r["label"]))
            best[str(combo)] = {k: row[k] for k in ("label", "config", "placed", "used_volume_cm3", "complete", "rest_serials")}
        result.update(runs=len(checked), hashed_files=len(hashes), complete_runs=sum(r["complete"] for r in checked),
                      independent_objectives=objectives, best_by_combination=best,
                      cpu_seconds=sum(r["solve_cpu_seconds"] for r in checked),
                      wall_seconds=sum(r["solve_wall_seconds"] for r in checked))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append("bundle read failed: " + str(exc))
    return dict(result, errors=errors, passed=not errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    result = verify_bundle(parser.parse_args().directory)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)

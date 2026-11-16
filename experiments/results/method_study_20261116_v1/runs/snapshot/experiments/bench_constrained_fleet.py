"""Versioned full-constraint fixed-fleet baseline; P1/P2 independently ranked.

All candidate configurations are tested; a heuristic failure never prunes a
vehicle combination as infeasible. Trivial volume/weight lower bounds are
valid necessary conditions, not sufficient packing certificates.
"""
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
from src.constrained_ep import pack_fixed_fleet
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain
from src.pack_lib import TRUCKS, expand_items, apply_level


def volume(item):
    return item["dims"][0] * item["dims"][1] * item["dims"][2]


def sort_items(items, order):
    keys = {
        "volume": lambda it: (-volume(it), it["serial"]),
        "height": lambda it: (it["dims"][2], -volume(it), it["serial"]),
        "fragile_last": lambda it: (it["kind"] == "fragile", -volume(it), it["serial"]),
        "fragile_first": lambda it: (it["kind"] != "fragile", -volume(it), it["serial"]),
        "standard_first": lambda it: (it["kind"] != "standard", -volume(it), it["serial"]),
    }
    if order not in keys:
        raise ValueError("unknown item order")
    return sorted(items, key=keys[order])


def candidate_combinations(total_volume, total_weight, trucks, max_vehicles, max_cost):
    """Finite search domain sufficient to improve supplied feasible incumbents.

    Union of count<=incumbent P1 and cost<=incumbent P2, NOT intersection.
    Positive costs imply a finite domain even if P2 uses more vehicles.
    """
    if any(tr.cost <= 0 for tr in trucks):
        raise ValueError("positive costs required")
    counts = [max(max_vehicles, max_cost // tr.cost) for tr in trucks]
    for combo in itertools.product(*(range(bound + 1) for bound in counts)):
        n = sum(combo)
        cost = sum(qty * tr.cost for qty, tr in zip(combo, trucks))
        if not n or not (n <= max_vehicles or cost <= max_cost):
            continue
        capacity = sum(qty * tr.dims[0] * tr.dims[1] * (tr.dims[2] - 3)
                       for qty, tr in zip(combo, trucks))
        weight_capacity = sum(qty * tr.cap_weight for qty, tr in zip(combo, trucks))
        if capacity >= total_volume and weight_capacity >= total_weight:
            yield combo


def select_objectives(records):
    feasible = [r for r in records if r["complete"] and not r["errors"]]
    if not feasible:
        return {"P1": None, "P2": None}
    p1 = min(feasible, key=lambda r: (r["vehicles"], r["cost"], r["label"]))
    p2 = min(feasible, key=lambda r: (r["cost"], r["vehicles"], r["label"]))
    return {"P1": {"objective": "vehicles", "value": p1["vehicles"], "label": p1["label"],
                   "cost": p1["cost"], "status": "best_verified_heuristic_not_global_optimum"},
            "P2": {"objective": "cost", "value": p2["cost"], "label": p2["label"],
                   "vehicles": p2["vehicles"], "status": "best_verified_heuristic_not_global_optimum"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--level", type=int, default=4, choices=range(5))
    parser.add_argument("--scope", choices=("single", "fleet"), default="fleet")
    parser.add_argument("--orders", nargs="+", default=["volume", "height", "fragile_last", "fragile_first", "standard_first"])
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("preserve existing evidence; use a new directory")
    catalog = load_catalog(ROOT / "data/items.csv")
    truck_catalog = load_trucks(ROOT / "data/trucks.csv")
    items = apply_level(expand_items(), args.level)
    args.output_dir.mkdir(parents=True)
    hashes = {}

    def save(name, payload):
        path = args.output_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    for rel in ("src/constrained_ep.py", "src/pack_lib.py", "src/constraints.py", "experiments/bench_constrained_fleet.py",
                "data/items.csv", "data/trucks.csv"):
        dest = args.output_dir / "snapshot" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / rel).read_bytes())
        hashes[dest.relative_to(args.output_dir).as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
    total_volume = sum(volume(it) for it in items)
    total_weight = sum(it["weight"] for it in items)
    if args.scope == "single":
        combos = [(1, 0), (0, 1)]
    else:
        # Historical feasible layouts give 2 vehicles and 1350 cost, but under
        # the old filter. Include witness fleets (3 small, 2 large) and verify
        # new chain-filtered constructions before claiming new incumbents.
        combos = list(candidate_combinations(total_volume, total_weight, TRUCKS, 3, 1400))
    planned = []
    for combo in combos:
        available = [tr for qty, tr in zip(combo, TRUCKS) for _ in range(qty)]
        sequences = [available]
        reverse = list(reversed(available))
        if reverse != available:
            sequences.append(reverse)
        for sequence in sequences:
            for order in args.orders:
                planned.append((combo, sequence, order))
    save("environment.json", {"platform": platform.platform(), "python": sys.version, "scope": args.scope,
                              "level": args.level, "pressure_model": "chain_area_v1", "support_ratio": 0,
                              "source_total_volume_cm3": total_volume, "source_total_weight_kg": total_weight,
                              "command": sys.argv, "planned_count": len(planned),
                              "limitation": "bounded_EP_orders_not_global_search_or_moment_equilibrium"})
    records = []
    for index, (combo, sequence, order) in enumerate(planned):
        gc.collect()
        started = time.perf_counter()
        fleet, rest = pack_fixed_fleet(sort_items(items, order), sequence, level=args.level)
        seconds = time.perf_counter() - started
        errors = check_fleet(fleet, truck_catalog, catalog, level=args.level,
                             pressure_model="chain_area_v1", require_complete=not rest)
        label = f"{args.scope}_L{args.level}_{index:03d}"
        row = {"label": label, "combination": combo, "vehicle_order": [tr.name for tr in sequence],
               "item_order": order, "level": args.level, "pressure_model": "chain_area_v1",
               "fleet": fleet, "rest_serials": [it["serial"] for it in rest], "complete": not rest,
               "vehicles": len(fleet), "cost": sum(truck_catalog[tr["truck_type"]]["cost"] for tr in fleet),
               "placed": sum(len(tr["boxes"]) for tr in fleet), "used_volume_cm3": sum(
                   b["l"] * b["w"] * b["h"] for tr in fleet for b in tr["boxes"]),
               "errors": errors, "solve_wall_seconds": seconds,
               "chain_audits": [audit_load_chain(tr["boxes"]) for tr in fleet] if args.level >= 4 else []}
        save(label + ".json", row)
        record = {k: v for k, v in row.items() if k not in ("fleet", "chain_audits")}
        record["file"] = label + ".json"
        records.append(record)
        save("manifest.json", {"status": "in_progress", "planned_count": len(planned), "runs": records})
        print(json.dumps({k: row[k] for k in ("label", "combination", "item_order", "placed", "vehicles", "cost", "complete", "errors", "solve_wall_seconds")}), flush=True)
        if errors:
            raise RuntimeError("independent verification rejected generated solution")
    save("manifest.json", {"status": "verified", "planned_count": len(planned), "runs": records,
                           "independent_objectives": select_objectives(records) if args.scope == "fleet" else None,
                           "single_objective": "maximize_loaded_volume_allow_subset" if args.scope == "single" else None,
                           "note": "partial fleets never enter P1/P2; heuristic failure does not prove infeasible"})
    (args.output_dir / "sha256.json").write_text(json.dumps({"algorithm": "SHA256", "files": hashes}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

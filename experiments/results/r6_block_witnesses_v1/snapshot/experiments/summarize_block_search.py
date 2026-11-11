"""R6 evidence-derived summary, objective certificates and coordinate roundtrip.

Optimality comes from a verified full-transport witness plus analytic original
fleet lower bounds, NOT completeness of the restricted block heuristic.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_block_search import verify_bundle
from experiments.verify_constrained_fleet import verify_bundle as verify_ep
from src.constraints import load_catalog, load_trucks, check_fleet, audit_load_chain
from src.solution_io import export_solution, read_solution, read_solution_csv, fleet_metrics


def build_summary(directory):
    directory = Path(directory)
    verification = verify_bundle(directory)
    baseline_dir = ROOT / "experiments/results/chain_mixed_L4_v1"
    baseline_verification = verify_ep(baseline_dir)
    if not verification["passed"] or not baseline_verification["passed"]:
        raise ValueError("evidence rejected")
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    runs = read(directory / "manifest.json")["runs"]
    baseline = read(baseline_dir / "manifest.json")["runs"]
    catalog = load_catalog(ROOT / "data/items.csv")
    trucks = load_trucks(ROOT / "data/trucks.csv")
    names = list(trucks)
    total_volume = sum(math.prod(spec["dims"]) * spec["qty"] for spec in catalog.values())
    total_weight = sum(spec["weight"] * spec["qty"] for spec in catalog.values())
    groups = []
    for combo in ((0, 1), (2, 0)):
        for capped in (False, True):
            selected = [r for r in runs if r["config"]["combination"] == list(combo) and r["config"]["capped"] == capped]
            best = min(selected, key=lambda r: (-r["used_volume_cm3"], r["label"]))
            groups.append(dict(combination=list(combo), capped=capped, runs=len(selected),
                               complete_runs=sum(r["complete"] for r in selected),
                               best_label=best["label"], placed=best["placed"],
                               used_volume_cm3=best["used_volume_cm3"]))
    witnesses = {}
    for combo in ((0, 1), (2, 0)):
        valid = [r for r in runs if r["config"]["combination"] == list(combo) and r["complete"] and not r["errors"]]
        if not valid:
            continue
        record = min(valid, key=lambda r: r["label"])
        row = read(directory / record["file"])
        fleet = row["fleet"]
        ratio_one = check_fleet(fleet, trucks, catalog, level=4, support_ratio=1,
                                pressure_model="chain_area_v1", require_complete=True)
        legacy = check_fleet(fleet, trucks, catalog, level=4, support_ratio=0,
                             pressure_model="legacy_b1", require_complete=True)
        audits = [audit_load_chain(tr["boxes"]) for tr in fleet]
        witnesses[str(combo)] = dict(label=record["label"], fleet=fleet,
                                     metrics=fleet_metrics(fleet, trucks, catalog),
                                     support_ratio_1_errors=ratio_one, legacy_b1_errors=legacy,
                                     max_top_pressure_kg_m2=max(v for a in audits for v in a["top_pressure"].values()),
                                     max_height_cm=max(b["z"] + b["h"] for tr in fleet for b in tr["boxes"]),
                                     floor_reaction_kg=sum(sum(a["floor_reactions"].values()) for a in audits),
                                     floor_reaction_residual_kg=sum(a["conservation_residual_kg"] for a in audits),
                                     by_vehicle=[dict(truck_type=tr["truck_type"], items=len(tr["boxes"]),
                                                      volume_cm3=sum(b["l"] * b["w"] * b["h"] for b in tr["boxes"]),
                                                      weight_kg=sum(b["weight"] for b in tr["boxes"]),
                                                      counts=dict(Counter(b["name"] for b in tr["boxes"]))) for tr in fleet])
    capacities = {name: spec["dims"][0] * spec["dims"][1] * (spec["dims"][2] - 3) for name, spec in trucks.items()}
    # Independent cost lower bound: enumerate EVERY original-type fleet cheaper
    # than the verified candidate. Positive costs bound this enumeration exactly.
    objectives = verification["independent_objectives"]
    certificates = {}
    if objectives["P1"] is not None and objectives["P2"] is not None:
        p1, p2 = objectives["P1"], objectives["P2"]
        count_lower = 1 if total_volume > 0 else 0
        cheaper = []
        for a in range((p2["value"] - 1) // trucks[names[0]]["cost"] + 1):
            for b in range((p2["value"] - 1) // trucks[names[1]]["cost"] + 1):
                quantities = (a, b)
                cost = sum(q * trucks[name]["cost"] for q, name in zip(quantities, names))
                if cost >= p2["value"]:
                    continue
                capacity = sum(q * capacities[name] for q, name in zip(quantities, names))
                weight_capacity = sum(q * trucks[name]["cap_weight"] for q, name in zip(quantities, names))
                cheaper.append(dict(combination=list(quantities), cost=cost, effective_volume_cm3=capacity,
                                    rejected_by_volume=capacity < total_volume,
                                    rejected_by_weight=weight_capacity < total_weight))
        cheaper_excluded = all(c["rejected_by_volume"] or c["rejected_by_weight"] for c in cheaper)
        certificates = dict(
            scope="original_300_items_two_truck_types_L4_chain_area_v1_support0_clearance3",
            P1=dict(lower_bound=count_lower, upper_bound=p1["value"],
                    witness=p1["label"], proven_optimal=p1["value"] == count_lower,
                    argument="nonempty shipment needs at least one vehicle"),
            P2=dict(lower_bound=p2["value"] if cheaper_excluded else None, upper_bound=p2["value"],
                    witness=p2["label"], proven_optimal=cheaper_excluded,
                    all_strictly_cheaper_fleets=cheaper,
                    argument="all cheaper original fleets fail necessary capacity; verified witness attains cost"),
            boundary="No optimality claim for maximal packing heuristics, other instances, physical safety or modified models")
    ep_best = {}
    for combo in ((0, 1), (2, 0)):
        selected = [r for r in baseline if r["combination"] == list(combo)]
        best = min(selected, key=lambda r: (-r["used_volume_cm3"], r["label"]))
        ep_best[str(combo)] = {k: best[k] for k in ("label", "placed", "used_volume_cm3", "complete")}
    return dict(verification=verification, baseline_verification=baseline_verification,
                source=dict(items=sum(s["qty"] for s in catalog.values()), volume_cm3=total_volume,
                            weight_kg=total_weight, effective_capacities_cm3=capacities),
                groups=groups, baseline_best=ep_best, witnesses=witnesses, certificates=certificates,
                note="known-instance development, configurations not independent random repetitions; no measured AI-time saving")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("preserve existing evidence; use a new directory")
    summary = build_summary(args.directory)
    args.output_dir.mkdir(parents=True)
    trucks = load_trucks(ROOT / "data/trucks.csv")
    catalog = load_catalog(ROOT / "data/items.csv")
    for key, witness in summary["witnesses"].items():
        stem = "one_large" if key == "(0, 1)" else "two_small"
        json_path, csv_path = args.output_dir / (stem + ".json"), args.output_dir / (stem + ".csv")
        fleet = witness.pop("fleet")
        export_solution(fleet, json_path, csv_path, trucks, pressure_model="chain_area_v1")
        for restored in (read_solution(json_path, trucks), read_solution_csv(csv_path, trucks)):
            if restored != fleet:
                raise ValueError("coordinate roundtrip differs from original")
            errors = check_fleet(restored, trucks, catalog, pressure_model="chain_area_v1", require_complete=True)
            if errors:
                raise ValueError("restored witness rejected: " + repr(errors))
        witness["export_files"] = [json_path.name, csv_path.name]
        witness["json_csv_roundtrip_passed"] = True
    for rel in ("experiments/summarize_block_search.py", "src/solution_io.py"):
        dest = args.output_dir / "snapshot" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / rel).read_bytes())
    target = args.output_dir / "summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    files = {p.relative_to(args.output_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in args.output_dir.rglob("*") if p.is_file()}
    (args.output_dir / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=files), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

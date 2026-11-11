"""R7 exact reuse of saved R6 layouts across a preregistered parameter grid."""
import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import load_catalog, load_trucks
from experiments.verify_block_search import verify_bundle
from experiments.parameter_envelope import (exact_thresholds, accepts, canonical_digest,
                                           check_parameter_fleet, boundary_cases)

ALPHAS = ["0", "1/4", "1/2", "3/4", "9/10", "1"]
PRESSURES = ["0", "100", "200", "250", "300", "317", "318", "350", "362", "363", "400", "500"]
CLEARANCES = ["0", "3", "5", "10", "11", "20", "25", "30", "40", "50"]
SNAPSHOTS = ["experiments/parameter_envelope.py", "experiments/bench_parameter_envelope.py",
             "experiments/verify_parameter_envelope.py", "experiments/verify_block_search.py",
             "experiments/verify_constrained_fleet.py", "src/constraints.py",
             "data/items.csv", "data/trucks.csv", "docs/10-R7参数区间协议.md"]


def objective_at(candidates, alpha, pressure, clearance, trucks, total_volume):
    valid = [r for r in candidates if accepts(r["threshold"], alpha, pressure, clearance)]
    if not valid:
        return dict(alpha=alpha, pressure=pressure, clearance=clearance, witness_count=0,
                    P1=None, P2=None, status="no_saved_witness_not_infeasible")
    p1 = min(valid, key=lambda r: (r["threshold"]["vehicles"], r["threshold"]["cost"], r["label"]))
    p2 = min(valid, key=lambda r: (r["threshold"]["cost"], r["threshold"]["vehicles"], r["label"]))
    cost = p2["threshold"]["cost"]
    names = list(trucks)
    cheaper_volume_excluded = True
    for quantities in itertools.product(*(range((cost - 1) // trucks[n]["cost"] + 1) for n in names)):
        if sum(q * trucks[n]["cost"] for q, n in zip(quantities, names)) >= cost:
            continue
        capacity = sum(q * trucks[n]["dims"][0] * trucks[n]["dims"][1] *
                       max(Fraction(0), trucks[n]["dims"][2] - Fraction(clearance))
                       for q, n in zip(quantities, names))
        if capacity >= total_volume:
            cheaper_volume_excluded = False
            break
    return dict(alpha=alpha, pressure=pressure, clearance=clearance, witness_count=len(valid),
                P1=dict(value=p1["threshold"]["vehicles"], witness=p1["label"],
                        proven_optimal=p1["threshold"]["vehicles"] == 1),
                P2=dict(value=cost, witness=p2["label"], proven_optimal=cheaper_volume_excluded),
                status="witness_and_lower_bounds" if p1["threshold"]["vehicles"] == 1 and cheaper_volume_excluded
                else "verified_upper_bounds_not_global_optimum")


def pareto_frontier(candidates, combination):
    selected = [r for r in candidates if r["combination"] == combination]
    signatures = {}
    for r in selected:
        t = r["threshold"]
        key = (t["alpha_max"], t["pressure_min"], t["clearance_max"])
        signatures.setdefault(key, []).append(r["label"])
    result = []
    for (a, p, d), labels in signatures.items():
        if any(Fraction(a2) >= Fraction(a) and Fraction(p2) <= Fraction(p) and Fraction(d2) >= Fraction(d)
               and (a2, p2, d2) != (a, p, d) for a2, p2, d2 in signatures):
            continue
        result.append(dict(alpha_max=a, pressure_min=p, clearance_max=d, witnesses=sorted(labels)))
    return sorted(result, key=lambda t: (Fraction(t["pressure_min"]), -Fraction(t["clearance_max"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if directory.exists():
        parser.error("preserve existing evidence; use a new directory")
    source = ROOT / "experiments/results/block_search_L4_v1"
    verification = verify_bundle(source)
    if not verification["passed"]:
        raise ValueError("R6 source rejected")
    directory.mkdir(parents=True)
    hashes = {}

    def save(name, data):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def copy(rel, dest):
        target = directory / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(rel.read_bytes())
        hashes[dest] = hashlib.sha256(target.read_bytes()).hexdigest()

    # Plan emitted before the first threshold/grid analysis, not after results.
    save("plan.json", dict(schema="r7_fixed_pool_v1", alphas=ALPHAS, pressures=PRESSURES,
                           clearances=CLEARANCES, planned_grid_points=720, source_runs=96,
                           source_complete_runs=44, candidate_policy="all_complete_original_R6_records",
                           pressure_model="chain_area_v1", source_default=dict(alpha="0", pressure="500", clearance="3"),
                           scope="fixed_layout_pool_inner_feasible_region_not_reoptimization"))
    for rel in SNAPSHOTS:
        copy(ROOT / rel, "snapshot/" + rel)
    copy(source / "manifest.json", "source/manifest.json")
    copy(source / "sha256.json", "source/sha256.json")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    source_records = [r for r in manifest["runs"] if r["complete"] and not r["errors"]]
    catalog = load_catalog(ROOT / "data/items.csv")
    trucks = load_trucks(ROOT / "data/trucks.csv")
    volume = sum(s["dims"][0] * s["dims"][1] * s["dims"][2] * s["qty"] for s in catalog.values())
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    candidates, all_layouts, seen = [], {}, {}
    for r in source_records:
        copy(source / r["file"], "source/" + r["file"])
        layout = json.loads((source / r["file"]).read_text(encoding="utf-8"))["fleet"]
        digest = canonical_digest(layout)
        if digest in seen:
            seen[digest]["aliases"].append(r["label"])
            continue
        threshold = exact_thresholds(layout, trucks, catalog)
        if not accepts(threshold, "0", "500", "3"):
            raise ValueError("original full layout fails exact base threshold")
        candidate = dict(label=r["label"], aliases=[r["label"]], digest=digest,
                         source_file="source/" + r["file"], combination=r["config"]["combination"], threshold=threshold)
        seen[digest] = candidate
        candidates.append(candidate)
        all_layouts[r["label"]] = layout
    save("thresholds.json", dict(source_complete_runs=len(source_records), unique_layouts=len(candidates), candidates=candidates))
    boundaries = []
    for candidate in candidates:
        for case in boundary_cases(candidate["threshold"]):
            parameters = {k: case[k] for k in ("alpha", "pressure", "clearance")}
            accepted = accepts(candidate["threshold"], **parameters)
            independent_errors = check_parameter_fleet(all_layouts[candidate["label"]], trucks, catalog, **parameters)
            if accepted != (not independent_errors):
                raise ValueError("exact threshold/original referee boundary mismatch")
            boundaries.append(dict(witness=candidate["label"], **case, accepted=accepted,
                                   independent_errors=independent_errors))
    save("boundary_checks.json", dict(runs=len(boundaries), checks=boundaries, passed=True))
    grid = [dict(index=i, **objective_at(candidates, a, p, d, trucks, volume))
            for i, (a, p, d) in enumerate(itertools.product(ALPHAS, PRESSURES, CLEARANCES))]
    save("grid.json", dict(points=len(grid), rows=grid))
    csv_path = directory / "grid.csv"
    fields = ["index", "alpha", "pressure", "clearance", "witness_count", "P1", "P2", "P1_proven", "P2_proven", "status"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in grid:
            writer.writerow({**{k: row[k] for k in fields if k not in ("P1", "P2", "P1_proven", "P2_proven")},
                             "P1": row["P1"]["value"] if row["P1"] else "",
                             "P2": row["P2"]["value"] if row["P2"] else "",
                             "P1_proven": row["P1"]["proven_optimal"] if row["P1"] else False,
                             "P2_proven": row["P2"]["proven_optimal"] if row["P2"] else False})
    hashes["grid.csv"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    frontier = {"one_large": pareto_frontier(candidates, [0, 1]), "two_small": pareto_frontier(candidates, [2, 0])}
    save("summary.json", dict(unique_layouts=len(candidates), source_complete_runs=len(source_records),
                               boundary_checks=len(boundaries), grid_points=len(grid),
                               status_counts=dict(Counter(r["status"] for r in grid)), frontier=frontier,
                               optimal_700_grid_points=sum(bool(r["P2"] and r["P2"]["value"] == 700 and r["P2"]["proven_optimal"]) for r in grid),
                               no_witness_is_not_infeasibility=True, no_ai_time_saving_claim=True))
    save("environment.json", dict(platform=platform.platform(), python=sys.version, command=sys.argv,
                                   analysis_wall_seconds=time.perf_counter() - start_wall,
                                   analysis_cpu_seconds=time.process_time() - start_cpu))
    save("manifest.json", dict(status="complete", files_before_manifest=sorted(hashes), source_verified=True))
    (directory / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=hashes), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(json.loads((directory / "summary.json").read_text(encoding="utf-8")), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

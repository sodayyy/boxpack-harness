"""Read-only R7 verification; recompute fixed-pool analysis, never run a solver.

Shares the exact threshold routine (not a second independent math proof), and
cross-checks every saved boundary with the original independent referee.
"""
import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.constraints import load_catalog, load_trucks
from experiments.parameter_envelope import (exact_thresholds, canonical_digest, accepts,
                                           check_parameter_fleet, boundary_cases)

SNAPSHOTS = ["experiments/parameter_envelope.py", "experiments/bench_parameter_envelope.py",
             "experiments/verify_parameter_envelope.py", "experiments/verify_block_search.py",
             "experiments/verify_constrained_fleet.py", "src/constraints.py",
             "data/items.csv", "data/trucks.csv", "docs/10-R7参数区间协议.md"]
ALPHAS = ["0", "1/4", "1/2", "3/4", "9/10", "1"]
PRESSURES = ["0", "100", "200", "250", "300", "317", "318", "350", "362", "363", "400", "500"]
CLEARANCES = ["0", "3", "5", "10", "11", "20", "25", "30", "40", "50"]


def verify_bundle(directory):
    directory = Path(directory).resolve()
    errors, result = [], dict(directory=str(directory))
    try:
        read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
        plan, hashes, manifest = read("plan.json"), read("sha256.json")["files"], read("manifest.json")
        if (plan != dict(schema="r7_fixed_pool_v1", alphas=ALPHAS, pressures=PRESSURES, clearances=CLEARANCES,
                         planned_grid_points=720, source_runs=96, source_complete_runs=44,
                         candidate_policy="all_complete_original_R6_records", pressure_model="chain_area_v1",
                         source_default=dict(alpha="0", pressure="500", clearance="3"),
                         scope="fixed_layout_pool_inner_feasible_region_not_reoptimization")):
            raise ValueError("plan differs from fixed R7 protocol")
        if manifest["status"] != "complete" or manifest["source_verified"] is not True:
            errors.append("incomplete execution")
        source_manifest = read("source/manifest.json")
        source_hashes = read("source/sha256.json")["files"]
        if (source_manifest["status"] != "verified" or len(source_manifest["runs"]) != 96 or
                hashlib.sha256((directory / "source/manifest.json").read_bytes()).hexdigest() != source_hashes["manifest.json"]):
            raise ValueError("R6 source manifest integrity failure")
        # Bind the subset to the verified original R6 bundle in this project.
        original = ROOT / "experiments/results/block_search_L4_v1"
        for name in ("manifest.json", "sha256.json"):
            if (directory / "source" / name).read_bytes() != (original / name).read_bytes():
                errors.append("source differs from archived R6: " + name)
        source_runs = [r for r in source_manifest["runs"] if r["complete"] and not r["errors"]]
        if len(source_runs) != 44:
            raise ValueError("wrong full-source selection")
        required = {"plan.json", "thresholds.json", "boundary_checks.json", "grid.json", "grid.csv", "summary.json",
                    "environment.json", "manifest.json", "source/manifest.json", "source/sha256.json"} | {
                    "snapshot/" + rel for rel in SNAPSHOTS} | {"source/" + r["file"] for r in source_runs}
        if set(hashes) != required:
            errors.append("hash set does not match required full R7 bundle")
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != required | {"sha256.json"}:
            errors.append("unexpected/missing files")
        if manifest["files_before_manifest"] != sorted(required - {"manifest.json"}):
            errors.append("execution manifest file list mismatch")
        for name, digest in hashes.items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("hash path outside evidence")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append("hash mismatch: " + name)
        for rel in ("data/items.csv", "data/trucks.csv"):
            if (directory / "snapshot" / rel).read_bytes() != (ROOT / rel).read_bytes():
                errors.append("catalog mismatch: " + rel)
        trucks = load_trucks(directory / "snapshot/data/trucks.csv")
        catalog = load_catalog(directory / "snapshot/data/items.csv")
        candidates, seen, fleets = [], {}, {}
        for r in source_runs:
            name = "source/" + r["file"]
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != source_hashes[r["file"]]:
                errors.append("source layout differs from R6 hash: " + name)
            row = read(name)
            fleet = row["fleet"]
            if row["label"] != r["label"] or row["config"] != r["config"]:
                errors.append("source record mismatch")
            digest = canonical_digest(fleet)
            if digest in seen:
                seen[digest]["aliases"].append(r["label"])
                continue
            threshold = exact_thresholds(fleet, trucks, catalog)
            item = dict(label=r["label"], aliases=[r["label"]], digest=digest,
                        source_file=name, combination=r["config"]["combination"], threshold=threshold)
            seen[digest] = item
            candidates.append(item)
            fleets[r["label"]] = fleet
        expected_thresholds = dict(source_complete_runs=44, unique_layouts=len(candidates), candidates=candidates)
        if read("thresholds.json") != expected_thresholds:
            errors.append("saved thresholds/deduplication differs from exact recomputation")
        checked_boundaries = []
        for candidate in candidates:
            for case in boundary_cases(candidate["threshold"]):
                params = {k: case[k] for k in ("alpha", "pressure", "clearance")}
                accepted = accepts(candidate["threshold"], **params)
                numeric_errors = check_parameter_fleet(fleets[candidate["label"]], trucks, catalog, **params)
                if accepted != (not numeric_errors):
                    errors.append("threshold/referee boundary mismatch")
                checked_boundaries.append(dict(witness=candidate["label"], **case, accepted=accepted,
                                                independent_errors=numeric_errors))
        if read("boundary_checks.json") != dict(runs=len(checked_boundaries), checks=checked_boundaries, passed=True):
            errors.append("saved boundary checks differ")
        # Independently rebuild rankings for every point; P1 bound is nonempty
        # shipment, P2 cheaper-fleet volume bound is recalculated explicitly.
        total_volume = sum(s["qty"] * s["dims"][0] * s["dims"][1] * s["dims"][2] for s in catalog.values())
        grid = read("grid.json")
        if grid["points"] != 720 or len(grid["rows"]) != 720:
            raise ValueError("truncated grid")
        csv_rows = list(csv.DictReader((directory / "grid.csv").open(encoding="utf-8-sig", newline="")))
        if len(csv_rows) != 720:
            raise ValueError("truncated CSV grid")
        names = list(trucks)
        for i, ((a, p, d), row, csv_row) in enumerate(zip(itertools.product(ALPHAS, PRESSURES, CLEARANCES), grid["rows"], csv_rows)):
            valid = [r for r in candidates if accepts(r["threshold"], a, p, d)]
            expected_row = dict(index=i, alpha=a, pressure=p, clearance=d, witness_count=len(valid),
                                P1=None, P2=None, status="no_saved_witness_not_infeasible")
            if valid:
                first = min(valid, key=lambda r: (r["threshold"]["vehicles"], r["threshold"]["cost"], r["label"]))
                second = min(valid, key=lambda r: (r["threshold"]["cost"], r["threshold"]["vehicles"], r["label"]))
                cost, excluded = second["threshold"]["cost"], True
                for qa in range((cost - 1) // trucks[names[0]]["cost"] + 1):
                    for qb in range((cost - 1) // trucks[names[1]]["cost"] + 1):
                        if qa * trucks[names[0]]["cost"] + qb * trucks[names[1]]["cost"] >= cost:
                            continue
                        capacity = sum(q * trucks[n]["dims"][0] * trucks[n]["dims"][1] * max(
                            Fraction(0), trucks[n]["dims"][2] - Fraction(d)) for q, n in zip((qa, qb), names))
                        if capacity >= total_volume:
                            excluded = False
                one = first["threshold"]["vehicles"] == 1
                expected_row.update(P1=dict(value=first["threshold"]["vehicles"], witness=first["label"], proven_optimal=one),
                                    P2=dict(value=cost, witness=second["label"], proven_optimal=excluded),
                                    status="witness_and_lower_bounds" if one and excluded else "verified_upper_bounds_not_global_optimum")
            if row != expected_row:
                errors.append("grid rank/status mismatch at " + str(i))
            expected_csv = {k: str(row[k]) for k in ("index", "alpha", "pressure", "clearance", "witness_count", "status")}
            expected_csv.update(P1=str(row["P1"]["value"]) if row["P1"] else "", P2=str(row["P2"]["value"]) if row["P2"] else "",
                                P1_proven=str(row["P1"]["proven_optimal"] if row["P1"] else False),
                                P2_proven=str(row["P2"]["proven_optimal"] if row["P2"] else False))
            if csv_row != expected_csv:
                errors.append("CSV/JSON alignment mismatch at " + str(i))
        # Check monotone witness availability under each one-axis relaxation.
        lookup = {(r["alpha"], r["pressure"], r["clearance"]): r["witness_count"] for r in grid["rows"]}
        monotone_checks = 0
        for (a, p, d), count in lookup.items():
            for aa in ALPHAS:
                if Fraction(aa) <= Fraction(a):
                    monotone_checks += 1
                    if lookup[aa, p, d] < count:
                        errors.append("alpha monotonicity failed")
            for pp in PRESSURES:
                if Fraction(pp) >= Fraction(p):
                    monotone_checks += 1
                    if lookup[a, pp, d] < count:
                        errors.append("pressure monotonicity failed")
            for dd in CLEARANCES:
                if Fraction(dd) <= Fraction(d):
                    monotone_checks += 1
                    if lookup[a, p, dd] < count:
                        errors.append("clearance monotonicity failed")
        summary = read("summary.json")
        if (summary["unique_layouts"] != len(candidates) or summary["source_complete_runs"] != 44 or
                summary["boundary_checks"] != len(checked_boundaries) or summary["grid_points"] != 720 or
                summary["status_counts"] != dict(Counter(r["status"] for r in grid["rows"])) or
                summary["no_witness_is_not_infeasibility"] is not True or summary["no_ai_time_saving_claim"] is not True or
                summary["optimal_700_grid_points"] != sum(bool(r["P2"] and r["P2"]["value"] == 700 and r["P2"]["proven_optimal"]) for r in grid["rows"])):
            errors.append("summary counts/claim mismatch")
        for key, combo in (("one_large", [0, 1]), ("two_small", [2, 0])):
            signatures = {}
            for r in candidates:
                if r["combination"] == combo:
                    t = r["threshold"]
                    signatures.setdefault((t["alpha_max"], t["pressure_min"], t["clearance_max"]), []).append(r["label"])
            frontier = []
            for sig, labels in signatures.items():
                a, p, d = map(Fraction, sig)
                dominated = any(Fraction(other[0]) >= a and Fraction(other[1]) <= p and Fraction(other[2]) >= d
                                and other != sig for other in signatures)
                if not dominated:
                    frontier.append(dict(alpha_max=sig[0], pressure_min=sig[1], clearance_max=sig[2], witnesses=sorted(labels)))
            frontier.sort(key=lambda t: (Fraction(t["pressure_min"]), -Fraction(t["clearance_max"])))
            if summary["frontier"][key] != frontier:
                errors.append("frontier dominance/coverage mismatch")
        result.update(grid_points=720, unique_layouts=len(candidates), source_complete_runs=44,
                      boundary_checks=len(checked_boundaries), monotonicity_checks=monotone_checks,
                      hashed_files=len(hashes), frontier=summary["frontier"], status_counts=summary["status_counts"])
    except (OSError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as exc:
        errors.append("verification failed: " + str(exc))
    return dict(result, errors=errors, passed=not errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    result = verify_bundle(parser.parse_args().directory)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)

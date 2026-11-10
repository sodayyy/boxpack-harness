"""Recompute R4 descriptive summaries from independently rechecked evidence.

Different stop rules remain separate. No equal-time leaderboard or statistical
significance claim is produced. This script does not rerun any solver.
"""
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_guesser_evidence import verify_bundle as verify_guesser
from experiments.verify_linux_components import verify_bundle as verify_components


def build_summary():
    results = ROOT / "experiments/results"
    source = ROOT / "data/thpack/thpack1.txt"
    names = ("guesser_dev10_5s30s_v1", "linux_components_dev10_v1", "guesser_frozen11_20_v1")
    checks = {name: (verify_components if name.startswith("linux_") else verify_guesser)(results / name, source)
              for name in names}
    if not all(check["passed"] for check in checks.values()):
        raise ValueError("evidence verification failed: " + json.dumps(checks))
    manifests = {name: json.loads((results / name / "manifest.json").read_text(encoding="utf-8"))
                 for name in names}
    components = manifests[names[1]]["runs"]
    old_ep = json.loads((results / "thpack1_ep_pure_geometry_v2.json").read_text(encoding="utf-8"))
    old_b2 = json.loads((results / "thpack1_b2_final_w8_s80.json").read_text(encoding="utf-8"))["rows"]
    historical = {}
    for method, old in (("ep", old_ep), ("b2", old_b2)):
        lookup = {str(row["pid"]): row for row in old}
        overlap = [r for r in components if r["method"] == method and r["pid"] in lookup]
        same_isd = same_boxes = 0
        for row in overlap:
            saved = json.loads((results / names[1] / row["file"]).read_text(encoding="utf-8"))["result"]
            same_isd += saved["isd"] == lookup[row["pid"]]["isd"]
            same_boxes += saved["boxes"] == lookup[row["pid"]]["boxes"]
        historical[method] = {"overlap_n": len(overlap), "identical_isd_n": same_isd,
                              "identical_box_lists_n": same_boxes}
    budget_changes = {}
    for name in (names[0], names[2]):
        pairs = {}
        for row in manifests[name]["runs"]:
            pairs.setdefault(row["pid"], {})[row["cpu_budget_seconds"]] = row["isd"]
        deltas = [pair[30] - pair[5] for pair in pairs.values()]
        budget_changes[name] = {"n": len(deltas), "mean_gain_percentage_points": mean(deltas) * 100,
                                "improved": sum(d > 1e-12 for d in deltas),
                                "unchanged": sum(abs(d) <= 1e-12 for d in deltas),
                                "decreased": sum(d < -1e-12 for d in deltas)}
    envs = {name: json.loads((results / name / "environment.json").read_text(encoding="utf-8"))
            for name in names}
    cpus = {env["cpu_affinity"] for env in envs.values()}
    if len(cpus) != 1:
        raise ValueError("comparison bundles use different logical CPUs")
    return {"scope": "R4 same-Linux configuration calibration and first frozen batch; not equal-time ranking",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "logical_cpu": next(iter(cpus)), "evidence_checks": checks,
            "guesser_summary_by_bundle": {name: manifests[name]["summary_by_budget"] for name in (names[0], names[2])},
            "budget_changes": budget_changes, "historical_layout_overlap": historical,
            "evidence_hash_manifests_sha256": {
                name: hashlib.sha256((results / name / "sha256.json").read_bytes()).hexdigest() for name in names},
            "limitations": ["EP stops after one deterministic construction; B2 uses w8/s80 state budget.",
                            "Guesser uses author CPU-time limits, not strict wall-time limits.",
                            "Rows 1-10 are development; rows 11-20 are frozen-parameter comparison, not unseen blind testing.",
                            "No confidence interval, general monotonicity or optimality proof from single runs.",
                            "Pure geometry only; no fragile/support/pressure or multi-vehicle conclusion."]}


def main():
    summary = build_summary()
    target = ROOT / "experiments/results/r4_linux_frozen_summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Read-only full-matrix verification and descriptive Guesser summary."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_guesser_evidence import verify_bundle
from src.thpack import parse_thpack


def build_summary():
    results = ROOT / "experiments/results"
    source = ROOT / "data/thpack/thpack1.txt"
    instances = parse_thpack(source)
    names = ["guesser_dev10_5s30s_v1"] + [f"guesser_frozen{i}_{i+9}_v1" for i in range(11, 101, 10)]
    checks, rows, hashes = {}, [], {}
    for name in names:
        directory = results / name
        check = verify_bundle(directory, source)
        checks[name] = check
        if not check["passed"]:
            raise ValueError("evidence rejected: " + json.dumps(check))
        rows.extend(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["runs"])
        hashes[name] = hashlib.sha256((directory / "sha256.json").read_bytes()).hexdigest()
    expected = Counter((str(inst["pid"]), budget) for inst in instances for budget in (5, 30))
    if Counter((r["pid"], r["cpu_budget_seconds"]) for r in rows) != expected:
        raise ValueError("cross-bundle complete 100 x 2 matrix mismatch")
    frozen_ids = {str(inst["pid"]) for inst in instances[10:]}
    parts = {"development_1_10": [r for r in rows if r["pid"] not in frozen_ids],
             "frozen_11_100": [r for r in rows if r["pid"] in frozen_ids],
             "all_1_100_descriptive": rows}
    summary = {}
    for split, selected in parts.items():
        budgets = {}
        for budget in (5, 30):
            runs = [r for r in selected if r["cpu_budget_seconds"] == budget]
            budgets[str(budget)] = dict(n=len(runs), mean_isd=mean(r["isd"] for r in runs),
                                       min_isd=min(r["isd"] for r in runs), max_isd=max(r["isd"] for r in runs),
                                       mean_process_cpu_seconds=mean(r["process_cpu_user_seconds"] + r["process_cpu_system_seconds"] for r in runs),
                                       mean_wall_seconds=mean(r["wall_seconds_solver_process"] for r in runs))
        pairs = {}
        for row in selected:
            pairs.setdefault(row["pid"], {})[row["cpu_budget_seconds"]] = row["isd"]
        deltas = [pair[30]-pair[5] for pair in pairs.values()]
        summary[split] = dict(by_budget=budgets, mean_gain_percentage_points=100*mean(deltas),
                             improved=sum(d > 1e-12 for d in deltas),
                             unchanged=sum(abs(d) <= 1e-12 for d in deltas),
                             decreased=sum(d < -1e-12 for d in deltas))
    return dict(passed=True, runs=len(rows), evidence_checks=checks, summaries=summary,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                evidence_hash_manifests_sha256=hashes,
                limitations=["Frozen parameters, not unseen blind testing; historical EP data had been viewed.",
                             "Single default run per budget; no statistical significance or monotonicity proof.",
                             "Author CPU limits; not equal-time ranking against deterministic EP/B2.",
                             "Pure geometry; no full-constraint fleet or physical safety conclusion."])


if __name__ == "__main__":
    summary = build_summary()
    target = ROOT / "experiments/results/r5_guesser100_summary.json"
    if target.exists():
        raise SystemExit("preserve existing summary")
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k != "evidence_checks"}, ensure_ascii=False, indent=2))

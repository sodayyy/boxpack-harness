"""Re-run existing research checks without solving or changing historical evidence.

Uses a fresh output directory, preserves command outputs and hashes inspected
source files. A successful audit is a project self-check, not an independent review.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.parent.is_dir():
        parser.error("output parent must exist")
    output.mkdir(exist_ok=False)
    checks = [
        ("unittest", ["-m", "unittest", "discover", "-s", "experiments", "-p", "test_*.py", "-v"]),
        ("constraint_triggers", ["experiments/test_constraints.py"]),
        ("R6_matrix", ["experiments/verify_block_search.py", "experiments/results/block_search_L4_v1"]),
        ("R6_one_large", ["experiments/verify_witness_exact.py", "experiments/results/r6_block_witnesses_v1/one_large.json"]),
        ("R6_two_small", ["experiments/verify_witness_exact.py", "experiments/results/r6_block_witnesses_v1/two_small.json"]),
        ("R7", ["experiments/verify_parameter_envelope.py", "experiments/results/parameter_envelope_R7_v1"]),
        ("R8", ["experiments/verify_variant_study.py", "experiments/results/quantity_variants_R8_v1"]),
        ("R9", ["experiments/verify_mixed_study.py", "experiments/results/mixed_blocks_R9_v1"]),
    ]
    report = dict(scope="read_only_evidence_recheck_not_new_search_or_AI_efficiency_measurement",
                  started=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  python=sys.version, platform=platform.platform(), commands=[],
                  source_sha256={})
    for folder in ("src", "experiments", "lean"):
        for path in sorted((ROOT / folder).glob("*")):
            if path.is_file() and path.suffix in (".py", ".lean", ".toml"):
                report["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for label, suffix in checks:
        command = [sys.executable, *suffix]
        result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=dict(os.environ), check=False)
        log = output / (label + ".log")
        log.write_bytes(result.stdout)
        record = dict(name=label, command=command, returncode=result.returncode,
                      log=log.name, sha256=hashlib.sha256(result.stdout).hexdigest())
        report["commands"].append(record)
        print(label, result.returncode, flush=True)
    report["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["passed"] = all(r["returncode"] == 0 for r in report["commands"])
    (output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Re-read and verify a completed Guesser evidence bundle without solving again."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.adapt_guesser_output import adapt, validate_input
from experiments.bench_guesser import output_errors
from src.thpack import parse_thpack


def verify_bundle(directory, source):
    errors = []
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))
    manifest = read("manifest.json")
    hashes = read("sha256.json")["files"]
    instances = {str(inst["pid"]): inst for inst in parse_thpack(source)}
    environment = read("environment.json")
    if hashlib.sha256(source.read_bytes()).hexdigest() != environment["source_data_sha256"]:
        errors.append("source data hash changed")
    for name, expected in hashes.items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append("hash mismatch: " + name)
    if manifest["status"] != "verified":
        errors.append("run manifest is not complete and verified")
    keys = set()
    for record in manifest["runs"]:
        label = record["label"]
        key = (record["pid"], record["cpu_budget_seconds"])
        if key in keys:
            errors.append("duplicate pid/budget: " + label)
        keys.add(key)
        try:
            inst = instances[record["pid"]]
            validate_input(inst, read(label + ".input.json"))
            payload = read(label + ".raw.json")
            recomputed = adapt(inst, payload)
            if recomputed != read(label + ".adapted.json"):
                errors.append("adaptation mismatch: " + label)
            errors.extend(label + ": " + err for err in output_errors(inst, payload, recomputed))
            if record["errors"] or record["returncode"] != 0:
                errors.append("process/validation failure: " + label)
            if record["placed"] != recomputed["placed"] or record["isd"] != recomputed["isd"]:
                errors.append("recorded metrics mismatch: " + label)
            for suffix in (".input.json", ".raw.json", ".adapted.json", ".stdout.log", ".stderr.log"):
                if label + suffix not in hashes:
                    errors.append("unhashed required artifact: " + label + suffix)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(label + ": " + str(exc))
    for budget, summary in manifest["summary_by_budget"].items():
        rows = [r for r in manifest["runs"] if r["cpu_budget_seconds"] == int(budget)]
        if summary["n"] != len(rows) or abs(summary["mean_isd"] - sum(r["isd"] for r in rows) / len(rows)) > 1e-12:
            errors.append("budget summary mismatch: " + budget)
    return {"runs": len(manifest["runs"]), "hashed_files": len(hashes),
            "errors": errors, "passed": not errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--file", type=Path, default=ROOT / "data/thpack/thpack1.txt")
    args = parser.parse_args()
    result = verify_bundle(args.directory, args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

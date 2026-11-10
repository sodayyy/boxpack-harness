"""Re-read and verify a completed Guesser evidence bundle without solving again."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.adapt_guesser_output import adapt, validate_input
from experiments.bench_guesser import output_errors, select_instances
from src.thpack import parse_thpack


def check_run_plan(manifest, environment, source_instances):
    """Check the declared full run matrix, not just the rows that survived."""
    errors = []
    try:
        if manifest.get("schema_version") == 2:
            selection = manifest["selection"]
            if selection != environment.get("selection"):
                errors.append("manifest/environment selection mismatch")
            start = selection["first_source_row"]
            last = selection["last_source_row"]
            if (isinstance(start, bool) or isinstance(last, bool)
                    or not isinstance(start, int) or not isinstance(last, int)):
                raise ValueError("source row indices must be integers")
            selected = select_instances(source_instances, start, last - start + 1,
                                        selection["split"])
            pids = [str(inst["pid"]) for inst in selected]
            if selection["pids"] != pids:
                errors.append("selection pids do not match source rows")
            budgets = selection["cpu_budgets_seconds"]
            if (not isinstance(budgets, list) or not budgets
                    or any(isinstance(b, bool) or not isinstance(b, int) or b < 1 for b in budgets)
                    or len(set(budgets)) != len(budgets)):
                raise ValueError("invalid CPU budget list")
            expected_rows = [{"pid": pid, "cpu_budget_seconds": budget}
                             for budget in budgets for pid in pids]
            if manifest["planned_runs"] != expected_rows:
                errors.append("declared run plan differs from selection")
        elif (manifest.get("schema_version") is None and manifest.get("scope") ==
              "first 10 development instances, author defaults, no claim of blind test or paper replication"):
            # Compatibility is restricted to the known R3 protocol, not any
            # arbitrary legacy bundle that happens to call itself verified.
            selected = select_instances(source_instances, 1, 10, "development")
            expected_rows = [{"pid": str(inst["pid"]), "cpu_budget_seconds": budget}
                             for budget in (5, 30) for inst in selected]
        else:
            raise ValueError("unsupported or missing evidence run plan")
        expected = Counter((r["pid"], r["cpu_budget_seconds"]) for r in expected_rows)
        actual_rows = manifest["runs"]
        for row in actual_rows:
            if (not isinstance(row["pid"], str)
                    or isinstance(row["cpu_budget_seconds"], bool)
                    or not isinstance(row["cpu_budget_seconds"], int)):
                raise ValueError("invalid run pid or CPU budget type")
        actual = Counter((r["pid"], r["cpu_budget_seconds"]) for r in actual_rows)
        if actual != expected:
            errors.append("actual runs do not match complete planned pid/budget matrix")
        expected_budgets = {str(budget) for _, budget in expected}
        if set(manifest["summary_by_budget"]) != expected_budgets:
            errors.append("budget summaries do not cover planned budgets")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append("invalid run plan: " + str(exc))
    return errors


def verify_bundle(directory, source):
    errors = []
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))
    manifest = read("manifest.json")
    hashes = read("sha256.json")["files"]
    source_instances = parse_thpack(source)
    instances = {str(inst["pid"]): inst for inst in source_instances}
    environment = read("environment.json")
    errors.extend(check_run_plan(manifest, environment, source_instances))
    for name in ("manifest.json", "environment.json"):
        if name not in hashes:
            errors.append("unhashed required metadata: " + name)
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
        if (not rows or summary["n"] != len(rows)
                or abs(summary["mean_isd"] - sum(r["isd"] for r in rows) / len(rows)) > 1e-12):
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

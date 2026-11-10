"""Read-only verification of the fixed first10 Linux EP/B2 evidence bundle.

Reconstruct the expected matrix from source order, check saved identities,
orientations and geometry, and recompute summaries. Never run a solver here.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.bench_guesser import select_instances
from experiments.verify_mes_result import verify
from src.thpack import parse_thpack, to_items

SNAPSHOTS = ("bench_linux_components.py", "bench_thpack.py", "bench_mes_beam.py",
             "bench_guesser.py", "verify_mes_result.py", "pack_lib.py",
             "mes_beam.py", "thpack.py")


def check_matrix(manifest, pids):
    expected = Counter((method, pid) for method in ("ep", "b2") for pid in pids)
    errors = []
    for key in ("planned_runs", "runs"):
        rows = manifest.get(key, [])
        if any(not isinstance(r, dict) or not isinstance(r.get("pid"), str)
               or not isinstance(r.get("method"), str) for r in rows):
            errors.append("invalid matrix row: " + key)
            continue
        if Counter((r["method"], r["pid"]) for r in rows) != expected:
            errors.append("incomplete or duplicated component matrix: " + key)
    if manifest.get("status") != "verified":
        errors.append("component manifest is not complete and verified")
    return errors


def expected_config(method):
    if method == "ep":
        return {"method": "EP", "order": "volume", "stop_rule": "one construction"}
    return {"method": "B2 disjoint-space partition + beam", "order": "volume",
            "beam_width": 8, "space_cap": 80, "state_priority": "volume",
            "stop_rule": "fixed state budget; not time interruptible"}


def verify_bundle(directory, source):
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))
    manifest, environment = read("manifest.json"), read("environment.json")
    hash_manifest = read("sha256.json")
    hashes = hash_manifest["files"]
    source_instances = select_instances(parse_thpack(source), 1, 10, "development")
    instances = {str(inst["pid"]): inst for inst in source_instances}
    errors = check_matrix(manifest, list(instances))
    if hash_manifest.get("algorithm") != "SHA256":
        errors.append("unsupported hash algorithm")
    required = {"manifest.json", "environment.json", "source_thpack.txt"}
    required.update("harness_snapshot/" + name for name in SNAPSHOTS)
    required.update(f"{method}_{pid}.json" for method in ("ep", "b2") for pid in instances)
    errors.extend("unhashed required artifact: " + name for name in sorted(required - set(hashes)))
    for name, digest in hashes.items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append("hash mismatch: " + name)
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if environment.get("source_sha256") != source_digest:
        errors.append("source data hash mismatch")
    if (directory / "source_thpack.txt").read_bytes() != source.read_bytes():
        errors.append("saved source copy mismatch")
    if environment.get("scope") != "first10 development; config calibration, not equal CPU budgets":
        errors.append("unexpected comparison scope")
    if environment.get("thread_env") != {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}:
        errors.append("unexpected thread configuration")
    if not str(environment.get("platform", "")).startswith("Linux-"):
        errors.append("expected Linux environment")
    if type(environment.get("cpu_affinity")) is not int:
        errors.append("missing single logical CPU affinity")
    verified_rows = []
    for record in manifest.get("runs", []):
        try:
            method, pid = record["method"], record["pid"]
            if method not in ("ep", "b2") or pid not in instances:
                raise ValueError("unknown method or source pid")
            filename = f"{method}_{pid}.json"
            if record["file"] != filename:
                raise ValueError("record filename mismatch")
            payload = read(filename)
            if payload["pid"] != pid or payload["config"] != expected_config(method):
                raise ValueError("pid or fixed configuration mismatch")
            if payload["verification_included_in_solve_time"] is not False:
                raise ValueError("unexpected timing boundary")
            errors.extend(filename + ": " + err for err in
                          verify(payload["result"], instances[pid]["box"], to_items(instances[pid])))
            if payload["errors"] or record["errors"]:
                errors.append("recorded validation failure: " + filename)
            if record["isd"] != payload["result"]["isd"]:
                errors.append("record metric mismatch: " + filename)
            for key in ("solve_cpu_seconds", "solve_wall_seconds"):
                value = payload[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0 or value != record[key]):
                    errors.append("invalid or inconsistent timing: " + filename + ": " + key)
            verified_rows.append(record)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append("invalid component record: " + str(exc))
    summaries = {}
    for method in ("ep", "b2"):
        rows = [r for r in verified_rows if r["method"] == method]
        if rows:
            summaries[method] = {"n": len(rows), "mean_isd": mean(r["isd"] for r in rows),
                                 "min_isd": min(r["isd"] for r in rows),
                                 "max_isd": max(r["isd"] for r in rows),
                                 "mean_solve_cpu_seconds": mean(r["solve_cpu_seconds"] for r in rows),
                                 "mean_solve_wall_seconds": mean(r["solve_wall_seconds"] for r in rows)}
    return {"runs": len(manifest.get("runs", [])), "hashed_files": len(hashes),
            "summary_by_method": summaries, "errors": errors, "passed": not errors}


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

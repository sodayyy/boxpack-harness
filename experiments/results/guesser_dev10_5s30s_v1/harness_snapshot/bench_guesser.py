"""Run the fixed unmodified Guesser binary on Linux and retain verifiable evidence.

The author's CPU-time stopping rule is preserved. A single allowed logical CPU
is pinned; wall and process CPU times are measured separately. Existing output
directories are refused to avoid overwriting earlier runs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.adapt_guesser_output import adapt, validate_input
from experiments.prepare_guesser_inputs import AUTHOR_COMMIT, convert
from experiments.verify_mes_result import verify
from src.thpack import parse_thpack, to_items


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def output_errors(inst, payload, adapted):
    errors = verify(adapted, inst["box"], to_items(inst))
    stats = payload.get("appendix", {}).get("packing_statistics", {})
    if stats.get("number_of_allocated_small_items") != adapted["placed"]:
        errors.append("author reported count mismatch")
    if stats.get("total_volume_of_allocated_small_items") != adapted["used_volume"]:
        errors.append("author reported volume mismatch")
    fraction = stats.get("volume_fraction_relative_to_large_object_volume")
    if (isinstance(fraction, bool) or not isinstance(fraction, (int, float))
            or not math.isfinite(fraction) or abs(fraction / 100 - adapted["isd"]) > 1e-9):
        errors.append("author reported ISD mismatch")
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=ROOT / "data/thpack/thpack1.txt")
    ap.add_argument("--instances", type=int, default=10)
    ap.add_argument("--budgets", type=int, nargs="+", default=[5, 30])
    ap.add_argument("--binary", type=Path, default=Path("/home/yzj/boxpack-author/build-release/app/allocate"))
    ap.add_argument("--author-source", type=Path, default=Path("/home/yzj/boxpack-author/sclp-75eec37"))
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.instances < 1 or any(b < 1 for b in args.budgets) or len(set(args.budgets)) != len(args.budgets):
        ap.error("instances and distinct budgets must be positive")
    if args.output_dir.exists():
        ap.error("output directory already exists; keep earlier evidence intact")
    if not args.binary.is_file() or not args.author_source.is_dir():
        ap.error("fixed author binary or source directory is missing")
    insts = parse_thpack(args.file)[:args.instances]
    if len(insts) != args.instances:
        ap.error("requested more instances than the source contains")
    cpu = min(os.sched_getaffinity(0))
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    args.output_dir.mkdir(parents=True)
    hashes = {}

    def register(path):
        hashes[str(path.relative_to(args.output_dir))] = sha256(path)

    environment = {"platform": platform.platform(), "python": sys.version,
                   "cpu_affinity": cpu, "allowed_cpus": sorted(os.sched_getaffinity(0)),
                   "cpu_model": next((line.split(":", 1)[1].strip() for line in
                                      Path("/proc/cpuinfo").read_text().splitlines()
                                      if line.startswith("model name")), "unknown"),
                   "binary": str(args.binary), "binary_sha256": sha256(args.binary),
                   "author_commit": AUTHOR_COMMIT, "build_type": "Release",
                   "thread_env": {k: env[k] for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
                   "started_utc": datetime.now(timezone.utc).isoformat(),
                   "source_data_sha256": sha256(args.file),
                   "harness_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
                   "harness_git_diff": subprocess.check_output(["git", "-C", str(ROOT), "diff", "--stat"], text=True),
                   "note": "working harness files are identified by per-file SHA256; HEAD alone is not the tested code",
                   "tool_versions": {}}
    for label, cmd in {"compiler": ["g++-14", "--version"], "cmake": ["cmake", "--version"],
                       "make": ["make", "--version"],
                       "boost": ["dpkg-query", "-W", "libboost-timer1.83-dev", "libboost-container1.83-dev"]}.items():
        environment["tool_versions"][label] = subprocess.check_output(cmd, text=True).strip()
    snapshot = args.output_dir / "harness_snapshot"
    snapshot.mkdir()
    for rel in ("experiments/bench_guesser.py", "experiments/adapt_guesser_output.py",
                "experiments/prepare_guesser_inputs.py", "experiments/verify_mes_result.py", "src/thpack.py"):
        dst = snapshot / Path(rel).name
        dst.write_bytes((ROOT / rel).read_bytes())
        register(dst)
    source_hasher = hashlib.sha256()
    source_files = 0
    for path in sorted(args.author_source.rglob("*")):
        if path.is_file():
            rel = path.relative_to(args.author_source).as_posix()
            source_hasher.update(rel.encode() + b"\0" + path.read_bytes() + b"\0")
            source_files += 1
    environment.update(author_export_tree_sha256=source_hasher.hexdigest(), author_export_files=source_files,
                       author_tree_hash_definition="sorted relative path UTF8 + NUL + file bytes + NUL")
    save_json(args.output_dir / "environment.json", environment)
    register(args.output_dir / "environment.json")
    records = []
    for budget in args.budgets:
        for inst in insts:
            label = f"thpack1_{inst['pid']}_{budget}s"
            inp = args.output_dir / (label + ".input.json")
            raw = args.output_dir / (label + ".raw.json")
            adapted_path = args.output_dir / (label + ".adapted.json")
            converted = convert(inst)
            validate_input(inst, converted)
            save_json(inp, converted)
            register(inp)
            command = ["taskset", "-c", str(cpu), str(args.binary), str(inp),
                       "--output-file=" + str(raw), f"--maximum_running_time_seconds={budget}"]
            record = {"label": label, "pid": str(inst["pid"]), "cpu_budget_seconds": budget,
                      "cpu_affinity": cpu, "command": command, "errors": []}
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            started = time.perf_counter()
            try:
                run = subprocess.run(command, capture_output=True, env=env,
                                     timeout=max(120, budget * 4))
                record["returncode"] = run.returncode
                stdout, stderr = run.stdout, run.stderr
            except subprocess.TimeoutExpired as exc:
                record.update(returncode=None, errors=["external wall timeout"])
                stdout, stderr = exc.stdout or b"", exc.stderr or b""
            record["wall_seconds_solver_process"] = time.perf_counter() - started
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            record["process_cpu_user_seconds"] = after.ru_utime - before.ru_utime
            record["process_cpu_system_seconds"] = after.ru_stime - before.ru_stime
            for suffix, data in (("stdout.log", stdout), ("stderr.log", stderr)):
                path = args.output_dir / (label + "." + suffix)
                path.write_bytes(data)
                register(path)
            if record["returncode"] != 0:
                record["errors"].append("author process did not succeed")
            elif not raw.exists():
                record["errors"].append("missing author output")
            else:
                register(raw)
                try:
                    payload = json.loads(raw.read_text(encoding="utf-8"))
                    adapted = adapt(inst, payload)
                    record["errors"].extend(output_errors(inst, payload, adapted))
                    save_json(adapted_path, adapted)
                    register(adapted_path)
                    record.update(placed=adapted["placed"], isd=adapted["isd"],
                                  elapsed_times=payload.get("appendix", {}).get("elapsed_times", {}))
                except (ValueError, KeyError, TypeError) as exc:
                    record["errors"].append(str(exc))
            records.append(record)
            save_json(args.output_dir / "manifest.json", {"status": "in_progress", "runs": records})
            print(json.dumps({k: record.get(k) for k in
                              ("label", "returncode", "placed", "isd", "errors")}), flush=True)
            if record["errors"]:
                break
        if records[-1]["errors"]:
            break
    passed = len(records) == len(insts) * len(args.budgets) and not any(r["errors"] for r in records)
    summaries = {}
    for budget in args.budgets:
        rows = [r for r in records if r["cpu_budget_seconds"] == budget and not r["errors"]]
        if rows:
            summaries[str(budget)] = {"n": len(rows), "mean_isd": statistics.mean(r["isd"] for r in rows),
                                      "min_isd": min(r["isd"] for r in rows),
                                      "max_isd": max(r["isd"] for r in rows),
                                      "mean_process_cpu_seconds": statistics.mean(
                                          r["process_cpu_user_seconds"] + r["process_cpu_system_seconds"] for r in rows),
                                      "mean_wall_seconds": statistics.mean(r["wall_seconds_solver_process"] for r in rows)}
    save_json(args.output_dir / "manifest.json", {"status": "verified" if passed else "failed",
              "scope": "first 10 development instances, author defaults, no claim of blind test or paper replication",
              "runs": records, "summary_by_budget": summaries})
    register(args.output_dir / "manifest.json")
    save_json(args.output_dir / "sha256.json", {"algorithm": "SHA256", "files": hashes,
              "note": "sha256.json is not self-hashed; anchor it by the Git commit"})
    print(json.dumps({"passed": passed, "summary_by_budget": summaries}), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

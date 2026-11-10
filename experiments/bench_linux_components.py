"""Serial Linux EP/B2 configuration calibration; NOT an equal-time leaderboard.

EP stops after one deterministic construction. B2 keeps the established w8/s80
state budget. CPU and wall times cover solving only; verification is separate.
Refuse existing output directories and retain inputs, layouts and source hashes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.bench_guesser import save_json, select_instances
from experiments.verify_mes_result import verify
from src.thpack import parse_thpack, to_items


def run_component(inst, method):
    # Imports occur before the solve clock. Missing NumPy is an error, not a
    # fallback to a different implementation or a fabricated timing.
    if method == "ep":
        from experiments.bench_thpack import pack_one
        solve = lambda: pack_one(inst, order="volume", verify=False)
        config = {"method": "EP", "order": "volume", "stop_rule": "one construction"}
    elif method == "b2":
        from experiments.bench_mes_beam import pack_one
        solve = lambda: pack_one(inst, beam_width=8, space_cap=80,
                                 order="volume", state_priority="volume")
        config = {"method": "B2 disjoint-space partition + beam", "order": "volume",
                  "beam_width": 8, "space_cap": 80, "state_priority": "volume",
                  "stop_rule": "fixed state budget; not time interruptible"}
    else:
        raise ValueError("unknown component")
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    row = solve()
    solve_wall = time.perf_counter() - started_wall
    solve_cpu = time.process_time() - started_cpu
    errors = verify(row, inst["box"], to_items(inst))
    return {"pid": str(inst["pid"]), "config": config,
            "solve_cpu_seconds": solve_cpu, "solve_wall_seconds": solve_wall,
            "verification_included_in_solve_time": False, "errors": errors,
            "result": row}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=ROOT / "data/thpack/thpack1.txt")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not hasattr(os, "sched_setaffinity"):
        parser.error("run inside the Linux research environment")
    if args.output_dir.exists():
        parser.error("output directory exists; preserve previous evidence")
    # Explicitly check both shared dependencies before creating a result bundle.
    import numpy
    from experiments.bench_thpack import pack_one as ep_entry
    from experiments.bench_mes_beam import pack_one as b2_entry
    instances = select_instances(parse_thpack(args.file), 1, 10, "development")
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    args.output_dir.mkdir(parents=True)
    snapshot = args.output_dir / "harness_snapshot"
    snapshot.mkdir()
    hashes = {}

    def register(path):
        hashes[path.relative_to(args.output_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()

    for rel in ("experiments/bench_linux_components.py", "experiments/bench_thpack.py",
                "experiments/bench_mes_beam.py", "experiments/bench_guesser.py",
                "experiments/verify_mes_result.py", "src/pack_lib.py", "src/mes_beam.py", "src/thpack.py"):
        target = snapshot / Path(rel).name
        target.write_bytes((ROOT / rel).read_bytes())
        register(target)
    source_copy = args.output_dir / "source_thpack.txt"
    source_copy.write_bytes(args.file.read_bytes())
    register(source_copy)
    environment = {"platform": platform.platform(), "python": sys.version,
                   "numpy": numpy.__version__, "cpu_affinity": cpu,
                   "started_utc": datetime.now(timezone.utc).isoformat(),
                   "source_sha256": hashlib.sha256(args.file.read_bytes()).hexdigest(),
                   "thread_env": {k: os.environ.get(k) for k in
                                  ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
                   "command": sys.argv,
                   "scope": "first10 development; config calibration, not equal CPU budgets"}
    save_json(args.output_dir / "environment.json", environment)
    register(args.output_dir / "environment.json")
    planned = [{"method": method, "pid": str(inst["pid"])}
               for method in ("ep", "b2") for inst in instances]
    records = []
    for planned_row in planned:
        method, pid = planned_row["method"], planned_row["pid"]
        inst = next(inst for inst in instances if str(inst["pid"]) == pid)
        row = run_component(inst, method)
        target = args.output_dir / f"{method}_{pid}.json"
        save_json(target, row)
        register(target)
        records.append({"method": method, "pid": pid, "file": target.name,
                        "isd": row["result"]["isd"], "errors": row["errors"],
                        "solve_cpu_seconds": row["solve_cpu_seconds"],
                        "solve_wall_seconds": row["solve_wall_seconds"]})
        save_json(args.output_dir / "manifest.json", {"status": "in_progress",
                  "planned_runs": planned, "runs": records})
        print(json.dumps(records[-1]), flush=True)
        if row["errors"]:
            break
    passed = len(records) == len(planned) and not any(r["errors"] for r in records)
    save_json(args.output_dir / "manifest.json", {"status": "verified" if passed else "failed",
              "planned_runs": planned, "runs": records,
              "note": "state-budget B2 and early-stopping EP are not an equal-time ranking"})
    register(args.output_dir / "manifest.json")
    save_json(args.output_dir / "sha256.json", {"algorithm": "SHA256", "files": hashes})
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Fixed-source Metasolver development baseline with audited stdout layouts.

Run under Linux after Guesser's serial matrix has completed. Uses the author's
default parameters and requested CPU-time limit, with logical CPU 0 pinned.
GPL author source is kept separate; only evidence and harness snapshots saved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.thpack import parse_thpack
from experiments.adapt_metasolver_output import extract_and_verify

REVISION = "bd7eef40e9f195c604cbc5e6dc0e7a9f98f11502"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=Path("/home/yzj/boxpack-author/metasolver-build-release/bsg"))
    parser.add_argument("--author-source", type=Path, default=Path("/home/yzj/boxpack-author/metasolver-bd7eef4"))
    args = parser.parse_args()
    if platform.system() != "Linux" or args.output_dir.exists():
        parser.error("requires Linux and a new evidence directory")
    source = ROOT / "data/thpack/thpack1.txt"
    instances = parse_thpack(source)[:10]
    args.output_dir.mkdir(parents=True)
    hashes = {}

    def save_bytes(name, content):
        dest = args.output_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()

    def save(name, payload):
        save_bytes(name, (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode())

    paths = ["experiments/bench_metasolver.py", "experiments/adapt_metasolver_output.py",
             "experiments/adapt_guesser_output.py", "experiments/verify_mes_result.py",
             "experiments/prepare_guesser_inputs.py", "src/thpack.py", "data/thpack/thpack1.txt"]
    for rel in paths:
        save_bytes("snapshot/"+rel, (ROOT / rel).read_bytes())
    author_hashes = {str(p.relative_to(args.author_source)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(args.author_source.rglob("*")) if p.is_file() and
                     (p.relative_to(args.author_source).parts[0] == "src" or p.name in ("CMakeLists.txt", "LICENSE", "README.md"))}
    command_env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    plan = [dict(pid=str(inst["pid"]), source_index=i, cpu_budget_seconds=budget)
            for budget in (5, 30) for i, inst in enumerate(instances)]
    save("environment.json", dict(platform=platform.platform(), python=sys.version,
                                  author_revision=REVISION, license="GPL-3.0; source separate",
                                  binary=str(args.binary), binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                                  author_source_hashes=author_hashes, cpu_affinity=0,
                                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                  planned_runs=plan, split="development_1_10", budgets=[5,30],
                                  thread_environment={key:command_env[key] for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
                                  limitation="author_cpu_stop_rule_not_equal_time_or_full_paper_replication"))
    rows = []
    for entry in plan:
        inst = instances[entry["source_index"]]
        label = f"metasolver_{entry['pid']}_{entry['cpu_budget_seconds']}s"
        cmd = ["taskset", "-c", "0", str(args.binary), str(source), "-i", str(entry["source_index"]),
               "-t", str(entry["cpu_budget_seconds"]), "--show_layout", "--json"]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        run = subprocess.run(cmd, capture_output=True, env=command_env, timeout=180)
        wall = time.perf_counter()-start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        save_bytes(label+".stdout.log", run.stdout)
        save_bytes(label+".stderr.log", run.stderr)
        if run.returncode:
            raise RuntimeError(f"author process failed: {label}: {run.returncode}")
        adapted = extract_and_verify(run.stdout.decode("utf-8"), inst)
        save(label+".adapted.json", adapted)
        row = dict(entry, label=label, command=cmd, returncode=run.returncode,
                   stdout=label+".stdout.log", stderr=label+".stderr.log", adapted=label+".adapted.json",
                   process_cpu_user_seconds=after.ru_utime-before.ru_utime,
                   process_cpu_system_seconds=after.ru_stime-before.ru_stime,
                   wall_seconds_solver_process=wall, placed=adapted["result"]["placed"],
                   isd=adapted["result"]["isd"], errors=[])
        rows.append(row)
        save("manifest.json", dict(status="in_progress", runs=rows))
        print(json.dumps({k:row[k] for k in ("label", "placed", "isd", "errors")}), flush=True)
    save("manifest.json", dict(status="verified", runs=rows))
    (args.output_dir / "sha256.json").write_text(json.dumps(dict(algorithm="SHA256", files=hashes), indent=2)+"\n")


if __name__ == "__main__":
    main()

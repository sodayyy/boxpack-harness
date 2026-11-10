"""Read-only full matrix, hash, source and layout verification for Metasolver."""
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
from experiments.adapt_metasolver_output import extract_and_verify
from src.thpack import parse_thpack


def verify_bundle(directory):
    directory = Path(directory)
    errors = []
    result = dict(directory=str(directory))
    try:
        read = lambda name: json.loads((directory/name).read_text(encoding="utf-8"))
        env, manifest = read("environment.json"), read("manifest.json")
        hashes = read("sha256.json")["files"]
        source = ROOT / "data/thpack/thpack1.txt"
        instances = parse_thpack(source)[:10]
        expected = [dict(pid=str(inst["pid"]), source_index=i, cpu_budget_seconds=budget)
                    for budget in (5,30) for i, inst in enumerate(instances)]
        if env["planned_runs"] != expected or env["split"] != "development_1_10":
            errors.append("declared plan differs from fixed development protocol")
        if (env["author_revision"] != "bd7eef40e9f195c604cbc5e6dc0e7a9f98f11502" or
                env["cpu_affinity"] != 0 or not env["platform"].startswith("Linux") or
                env["budgets"] != [5,30] or any(v != "1" for v in env["thread_environment"].values())):
            errors.append("author/environment protocol mismatch")
        if (env["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest() or
                (directory/"snapshot/data/thpack/thpack1.txt").read_bytes() != source.read_bytes()):
            errors.append("source binding mismatch")
        rows = manifest["runs"]
        planned_keys = Counter((r["pid"], r["source_index"], r["cpu_budget_seconds"]) for r in expected)
        if manifest["status"] != "verified" or Counter((r["pid"],r["source_index"],r["cpu_budget_seconds"]) for r in rows) != planned_keys:
            raise ValueError("missing, duplicate or unexpected runs")
        paths = ["experiments/bench_metasolver.py", "experiments/adapt_metasolver_output.py",
                 "experiments/adapt_guesser_output.py", "experiments/verify_mes_result.py",
                 "experiments/prepare_guesser_inputs.py", "src/thpack.py", "data/thpack/thpack1.txt"]
        required = {"environment.json", "manifest.json"} | {"snapshot/"+p for p in paths}
        required.update(f"metasolver_{e['pid']}_{e['cpu_budget_seconds']}s.{suffix}"
                        for e in expected for suffix in ("stdout.log", "stderr.log", "adapted.json"))
        if set(hashes) != required:
            errors.append("hash file set differs from required evidence")
        for name,digest in hashes.items():
            path = directory/name
            if not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("path escapes bundle")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append("hash mismatch: "+name)
        for row in rows:
            label = f"metasolver_{row['pid']}_{row['cpu_budget_seconds']}s"
            if row["label"] != label or row["returncode"] != 0 or row["errors"]:
                errors.append(label+": process status mismatch")
            for key,suffix in (("stdout","stdout.log"),("stderr","stderr.log"),("adapted","adapted.json")):
                if row[key] != label+"."+suffix:
                    raise ValueError("unexpected filename")
            cmd = row["command"]
            if (cmd[:4] != ["taskset","-c","0",env["binary"]] or
                    cmd[5:] != ["-i",str(row["source_index"]),"-t",str(row["cpu_budget_seconds"]),"--show_layout","--json"] or
                    not cmd[4].endswith("/data/thpack/thpack1.txt")):
                errors.append(label+": command protocol mismatch")
            computed = extract_and_verify((directory/row["stdout"]).read_text(encoding="utf-8"), instances[row["source_index"]])
            if computed != read(row["adapted"]) or row["isd"] != computed["result"]["isd"] or row["placed"] != computed["result"]["placed"]:
                errors.append(label+": adapted/summary mismatch")
            for key in ("wall_seconds_solver_process", "process_cpu_user_seconds", "process_cpu_system_seconds"):
                value = row[key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
                    errors.append(label+": invalid timing")
        summary = {}
        for budget in (5,30):
            selected = [r for r in rows if r["cpu_budget_seconds"]==budget]
            summary[str(budget)] = dict(n=len(selected), mean_isd=mean(r["isd"] for r in selected),
                                        mean_process_cpu_seconds=mean(r["process_cpu_user_seconds"]+r["process_cpu_system_seconds"] for r in selected),
                                        mean_wall_seconds=mean(r["wall_seconds_solver_process"] for r in selected))
        result.update(runs=len(rows), hashed_files=len(hashes), summary_by_budget=summary,
                      binary_sha256=env["binary_sha256"])
    except (OSError,ValueError,KeyError,TypeError) as exc:
        errors.append(str(exc))
    return dict(result, errors=errors, passed=not errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = verify_bundle(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)

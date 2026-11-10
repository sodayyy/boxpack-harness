"""Translate thpack to Guesser input schema; does not run the author solver.

Schema checked against sclp-heuristic commit 75eec37e27a34509f3dd9b806ffb33fdcda38957,
doc/set_1_instance_1.json and src/Geometry/Orientation.cpp.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.thpack import allowed_orients, parse_thpack

AUTHOR_COMMIT = "75eec37e27a34509f3dd9b806ffb33fdcda38957"
PERMUTATIONS = {
    "xyz": (0, 1, 2), "yxz": (1, 0, 2), "zyx": (2, 1, 0),
    "xzy": (0, 2, 1), "zxy": (2, 0, 1), "yzx": (1, 2, 0),
}


def convert(inst):
    result = {"type": "input", "version": "0.8.0",
              "large_object": {"measurement": dict(zip("xyz", inst["box"]))},
              "small_items": []}
    for tp in inst["types"]:
        dims, flags = tp["dims"], tp["flags"]
        if not any(flags):
            raise ValueError(f"type {tp['t']} has no allowed vertical axis")
        allowed = set(allowed_orients(dims, flags))
        # Compare physical dimensions, including equal-edge symmetries.
        orientation = {key: tuple(dims[i] for i in perm) in allowed
                       for key, perm in PERMUTATIONS.items()}
        result["small_items"].append({
            "profit": dims[0] * dims[1] * dims[2], "quantity": tp["qty"],
            "measurement": dict(zip("xyz", dims)),
            "constraint": {"orientation": orientation}})
    return result


def validate_conversion(inst, converted):
    """Self-check roundtrip of counts, volumes and the allowed dimension sets."""
    if tuple(converted["large_object"]["measurement"][a] for a in "xyz") != tuple(inst["box"]):
        raise ValueError("container changed")
    if len(converted["small_items"]) != len(inst["types"]):
        raise ValueError("number of types changed")
    for tp, item in zip(inst["types"], converted["small_items"]):
        dims = tuple(item["measurement"][a] for a in "xyz")
        if dims != tuple(tp["dims"]) or item["quantity"] != tp["qty"]:
            raise ValueError("dimensions or quantity changed")
        if item["profit"] != dims[0] * dims[1] * dims[2]:
            raise ValueError("profit is not volume")
        got = {tuple(dims[i] for i in PERMUTATIONS[key])
               for key, enabled in item["constraint"]["orientation"].items() if enabled}
        if got != set(allowed_orients(tp["dims"], tp["flags"])):
            raise ValueError("allowed physical orientations changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=ROOT / "data/thpack/thpack1.txt")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instances", type=int, default=10, help="0 means all")
    args = parser.parse_args()
    if args.instances < 0:
        parser.error("instances must be nonnegative")
    insts = parse_thpack(args.file)
    if args.instances:
        insts = insts[:args.instances]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"author_commit": AUTHOR_COMMIT, "status": "inputs_prepared_solver_not_run",
                "source_name": args.file.name,
                "source_sha256": hashlib.sha256(args.file.read_bytes()).hexdigest(),
                "units": "original thpack units; no clearance", "level": 0, "instances": []}
    for inst in insts:
        converted = convert(inst)
        validate_conversion(inst, converted)
        filename = f"{args.file.stem}_instance_{inst['pid']}.json"
        target = args.output_dir / filename
        data = (json.dumps(converted, indent=2) + "\n").encode("utf-8")
        target.write_bytes(data)
        manifest["instances"].append({"pid": inst["pid"], "file": filename,
                                      "sha256": hashlib.sha256(data).hexdigest(),
                                      "type_order": [tp["t"] for tp in inst["types"]]})
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared and self-checked {len(insts)} inputs; author solver NOT run.")


if __name__ == "__main__":
    main()

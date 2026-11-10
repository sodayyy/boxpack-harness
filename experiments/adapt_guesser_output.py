"""Attach legal thpack identities to Guesser's dimension-only output.

The fixed Guesser output contains dimensions and positions, but no source type or
serial. This adapter matches each output cuboid to a source type using exact
physical dimensions, allowed orientations, and type quantities. It refuses an
ambiguous type assignment instead of assigning identities by list order.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_mes_result import verify  # noqa: E402
from src.thpack import parse_thpack, to_items  # noqa: E402


def _raw_boxes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("small_items"), list):
        raise ValueError("author output must contain a small_items list")
    boxes = []
    for index, raw in enumerate(payload["small_items"]):
        if not isinstance(raw, dict):
            raise ValueError(f"small_items[{index}] is not an object")
        measurement = raw.get("measurement")
        position = raw.get("position")
        if not isinstance(measurement, dict) or not isinstance(position, dict):
            raise ValueError(f"small_items[{index}] lacks measurement or position")
        try:
            dims = tuple(measurement[a] for a in "xyz")
            xyz = tuple(position[a] for a in "xyz")
        except KeyError as exc:
            raise ValueError(f"small_items[{index}] missing coordinate {exc.args[0]}")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in dims + xyz):
            raise ValueError(f"small_items[{index}] has nonnumeric or nonfinite geometry")
        boxes.append(dict(x=xyz[0], y=xyz[1], z=xyz[2],
                          l=dims[0], w=dims[1], h=dims[2]))
    return boxes


def _type_descriptors(inst):
    descriptors = []
    for tp in inst["types"]:
        allowed = set()
        # Keep this independent from the author output and use the project's
        # thpack interpretation as the source of truth.
        from src.thpack import allowed_orients
        allowed.update(allowed_orients(tp["dims"], tp["flags"]))
        descriptors.append({"name": f"T{tp['t']}", "dims": tuple(tp["dims"]),
                            "allowed": allowed, "quantity": tp["qty"]})
    return descriptors


def _candidate_types(box, descriptors):
    dims = (box["l"], box["w"], box["h"])
    return [i for i, tp in enumerate(descriptors) if dims in tp["allowed"]]


def _solve_type_assignment(boxes, descriptors):
    candidates = [_candidate_types(box, descriptors) for box in boxes]
    for i, options in enumerate(candidates):
        if not options:
            raise ValueError(f"output box {i} has no legal source type for dimensions")
    # Most constrained first, then restore original output order in the result.
    order = sorted(range(len(boxes)), key=lambda i: (len(candidates[i]), i))
    remaining = [tp["quantity"] for tp in descriptors]
    assignment = [None] * len(boxes)
    solutions = []

    def search(depth):
        if len(solutions) >= 2:
            return
        if depth == len(order):
            solutions.append(tuple(assignment))
            return
        box_index = order[depth]
        for type_index in candidates[box_index]:
            if remaining[type_index] <= 0:
                continue
            remaining[type_index] -= 1
            assignment[box_index] = type_index
            search(depth + 1)
            assignment[box_index] = None
            remaining[type_index] += 1

    search(0)
    if not solutions:
        raise ValueError("output exceeds source type quantities")
    # Only type assignment ambiguity matters. Serial order among identical
    # source items is exchangeable and is assigned deterministically below.
    if len(solutions) > 1 and solutions[0] != solutions[1]:
        raise ValueError("ambiguous source type assignment; no identity fabricated")
    return solutions[0]


def adapt(inst, author_payload):
    raw_boxes = _raw_boxes(author_payload)
    descriptors = _type_descriptors(inst)
    assignment = _solve_type_assignment(raw_boxes, descriptors)
    items = to_items(inst)
    serial_pools = {}
    for item in items:
        serial_pools.setdefault(item["name"], []).append(item["serial"])
    counters = Counter()
    boxes = []
    for raw, type_index in zip(raw_boxes, assignment):
        name = descriptors[type_index]["name"]
        serial = serial_pools[name][counters[name]]
        counters[name] += 1
        boxes.append(dict(raw, serial=serial, name=name,
                          kind="standard", weight=1))
    return {"pid": inst["pid"], "boxes": boxes,
            "placed": len(boxes),
            "used_volume": sum(b["l"] * b["w"] * b["h"] for b in boxes),
            "isd": sum(b["l"] * b["w"] * b["h"] for b in boxes) /
                   (inst["box"][0] * inst["box"][1] * inst["box"][2]),
            "n": sum(tp["qty"] for tp in inst["types"]),
            "rest": sum(tp["qty"] for tp in inst["types"]) - len(boxes)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--file", type=Path, default=ROOT / "data/thpack/thpack1.txt")
    ap.add_argument("--adapted", type=Path, required=True)
    args = ap.parse_args()
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    insts = {str(inst["pid"]): inst for inst in parse_thpack(args.file)}
    pid = payload.get("appendix", {}).get("pid") if isinstance(payload, dict) else None
    # The CLI output has no pid; the input filename is the authoritative key.
    if pid is None:
        stem = args.input.stem
        pid = stem.rsplit("_", 1)[-1]
    inst = insts[str(pid)]
    adapted = adapt(inst, payload)
    errors = verify(adapted, inst["box"], to_items(inst))
    if errors:
        raise SystemExit("adapted output failed independent verification: " + "; ".join(errors))
    args.adapted.write_text(json.dumps(adapted, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"Adapted and independently verified pid={pid}: {len(adapted['boxes'])} boxes")


if __name__ == "__main__":
    main()

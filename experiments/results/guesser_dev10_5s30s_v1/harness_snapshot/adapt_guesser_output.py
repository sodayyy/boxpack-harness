"""Attach legal thpack identities to Guesser's dimension-only output.

The fixed Guesser output contains dimensions and positions, but no source type or
serial. This adapter matches each output cuboid to a source type using exact
physical dimensions, allowed orientations, and type quantities. It refuses an
ambiguous type assignment instead of assigning identities by list order.
"""
import argparse
import json
import math
from collections import Counter, deque
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_mes_result import verify  # noqa: E402
from src.thpack import parse_thpack, to_items  # noqa: E402
from experiments.prepare_guesser_inputs import convert  # noqa: E402


def validate_input(inst, payload):
    """Bind the run to the full canonical author input, never a filename."""
    if payload != convert(inst):
        raise ValueError("author input does not match canonical source instance")


def _check_container(inst, payload):
    try:
        dims = tuple(payload["large_object"]["measurement"][a] for a in "xyz")
    except (KeyError, TypeError):
        raise ValueError("author output lacks container measurement") from None
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 0 for v in dims):
        raise ValueError("author output has invalid container measurement")
    if dims != tuple(inst["box"]):
        raise ValueError("author output container mismatch")
    appendix = payload.get("appendix", {})
    if not isinstance(appendix, dict):
        raise ValueError("author output appendix must be an object")
    if "pid" in appendix and str(appendix["pid"]) != str(inst["pid"]):
        raise ValueError("author output pid mismatch")


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
        if any(v <= 0 for v in dims) or any(v < 0 for v in xyz):
            raise ValueError(f"small_items[{index}] has nonpositive dimensions or negative position")
        boxes.append(dict(x=xyz[0], y=xyz[1], z=xyz[2],
                          l=dims[0], w=dims[1], h=dims[2]))
    return boxes


def _type_descriptors(inst):
    descriptors = []
    for tp in inst["types"]:
        if not any(tp["flags"]):
            raise ValueError(f"source type {tp['t']} has no legal orientation")
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
    # Iterative capacitated matching: no recursion proportional to box count.
    order = sorted(range(len(boxes)), key=lambda i: (len(candidates[i]), i))
    assignment = [None] * len(boxes)
    residents = [set() for _ in descriptors]
    for start in order:
        queue = deque([start])
        seen_boxes = {start}
        parent_type = {}
        free_type = None
        while queue and free_type is None:
            box_index = queue.popleft()
            for type_index in candidates[box_index]:
                if type_index in parent_type:
                    continue
                parent_type[type_index] = box_index
                if len(residents[type_index]) < descriptors[type_index]["quantity"]:
                    free_type = type_index
                    break
                for occupant in sorted(residents[type_index]):
                    if occupant not in seen_boxes:
                        seen_boxes.add(occupant)
                        queue.append(occupant)
        if free_type is None:
            raise ValueError("output exceeds source type quantities")
        while free_type is not None:
            box_index = parent_type[free_type]
            old_type = assignment[box_index]
            if old_type is not None:
                residents[old_type].remove(box_index)
            residents[free_type].add(box_index)
            assignment[box_index] = free_type
            free_type = old_type

    # Removing one matched edge creates a free slot in its original type.
    # Any alternating path from another candidate to a free slot yields a
    # genuinely different legal type assignment (including alternating cycles).
    for box_index, old_type in enumerate(assignment):
        queue = deque(t for t in candidates[box_index] if t != old_type)
        seen_types = set(queue)
        while queue:
            type_index = queue.popleft()
            if (type_index == old_type or
                    len(residents[type_index]) < descriptors[type_index]["quantity"]):
                raise ValueError("ambiguous source type assignment; no identity fabricated")
            for occupant in residents[type_index]:
                for next_type in candidates[occupant]:
                    if next_type not in seen_types:
                        seen_types.add(next_type)
                        queue.append(next_type)
    return tuple(assignment)


def adapt(inst, author_payload):
    raw_boxes = _raw_boxes(author_payload)
    _check_container(inst, author_payload)
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
    ap.add_argument("--pid", help="explicit source instance key; otherwise match full input")
    args = ap.parse_args()
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    input_payload = json.loads(args.input.read_text(encoding="utf-8"))
    insts = {str(inst["pid"]): inst for inst in parse_thpack(args.file)}
    if args.pid is not None:
        if args.pid not in insts:
            raise SystemExit("unknown source pid")
        inst = insts[args.pid]
    else:
        matches = [inst for inst in insts.values() if convert(inst) == input_payload]
        if len(matches) != 1:
            raise SystemExit("input must uniquely match a source instance; supply --pid if duplicated")
        inst = matches[0]
    validate_input(inst, input_payload)
    pid = inst["pid"]
    adapted = adapt(inst, payload)
    errors = verify(adapted, inst["box"], to_items(inst))
    if errors:
        raise SystemExit("adapted output failed independent verification: " + "; ".join(errors))
    args.adapted.write_text(json.dumps(adapted, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"Adapted and independently verified pid={pid}: {len(adapted['boxes'])} boxes")


if __name__ == "__main__":
    main()

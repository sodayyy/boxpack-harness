"""Exact-arithmetic self-check of exported R6 witnesses, no solver/referee imports.

Uses CSV source dimensions and integer coordinates directly in exported
right-rear-bottom coordinates. Reflections preserve all checked predicates.
This is another implementation self-check, not a third-party safety audit.
"""
import argparse
from collections import Counter
import csv
from fractions import Fraction
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(path):
    errors = []
    with (ROOT / "data/items.csv").open(encoding="utf-8-sig", newline="") as f:
        catalog = {r["编号"]: dict(dims=tuple(int(r[k]) for k in ("长_cm", "宽_cm", "高_cm")),
                                  weight=int(r["单重_kg"]), qty=int(r["数量"]),
                                  kind={"标准件": "standard", "易碎件": "fragile", "定向件": "oriented"}[r["类型"]])
                   for r in csv.DictReader(f)}
    with (ROOT / "data/trucks.csv").open(encoding="utf-8-sig", newline="") as f:
        truck_rows = list(csv.DictReader(f))
    # Original CSV schema is explicit, not guessed from saved solver metadata.
    trucks = {r["车型"]: dict(dims=tuple(int(r[k]) for k in ("内长_cm", "内宽_cm", "内高_cm")),
                              cap=int(r["额定载重_kg"]), cost=int(r["单次成本_元"])) for r in truck_rows}
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if (record["coordinate_system"] != "right_rear_bottom" or record["schema_version"] != 1 or
            record["units"] != {"length": "cm", "mass": "kg"} or
            record["rules"] != dict(level=4, support_ratio=0.0, pressure_model="chain_area_v1")):
        raise ValueError("unexpected coordinate/rule protocol")
    ids, pressures, reactions, weight_total, volume_total = [], [], [], 0, 0
    support_ratio_min = Fraction(1)
    max_z = 0
    vehicle_details = []
    for vehicle in record["fleet"]:
        spec = trucks[vehicle["truck_type"]]
        boxes = vehicle["boxes"]
        if not boxes:
            errors.append("empty vehicle")
        for b in boxes:
            if any(type(b[k]) is not int for k in ("x", "y", "z", "l", "w", "h", "weight")):
                raise ValueError("exact witness requires integer cm/kg fields")
            item = catalog[b["name"]]
            allowed = [item["dims"]] if item["kind"] == "oriented" else list(itertools.permutations(item["dims"]))
            if (tuple(b[k] for k in ("l", "w", "h")) not in allowed or b["kind"] != item["kind"] or
                    b["weight"] != item["weight"]):
                errors.append(b["serial"] + ": catalog/orientation mismatch")
            if (min(b["x"], b["y"], b["z"]) < 0 or min(b["l"], b["w"], b["h"]) <= 0 or
                    b["x"] + b["l"] > spec["dims"][0] or b["y"] + b["w"] > spec["dims"][1] or
                    b["z"] + b["h"] > spec["dims"][2] - 3):
                errors.append(b["serial"] + ": boundary failure")
            ids.append(b["serial"])
            volume_total += b["l"] * b["w"] * b["h"]
            max_z = max(max_z, b["z"] + b["h"])
        if sum(b["weight"] for b in boxes) > spec["cap"]:
            errors.append("truck overweight")
        for i, a in enumerate(boxes):
            for b in boxes[:i]:
                if all(max(a[axis], b[axis]) < min(a[axis] + a[side], b[axis] + b[side])
                       for axis, side in (("x", "l"), ("y", "w"), ("z", "h"))):
                    errors.append(a["serial"] + ": overlap with " + b["serial"])
        load = [Fraction(b["weight"]) for b in boxes]
        floor_load = Fraction(0)
        for i in sorted(range(len(boxes)), key=lambda i: boxes[i]["z"], reverse=True):
            b = boxes[i]
            pressure = (load[i] - b["weight"]) * 10000 / (b["l"] * b["w"])
            pressures.append(pressure)
            if pressure > 500 or (b["kind"] == "fragile" and load[i] != b["weight"]):
                errors.append(b["serial"] + ": pressure/fragile external load failure")
            if b["z"] == 0:
                floor_load += load[i]
                continue
            contacts = []
            for j, base in enumerate(boxes):
                if base["z"] + base["h"] != b["z"]:
                    continue
                area = max(0, min(b["x"] + b["l"], base["x"] + base["l"]) - max(b["x"], base["x"])) * max(
                    0, min(b["y"] + b["w"], base["y"] + base["w"]) - max(b["y"], base["y"]))
                if area <= 0:
                    continue
                contacts.append((j, area))
                if base["kind"] == "fragile" or (b["kind"] == "fragile" and base["kind"] != "standard"):
                    errors.append(b["serial"] + ": support type failure")
                if base["kind"] == "oriented" and not (
                        2 * base["x"] <= 2 * b["x"] + b["l"] <= 2 * (base["x"] + base["l"]) and
                        2 * base["y"] <= 2 * b["y"] + b["w"] <= 2 * (base["y"] + base["w"])):
                    errors.append(b["serial"] + ": oriented support center failure")
            area = sum(a for _, a in contacts)
            if area == 0:
                errors.append(b["serial"] + ": floating")
                continue
            ratio = Fraction(area, b["l"] * b["w"])
            support_ratio_min = min(support_ratio_min, ratio)
            # Stronger than the registered ordinary support0 rule: check full
            # support for EVERY positive-height box in this particular witness.
            if ratio != 1:
                errors.append(b["serial"] + ": full-support robustness check failed")
            for j, area_j in contacts:
                load[j] += load[i] * Fraction(area_j, area)
        weight = sum(b["weight"] for b in boxes)
        if floor_load != weight:
            errors.append("exact vertical force conservation failed")
        weight_total += weight
        reactions.append(floor_load)
        vehicle_details.append(dict(truck_type=vehicle["truck_type"], count=len(boxes),
                                    weight_kg=weight, exact_floor_reaction_kg=str(floor_load)))
    expected = {f"{name}-{i:03d}": name for name, spec in catalog.items() for i in range(spec["qty"])}
    if Counter(ids) != Counter(expected.keys()):
        errors.append("global item identity conservation failed")
    for vehicle in record["fleet"]:
        for b in vehicle["boxes"]:
            if expected.get(b["serial"]) != b["name"]:
                errors.append("serial/name mismatch")
    return dict(file=str(path), passed=not errors, errors=errors, items=len(ids), volume_cm3=volume_total,
                weight_kg=weight_total, vehicles=vehicle_details, exact_floor_reaction_kg=str(sum(reactions)),
                exact_max_top_pressure_kg_m2=str(max(pressures, default=Fraction(0))),
                exact_min_support_ratio=str(support_ratio_min), max_height_cm=max_z,
                method="integer geometry and Fraction load propagation; no solver or original checker imports",
                scope="original catalog, fragile six orientations, oriented original pose, full support, no moment/dynamic certification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("witness", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.witness)
    if args.output:
        if args.output.exists():
            parser.error("preserve old verification output")
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)

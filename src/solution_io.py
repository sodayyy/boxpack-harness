"""Versioned per-item solution I/O; coordinate reflection is an involution."""
import csv
import json
from pathlib import Path

COORDINATES = {
    "internal": {"origin": "left_front_bottom", "x": "front_to_rear",
                 "y": "left_to_right", "z": "up"},
    "right_rear_bottom": {"origin": "right_rear_bottom", "x": "rear_to_front",
                          "y": "right_to_left", "z": "up"},
}
FIELDS = ("truck_id", "truck_type", "coordinate_system", "serial", "name", "kind",
          "weight", "x", "y", "z", "l", "w", "h")


def reflect_box(box, dims):
    L, W, _ = dims
    return dict(box, x=L - box["x"] - box["l"], y=W - box["y"] - box["w"])


def export_solution(fleet, json_path, csv_path, truck_catalog, level=4,
                    support_ratio=0.0, pressure_model="legacy_b1"):
    """fleet uses internal coordinates. Include empty trucks in JSON, not CSV."""
    output = []
    rows = []
    for i, truck in enumerate(fleet, 1):
        name = truck["truck_type"]
        boxes = [reflect_box(b, truck_catalog[name]["dims"]) for b in truck["boxes"]]
        output.append(dict(truck_id=i, truck_type=name, boxes=boxes))
        rows.extend(dict(b, truck_id=i, truck_type=name,
                         coordinate_system="right_rear_bottom") for b in boxes)
    record = dict(schema_version=1, coordinate_system="right_rear_bottom",
                  axes=COORDINATES["right_rear_bottom"], units={"length": "cm", "mass": "kg"},
                  rules=dict(level=level, support_ratio=support_ratio,
                             pressure_model=pressure_model), fleet=output)
    Path(json_path).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    with Path(csv_path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({k: row[k] for k in FIELDS} for row in rows)


def read_solution(path, truck_catalog):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if (record.get("schema_version") != 1
            or record.get("coordinate_system") != "right_rear_bottom"
            or record.get("axes") != COORDINATES["right_rear_bottom"]
            or record.get("units") != {"length": "cm", "mass": "kg"}):
        raise ValueError("unknown schema, units or coordinate system")
    ids = [tr["truck_id"] for tr in record["fleet"]]
    if ids != list(range(1, len(ids) + 1)):
        raise ValueError("invalid truck identities")
    return [dict(truck_type=tr["truck_type"], boxes=[
        reflect_box(b, truck_catalog[tr["truck_type"]]["dims"]) for b in tr["boxes"]])
            for tr in record["fleet"]]


def read_solution_csv(path, truck_catalog):
    groups = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("unknown CSV fields")
        for row in reader:
            if row["coordinate_system"] != "right_rear_bottom":
                raise ValueError("unknown coordinates")
            index, name = int(row["truck_id"]), row["truck_type"]
            if index in groups and groups[index]["truck_type"] != name:
                raise ValueError("conflicting truck types")
            truck = groups.setdefault(index, dict(truck_type=name, boxes=[]))
            box = {k: row[k] for k in ("serial", "name", "kind")}
            for key in ("weight", "x", "y", "z", "l", "w", "h"):
                value = float(row[key])
                box[key] = int(value) if value.is_integer() else value
            truck["boxes"].append(reflect_box(box, truck_catalog[name]["dims"]))
    if sorted(groups) != list(range(1, len(groups) + 1)):
        raise ValueError("nonconsecutive CSV truck ids")
    return [groups[i] for i in sorted(groups)]


def fleet_metrics(fleet, truck_catalog, catalog, clearance=3):
    boxes = [b for tr in fleet for b in tr["boxes"]]
    used_v = sum(b["l"] * b["w"] * b["h"] for b in boxes)
    total_v = sum(s["dims"][0] * s["dims"][1] * s["dims"][2] * s["qty"]
                  for s in catalog.values())
    nominal = effective = cap_weight = cost = 0
    for tr in fleet:
        spec = truck_catalog[tr["truck_type"]]
        L, W, H = spec["dims"]
        nominal += L * W * H
        effective += L * W * (H - clearance)
        cap_weight += spec["cap_weight"]
        cost += spec["cost"]
    return dict(trucks=len(fleet), placed=len(boxes), cost=cost,
                nominal_space_util=used_v / nominal if nominal else 0,
                effective_space_util=used_v / effective if effective else 0,
                shipment_completion=used_v / total_v if total_v else 0,
                weight_util=sum(b["weight"] for b in boxes) / cap_weight if cap_weight else 0)

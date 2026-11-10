# -*- coding: utf-8 -*-
"""Independent identity, orientation, geometry and metric checks for saved L0 layouts."""
import argparse
import json
import math
from numbers import Real
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.thpack import parse_thpack, to_items  # noqa: E402


def verify(row, container, items=None):
    L, W, H = container
    errors = []
    boxes = row.get("boxes")
    if not isinstance(boxes, list):
        return ["missing or invalid boxes list"]
    required = {"serial", "name", "x", "y", "z", "l", "w", "h"}
    for index, b in enumerate(boxes):
        if not isinstance(b, dict) or not required.issubset(b):
            errors.append(f"missing box fields: index {index}")
            continue
        if not isinstance(b["serial"], str) or not isinstance(b["name"], str):
            errors.append(f"invalid identity type: index {index}")
        for key in ("x", "y", "z", "l", "w", "h"):
            value = b[key]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                errors.append(f"nonfinite or nonnumeric {key}: index {index}")
    if errors:
        return errors
    serials = [b["serial"] for b in boxes]
    if len(serials) != len(set(serials)):
        errors.append("duplicate serial")
    for b in boxes:
        if min(b[k] for k in ("l", "w", "h")) <= 0:
            errors.append(f"nonpositive dimensions: {b['serial']}")
        if not (0 <= b["x"] and 0 <= b["y"] and 0 <= b["z"] and
                b["x"] + b["l"] <= L and b["y"] + b["w"] <= W and
                b["z"] + b["h"] <= H):
            errors.append(f"out of bounds: {b['serial']}")
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
                       a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
                       a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"])
            if overlap:
                errors.append(f"overlap: {a['serial']} / {b['serial']}")
    volume = sum(b["l"] * b["w"] * b["h"] for b in boxes)
    if "used_volume" in row and row["used_volume"] != volume:
        errors.append("reported used_volume mismatch")
    if "isd" in row:
        isd = row["isd"]
        if (isinstance(isd, bool) or not isinstance(isd, Real) or
                not math.isfinite(isd) or abs(isd - volume / (L * W * H)) > 1e-9):
            errors.append("reported isd mismatch")
    if "placed" in row and row["placed"] != len(boxes):
        errors.append("reported placed mismatch")
    if items is not None:
        catalog = {it["serial"]: it for it in items}
        for b in boxes:
            source = catalog.get(b["serial"])
            if source is None or source["name"] != b["name"]:
                errors.append(f"unknown identity: {b['serial']}")
            elif tuple(b[k] for k in ("l", "w", "h")) not in source["allowed"]:
                errors.append(f"disallowed orientation: {b['serial']}")
        if "n" in row and row["n"] != len(items):
            errors.append("reported input count mismatch")
        if "rest" in row and row["rest"] != len(items) - len(boxes):
            errors.append("reported rest mismatch")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    repo_root = Path(__file__).resolve().parents[1]
    ap.add_argument("--file", default=str(repo_root / "data/thpack/thpack1.txt"))
    args = ap.parse_args()
    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    insts = {str(i["pid"]): i for i in parse_thpack(Path(args.file))}
    all_errors = []
    for row in (payload if isinstance(payload, list) else payload["rows"]):
        inst = insts[str(row["pid"])]
        errors = verify(row, inst["box"], to_items(inst))
        all_errors.extend(errors)
        print(f"算例 {row['pid']}: {len(row['boxes'])} boxes, errors={len(errors)}")
    if all_errors:
        raise SystemExit("; ".join(all_errors[:10]))
    print("Independent L0 identity/orientation/geometry/metrics verification: 0 errors")


if __name__ == "__main__":
    main()

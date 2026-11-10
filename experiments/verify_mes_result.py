# -*- coding: utf-8 -*-
"""Independent geometry check for a saved MES+Beam result."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.thpack import parse_thpack  # noqa: E402


def verify(row, container):
    L, W, H = container
    boxes = row["boxes"]
    errors = []
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
    for row in payload["rows"]:
        errors = verify(row, insts[str(row["pid"])] ["box"])
        all_errors.extend(errors)
        print(f"算例 {row['pid']}: {len(row['boxes'])} boxes, errors={len(errors)}")
    if all_errors:
        raise SystemExit("; ".join(all_errors[:10]))
    print("Independent MES geometry verification: 0 errors")


if __name__ == "__main__":
    main()

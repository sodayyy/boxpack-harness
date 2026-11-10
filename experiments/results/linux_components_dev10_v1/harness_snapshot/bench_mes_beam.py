# -*- coding: utf-8 -*-
"""B2 MES+Beam single-container L0 calibration.

Run from the repository root. This is a component calibration, not the full
multi-truck/fragile problem and not a reproduction claim for any paper.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mes_beam import beam_pack  # noqa: E402
from src.pack_lib import TruckType, expand_items, orients  # noqa: E402
from src.thpack import parse_thpack, to_items  # noqa: E402


def pack_one(inst, beam_width, space_cap, order="volume", state_priority="volume"):
    items = to_items(inst)
    if order == "volume":
        items.sort(key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    elif order == "height":
        items.sort(key=lambda it: (-it["dims"][2], -it["dims"][0] * it["dims"][1]))
    elif order == "area":
        items.sort(key=lambda it: -it["dims"][0] * it["dims"][1])
    result = beam_pack(items, inst["box"], beam_width=beam_width,
                       space_cap=space_cap, state_priority=state_priority)
    result.update(pid=inst["pid"], n=len(items), isd=result["used_volume"] /
                  (inst["box"][0] * inst["box"][1] * inst["box"][2]),
                  rest=len(items) - result["placed"])
    return result


def main():
    ap = argparse.ArgumentParser()
    repo_root = Path(__file__).resolve().parents[1]
    ap.add_argument("--file", default=str(repo_root / "data/thpack/thpack1.txt"))
    ap.add_argument("--instances", type=int, default=10)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--space-cap", type=int, default=80)
    ap.add_argument("--order", default="volume", choices=["volume", "height", "area"])
    ap.add_argument("--state-priority", default="volume", choices=["volume", "count"])
    ap.add_argument("--json", default="experiments/results/thpack1_b2.json")
    args = ap.parse_args()
    insts = parse_thpack(Path(args.file))[:args.instances or None]
    rows = []
    for inst in insts:
        start = time.perf_counter()
        row = pack_one(inst, args.beam_width, args.space_cap, args.order,
                       args.state_priority)
        row["seconds"] = round(time.perf_counter() - start, 3)
        rows.append(row)
        print(f"算例 {row['pid']:>3}: {row['placed']}/{row['n']} 件, "
              f"ISD={row['isd'] * 100:.1f}%, rest={row['rest']}, "
              f"{row['seconds']:.3f}s")
    mean = sum(r["isd"] for r in rows) / len(rows) if rows else 0
    summary = dict(method="MES+Beam", scope="single_container_L0_component_calibration",
                   beam_width=args.beam_width, space_cap=args.space_cap,
                   state_priority=args.state_priority, order=args.order,
                   instances=len(rows), mean_isd=mean,
                   rows=rows, status="bounded_heuristic_not_optimal")
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"平均 ISD={mean * 100:.1f}%; 结果写入 {out}")


if __name__ == "__main__":
    main()

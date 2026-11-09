# -*- coding: utf-8 -*-
"""约束层级递进实验（L0 → L4）

老师的要求：「先做好刚体层面的，可以一点点加约束」。
本脚本按层级逐级加约束，测每一层的代价：

  L0 刚体      不重叠、不越界
  L1 +支撑     不得悬空
  L2 +易碎     易碎件单层：100% 贴合、只落标准件顶面、自身不承重
  L3 +定向     定向件单一姿态、上层重心不超出其顶面投影
  L4 +承重     500 kg/m²

用法：
    py -3.12 experiments/ablation_levels.py            # 车型2（默认）
    py -3.12 experiments/ablation_levels.py --truck 0   # 车型1
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pack_lib import (LEVEL_FRAGILE, LEVEL_ORIENT, LEVEL_PRESSURE,  # noqa: E402
                          LEVEL_RIGID, LEVEL_SUPPORT, TRUCKS, apply_level,
                          expand_items, pack_ep)

LEVELS = [
    (LEVEL_RIGID, "L0 刚体", "不重叠、不越界"),
    (LEVEL_SUPPORT, "L1 +支撑", "不得悬空"),
    (LEVEL_FRAGILE, "L2 +易碎", "单层 / 100% 贴合 / 只落标准件"),
    (LEVEL_ORIENT, "L3 +定向", "单一姿态 / 重心不超投影"),
    (LEVEL_PRESSURE, "L4 +承重", "500 kg/m²"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truck", type=int, default=1, help="0=车型1, 1=车型2")
    ap.add_argument("--max-trucks", type=int, default=6)
    ap.add_argument("--json", default="experiments/results/ablation_levels.json")
    args = ap.parse_args()

    spec = TRUCKS[args.truck]
    cap = spec.dims[0] * spec.dims[1] * spec.dims[2] / 1e6
    base = expand_items()
    base.sort(key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])

    print(f"算例：附件 1，{len(base)} 件，货物总体积 "
          f"{sum(it['dims'][0]*it['dims'][1]*it['dims'][2] for it in base)/1e6:.3f} m³")
    print(f"车型：{spec.name}  {spec.dims[0]}×{spec.dims[1]}×{spec.dims[2]} = {cap:.2f} m³"
          f"，载重 {spec.cap_weight} kg，{spec.cost} 元/趟")
    print(f"装进 1 辆需要的装载率：{sum(it['dims'][0]*it['dims'][1]*it['dims'][2] for it in base)/1e6/cap*100:.1f}%\n")

    rows = []
    prev = None
    for lv, name, desc in LEVELS:
        items = apply_level(base, lv)
        t0 = time.time()
        trucks, rest = pack_ep(items, spec, max_trucks=args.max_trucks, level=lv)
        dt = time.time() - t0
        used = sum(t.used_volume() for t in trucks) / 1e6
        first = trucks[0].used_volume() / (cap * 1e6) * 100 if trucks else 0.0
        cost = sum(t.spec.cost for t in trucks)
        row = dict(level=lv, name=name, desc=desc, trucks=len(trucks),
                   first_pct=round(first, 1), used_m3=round(used, 3),
                   cost=cost, rest=len(rest), seconds=round(dt, 1))
        rows.append(row)

        delta = ""
        if prev is not None and prev["trucks"] != len(trucks):
            delta = f"  ← 车辆数 {prev['trucks']} → {len(trucks)}"
        print(f"{name:<10} {desc:<26} 车 {len(trucks)} 辆  首车 {first:5.1f}%  "
              f"成本 {cost:>4} 元  未装 {len(rest):>2}  {dt:4.1f}s{delta}")
        prev = row

    print()
    a, b = rows[0], rows[-1]
    if a["trucks"] != b["trucks"]:
        print(f"全部约束的代价：车辆数 {a['trucks']} → {b['trucks']}，"
              f"成本 {a['cost']} → {b['cost']} 元，"
              f"涨幅 {(b['cost']-a['cost'])/a['cost']*100:.0f}%")
    else:
        print(f"全部约束未改变车辆数（{a['trucks']} 辆），但首车装载率 "
              f"{a['first_pct']}% → {b['first_pct']}%")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"结果已写入 {args.json}")


if __name__ == "__main__":
    main()

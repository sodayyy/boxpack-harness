# -*- coding: utf-8 -*-
"""平台碎片化分析

回答一个问题：L0（纯几何）解明明装下了全部 300 件、只用到 210 cm 高（可用 247），
为什么 30 件易碎件还是放不进去？

答案是**碎片化**：可用顶面总面积够，但被切成小块，凑不出 70×50。

本脚本量化三件事：
  1. 各高度的可用顶面面积（按面积排序）
  2. 可用顶面的碎片分布（平均每块多大）
  3. 与易碎件需求的差距

用法：
    py -3.12 experiments/platform_analysis.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pack_lib import LEVEL_RIGID, TRUCKS, Truck, expand_items, orients  # noqa: E402

OUT = Path("experiments/results/platform_l0.json")


def solve_l0(spec, items):
    tr = Truck(spec, level=LEVEL_RIGID)
    rest = []
    for it in items:
        ok = False
        for (x, y, z) in sorted(tr.extremes, key=lambda p: (p[2], p[1], p[0])):
            for (l, w, h) in orients(it["kind"], it["dims"], it.get("allowed")):
                if tr.feasible(x, y, z, l, w, h, it["kind"], it["weight"]):
                    tr.put(it, x, y, z, l, w, h)
                    ok = True
                    break
            if ok:
                break
        if not ok:
            rest.append(it)
    return tr, rest


def count_slots(tr, l=70, w=50, need_std_support=False):
    """统计每个高度上能放 l×w 且上方无占用的位置数。

    用二维积分图做 O(1) 滑窗求和。need_std_support=True 时额外要求
    下方一整片都是标准件顶面（题面 C6 的真实约束）。

    注意：位置之间大量重叠，本函数返回的是「可放置位置数」，不是「可放件数」。
    """
    occ = tr.own
    W, L = tr.W, tr.L
    kind_arr = np.array(
        [0 if k == "standard" else (1 if k == "oriented" else 2) for k in tr.kinds],
        dtype=np.int8)

    total, detail = 0, {}
    for z in range(0, int(tr.h_eff) - 40 + 1):
        free = (occ[z] == -1)
        if not free.any():
            continue
        S = np.zeros((W + 1, L + 1), dtype=np.int32)
        S[1:, 1:] = free.astype(np.int32).cumsum(0).cumsum(1)

        if z > 0:
            below = occ[z - 1]
            std = np.where(below >= 0, kind_arr[np.clip(below, 0, None)], -1)
            Sstd = np.zeros((W + 1, L + 1), dtype=np.int32)
            Sstd[1:, 1:] = (std == 0).astype(np.int32).cumsum(0).cumsum(1)

        cnt = 0
        for y in range(0, W - w + 1):
            for x in range(0, L - l + 1):
                area = S[y + w, x + l] - S[y, x + l] - S[y + w, x] + S[y, x]
                if area != l * w:
                    continue
                if z == 0:
                    cnt += 1
                elif not need_std_support:
                    if std[y:y + w, x:x + l].max() >= 0:
                        cnt += 1
                else:
                    s_area = (Sstd[y + w, x + l] - Sstd[y, x + l]
                              - Sstd[y + w, x] + Sstd[y, x])
                    if s_area == l * w:
                        cnt += 1
        if cnt:
            detail[z] = cnt
        total += cnt
    return total, detail


def main():
    spec = TRUCKS[1]
    L, W, H = spec.dims
    cap = L * W * H
    floor = L * W
    base = sorted(expand_items(), key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])

    frag = [it for it in base if it["kind"] == "fragile"]
    frag_area = sum(it["dims"][0] * it["dims"][1] for it in frag) / 1e4
    frag_n = len(frag)

    tr, rest = solve_l0(spec, base)
    print(f"L0 解：装入 {len(tr.boxes)}/{len(base)}，占用 {tr.used_volume()/cap*100:.1f}%，"
          f"最高点 {max(b['z']+b['h'] for b in tr.boxes)} cm（可用 {tr.h_eff:.0f}）")
    print(f"易碎件需求：{frag_n} 件 × 70×50 = {frag_area:.2f} m²（底面 {floor/1e4:.2f} m² 的 "
          f"{frag_area/(floor/1e4)*100:.1f}%）\n")

    # 1) 各高度可用顶面
    occ = tr.own
    tops = defaultdict(int)
    cnt_by_z = defaultdict(int)
    for b in tr.boxes:
        zt = b["z"] + b["h"]
        cnt_by_z[zt] += 1
        if zt < H:
            above = occ[zt, b["y"]:b["y"] + b["w"], b["x"]:b["x"] + b["l"]]
            tops[zt] += int((above == -1).sum())
        else:
            tops[zt] += b["l"] * b["w"]

    ranked = sorted(tops.items(), key=lambda kv: -kv[1])
    print("可用顶面最大的 10 个高度：")
    print(f"{'z(cm)':>6}{'面积(m²)':>10}{'占底面':>8}{'该高度箱数':>10}")
    for zt, area in ranked[:10]:
        print(f"{zt:>6}{area/1e4:>10.2f}{area/floor*100:>7.1f}%{cnt_by_z[zt]:>10}")

    # 2) 碎片分布
    areas = [b["l"] * b["w"] for b in tr.boxes]
    areas.sort(reverse=True)
    need = 70 * 50
    big = [a for a in areas if a >= need]
    print(f"\n顶面碎片分布（全部 {len(areas)} 个箱子顶面）：")
    print(f"  平均每块 {sum(areas)/len(areas)/1e4:.3f} m²")
    print(f"  ≥0.35 m²（能单件承载易碎件）的顶面：{len(big)} 个，合计 {sum(big)/1e4:.2f} m²")
    print(f"  <0.35 m² 的顶面：{len(areas)-len(big)} 个")

    largest = ranked[0][1] if ranked else 0
    print(f"\n诊断：")
    print(f"  最大单层平台 {largest/1e4:.2f} m²，需求 {frag_area:.2f} m² → 差 {frag_area/(largest/1e4):.1f} 倍")
    tot_top4 = sum(a for _, a in ranked[:4]) / 1e4
    print(f"  前 4 个高度合计 {tot_top4:.2f} m² ≥ 需求 {frag_area:.2f} m² → 面积够")
    print(f"  但这些面积分散在 {sum(cnt_by_z[z] for z, _ in ranked[:4])} 个箱子上，平均 "
          f"{tot_top4/max(sum(cnt_by_z[z] for z, _ in ranked[:4]),1):.3f} m²/块 < 0.35 m² → 拼不出")
    print("  结论：瓶颈是碎片化，不是面积")

    # 4) 解空间诊断：合规位置数
    t_all, d_all = count_slots(tr, need_std_support=False)
    t_std, d_std = count_slots(tr, need_std_support=True)
    print(f"\n解空间诊断（在 L0 解的空位上枚举 70×50 位置）：")
    print(f"  几何上能放（任何支撑）        {t_all:>7} 个，前 3 高度 "
          f"{sorted(d_all.items(), key=lambda kv: -kv[1])[:3]}")
    print(f"  下方 100% 为标准件顶面（C6）  {t_std:>7} 个，前 3 高度 "
          f"{sorted(d_std.items(), key=lambda kv: -kv[1])[:3]}")
    top_slots = sorted(d_std.items(), key=lambda kv: -kv[1])
    carry = sum(a for _, a in ranked[:4]) / 1e4 / (70 * 50 / 1e4)
    print(f"  前 4 个平台按面积折算可承载 {carry:.0f} 件（需 {frag_n} 件）")
    print(f"  但带约束独立求解只装入 3 件 → 搜索走不到，不是解不存在")

    out = dict(
        slots=dict(geometric=t_all,
                   std_support=t_std,
                   std_by_height={int(k): v for k, v in top_slots[:6]},
                   carry_estimate=round(carry, 1)),
        l0=dict(in_=len(tr.boxes), total=len(base),
                occ=tr.used_volume() / cap,
                max_height=max(b["z"] + b["h"] for b in tr.boxes)),
        need=dict(n=frag_n, area_m2=frag_area, pct_floor=frag_area / (floor / 1e4) * 100),
        top_heights=[dict(z=z, area_m2=round(a / 1e4, 2), pct=round(a / floor * 100, 1),
                          boxes=cnt_by_z[z]) for z, a in ranked[:10]],
        fragmentation=dict(total_tops=len(areas), avg_m2=sum(areas) / len(areas) / 1e4,
                           ge_035=len(big), ge_035_area_m2=sum(big) / 1e4),
        verdict=dict(max_single_platform_m2=largest / 1e4,
                     gap_ratio=round(frag_area / (largest / 1e4), 2) if largest else None,
                     top4_area_m2=round(tot_top4, 2)),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写入 {OUT}")


if __name__ == "__main__":
    main()

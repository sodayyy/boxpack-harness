# -*- coding: utf-8 -*-
"""冻结历史几何布局上的平台诊断，不判定一车全约束可行性。

旧版只检查候选底面切片，且把顶面面积折算成可装件数；两者均不足以
证明三维可行。现检查完整候选长方体，分别统计重叠候选与贪心非重叠选择。
宿主布局保留历史构造方式（定向件仍固定姿态），不冒充标准 L0 消融结果。
用法：从仓库根目录运行 py -3.12 experiments/platform_analysis.py
"""
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pack_lib import LEVEL_RIGID, TRUCKS, Truck, expand_items, orients

OUT = Path("experiments/results/platform_l0.json")


def solve_l0(spec, items):
    """历史宿主构造：几何可行性，保留输入货物姿态规则。"""
    tr = Truck(spec, level=LEVEL_RIGID)
    rest = []
    for it in items:
        for x, y, z in sorted(tr.extremes, key=lambda p: (p[2], p[1], p[0])):
            for l, w, h in orients(it["kind"], it["dims"], it.get("allowed")):
                if tr.feasible(x, y, z, l, w, h, it["kind"], it["weight"]):
                    tr.put(it, x, y, z, l, w, h)
                    break
            else:
                continue
            break
        else:
            rest.append(it)
    return tr, rest


def _window_counts(mask, l, w):
    integral = np.zeros((mask.shape[0] + 1, mask.shape[1] + 1), dtype=np.int32)
    integral[1:, 1:] = mask.astype(np.int32).cumsum(0).cumsum(1)
    return (integral[w:, l:] - integral[:-w, l:]
            - integral[w:, :-l] + integral[:-w, :-l])


def enumerate_slots(tr, dims=(70, 50, 40), need_std_support=True):
    """完整三维空位 + 局部支撑；返回互相可能重叠的候选。

    为满足候选易碎件 C5，还排除顶面与既有货物直接接触的位置。
    不检查宿主布局的全局合法性，也不把候选数量作为最大装载量。
    """
    l, w, h = dims
    if l > tr.L or w > tr.W or h > tr.h_eff:
        return []
    heights = sorted({0} | {b["z"] + b["h"] for b in tr.boxes})
    std_ids = np.array([i for i, k in enumerate(tr.kinds) if k == "standard"])
    slots = []
    for z in heights:
        if z + h > tr.h_eff:
            continue
        free = ~np.any(tr.own[z:z + h] >= 0, axis=0)
        valid = _window_counts(free, l, w) == l * w
        if z > 0:
            below = tr.own[z - 1]
            support = np.isin(below, std_ids) if need_std_support else below >= 0
            counts = _window_counts(support, l, w)
            valid &= counts == l * w if need_std_support else counts > 0
        if z + h < tr.H:
            valid &= _window_counts(tr.own[z + h] >= 0, l, w) == 0
        ys, xs = np.nonzero(valid)
        slots.extend((int(x), int(y), z, l, w, h) for y, x in zip(ys, xs))
    return slots


def count_slots(tr, l=70, w=50, need_std_support=False):
    """兼容旧调用；现在检查完整 40 cm 高候选体，而非底面切片。"""
    slots = enumerate_slots(tr, (l, w, 40), need_std_support)
    return len(slots), dict(sorted(Counter(p[2] for p in slots).items()))


def _conflict(a, b):
    xy = (a[0] < b[0] + b[3] and b[0] < a[0] + a[3]
          and a[1] < b[1] + b[4] and b[1] < a[1] + a[4])
    # 顶面直接接触同样会违反易碎件不承压规则。
    return xy and a[2] <= b[2] + b[5] and b[2] <= a[2] + a[5]


def select_nonoverlapping(slots, limit=30):
    """确定性贪心选择；返回一个构造，不是最大数的上界或最优证明。"""
    chosen = []
    for p in sorted(set(slots), key=lambda s: (s[2], s[1], s[0], s[5], s[4], s[3])):
        if not any(_conflict(p, q) for q in chosen):
            chosen.append(p)
            if len(chosen) == limit:
                break
    return chosen


def main():
    spec = TRUCKS[1]
    base = sorted(expand_items(), key=lambda it: -np.prod(it["dims"]))
    tr, rest = solve_l0(spec, base)
    scenarios = {}
    for label, poses in (
        ("fixed_70x50x40", [(70, 50, 40)]),
        ("all_six_orientations", sorted(set(itertools.permutations((70, 50, 40))))),
    ):
        slots = [p for pose in poses for p in enumerate_slots(tr, pose, True)]
        chosen = select_nonoverlapping(slots)
        scenarios[label] = dict(
            overlapping_candidates=len(slots),
            candidates_by_height=dict(sorted(Counter(p[2] for p in slots).items())),
            greedy_selected=len(chosen),
            selected_xyz_lwh=[list(p) for p in chosen],
            status="greedy_construction_on_frozen_host_not_global_optimum",
        )
        print(f"{label}: 重叠候选 {len(slots)}；非重叠贪心选择 {len(chosen)}")
    tops = defaultdict(int)
    for b in tr.boxes:
        z = b["z"] + b["h"]
        if z < tr.H:
            tops[z] += int((tr.own[z, b["y"]:b["y"] + b["w"],
                                     b["x"]:b["x"] + b["l"]] == -1).sum())
    out = dict(
        schema_version=2,
        host=dict(description="historical_geometry_host_orientation_rules_retained",
                  in_=len(tr.boxes), total=len(base), rest=len(rest),
                  occ=tr.used_volume() / np.prod(spec.dims).item(),
                  max_height=max(b["z"] + b["h"] for b in tr.boxes)),
        scenarios=scenarios,
        exposed_top_areas_m2={int(z): a / 1e4 for z, a in sorted(tops.items())},
        legacy=dict(slice_candidates=7602, area_equivalent_items=39,
                    status="withdrawn_not_a_3d_packing_certificate"),
        conclusion="局部候选与贪心选择仅用于诊断；一车全约束可行性仍未判定。",
        limitations=["宿主保留既有易碎件，新增候选不是 300 件货物的迁移解。",
                     "未证明选择数最优，不可作为全局容量上界。",
                     "未验证宿主的 L1-L4、承重与载荷链。"],
    )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"结果已写入 {OUT}；已撤销面积折算和全局可行性断言。")


if __name__ == "__main__":
    main()

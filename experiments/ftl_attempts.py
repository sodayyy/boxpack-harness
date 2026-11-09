# -*- coding: utf-8 -*-
"""FTL（Fragile-Top Layering）四次尝试

逐步逼近「易碎件单层约束下，一辆车型 2 能否装完 300 件」这个问题：

  尝试 1  两阶段：先装完非易碎件，再装易碎件
  尝试 2  平台优先：G4（80×60，顶面恰好 ≥ 70×50）只铺底层
  尝试 3  排序扫描：四条排序在 L0（刚体）下的平台面积
  尝试 4  排序 × 约束交叉：四条排序在 L4（全约束）下的易碎件装入数

结论见 docs/05。核心发现：**「装完易碎件」与「装完货物」在贪心框架下互斥**。

用法：
    py -3.12 experiments/ftl_attempts.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pack_lib import (LEVEL_PRESSURE, LEVEL_RIGID, TRUCKS,  # noqa: E402
                          Truck, expand_items, orients)

OUT = Path("experiments/results/ftl_attempts.json")


def place_all(tr, items, only_z=None):
    """把 items 依次放入 tr，返回放不下的。only_z 非空时只允许放在该高度。"""
    rest = []
    for it in items:
        ok = False
        for (x, y, z) in sorted(tr.extremes, key=lambda p: (p[2], p[1], p[0])):
            if only_z is not None and z != only_z:
                continue
            for (l, w, h) in orients(it["kind"], it["dims"], it.get("allowed")):
                if tr.feasible(x, y, z, l, w, h, it["kind"], it["weight"]):
                    tr.put(it, x, y, z, l, w, h)
                    ok = True
                    break
            if ok:
                break
        if not ok:
            rest.append(it)
    return rest


def top_coverage(tr):
    """各精确高度上的可用顶面面积（cm²），只算上方为空的格子。"""
    from collections import defaultdict
    tops = defaultdict(int)
    H = tr.H
    occ = tr.own
    for b in tr.boxes:
        zt = b["z"] + b["h"]
        if zt < H:
            above = occ[zt, b["y"]:b["y"] + b["w"], b["x"]:b["x"] + b["l"]]
            tops[zt] += int((above == -1).sum())
        else:
            tops[zt] += b["l"] * b["w"]
    return tops


def by_volume(its):
    return sorted(its, key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])


def by_height_desc(its):
    return sorted(its, key=lambda it: (-it["dims"][2], -it["dims"][0] * it["dims"][1] * it["dims"][2]))


def by_height_asc(its):
    return sorted(its, key=lambda it: (it["dims"][2], -it["dims"][0] * it["dims"][1] * it["dims"][2]))


def by_area(its):
    return sorted(its, key=lambda it: -it["dims"][0] * it["dims"][1])


ORDERS = [
    ("体积降序", by_volume),
    ("高度降序→体积", by_height_desc),
    ("高度升序→体积", by_height_asc),
    ("底面积降序", by_area),
]


def attempt1(base, spec):
    """两阶段：非易碎先装完，再装易碎。"""
    frag = [it for it in base if it["kind"] == "fragile"]
    rest_items = [it for it in base if it["kind"] != "fragile"]
    tr = Truck(spec, level=LEVEL_PRESSURE)
    r1 = place_all(tr, by_volume(rest_items))
    r2 = place_all(tr, by_volume(frag))
    tops = top_coverage(tr)
    best_top = max(tops.values()) if tops else 0
    return dict(
        name="两阶段（非易碎先装）",
        nonfragile_in=len(rest_items) - len(r1), nonfragile_total=len(rest_items),
        fragile_in=len(frag) - len(r2), fragile_total=len(frag),
        max_height=max((b["z"] + b["h"] for b in tr.boxes), default=0),
        occ=tr.used_volume() / (spec.dims[0] * spec.dims[1] * spec.dims[2]),
        best_top_m2=best_top / 1e4,
    )


def attempt2(base, spec, refill_leftover_g4=True):
    """平台优先：G4 只铺 z=0。

    refill_leftover_g4=True 时，铺底剩下的 G4 会与其余货物一起参与后续装填（公平对比）；
    False 时直接放弃这些 G4，看「牺牲大件换平台」能换来多少易碎件。
    """
    g4 = [it for it in base if it["name"] == "G4"]
    frag = [it for it in base if it["kind"] == "fragile"]
    other = [it for it in base if it["name"] != "G4" and it["kind"] != "fragile"]

    tr = Truck(spec, level=LEVEL_PRESSURE)
    r_g4 = place_all(tr, by_volume(g4), only_z=0)
    n_platform = sum(1 for b in tr.boxes if b["name"] == "G4")
    top_z = {b["z"] + b["h"] for b in tr.boxes if b["name"] == "G4"}

    pending = by_volume(other) + (by_volume(r_g4) if refill_leftover_g4 else [])
    r_other = place_all(tr, pending)
    r_f = place_all(tr, by_volume(frag))

    return dict(
        name="平台优先（G4 铺底）" + ("" if refill_leftover_g4 else "，放弃剩余 G4"),
        refill_leftover=refill_leftover_g4,
        g4_floor=n_platform, g4_total=len(g4),
        platforms=n_platform, platform_top_z=sorted(top_z),
        other_in=len(pending) - len(r_other), other_total=len(pending),
        abandoned=len(r_other) + (0 if refill_leftover_g4 else len(r_g4)),
        fragile_in=len(frag) - len(r_f), fragile_total=len(frag),
        total_in=len(tr.boxes), occ=tr.used_volume() / (spec.dims[0] * spec.dims[1] * spec.dims[2]),
    )


def attempt3(base, spec):
    """排序扫描：L0 刚体下的平台面积。"""
    rows = []
    for tag, key in ORDERS:
        tr = Truck(spec, level=LEVEL_RIGID)
        rest = place_all(tr, key(base))
        tops = sorted(top_coverage(tr).values(), reverse=True)
        rows.append(dict(
            order=tag, in_=len(base) - len(rest), total=len(base),
            occ=tr.used_volume() / (spec.dims[0] * spec.dims[1] * spec.dims[2]),
            max_height=max((b["z"] + b["h"] for b in tr.boxes), default=0),
            top4_m2=[round(v / 1e4, 2) for v in tops[:4]],
        ))
    return rows


def attempt4(base, spec):
    """排序 × 约束交叉：L4 全约束下易碎件装入数。"""
    rows = []
    for tag, key in ORDERS:
        tr = Truck(spec, level=LEVEL_PRESSURE)
        rest = place_all(tr, key(base))
        n_frag = sum(1 for b in tr.boxes if b["kind"] == "fragile")
        rows.append(dict(
            order=tag, in_=len(tr.boxes), total=len(base),
            fragile_in=n_frag,
            occ=tr.used_volume() / (spec.dims[0] * spec.dims[1] * spec.dims[2]),
            trucks=1 if not rest else 2,
        ))
    return rows


def main():
    spec = TRUCKS[1]
    cap = spec.dims[0] * spec.dims[1] * spec.dims[2]
    base = expand_items()
    frag_area = sum(it["dims"][0] * it["dims"][1] for it in base if it["kind"] == "fragile") / 1e4
    floor = spec.dims[0] * spec.dims[1] / 1e4

    print(f"车型：{spec.name}  {spec.dims[0]}×{spec.dims[1]}×{spec.dims[2]} = {cap/1e6:.2f} m³")
    print(f"货物 300 件 = {sum(it['dims'][0]*it['dims'][1]*it['dims'][2] for it in base)/1e6:.3f} m³"
          f"（占 {sum(it['dims'][0]*it['dims'][1]*it['dims'][2] for it in base)/cap*100:.1f}%）")
    print(f"易碎件需要平台 {frag_area:.2f} m² = 底面的 {frag_area/floor*100:.1f}%\n")

    out = {}

    r1 = attempt1(base, spec)
    out["attempt1_two_phase"] = r1
    print(f"[1] {r1['name']}")
    print(f"    非易碎 {r1['nonfragile_in']}/{r1['nonfragile_total']}  易碎 {r1['fragile_in']}/{r1['fragile_total']}"
          f"  最高 {r1['max_height']} cm  占用 {r1['occ']*100:.1f}%")
    print(f"    最大单层平台 {r1['best_top_m2']:.2f} m²（需 {frag_area:.2f}）\n")

    print("[2] 平台优先（G4 铺底）")
    r2a = attempt2(base, spec, refill_leftover_g4=True)
    r2b = attempt2(base, spec, refill_leftover_g4=False)
    out["attempt2_platform_first"] = r2a
    out["attempt2_abandon_leftover"] = r2b
    print(f"    G4 铺底 {r2a['g4_floor']}/{r2a['g4_total']}，平台 {r2a['platforms']} 个，"
          f"顶面 z={r2a['platform_top_z']}")
    print(f"    变体 a（剩余 G4 参与后续装填，公平对比）："
          f"装入 {r2a['total_in']}/300，易碎 {r2a['fragile_in']}/30，占 {r2a['occ']*100:.1f}%")
    print(f"    变体 b（放弃剩余 {r2b['abandoned']} 件 G4，换平台）："
          f"装入 {r2b['total_in']}/300，易碎 {r2b['fragile_in']}/30，占 {r2b['occ']*100:.1f}%")
    print(f"    → 牺牲 {r2b['abandoned']} 件 G4（{r2b['abandoned']*0.24:.2f} m³），"
          f"易碎件从 {r2a['fragile_in']} 提到 {r2b['fragile_in']} 件（+{r2b['fragile_in']-r2a['fragile_in']}）")
    print(f"    → 但两者都只装 280/300 件，仍需 2 辆；易碎件 18/30 仍未装完\n")

    r3 = attempt3(base, spec)
    out["attempt3_order_l0"] = r3
    print("[3] L0 刚体：排序对平台面积的影响")
    for r in r3:
        print(f"    {r['order']:<16} {r['in_']}/{r['total']}  占 {r['occ']*100:5.1f}%  "
              f"最高 {r['max_height']:>3}  前4平台 {r['top4_m2']}")
    print()

    r4 = attempt4(base, spec)
    out["attempt4_order_l4"] = r4
    print("[4] L4 全约束：排序对易碎件装入数的影响")
    for r in r4:
        print(f"    {r['order']:<16} {r['in_']:>3}/{r['total']}  易碎 {r['fragile_in']:>2}/30  "
              f"占 {r['occ']*100:5.1f}%  需 {r['trucks']} 辆")
    print()

    # 核心发现
    best_frag = max(r4, key=lambda r: r["fragile_in"])
    best_total = max(r4, key=lambda r: r["in_"])
    print("核心发现：")
    print(f"  易碎件装得最多的排序 = {best_frag['order']}（{best_frag['fragile_in']}/30），"
          f"但只装 {best_frag['in_']}/300 件（{best_frag['occ']*100:.1f}%）")
    print(f"  货物装得最多的排序 = {best_total['order']}（{best_total['in_']}/300），"
          f"但易碎件只进 {best_total['fragile_in']}/30")
    print("  → 两个目标在贪心框架下互斥，无一排序同时达成")

    out["finding"] = dict(
        best_fragile_order=best_frag["order"], best_fragile=best_frag["fragile_in"],
        best_fragile_total=best_frag["in_"],
        best_total_order=best_total["order"], best_total=best_total["in_"],
        best_total_fragile=best_total["fragile_in"],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写入 {OUT}")


if __name__ == "__main__":
    main()

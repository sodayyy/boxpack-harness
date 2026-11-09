"""10 条约束的独立校验实现。

设计原则（对应 Open Math Harness 的「能力分离」）
------------------------------------------------
本模块只读取「解」——每件货的坐标与姿态，以及一份独立的规格表——
**不调用求解器的任何函数，也不依赖求解器的中间状态**。
求解器说"装下了"不算，本模块复核通过才算。

规格表来自 `data/items.csv` / `data/trucks.csv`（题面抄录版），
而非求解器里的常量。若两者不一致，这里会暴露出来。

依据：MathorCup 2026 D 题 附件 1（P12–P18）
------------------------------------------------
    P12  标准件：长方体纸箱，可任意方向摆放，可堆叠，无特殊约束
    P13  易碎件：仅允许单层放置，不可堆叠，摆放时底面必须完全贴合
                 箱体底面或其他标准件顶面
    P14  定向件：仅允许一种摆放姿态，可堆叠但上层货物重心不得
                 超出下层投影范围
    P15  均为刚性长方体，不可挤压、不可拆分；货物之间、货物与箱体
         之间不得重叠；必须保持正交摆放（棱与箱体棱平行）
    P17  下层货物承重上限 500 kg/平方米，超重则不允许堆叠
    P18  货物高度不得超过车厢高度，顶层货物距车厢顶部预留不小于 3 cm
"""
import csv
from collections import Counter

import numpy as np

CLEARANCE = 3          # C10：顶部余隙 cm
MAX_PRESSURE = 500.0   # C9：kg/m²
EPS = 1e-9

KIND_MAP = {"标准件": "standard", "易碎件": "fragile", "定向件": "oriented"}


# ------------------------------------------------------------------ 规格表
def load_catalog(path):
    """读 data/items.csv → {编号: {dims, weight, kind}}"""
    cat = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cat[r["编号"]] = dict(
                dims=(int(r["长_cm"]), int(r["宽_cm"]), int(r["高_cm"])),
                weight=int(r["单重_kg"]),
                kind=KIND_MAP[r["类型"]],
            )
    return cat


def load_trucks(path):
    """读 data/trucks.csv → {车型: {dims, cap_weight, cost}}"""
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["车型"]] = dict(
                dims=(int(r["内长_cm"]), int(r["内宽_cm"]), int(r["内高_cm"])),
                cap_weight=int(r["额定载重_kg"]),
                cost=int(r["单次成本_元"]),
            )
    return out


# ------------------------------------------------------------------ 几何工具
def _overlap_xy(a, b):
    return (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
            a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"])


def _overlap_area(a, b):
    dx = min(a["x"] + a["l"], b["x"] + b["l"]) - max(a["x"], b["x"])
    dy = min(a["y"] + a["w"], b["y"] + b["w"]) - max(a["y"], b["y"])
    return max(0, dx) * max(0, dy)


def _resting_on(upper, lower):
    """upper 是否直接坐在 lower 的顶面上（高度相接且水平投影有交）"""
    return (abs(upper["z"] - (lower["z"] + lower["h"])) < EPS
            and _overlap_xy(upper, lower))


# ------------------------------------------------------------------ C1 / C4 / C7
def check_orientation(boxes, catalog, errors):
    """C1 正交且尺寸不变量；C4 标准件任意方向；C7 定向件仅原姿态。"""
    for b in boxes:
        spec = catalog.get(b["name"])
        if spec is None:
            errors.append(f"C1 {b['serial']}: 型号 {b['name']} 不在规格表中")
            continue
        got = (b["l"], b["w"], b["h"])
        src = spec["dims"]
        if spec["kind"] == "oriented":
            if got != src:
                errors.append(f"C7 {b['serial']}: 定向件姿态被改动 {got} != {src}")
        else:
            if sorted(got) != sorted(src):
                errors.append(f"C1 {b['serial']}: 尺寸非原始尺寸的排列 {got} vs {src}")


# ------------------------------------------------------------------ C2
def check_overlap(boxes, errors):
    """C2 任意两件不得重叠。"""
    n = len(boxes)
    for i in range(n):
        a = boxes[i]
        for j in range(i + 1, n):
            b = boxes[j]
            if (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
                    a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
                    a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"]):
                errors.append(f"C2 {a['serial']} 与 {b['serial']} 重叠")


# ------------------------------------------------------------------ C5
def check_fragile_single_layer(boxes, errors):
    """C5 易碎件仅单层：不得有货物**直接压在**易碎件顶面上。

    口径说明：题面「仅允许单层放置，不可堆叠」约束的是「堆叠」即承重关系，
    因此判定为「某件货的底面与易碎件顶面接触」。若货物由其他件支撑、
    只是悬在易碎件上方（不接触），不计为堆叠——这种情况由 A1 支撑比控制，
    并在敏感性分析中单独讨论。
    """
    for f in boxes:
        if f["kind"] != "fragile":
            continue
        for b in boxes:
            if b is f:
                continue
            if _resting_on(b, f):
                errors.append(f"C5 {f['serial']}: 上方直接压有 {b['serial']}")


# ------------------------------------------------------------------ C6
def check_fragile_support(boxes, errors):
    """C6 易碎件底面须 100% 贴合车厢底面或其他标准件顶面。"""
    for f in boxes:
        if f["kind"] != "fragile":
            continue
        if f["z"] == 0:
            continue                      # 落在车厢底面上，合规
        below = [b for b in boxes if b is not f and _resting_on(f, b)]
        if not below:
            errors.append(f"C6 {f['serial']}: 悬空（z={f['z']} 下方无支撑）")
            continue
        covered = np.zeros((f["w"], f["l"]), dtype=bool)
        for b in below:
            x0 = max(b["x"], f["x"]) - f["x"]
            x1 = min(b["x"] + b["l"], f["x"] + f["l"]) - f["x"]
            y0 = max(b["y"], f["y"]) - f["y"]
            y1 = min(b["y"] + b["w"], f["y"] + f["w"]) - f["y"]
            covered[y0:y1, x0:x1] = True
        ratio = covered.sum() / covered.size
        if ratio < 1.0 - 1e-9:
            errors.append(f"C6 {f['serial']}: 底面仅贴合 {ratio:.1%}，要求 100%")
        for b in below:
            if b["kind"] != "standard":
                errors.append(f"C6 {f['serial']}: 落在 {b['kind']} 上，"
                              f"只允许车厢底面或标准件")


# ------------------------------------------------------------------ C8
def check_oriented_cog(boxes, errors):
    """C8 定向件上方货物的重心不得超出该定向件的顶面投影。

    题面原文（P14）：「定向件……可堆叠但上层货物重心不得超出下层投影范围」。
    解读：约束对象是「堆在定向件之上的货物」；判定用该货物的底面重心投影点。
    """
    for b in boxes:
        if b["z"] == 0:
            continue
        below = [o for o in boxes if o is not b and _resting_on(b, o)]
        if not below:
            continue
        cx = b["x"] + b["l"] / 2.0
        cy = b["y"] + b["w"] / 2.0
        for o in below:
            if o["kind"] != "oriented":
                continue
            inside = (o["x"] - EPS <= cx <= o["x"] + o["l"] + EPS and
                      o["y"] - EPS <= cy <= o["y"] + o["w"] + EPS)
            if not inside:
                errors.append(
                    f"C8 {b['serial']}: 重心 ({cx:.1f},{cy:.1f}) 超出下层定向件 "
                    f"{o['serial']} 的投影 [{o['x']},{o['x'] + o['l']}]x"
                    f"[{o['y']},{o['y'] + o['w']}]")


# ------------------------------------------------------------------ A3
def check_floating(boxes, errors):
    """A3（假设）：任何货物不得悬空——z>0 时下方至少有一件直接支撑。

    题面未明写，但物理必需（且 OR-Library 等公开基准亦以此为前提）。
    「可堆叠」隐含「必须堆在东西上面」，故列为假设并在 README 中标注。
    """
    for b in boxes:
        if b["z"] == 0:
            continue
        if not any(o is not b and _resting_on(b, o) for o in boxes):
            errors.append(f"A3 {b['serial']}: 悬空（z={b['z']} 下方无任何支撑）")


# ------------------------------------------------------------------ C9
def check_pressure(boxes, errors):
    """C9 下层货物承重 ≤ 500 kg/m²（按接触面积分摊，未做链路传递，见假设 B1）。"""
    carried = {}
    for b in boxes:
        if b["z"] == 0:
            continue
        below = [o for o in boxes if o is not b and _resting_on(b, o)]
        if not below:
            continue
        base = b["l"] * b["w"]
        for o in below:
            share = _overlap_area(o, b) / base
            carried[o["serial"]] = carried.get(o["serial"], 0.0) + b["weight"] * share
    for b in boxes:
        area_m2 = b["l"] * b["w"] * 1e-4
        p = (b["weight"] + carried.get(b["serial"], 0.0)) / area_m2
        if p > MAX_PRESSURE + 1e-6:
            errors.append(f"C9 {b['serial']}: 承压 {p:.0f} kg/m² 超过 {MAX_PRESSURE:.0f}")


# ------------------------------------------------------------------ C10
def check_bounds(boxes, spec, errors):
    """C10 越界、高度不超车厢、顶部留 ≥3 cm。"""
    L, W, H = spec["dims"]
    h_eff = H - CLEARANCE
    for b in boxes:
        if b["x"] < 0 or b["y"] < 0 or b["z"] < 0:
            errors.append(f"C10 {b['serial']}: 负坐标")
        if b["x"] + b["l"] > L or b["y"] + b["w"] > W:
            errors.append(f"C10 {b['serial']}: 水平越界")
        if b["z"] + b["h"] > h_eff:
            errors.append(f"C10 {b['serial']}: 顶面 {b['z'] + b['h']} 超过可用高度 {h_eff}")
    total = sum(b["weight"] for b in boxes)
    if total > spec["cap_weight"]:
        errors.append(f"C10 超载 {total} / {spec['cap_weight']} kg")


# ------------------------------------------------------------------ C3
def check_counts(boxes, expect, errors):
    """C3 件数与型号守恒（不可拆分、不可漏装）。"""
    cnt = Counter(b["name"] for b in boxes)
    for name, need in expect.items():
        if cnt.get(name, 0) != need:
            errors.append(f"C3 {name}: 数量 {cnt.get(name, 0)} ≠ {need}")
    for name in cnt:
        if name not in expect:
            errors.append(f"C3 出现未知型号 {name}")


# ------------------------------------------------------------------ 入口
def check_all(boxes, spec, catalog, expect_counts=None, max_errors=200):
    """跑全部 10 条约束，返回违规描述列表（空列表 = 合法）。"""
    errors = []
    check_orientation(boxes, catalog, errors)
    check_overlap(boxes, errors)
    check_fragile_single_layer(boxes, errors)
    check_fragile_support(boxes, errors)
    check_oriented_cog(boxes, errors)
    check_pressure(boxes, errors)
    check_floating(boxes, errors)
    check_bounds(boxes, spec, errors)
    if expect_counts:
        check_counts(boxes, expect_counts, errors)
    return errors[:max_errors]


def summarize(errors):
    """按约束编号统计违规条数，便于定位「哪一类最容易违反」。"""
    cnt = Counter()
    for e in errors:
        cnt[e.split()[0]] += 1
    return dict(sorted(cnt.items()))

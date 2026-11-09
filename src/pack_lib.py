"""
装箱 harness 核心库
- 数据定义（题目给定）
- Truck：占用栅格 + 约束检查
- pack_ep()   极值点贪心
- pack_layer() 分层 + 二维货架
- verifier()  独立复核（不信任求解器任何中间状态）
- metrics()   下界与指标

坐标：x=长, y=宽, z=高；单位 cm / kg
"""
import itertools
import os
from dataclasses import dataclass, field

import numpy as np

CLEARANCE = 3
MAX_PRESSURE = 500.0

# 假设 A1：非易碎件底面最小接触面积比。
# 题面（附件1 P12）对标准件只说「可堆叠，无特殊约束」，**未规定接触比**。
# 故默认 0（严格对齐题面，只要求不悬空）；可用环境变量覆盖做敏感性分析：
#     SUPPORT_RATIO=0.75 py -3.12 experiments/run_baselines.py
SUPPORT_RATIO = float(os.environ.get("SUPPORT_RATIO", "0"))


# ------------------------------------------------------------------ 数据
@dataclass(frozen=True)
class ItemType:
    name: str
    dims: tuple
    weight: int
    qty: int
    kind: str


TYPES = [
    ItemType("G1", (60, 40, 30), 12, 80, "standard"),
    ItemType("G2", (50, 35, 25), 8, 100, "standard"),
    ItemType("G3", (70, 50, 40), 15, 30, "fragile"),
    ItemType("G4", (80, 60, 50), 25, 40, "oriented"),
    ItemType("G5", (40, 40, 60), 18, 50, "oriented"),
]


@dataclass(frozen=True)
class TruckType:
    name: str
    dims: tuple
    cap_weight: int
    cost: int


TRUCKS = [
    TruckType("车型1", (420, 210, 220), 6000, 450),
    TruckType("车型2", (680, 245, 250), 10000, 700),
]


def orients(kind, dims):
    if kind == "oriented":
        return [tuple(dims)]
    return list(dict.fromkeys(itertools.permutations(dims)))


def expand_items():
    out = []
    for t in TYPES:
        for k in range(t.qty):
            out.append({"name": t.name, "kind": t.kind, "dims": t.dims,
                        "weight": t.weight, "serial": f"{t.name}-{k:03d}"})
    return out


# ------------------------------------------------------------------ 容器
class Truck:
    def __init__(self, spec: TruckType):
        self.spec = spec
        L, W, H = spec.dims
        self.L, self.W, self.H = L, W, H
        self.h_eff = H - CLEARANCE
        self.own = np.full((H, W, L), -1, dtype=np.int16)
        self.boxes = []          # list of dict
        self.kinds = []
        self.areas = []
        self.weights = []
        self.carried = {}
        self.total_weight = 0
        self.extremes = {(0, 0, 0)}

    # --- 可行性
    def feasible(self, x, y, z, l, w, h, kind, weight):
        if x < 0 or y < 0 or z < 0:
            return False
        if x + l > self.L or y + w > self.W or z + h > self.h_eff:
            return False
        if self.own[z:z + h, y:y + w, x:x + l].max() != -1:
            return False
        if z > 0:
            below = self.own[z - 1, y:y + w, x:x + l]
            n_support = int((below != -1).sum())
            if n_support == 0:
                return False        # 假设 A3：任何货物不得悬空
            ratio = n_support / (l * w)
            need = 1.0 if kind == "fragile" else SUPPORT_RATIO
            if ratio < need:
                return False
            owners = set(below[below != -1].ravel().tolist())
            for o in owners:
                if self.kinds[o] == "fragile":      # 易碎件不能承重
                    return False
                if kind == "fragile" and self.kinds[o] != "standard":
                    return False
            total = l * w
            for o in owners:
                cells = int((below == o).sum())
                extra = weight * cells / total
                cur = self.carried.get(o, 0) + extra
                area_m2 = self.areas[o] * 1e-4
                if (self.weights[o] + cur) / area_m2 > MAX_PRESSURE:
                    return False
            # C8（题面 P14）：若下方有定向件，本件重心投影须落在其顶面投影内
            cx, cy = x + l / 2.0, y + w / 2.0
            for o in owners:
                if self.kinds[o] != "oriented":
                    continue
                ob = self.boxes[o]
                if not (ob["x"] <= cx <= ob["x"] + ob["l"] and
                        ob["y"] <= cy <= ob["y"] + ob["w"]):
                    return False
        if self.total_weight + weight > self.spec.cap_weight:
            return False
        return True

    # --- 落子
    def put(self, meta, x, y, z, l, w, h):
        idx = len(self.boxes)
        self.own[z:z + h, y:y + w, x:x + l] = idx
        self.boxes.append(dict(serial=meta["serial"], name=meta["name"], kind=meta["kind"],
                               x=x, y=y, z=z, l=l, w=w, h=h, weight=meta["weight"]))
        self.kinds.append(meta["kind"])
        self.areas.append(l * w)
        self.weights.append(meta["weight"])
        self.total_weight += meta["weight"]
        if z > 0:
            below = self.own[z - 1, y:y + w, x:x + l]
            total = l * w
            for o in set(below[below != -1].ravel().tolist()):
                cells = int((below == o).sum())
                self.carried[o] = self.carried.get(o, 0) + meta["weight"] * cells / total
        if hasattr(self, "extremes"):
            # 底面三个边角 + 顶面四个角（角点越丰富，缝隙利用率越高）
            self.extremes.update({
                (x + l, y, z), (x, y + w, z), (x + l, y + w, z),
                (x, y, z + h), (x + l, y, z + h), (x, y + w, z + h), (x + l, y + w, z + h),
            })
        self._hm = None

    def used_volume(self):
        return sum(b["l"] * b["w"] * b["h"] for b in self.boxes)


# ------------------------------------------------------------------ 求解器 1：极值点贪心
def pack_ep(items, spec, max_trucks=30, ep_cap=1500):
    trucks, rest = [], []
    for it in items:
        placed = False
        for tr in trucks:
            if _ep_one(tr, it, ep_cap):
                placed = True
                break
        if not placed and len(trucks) < max_trucks:
            tr = Truck(spec)
            if _ep_one(tr, it, ep_cap):
                trucks.append(tr)
                placed = True
        if not placed:
            rest.append(it)
    return trucks, rest


def _ep_one(tr, it, ep_cap):
    pts = sorted(tr.extremes, key=lambda p: (p[2], p[1], p[0]))[:ep_cap]
    for (x, y, z) in pts:
        for (l, w, h) in orients(it["kind"], it["dims"]):
            if tr.feasible(x, y, z, l, w, h, it["kind"], it["weight"]):
                tr.put(it, x, y, z, l, w, h)
                return True
    return False


# ------------------------------------------------------------------ 求解器 2：分层 + 二维货架
def pack_layer(items, spec):
    """按高度分层；层内按货架(shelf)摆二维矩形。层内货物等高或更矮，保证完全支撑。"""
    remaining = list(items)
    trucks = []
    guard = 0
    while remaining and guard < 40:
        guard += 1
        tr = Truck(spec)
        # 关闭极值点，避免无谓开销
        tr.__dict__.pop("extremes", None)
        z = 0
        while z < tr.h_eff and remaining:
            # 选层高：取剩余货物中最高的可行高度（定向件优先用其唯一姿态高度）
            cand_h = sorted({min(o[2] for o in orients(it["kind"], it["dims"]))
                             for it in remaining})
            layer_h = None
            for hh in cand_h:
                if z + hh <= tr.h_eff:
                    layer_h = hh
                    break
            if layer_h is None:
                break
            fits = [it for it in remaining
                    if min(o[2] for o in orients(it["kind"], it["dims"])) <= layer_h]
            if not fits:
                break
            got = _shelf_layer(tr, fits, remaining, z, layer_h)
            if got == 0:
                break
            z += layer_h
        if tr.boxes:
            trucks.append(tr)
        if not tr.boxes and remaining:
            break   # 防止死循环
    return trucks, remaining


def _shelf_layer(tr, fits, remaining, z, layer_h):
    """在高度 z 处铺一层。返回放置件数。"""
    L, W = tr.L, tr.W
    # 按底面积降序
    fits = sorted(fits, key=lambda it: -max(o[0] * o[1] for o in orients(it["kind"], it["dims"])))
    cur_x, cur_y, row_d = 0, 0, 0
    count = 0
    for it in fits:
        if it not in remaining:
            continue
        best = None
        for (l, w, h) in orients(it["kind"], it["dims"]):
            if h > layer_h:
                continue
            if cur_x + l <= L and cur_y + w <= W:
                cand = (l, w, h, cur_x, cur_y)
                if best is None or (l * w) > (best[0] * best[1]):
                    best = cand
        if best is None:
            # 换行
            cur_x = 0
            cur_y += row_d if row_d else max(min(o[1] for o in orients(it["kind"], it["dims"])), 1)
            row_d = 0
            if cur_y >= W:
                break
            for (l, w, h) in orients(it["kind"], it["dims"]):
                if h > layer_h:
                    continue
                if cur_x + l <= L and cur_y + w <= W:
                    cand = (l, w, h, cur_x, cur_y)
                    if best is None or (l * w) > (best[0] * best[1]):
                        best = cand
            if best is None:
                continue
        l, w, h, x, y = best
        if not tr.feasible(x, y, z, l, w, h, it["kind"], it["weight"]):
            continue
        tr.put(it, x, y, z, l, w, h)
        remaining.remove(it)
        cur_x += l
        row_d = max(row_d, w)
        count += 1
    return count


# ------------------------------------------------------------------ 校验器（独立实现）
def verify(trucks, expect_counts):
    errs = []
    counts = {}
    for ti, tr in enumerate(trucks, 1):
        L, W, H = tr.spec.dims
        h_eff = H - CLEARANCE
        occ = np.zeros((H, W, L), dtype=np.int32)
        meta = {}
        for pi, b in enumerate(tr.boxes, 1):
            counts[b["name"]] = counts.get(b["name"], 0) + 1
            if b["x"] < 0 or b["y"] < 0 or b["z"] < 0:
                errs.append(f"车{ti} {b['serial']}: 负坐标")
            if b["x"] + b["l"] > L or b["y"] + b["w"] > W or b["z"] + b["h"] > h_eff:
                errs.append(f"车{ti} {b['serial']}: 越界或超 3cm 余隙")
                continue
            if occ[b["z"]:b["z"] + b["h"], b["y"]:b["y"] + b["w"], b["x"]:b["x"] + b["l"]].max() > 0:
                errs.append(f"车{ti} {b['serial']}: 重叠")
            occ[b["z"]:b["z"] + b["h"], b["y"]:b["y"] + b["w"], b["x"]:b["x"] + b["l"]] = pi
            meta[pi] = b
        for pi, b in meta.items():
            if b["z"] == 0:
                continue
            below = occ[b["z"] - 1, b["y"]:b["y"] + b["w"], b["x"]:b["x"] + b["l"]]
            ratio = float((below != 0).sum()) / (b["l"] * b["w"])
            need = 1.0 if b["kind"] == "fragile" else SUPPORT_RATIO
            if ratio + 1e-9 < need:
                errs.append(f"车{ti} {b['serial']}: 支撑不足 {ratio:.2f} < {need}")
            for v in set(below[below != 0].ravel().tolist()):
                if meta[v]["kind"] == "fragile":
                    errs.append(f"车{ti} {b['serial']}: 压在易碎件 {meta[v]['serial']} 上")
                if b["kind"] == "fragile" and meta[v]["kind"] != "standard":
                    errs.append(f"车{ti} {b['serial']}: 易碎件未落在标准件/地面")
            if b["kind"] == "oriented":
                if (b["l"], b["w"], b["h"]) != tuple(next(t.dims for t in TYPES if t.name == b["name"])):
                    errs.append(f"车{ti} {b['serial']}: 定向件姿态被改动")
        if tr.total_weight > tr.spec.cap_weight:
            errs.append(f"车{ti}: 超载 {tr.total_weight}/{tr.spec.cap_weight}")
    for name, need in expect_counts.items():
        if counts.get(name, 0) != need:
            errs.append(f"{name} 数量 {counts.get(name,0)} ≠ {need}")
    return errs


# ------------------------------------------------------------------ 指标
def lower_bound(spec):
    tv = sum(t.dims[0] * t.dims[1] * t.dims[2] * t.qty for t in TYPES)
    tw = sum(t.weight * t.qty for t in TYPES)
    L, W, H = spec.dims
    cv = L * W * H
    return max(-(-tv // cv), -(-tw // spec.cap_weight)), tv, tw, cv

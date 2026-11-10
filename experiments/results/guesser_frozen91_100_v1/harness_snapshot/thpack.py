# -*- coding: utf-8 -*-
"""OR-Library thpack 格式解析（Bischoff & Ratcliff 1995 标准算例）

数据来源：https://people.brunel.ac.uk/~mastjjb/jeb/orlib/thpackinfo.html
文件格式（以 thpack1 为例）：

    <算例数>
    每个算例：
      <编号> <某参数>
      <容器长> <容器宽> <容器高>
      <箱型数>
      每类箱型占 1 行：<类型号> <长> <长可否竖放> <宽> <宽可否竖放> <高> <高可否竖放> <数量>

说明：题面「定向约束」在该数据集中的标准写法就是这三个 0/1 标记，
因此解析结果可直接作为 orients() 的 allowed 参数。
"""
from pathlib import Path


def parse_thpack(path):
    """解析 thpack 文件，返回算例列表。

    每个算例：dict(pid, seed, box=(L,W,H), types=[dict(t, dims, flags, qty)])
    """
    lines = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln]
    i = 0
    n_inst = int(lines[i]); i += 1
    out = []
    for _ in range(n_inst):
        pid, seed = lines[i].split(); i += 1
        L, W, H = map(int, lines[i].split()); i += 1
        n_types = int(lines[i]); i += 1
        types = []
        for _t in range(n_types):
            v = list(map(int, lines[i].split())); i += 1
            t, l, il, w, iw, h, ih, qty = v
            types.append(dict(t=t, dims=(l, w, h), flags=(il, iw, ih), qty=qty))
        out.append(dict(pid=pid, seed=seed, box=(L, W, H), types=types))
    return out


def allowed_orients(dims, flags):
    """把 0/1 方向标记翻译成允许的姿态列表。flags[d] == 1 表示维度 d 可作竖直方向。"""
    res = []
    for d in range(3):
        if not flags[d]:
            continue
        rest = [dims[k] for k in range(3) if k != d]
        for a, b in ((rest[0], rest[1]), (rest[1], rest[0])):
            o = (a, b, dims[d])
            if o not in res:
                res.append(o)
    return res or [tuple(dims)]


def to_items(inst, kind="standard", weight=1):
    """把一个算例展开成逐件明细，供 pack_lib 使用。"""
    items = []
    for tp in inst["types"]:
        allowed = allowed_orients(tp["dims"], tp["flags"])
        for k in range(tp["qty"]):
            items.append(dict(
                name=f"T{tp['t']}", kind=kind, dims=tp["dims"], weight=weight,
                serial=f"T{tp['t']}-{k:03d}", allowed=allowed,
            ))
    return items

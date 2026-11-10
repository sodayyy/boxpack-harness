# -*- coding: utf-8 -*-
"""OR-Library thpack 标准算例校准

用途：给「实现水平」一个外部参照。自造算例上的任何数字都无法回答
「你的实现本身有没有写错」，只有公开标准算例可以。

口径（与文献一致）：
  - 单容器（thpack 为标准单容器算例；允许多容器会把 ISD 算错）
  - 姿态按数据的 0/1 方向标记
  - 无易碎/承重约束（标准算例只含几何）
  - 指标 ISD = 装入体积 / 容器容积

用法：
    py -3.12 experiments/bench_thpack.py                      # 100 个算例
    py -3.12 experiments/bench_thpack.py --instances 10       # 前 10 个
    py -3.12 experiments/bench_thpack.py --file data/thpack/thpack9.txt
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pack_lib import TruckType, orients  # noqa: E402
from src.thpack import parse_thpack, to_items  # noqa: E402


def pack_one(inst, order="volume", verify=False):
    """单容器装载（不用 pack_ep，因为它是多容器首次适应）。"""
    from src.pack_lib import Truck

    L, W, H = inst["box"]
    spec = TruckType("BR", (L, W, H), 10 ** 9, 1)
    items = to_items(inst)
    if order == "volume":
        items.sort(key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    elif order == "height":
        items.sort(key=lambda it: (-it["dims"][2], -it["dims"][0] * it["dims"][1]))
    elif order == "area":
        items.sort(key=lambda it: -it["dims"][0] * it["dims"][1])

    # clearance=0：标准算例不含题面的 3 cm 顶部余隙
    tr = Truck(spec, clearance=0, level=0)
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

    cap = L * W * H
    return dict(pid=inst["pid"], n=len(items), placed=len(items) - len(rest),
                isd=tr.used_volume() / cap, rest=len(rest),
                boxes=tr.boxes, level=0,
                geometry_errors=check_solution(tr, L, W, H) if verify else None)


def check_solution(tr, L, W, H):
    """独立检查：越界 + 重叠。返回违规条数。"""
    errs = 0
    bs = tr.boxes
    for i, a in enumerate(bs):
        if (min(a["x"], a["y"], a["z"]) < 0 or
                min(a["l"], a["w"], a["h"]) <= 0 or
                a["x"] + a["l"] > L or a["y"] + a["w"] > W or a["z"] + a["h"] > H):
            errs += 1
        for b in bs[i + 1:]:
            if (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
                    a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
                    a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"]):
                errs += 1
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/thpack/thpack1.txt")
    ap.add_argument("--instances", type=int, default=0, help="0 表示全部")
    ap.add_argument("--order", default="volume", choices=["volume", "height", "area"])
    ap.add_argument("--json", default="experiments/results/thpack1_ep_pure_geometry_v2.json")
    ap.add_argument("--verify", action="store_true", help="额外做越界/重叠独立检查")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"找不到算例文件 {path}")
        print("下载：curl -L -o data/thpack/thpack1.txt "
              "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/thpack1.txt")
        return 1

    insts = parse_thpack(path)
    if args.instances:
        insts = insts[:args.instances]
    print(f"{path}：{len(insts)} 个算例，容器 {insts[0]['box']}，排序 {args.order}\n")

    rows = []
    t_all = time.time()
    for inst in insts:
        t0 = time.time()
        r = pack_one(inst, args.order, args.verify)
        r["seconds"] = round(time.time() - t0, 2)
        rows.append(r)
        print(f"  算例 {r['pid']:>3}  {r['n']:>3} 件  装入 {r['placed']:>3}  "
              f"ISD {r['isd']*100:5.1f}%  {r['seconds']:4.1f}s")

    v = [r["isd"] for r in rows]
    print(f"\n平均 ISD {sum(v)/len(v)*100:.1f}%  最高 {max(v)*100:.1f}%  "
          f"最低 {min(v)*100:.1f}%  总耗时 {time.time()-t_all:.0f}s")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

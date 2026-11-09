"""逐车明细诊断：看清「装不下」究竟卡在哪里。

用法：
    py -3.12 experiments/inspect_solution.py [车型名] [排序]
例：
    py -3.12 experiments/inspect_solution.py 车型2 体积降序
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pack_lib import TRUCKS, TYPES, expand_items, lower_bound, pack_ep

KIND_CN = {"standard": "标准", "fragile": "易碎", "oriented": "定向"}


def sort_items(items, how):
    if how == "体积降序":
        return sorted(items, key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    if how == "底面积降序":
        return sorted(items, key=lambda it: -(it["dims"][0] * it["dims"][1]))
    if how == "易碎优先":
        pri = {"fragile": 0, "oriented": 1, "standard": 2}
        return sorted(items, key=lambda it: (pri[it["kind"]], -it["dims"][0] * it["dims"][1]))
    if how == "定向优先":
        pri = {"oriented": 0, "fragile": 1, "standard": 2}
        return sorted(items, key=lambda it: (pri[it["kind"]],
                                             -it["dims"][0] * it["dims"][1] * it["dims"][2]))
    raise ValueError(how)


def main():
    truck_name = sys.argv[1] if len(sys.argv) > 1 else "车型2"
    how = sys.argv[2] if len(sys.argv) > 2 else "体积降序"

    spec = next(t for t in TRUCKS if t.name == truck_name)
    lb, tv, tw, cv = lower_bound(spec)
    items = sort_items(expand_items(), how)
    trucks, rest = pack_ep(items, spec)

    print(f"车型 {spec.name}  {spec.dims}  容积 {cv/1e6:.2f} m³  排序 {how}")
    print(f"货物总体积 {tv/1e6:.3f} m³（占单车 {tv/cv*100:.1f}%）  下界 {lb} 辆")
    print(f"结果：{len(trucks)} 辆，未装 {len(rest)} 件\n")

    for i, tr in enumerate(trucks, 1):
        c = Counter(b["name"] for b in tr.boxes)
        kinds = Counter(b["kind"] for b in tr.boxes)
        vol = tr.used_volume()
        zmax = max((b["z"] + b["h"] for b in tr.boxes), default=0)
        frag = [b for b in tr.boxes if b["kind"] == "fragile"]
        frag_z = sorted({b["z"] for b in frag})
        print(f"车{i}: {len(tr.boxes):3d} 件 | {vol/1e6:6.3f} m³ | 占用 {vol/cv*100:5.1f}% "
              f"| {tr.total_weight:5d} kg | 最高点 {zmax:3d} cm")
        print(f"      型号 {dict(c)}")
        print(f"      类型 {{{', '.join(f'{KIND_CN[k]}:{v}' for k, v in kinds.items())}}}")
        if frag:
            print(f"      易碎件 {len(frag)} 件，所在高度 {frag_z}")

    print("\n=== 逐类型总量核对 ===")
    tot = Counter()
    for tr in trucks:
        for b in tr.boxes:
            tot[b["name"]] += 1
    for t in TYPES:
        print(f"  {t.name} {KIND_CN[t.kind]:<2} 装 {tot[t.name]:3d} / {t.qty:3d}")

    print("\n=== 车1 的空间利用结构 ===")
    tr = trucks[0]
    L, W, H = spec.dims
    h_eff = H - 3
    # 按 10cm 高度切片，统计每层的底面覆盖比例
    print("  高度切片：占用底面积比例（用于判断碎片化）")
    step = 20
    for z0 in range(0, h_eff, step):
        z1 = min(z0 + step, h_eff)
        cells = set()
        for b in tr.boxes:
            if b["z"] < z1 and b["z"] + b["h"] > z0:
                for x in range(b["x"], b["x"] + b["l"], 10):
                    for y in range(b["y"], b["y"] + b["w"], 10):
                        cells.add((x // 10, y // 10))
        frac = len(cells) / ((L // 10) * (W // 10))
        bar = "#" * int(frac * 40)
        print(f"    z {z0:3d}-{z1:3d}: {frac*100:5.1f}% {bar}")


if __name__ == "__main__":
    main()

"""跑全部策略 × 两种车型，输出指标表 + 校验结果。

校验使用 `src/constraints.py` 的独立实现（不调用求解器的 verify），
数量守恒在全局统计，其余 9 条逐车检查。

用法：
    py -3.12 experiments/run_baselines.py
    SUPPORT_RATIO=0.75 py -3.12 experiments/run_baselines.py    # 假设 A1 敏感性
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.constraints import check_all, load_catalog, load_trucks, summarize
from src.pack_lib import (TRUCKS, TYPES, expand_items, lower_bound, pack_ep,
                          pack_layer)

OUT = Path(__file__).resolve().parent / "results" / "baseline_v1.json"
CATALOG = load_catalog(ROOT / "data" / "items.csv")
TRUCK_INFO = load_trucks(ROOT / "data" / "trucks.csv")
EXPECT = {t.name: t.qty for t in TYPES}
SUPPORT_RATIO = os.environ.get("SUPPORT_RATIO", "0")


def verify_all(trucks, spec_name):
    """独立复核：逐车跑 9 条结构约束，件数在全局核对。"""
    spec = TRUCK_INFO[spec_name]
    errs = []
    for i, tr in enumerate(trucks, 1):
        for e in check_all(tr.boxes, spec, CATALOG):
            errs.append(f"车{i} {e}")
    cnt = Counter(b["name"] for tr in trucks for b in tr.boxes)
    for name, need in EXPECT.items():
        if cnt.get(name, 0) != need:
            errs.append(f"C3 {name}: 总数 {cnt.get(name, 0)} ≠ {need}")
    return errs


def sort_items(items, how):
    if how == "体积降序":
        return sorted(items, key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    if how == "底面积降序":
        return sorted(items, key=lambda it: -(it["dims"][0] * it["dims"][1]))
    if how == "易碎优先":
        pri = {"fragile": 0, "oriented": 1, "standard": 2}
        return sorted(items, key=lambda it: (pri[it["kind"]],
                                             -it["dims"][0] * it["dims"][1]))
    if how == "定向优先":
        pri = {"oriented": 0, "fragile": 1, "standard": 2}
        return sorted(items, key=lambda it: (pri[it["kind"]],
                                             -it["dims"][0] * it["dims"][1] * it["dims"][2]))
    raise ValueError(how)


def run_one(spec, how, algo):
    items = sort_items(expand_items(), how)
    t0 = time.time()
    if algo == "EP":
        trucks, rest = pack_ep(items, spec)
    else:
        trucks, rest = pack_layer(items, spec)
    dt = time.time() - t0

    errs = verify_all(trucks, spec.name)
    lb, tv, tw, cv = lower_bound(spec)
    n = len(trucks)
    used_v = sum(tr.used_volume() for tr in trucks)
    used_w = sum(tr.total_weight for tr in trucks)
    return dict(truck=spec.name, sort=how, algo=algo, trucks=n, lower=lb,
                support_ratio=float(SUPPORT_RATIO),
                veh_eff=round(n / lb, 3),
                space_util=round(used_v / (n * cv), 4),
                fill_rate=round(used_v / tv, 4),
                weight_util=round(used_w / (n * spec.cap_weight), 4),
                cost=n * spec.cost, unplaced=len(rest),
                verify_errors=len(errs),
                err_by_constraint=summarize(errs),
                err_sample=errs[:3],
                seconds=round(dt, 1))


def main():
    print(f"假设 A1  SUPPORT_RATIO = {SUPPORT_RATIO}（题面未规定非易碎件接触比）")
    print(f"独立校验器：src/constraints.py，10 条约束\n")

    rows = []
    for spec in TRUCKS:
        for algo in ("EP", "LAYER"):
            hows = ["体积降序", "底面积降序", "易碎优先", "定向优先"] if algo == "EP" else ["体积降序"]
            for how in hows:
                r = run_one(spec, how, algo)
                rows.append(r)
                print(f"{r['truck']} {r['algo']:>5} {r['sort']:<10} "
                      f"车{r['trucks']} 下界{r['lower']} 空间{r['space_util']*100:5.1f}% "
                      f"校验{'OK' if r['verify_errors']==0 else r['verify_errors']} "
                      f"{r['seconds']}s")
                if r["verify_errors"]:
                    for e in r["err_sample"]:
                        print("      ", e)

    print("\n" + "=" * 92)
    print(f"{'车型':<7}{'算法':<7}{'排序':<11}{'车数':>4}{'下界':>4}{'车辆效率':>9}"
          f"{'空间利用':>9}{'满载率':>8}{'成本':>6}{'校验':>6}")
    print("-" * 92)
    for r in sorted(rows, key=lambda x: (x["truck"], x["trucks"], -x["space_util"])):
        print(f"{r['truck']:<7}{r['algo']:<7}{r['sort']:<11}{r['trucks']:>4}{r['lower']:>4}"
              f"{r['veh_eff']:>9.2f}{r['space_util']*100:>8.1f}%{r['fill_rate']*100:>7.1f}%"
              f"{r['cost']:>6}{('OK' if r['verify_errors']==0 else 'X'):>6}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

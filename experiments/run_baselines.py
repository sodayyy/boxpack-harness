"""跑全部策略 × 两种车型，输出指标表 + 校验结果。

校验使用 `src/constraints.py` 的独立实现（不调用求解器的 verify），
数量守恒在全局统计，其余 9 条逐车检查。

用法：
    py -3.12 experiments/run_baselines.py
    SUPPORT_RATIO=0.75 py -3.12 experiments/run_baselines.py    # 假设 A1 敏感性
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.constraints import audit_load_chain, check_fleet, load_catalog, load_trucks, summarize
from src.solution_io import export_solution, read_solution, read_solution_csv, fleet_metrics
from src.pack_lib import (TRUCKS, expand_items, lower_bound, pack_ep,
                          pack_layer)

OUT = ROOT / "experiments/results/baseline_v2_protocol.json"
CATALOG = load_catalog(ROOT / "data" / "items.csv")
TRUCK_INFO = load_trucks(ROOT / "data" / "trucks.csv")
SUPPORT_RATIO = os.environ.get("SUPPORT_RATIO", "0")


def verify_all(trucks, spec_name):
    """独立复核：逐车跑 9 条结构约束，件数在全局核对。"""
    fleet = [dict(truck_type=spec_name, boxes=tr.boxes) for tr in trucks]
    return check_fleet(fleet, TRUCK_INFO, CATALOG,
                       support_ratio=float(SUPPORT_RATIO))


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


def run_one(spec, how, algo, solution_dir=None):
    items = sort_items(expand_items(), how)
    t0 = time.time()
    if algo == "EP":
        trucks, rest = pack_ep(items, spec, level=4)
    else:
        trucks, rest = pack_layer(items, spec)
    dt = time.time() - t0

    errs = verify_all(trucks, spec.name)
    lb, _, _, _ = lower_bound(spec)
    n = len(trucks)
    fleet = [dict(truck_type=spec.name, boxes=tr.boxes) for tr in trucks]
    metrics = fleet_metrics(fleet, TRUCK_INFO, CATALOG)
    chain = [audit_load_chain(tr.boxes) for tr in trucks]
    solution_files = []
    if solution_dir is not None:
        stem = f"{spec.name}_{algo}_{how}"
        jp, cp = solution_dir / (stem + ".json"), solution_dir / (stem + ".csv")
        export_solution(fleet, jp, cp, TRUCK_INFO, support_ratio=float(SUPPORT_RATIO))
        for restored in (read_solution(jp, TRUCK_INFO), read_solution_csv(cp, TRUCK_INFO)):
            if restored != fleet:
                raise AssertionError("coordinate roundtrip changed layout")
            if check_fleet(restored, TRUCK_INFO, CATALOG,
                           support_ratio=float(SUPPORT_RATIO)) != errs:
                raise AssertionError("roundtrip validation changed")
        solution_files = [jp.relative_to(ROOT).as_posix(), cp.relative_to(ROOT).as_posix()]
    return dict(truck=spec.name, sort=how, algo=algo, trucks=n, lower=lb,
                schema_version=2, pressure_model="legacy_b1",
                chain_audit=chain, chain_audit_errors=sum(len(a["errors"]) for a in chain),
                solution_files=solution_files,
                nominal_space_util=round(metrics["nominal_space_util"], 4),
                effective_space_util=round(metrics["effective_space_util"], 4),
                shipment_completion=round(metrics["shipment_completion"], 4),
                support_ratio=float(SUPPORT_RATIO),
                veh_eff=round(n / lb, 3),
                space_util=round(metrics["nominal_space_util"], 4),
                weight_util=round(metrics["weight_util"], 4),
                cost=n * spec.cost, unplaced=len(rest),
                verify_errors=len(errs),
                err_by_constraint=summarize(errs),
                err_sample=errs[:3],
                seconds=round(dt, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="两车型EP体积排序")
    ap.add_argument("--json", default=str(OUT))
    args = ap.parse_args()
    out = Path(args.json)
    solution_dir = out.parent / (out.stem + "_solutions")
    solution_dir.mkdir(parents=True, exist_ok=True)
    print(f"假设 A1  SUPPORT_RATIO = {SUPPORT_RATIO}（题面未规定非易碎件接触比）")
    print(f"独立校验器：src/constraints.py，10 条约束\n")

    rows = []
    for spec in TRUCKS:
        for algo in (("EP",) if args.quick else ("EP", "LAYER")):
            hows = ["体积降序", "底面积降序", "易碎优先", "定向优先"] if algo == "EP" else ["体积降序"]
            if args.quick:
                hows = ["体积降序"]
            for how in hows:
                r = run_one(spec, how, algo, solution_dir)
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
          f"{'空间利用':>9}{'运输完成':>8}{'成本':>6}{'校验':>6}")
    print("-" * 92)
    for r in sorted(rows, key=lambda x: (x["truck"], x["trucks"], -x["space_util"])):
        print(f"{r['truck']:<7}{r['algo']:<7}{r['sort']:<11}{r['trucks']:>4}{r['lower']:>4}"
              f"{r['veh_eff']:>9.2f}{r['space_util']*100:>8.1f}%{r['shipment_completion']*100:>7.1f}%"
              f"{r['cost']:>6}{('OK' if r['verify_errors']==0 else 'X'):>6}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""校验器的违规触发测试。

目的：证明 `src/constraints.py` 对**每一条**约束都真的会报错，
而不是"写了但从来不触发"。每条用例都是人为构造的故意违规解，
断言错误列表里出现对应的约束编号。

用法：
    py -3.12 experiments/test_constraints.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.constraints import check_all, load_catalog, load_trucks, summarize

CATALOG = load_catalog(ROOT / "data" / "items.csv")
TRUCKS = load_trucks(ROOT / "data" / "trucks.csv")
SPEC = TRUCKS["车型2"]


def mk(name, kind, x, y, z, l, w, h, weight, serial):
    return dict(serial=serial, name=name, kind=kind, x=x, y=y, z=z,
                l=l, w=w, h=h, weight=weight)


# ------------------------------------------------------------------ 用例
def case_C1():
    """标准件尺寸被改成一个非原始尺寸的排列。"""
    return [mk("G1", "standard", 0, 0, 0, 60, 40, 35, 12, "C1-a")]


def case_C2():
    """两件完全重叠。"""
    return [mk("G1", "standard", 0, 0, 0, 60, 40, 30, 12, "C2-a"),
            mk("G1", "standard", 0, 0, 0, 60, 40, 30, 12, "C2-b")]


def case_C3():
    """数量与期望不符（少一件）。"""
    return ([mk("G1", "standard", 0, 0, 0, 60, 40, 30, 12, "C3-a")],
            {"G1": 2})


def case_C5():
    """标准件压在易碎件上方（易碎件违反「仅单层」）。"""
    return [mk("G3", "fragile", 0, 0, 0, 70, 50, 40, 15, "C5-frag"),
            mk("G1", "standard", 0, 0, 40, 60, 40, 30, 12, "C5-up")]


def case_C6_ratio():
    """易碎件底面只贴合 68.6%，未达 100%。"""
    return [mk("G1", "standard", 0, 0, 0, 60, 40, 30, 12, "C6-base"),
            mk("G3", "fragile", 0, 0, 30, 70, 50, 40, 15, "C6-frag")]


def case_C6_kind():
    """易碎件落在定向件顶面上（只允许车厢底面或标准件）。"""
    return [mk("G4", "oriented", 0, 0, 0, 80, 60, 50, 25, "C6-orient"),
            mk("G3", "fragile", 0, 0, 50, 70, 50, 40, 15, "C6-frag2")]


def case_C7():
    """定向件姿态被改动（尺寸是原尺寸的排列，但方向不对）。"""
    return [mk("G4", "oriented", 0, 0, 0, 60, 80, 50, 25, "C7-a")]


def case_C8():
    """压在定向件上的货物重心超出定向件投影（重心 x=90 > 80）。"""
    return [mk("G4", "oriented", 0, 0, 0, 80, 60, 50, 25, "C8-base"),
            mk("G1", "standard", 60, 0, 50, 60, 40, 30, 12, "C8-up")]


def case_C9():
    """合成用例：一件 200 kg / 0.175 m² 的重物会把下层压到 500 kg/m² 以上。

    使用单独的合成重物目录，不篡改原始G2重量。总体平均密度不能证明
    局部压力上界，本例只验证旧B1压力逻辑。
    """
    heavy = mk("G2", "standard", 0, 0, 0, 50, 35, 25, 8, "C9-base")
    top = mk("H1", "standard", 0, 0, 25, 50, 35, 25, 200, "C9-heavy")
    return [heavy, top]


def case_C10():
    """水平越界（650+60=710 > 680）。"""
    return [mk("G1", "standard", 650, 0, 0, 60, 40, 30, 12, "C10-a")]


def case_A3():
    """悬空：z=100 处无任何支撑。"""
    return [mk("G1", "standard", 0, 0, 100, 60, 40, 30, 12, "A3-a")]


def case_OK():
    """合法解：两件标准件平铺在地面，不重叠。"""
    return [mk("G1", "standard", 0, 0, 0, 60, 40, 30, 12, "OK-a"),
            mk("G1", "standard", 60, 0, 0, 60, 40, 30, 12, "OK-b")]


CASES = [
    ("C1 正交/尺寸", case_C1, "C1"),
    ("C2 不重叠", case_C2, "C2"),
    ("C3 件数守恒", case_C3, "C3"),
    ("C5 易碎件单层", case_C5, "C5"),
    ("C6 易碎件贴合率", case_C6_ratio, "C6"),
    ("C6 易碎件支撑类型", case_C6_kind, "C6"),
    ("C7 定向件姿态", case_C7, "C7"),
    ("C8 重心投影", case_C8, "C8"),
    ("C9 承压上限", case_C9, "C9"),
    ("C10 边界/高度", case_C10, "C10"),
    ("A3 不得悬空", case_A3, "A3"),
]


def main():
    print(f"{'用例':<20}{'期望':<6}{'结果':<6}命中详情")
    print("-" * 86)
    passed = failed = 0
    for label, fn, expect in CASES:
        out = fn()
        if isinstance(out, tuple):
            boxes, counts = out
        else:
            boxes, counts = out, None
        catalog = dict(CATALOG)
        if fn is case_C9:
            catalog["H1"] = dict(dims=(50, 35, 25), weight=200,
                                 kind="standard", qty=1)
        errs = check_all(boxes, SPEC, catalog, counts)
        hit = [e for e in errs if e.startswith(expect + " ")]
        ok = bool(hit)
        passed += ok
        failed += (not ok)
        detail = hit[0][:56] if hit else ("（未触发）" if not errs else errs[0][:56])
        print(f"{label:<20}{expect:<6}{'PASS' if ok else 'FAIL':<6}{detail}")

    # 反向用例：合法解必须 0 违规
    errs = check_all(case_OK(), SPEC, CATALOG)
    ok = not errs
    passed += ok
    failed += (not ok)
    print(f"{'合法解应为 0 违规':<20}{'—':<6}{'PASS' if ok else 'FAIL':<6}"
          f"{'0 条' if ok else errs[0][:56]}")

    print("-" * 86)
    print(f"合计 {passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

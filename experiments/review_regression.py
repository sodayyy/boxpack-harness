# -*- coding: utf-8 -*-
"""复查归档回归：两车型五层结果及按层启用的独立检查。

从仓库根目录运行 py -3.12 experiments/review_regression.py。
不覆写历史 baseline_v1.json；运行耗时只作记录，不当作改进证据。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import constraints as c
from src.pack_lib import TRUCKS, SUPPORT_RATIO, apply_level, expand_items, pack_ep

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path,
                        default=ROOT / "experiments/results/review_v07_protocol_regression.json")
    args = parser.parse_args()
    base = sorted(expand_items(), key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    catalog = c.load_catalog(ROOT / "data/items.csv")
    specs = c.load_trucks(ROOT / "data/trucks.csv")
    rows = []
    for ti, spec in enumerate(TRUCKS):
        for level in range(5):
            items = apply_level(base, level)
            start = time.perf_counter()
            trucks, rest = pack_ep(items, spec, max_trucks=6, level=level)
            fleet = [dict(truck_type=spec.name, boxes=tr.boxes) for tr in trucks]
            errors = c.check_fleet(fleet, specs, catalog, level=level,
                                   support_ratio=SUPPORT_RATIO,
                                   pressure_model="legacy_b1", require_complete=True)
            expected = [2, 2, 3, 3, 3] if ti == 0 else [1, 1, 2, 2, 2]
            row = dict(truck=spec.name, level=level, trucks=len(trucks), rest=len(rest),
                       cost=sum(tr.spec.cost for tr in trucks),
                       independently_checked_errors=errors,
                       regression_matches=len(trucks) == expected[level] and not rest and not errors,
                       seconds=round(time.perf_counter() - start, 3))
            rows.append(row)
            print(f"{spec.name} L{level}: {len(trucks)} 辆，未装 {len(rest)}，独立违规 {len(errors)}，回归 {row['regression_matches']}")
    result = dict(recorded_at=datetime.now().astimezone().isoformat(),
                  python=sys.version, support_ratio=SUPPORT_RATIO,
                  scope="fixed_EP_FF_layer_specific_independent_checks_not_global_optimality",
                  rows=rows, all_passed=all(r["regression_matches"] for r in rows))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved strict protocol regression: {args.json}")
    if not result["all_passed"]:
        raise SystemExit("Regression failed; inspect result file")


if __name__ == "__main__":
    main()

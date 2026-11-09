# -*- coding: utf-8 -*-
"""复查归档回归：两车型五层结果及按层启用的独立检查。

从仓库根目录运行 py -3.12 experiments/review_regression.py。
不覆写历史 baseline_v1.json；运行耗时只作记录，不当作改进证据。
"""
import itertools
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import constraints as c
from src.pack_lib import TRUCKS, SUPPORT_RATIO, apply_level, expand_items, pack_ep

OUT = Path("experiments/results/review_v04_regression.json")


def main():
    base = sorted(expand_items(), key=lambda it: -it["dims"][0] * it["dims"][1] * it["dims"][2])
    catalog = c.load_catalog("data/items.csv")
    specs = c.load_trucks("data/trucks.csv")
    rows = []
    for ti, spec in enumerate(TRUCKS):
        for level in range(5):
            items = apply_level(base, level)
            start = time.perf_counter()
            trucks, rest = pack_ep(items, spec, max_trucks=6, level=level)
            errors = []
            all_boxes = [b for tr in trucks for b in tr.boxes]
            c.check_counts(all_boxes, Counter(it["name"] for it in base), errors)
            if len({b["serial"] for b in all_boxes}) != len(all_boxes):
                errors.append("C3 duplicate serial")
            for tr in trucks:
                boxes = tr.boxes
                c.check_overlap(boxes, errors)
                c.check_bounds(boxes, specs[spec.name], errors)
                for b in boxes:
                    source = catalog[b["name"]]
                    poses = set(itertools.permutations(source["dims"]))
                    if level >= 3 and source["kind"] == "oriented":
                        poses = {source["dims"]}
                    if (b["l"], b["w"], b["h"]) not in poses:
                        errors.append("orientation violation")
                if level >= 1:
                    c.check_floating(boxes, errors)
                if level >= 2:
                    c.check_fragile_single_layer(boxes, errors)
                    c.check_fragile_support(boxes, errors)
                if level >= 3:
                    c.check_oriented_cog(boxes, errors)
                if level >= 4:
                    c.check_pressure(boxes, errors)
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
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not result["all_passed"]:
        raise SystemExit("Regression failed; inspect result file")


if __name__ == "__main__":
    main()

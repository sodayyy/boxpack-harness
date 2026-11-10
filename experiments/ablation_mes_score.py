# -*- coding: utf-8 -*-
"""Small L0 ablation for B2 state-priority rules.

This is a diagnostic, not a claim that either priority is a strong method.
All rows use the same item order, container and B2 action generator; only the
beam-state lexicographic priority changes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mes_beam import beam_pack  # noqa: E402
from experiments.exact_l0 import solve_exact  # noqa: E402
from experiments.bench_small_l0 import INSTANCES  # noqa: E402


CASES = ["toy_exact_fill_8", "b2_gap_3", "b2_gap_5"]


def run():
    selected = [x for x in INSTANCES if x["instance_id"] in CASES]
    rows = []
    for instance in selected:
        items = [dict(item, dims=tuple(item["dims"])) for item in instance["items"]]
        items.sort(key=lambda it: (-it["dims"][0] * it["dims"][1] * it["dims"][2],
                                  str(it.get("serial", ""))))
        container = tuple(instance["container"])
        exact = solve_exact(items, container, time_limit=5.0,
                            node_limit=2_000_000,
                            objective="volume_then_count")
        for priority in ("volume", "count"):
            result = beam_pack(items, container, beam_width=8, space_cap=80,
                               state_priority=priority)
            rows.append({
                "instance_id": instance["instance_id"],
                "state_priority": priority,
                "beam_width": 8,
                "space_cap": 80,
                "exact_status": exact.status,
                "exact_placed": exact.placed,
                "exact_used_volume": exact.used_volume,
                "placed": result["placed"],
                "used_volume": result["used_volume"],
                "count_gap_if_exact": (exact.placed - result["placed"]
                                       if exact.status == "optimal" else None),
                "volume_gap_if_exact": (exact.used_volume - result["used_volume"]
                                        if exact.status == "optimal" else None),
            })
    return {
        "method": "B2_state_priority_ablation",
        "scope": "small_single_container_integer_grid_L0_diagnostic",
        "common_item_order": "volume_desc_then_serial",
        "fixed_actions": "lower_front_left_MES_anchor",
        "rows": rows,
        "interpretation": (
            "Only state_priority changes. Exact gaps are reported only for "
            "optimal referee rows; this small diagnostic does not establish "
            "a general ranking of scoring rules."
        ),
    }


def main():
    output = Path(__file__).resolve().parent / "results" / "mes_score_ablation_v1.json"
    output.write_text(json.dumps(run(), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"结果写入 {output}")


if __name__ == "__main__":
    main()

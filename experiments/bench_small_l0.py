# -*- coding: utf-8 -*-
"""Compare B2 with a complete integer-grid small-instance L0 referee.

The referee is only exact when it returns ``status=optimal``. A time-limited
run reports a feasible incumbent and conservative count bound, never an
optimum.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mes_beam import beam_pack  # noqa: E402
from experiments.exact_l0 import solve_exact  # noqa: E402
from experiments.verify_mes_result import verify  # noqa: E402


def validate_layout(result, items, container):
    """Check saved coordinates independently of either search implementation."""
    errors = verify(result, container)
    catalog = {it["serial"]: it for it in items}
    for box in result["boxes"]:
        item = catalog.get(box["serial"])
        if item is None:
            errors.append(f"unknown serial: {box['serial']}")
            continue
        allowed = item.get("allowed") or [item["dims"]]
        if (box["l"], box["w"], box["h"]) not in [tuple(d) for d in allowed]:
            errors.append(f"orientation mismatch: {box['serial']}")
        if any(not isinstance(box[k], int) for k in ("x", "y", "z")):
            errors.append(f"noninteger origin: {box['serial']}")
    if result["placed"] != len(result["boxes"]):
        errors.append("placed count mismatch")
    if result["used_volume"] != sum(b["l"] * b["w"] * b["h"] for b in result["boxes"]):
        errors.append("used volume mismatch")
    if errors:
        raise ValueError("; ".join(errors))
    return errors


INSTANCES = [
    {
        "instance_id": "toy_exact_fill_8",
        "container": [4, 4, 4],
        "items": [{"serial": f"I{i}", "dims": [2, 2, 2]} for i in range(8)],
    },
    {
        "instance_id": "mixed_8",
        "container": [10, 10, 10],
        "items": [
            {"serial": "A", "dims": [5, 5, 5]},
            {"serial": "B", "dims": [5, 5, 4]},
            {"serial": "C", "dims": [5, 4, 4]},
            {"serial": "D", "dims": [4, 4, 4]},
            {"serial": "E", "dims": [4, 3, 3]},
            {"serial": "F", "dims": [3, 3, 3]},
            {"serial": "G", "dims": [3, 2, 2]},
            {"serial": "H", "dims": [2, 2, 2]},
        ],
    },
    {
        "instance_id": "tight_12",
        "container": [10, 10, 10],
        "items": [
            {"serial": f"T{i}", "dims": dims}
            for i, dims in enumerate([
                [5, 5, 4], [5, 4, 4], [4, 4, 4], [4, 4, 3],
                [4, 3, 3], [4, 3, 3], [3, 3, 3], [3, 3, 2],
                [3, 2, 2], [2, 2, 2], [2, 2, 2], [2, 2, 1],
            ])
        ],
    },
    {
        "instance_id": "b2_gap_5",
        "container": [10, 10, 10],
        "items": [
            {"serial": f"G{i}", "dims": list(dims)}
            for i, dims in enumerate([
                (2, 2, 1), (5, 4, 3), (6, 5, 4), (6, 5, 4), (2, 2, 1)
            ])
        ],
    },
    {
        "instance_id": "b2_gap_3",
        "container": [4, 4, 4],
        "items": [
            {"serial": "R0", "dims": [1, 3, 1]},
            {"serial": "R1", "dims": [4, 3, 1]},
            {"serial": "R2", "dims": [1, 4, 3]},
        ],
    },
]


def _run_one(instance, time_limit, node_limit):
    items = [dict(item, dims=tuple(item["dims"])) for item in instance["items"]]
    # B2's production calibration uses the same deterministic volume-descending
    # input order. Keep the referee and B2 on exactly this common sequence.
    items.sort(key=lambda it: (-it["dims"][0] * it["dims"][1] * it["dims"][2],
                              str(it.get("serial", ""))))
    container = tuple(instance["container"])
    exact = solve_exact(items, container, time_limit=time_limit, node_limit=node_limit,
                        objective="volume_then_count")
    b2_start = time.perf_counter()
    b2 = beam_pack(items, container, beam_width=8, space_cap=80)
    b2_seconds = time.perf_counter() - b2_start
    # The public B2 result does not expose its final MES list.  Dedicated unit
    # tests exercise the internal update invariant separately.
    b2_boxes = b2["boxes"]
    b2_volume = sum(b["l"] * b["w"] * b["h"] for b in b2_boxes)
    exact_errors = validate_layout(vars(exact), items, container)
    b2_errors = validate_layout(b2, items, container)
    return {
        "instance_id": instance["instance_id"],
        "container": list(container),
        "n_items": len(items),
        "exact": {
            "status": exact.status,
            "placed": exact.placed,
            "used_volume": exact.used_volume,
            "nodes": exact.nodes,
            "upper_bound": exact.upper_bound,
            "volume_upper_bound": exact.volume_upper_bound,
            "objective": exact.objective,
            "termination": exact.termination,
            "boxes": exact.boxes,
            "independent_validation_errors": exact_errors,
            "seconds": round(exact.seconds, 6),
        },
        "b2": {
            "beam_width": b2["beam_width"],
            "space_cap": b2["space_cap"],
            "state_priority": b2["state_priority"],
            "boxes": b2_boxes,
            "independent_validation_errors": b2_errors,
            "placed": b2["placed"],
            "used_volume": b2["used_volume"],
            "recomputed_volume": b2_volume,
            "skipped": b2["skipped"],
            "seconds": round(b2_seconds, 6),
            "internal_space_check_note": "Final MES list is not part of the public result; dedicated unit tests cover the update invariant."
        },
        "count_gap_if_exact": (exact.placed - b2["placed"]
                               if exact.status == "optimal" else None),
        "volume_gap_if_exact": (exact.used_volume - b2["used_volume"]
                                if exact.status == "optimal" else None),
        "common_item_order": "volume_desc_then_serial",
    }


def main():
    output = Path(__file__).resolve().parent / "results" / "small_l0_referee_v1.json"
    time_limit = 5.0
    node_limit = 2_000_000
    rows = [_run_one(instance, time_limit, node_limit) for instance in INSTANCES]
    payload = {
        "schema_version": 2,
        "objective": "volume_then_count",
        "method": "B2_vs_exact_L0_referee",
        "scope": "small_single_container_integer_grid_axis_aligned_geometry",
        "time_limit_seconds": time_limit,
        "node_limit": node_limit,
        "instances": rows,
        "interpretation": "Same volume-then-count objective and deterministic volume-descending item order. Optimality follows from integer-grid exhaustion or a validated full-item layout attaining both trivial global bounds. Count differences are descriptive, not separate count-optimality claims. Budget-limited rows retain valid loose count and volume upper bounds; no optimality claim.",
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        exact = row["exact"]
        print(f"{row['instance_id']}: exact={exact['status']} {exact['placed']}件, "
              f"B2={row['b2']['placed']}件, nodes={exact['nodes']}")
    print(f"结果写入 {output}")


if __name__ == "__main__":
    main()

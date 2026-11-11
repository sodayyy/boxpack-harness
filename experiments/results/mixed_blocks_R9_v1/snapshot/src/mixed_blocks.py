"""Sequential single-truck block reconstruction for a declared heterogeneous fleet.

Keeps the old equal-height pack_blocks interface and recipes unchanged. Remaining
items are reconstructed at each truck's height; this is not joint optimization.
"""
from src.block_search import pack_blocks


def pack_mixed_blocks(items, specs, capped=True, order="area", axis="yx", rotation="original"):
    if not specs:
        raise ValueError("nonempty declared fleet required")
    if len({it["serial"] for it in items}) != len(items):
        raise ValueError("duplicate item identity")
    if type(capped) is not bool or order not in ("area", "long", "volume", "height") or axis not in ("xy", "yx") or rotation not in ("original", "wide", "long"):
        raise ValueError("invalid mixed configuration")
    remaining = list(items)
    fleet, stages = [], []
    for index, spec in enumerate(specs):
        before = [it["serial"] for it in remaining]
        if remaining:
            loaded, remaining, stats = pack_blocks(remaining, [spec], capped=capped, order=order, axis=axis, rotation=rotation)
        else:
            loaded, stats = [], None
        placed = [b["serial"] for tr in loaded for b in tr["boxes"]]
        after = [it["serial"] for it in remaining]
        if len(placed) + len(after) != len(before) or set(placed).intersection(after) or set(placed + after) != set(before):
            raise AssertionError("stage identity conservation")
        fleet.extend(loaded)
        stages.append(dict(vehicle_index=index, truck_type=spec.name, input_serials=before,
                           placed_serials=placed, rest_serials=after, search=stats))
    return fleet, remaining, dict(strategy="sequential_rebuild_remaining_v1", stages=stages)

"""Restricted full-support blocks plus deterministic 2D floor placement.

This is a new constructive heuristic, not a complete packing search or a
literature-algorithm reproduction. Every block has disjoint floor footprint;
standard columns may carry a fragile cap. Final acceptance is external.
"""
from collections import defaultdict
import math

import numpy as np

from src.constrained_ep import ChainTruck
from src.pack_lib import orients


def volume(item):
    return math.prod(item["dims"])


def make_blocks(items, height, capped=True):
    """Fixed original-catalog recipes; never manufactures or duplicates items.

    G1: 60x40 standard columns, optionally topped by 50x40x70 fragile.
    G2: two 35x50 standard columns making a 70x50 platform, optionally
        topped by a 70x50x40 fragile. Paired layers have equal heights.
    G4/G5 keep their original (unrotated) orientation.
    These recipes are deliberately a subset of the original feasible domain.
    """
    if type(height) is not int or height <= 0 or type(capped) is not bool:
        raise ValueError("invalid block configuration")
    if len({it["serial"] for it in items}) != len(items):
        raise ValueError("duplicate item identity")
    expected = {"G1": ((60, 40, 30), "standard", 12),
                "G2": ((50, 35, 25), "standard", 8),
                "G3": ((70, 50, 40), "fragile", 15),
                "G4": ((80, 60, 50), "oriented", 25),
                "G5": ((40, 40, 60), "oriented", 18)}
    pools = defaultdict(list)
    for it in sorted(items, key=lambda it: it["serial"]):
        if (it["name"] not in expected or
                (tuple(it["dims"]), it["kind"], it["weight"]) != expected[it["name"]]):
            raise ValueError("recipes require the original catalog")
        pools[it["name"]].append(it)
    blocks = []

    def add(parts, l, w, h, rotate):
        for item, x, y, z, a, b, c in parts:
            if (a, b, c) not in orients(item["kind"], item["dims"], item.get("allowed")):
                raise ValueError("recipe violates item orientation")
        blocks.append({"id": len(blocks), "l": l, "w": w, "h": h,
                       "rotate": rotate, "parts": parts,
                       "volume": sum(volume(p[0]) for p in parts)})

    while pools["G1"]:
        cap = capped and bool(pools["G3"]) and height >= 100
        count = min(len(pools["G1"]), (height - (70 if cap else 0)) // 30, 9 if cap else 10)
        # At most 10 G1 boxes keeps bottom external pressure below 500 kg/m2.
        if count <= 0:
            raise ValueError("height too small for G1 recipe")
        parts = [(pools["G1"].pop(0), 0, 0, j * 30, 60, 40, 30) for j in range(count)]
        if cap:
            parts.append((pools["G3"].pop(0), 0, 0, count * 30, 50, 40, 70))
        add(parts, 60, 40, count * 30 + (70 if cap else 0), True)

    while pools["G2"]:
        cap = capped and bool(pools["G3"]) and len(pools["G2"]) >= 2 and height >= 65
        if cap:
            layers = min(len(pools["G2"]) // 2, (height - 40) // 25, 10)
            parts = [(pools["G2"].pop(0), side * 35, 0, j * 25, 35, 50, 25)
                     for j in range(layers) for side in range(2)]
            parts.append((pools["G3"].pop(0), 0, 0, layers * 25, 70, 50, 40))
            add(parts, 70, 50, layers * 25 + 40, True)
        else:
            count = min(len(pools["G2"]), height // 25, 11)
            if count <= 0:
                raise ValueError("height too small for G2 recipe")
            parts = [(pools["G2"].pop(0), 0, 0, j * 25, 50, 35, 25) for j in range(count)]
            add(parts, 50, 35, count * 25, True)

    for name, dims, limit in (("G4", (80, 60, 50), 10), ("G5", (40, 40, 60), 5)):
        l, w, h = dims
        while pools[name]:
            count = min(len(pools[name]), height // h, limit)
            if count <= 0:
                raise ValueError("height too small for oriented recipe")
            parts = [(pools[name].pop(0), 0, 0, j * h, l, w, h) for j in range(count)]
            add(parts, l, w, count * h, False)
    for item in pools["G3"]:
        if height < 70:
            raise ValueError("height too small for fragile recipe")
        add([(item, 0, 0, 0, 50, 40, 70)], 50, 40, 70, True)
    serials = [p[0]["serial"] for b in blocks for p in b["parts"]]
    if sorted(serials) != sorted(it["serial"] for it in items):
        raise AssertionError("block construction failed item conservation")
    return blocks


def pack_blocks(items, specs, capped=True, order="area", axis="yx", rotation="original"):
    """Greedy whole-block first-fit, bounded by a fixed declared fleet.

    Candidate origins are Cartesian products of existing right/top edges and
    zero, ordered by axis. No full-domain infeasibility or maximality claim.
    """
    if not specs or len({spec.dims[2] for spec in specs}) != 1:
        raise ValueError("nonempty equal-height fleet required")
    keys = {"area": lambda b: (-b["l"] * b["w"], -max(b["l"], b["w"]), b["id"]),
            "long": lambda b: (-max(b["l"], b["w"]), -b["l"] * b["w"], b["id"]),
            "volume": lambda b: (-b["volume"], -b["l"] * b["w"], b["id"]),
            "height": lambda b: (-b["h"], -b["l"] * b["w"], b["id"])}
    if order not in keys or axis not in ("xy", "yx") or rotation not in ("original", "wide", "long"):
        raise ValueError("invalid floor-search configuration")
    blocks = make_blocks(items, specs[0].dims[2] - 3, capped)
    trucks = [ChainTruck(spec, level=4, support_ratio=0.0) for spec in specs]
    floors = [np.zeros((tr.W, tr.L), dtype=np.bool_) for tr in trucks]
    edges = [({0}, {0}) for _ in trucks]
    rest, placements = [], []
    candidate_checks = 0
    for block in sorted(blocks, key=keys[order]):
        poses = [(block["l"], block["w"], False)]
        if block["rotate"] and block["l"] != block["w"]:
            poses.append((block["w"], block["l"], True))
        if rotation == "wide":
            poses.sort(key=lambda p: (-p[1], -p[0]))
        elif rotation == "long":
            poses.sort(key=lambda p: (-p[0], -p[1]))
        placed = False
        for k, tr in enumerate(trucks):
            xs, ys = edges[k]
            points = sorted(((x, y) for x in xs for y in ys),
                            key=lambda p: p if axis == "xy" else (p[1], p[0]))
            for x, y in points:
                for l, w, rotated in poses:
                    candidate_checks += 1
                    if x + l > tr.L or y + w > tr.W or floors[k][y:y+w, x:x+l].any():
                        continue
                    # Insert in original topological order. Diagonally reflecting
                    # the block swaps x/y and l/w without changing z or support.
                    for item, px, py, pz, a, b, c in block["parts"]:
                        if rotated:
                            px, py, a, b = py, px, b, a
                        tr.put(item, x + px, y + py, pz, a, b, c)
                    floors[k][y:y+w, x:x+l] = True
                    xs.add(x + l)
                    ys.add(y + w)
                    placements.append({"block_id": block["id"], "vehicle_index": k,
                                       "x": x, "y": y, "l": l, "w": w,
                                       "rotated": rotated,
                                       "serials": [p[0]["serial"] for p in block["parts"]]})
                    placed = True
                    break
                if placed:
                    break
            if placed:
                break
        if not placed:
            rest.extend(part[0] for part in block["parts"])
    fleet = [{"truck_type": tr.spec.name, "boxes": tr.boxes} for tr in trucks if tr.boxes]
    return fleet, rest, {"blocks": len(blocks), "placed_blocks": len(placements),
                         "footprint_cm2": sum(b["l"] * b["w"] for b in blocks),
                         "candidate_checks": candidate_checks, "placements": placements}

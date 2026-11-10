# -*- coding: utf-8 -*-
"""Small-instance exact L0 orthogonal packing referee.

This solver is intentionally limited to one container and rigid axis-aligned
boxes. It enumerates boundary/contact coordinates, keeps skip branches, and
returns an optimality certificate only when the complete search finishes.
It is a referee for small instances, not a replacement for the large heuristic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class SearchResult:
    status: str
    container: tuple
    placed: int
    used_volume: int
    boxes: list
    nodes: int
    upper_bound: int
    seconds: float


def _overlap(a, b):
    return (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
            a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
            a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"])


def _orientations(item):
    raw = item.get("allowed") or [tuple(item["dims"])]
    out = []
    for dims in raw:
        dims = tuple(int(v) for v in dims)
        if dims not in out:
            out.append(dims)
    return out


def _candidate_origins(boxes, dims, container):
    L, W, H = container
    l, w, h = dims
    if l > L or w > W or h > H:
        return []
    xs = {0, L - l}
    ys = {0, W - w}
    zs = {0, H - h}
    for b in boxes:
        xs.add(b["x"] + b["l"])
        ys.add(b["y"] + b["w"])
        zs.add(b["z"] + b["h"])
    return [(x, y, z) for z in sorted(zs) for y in sorted(ys) for x in sorted(xs)
            if 0 <= x <= L - l and 0 <= y <= W - w and 0 <= z <= H - h]


def _fits(box, boxes):
    return not any(_overlap(box, old) for old in boxes)


def solve_exact(items, container, time_limit=10.0, node_limit=500_000):
    """Maximize placed item count, then placed volume, for a small L0 instance."""
    start = time.perf_counter()
    ordered = list(items)
    ordered.sort(key=lambda it: (-it["dims"][0] * it["dims"][1] * it["dims"][2],
                                 str(it.get("serial", ""))))
    best = {"placed": 0, "used_volume": 0, "boxes": []}
    nodes = 0
    complete = True
    cutoff_upper_bound = len(ordered)
    memo = set()

    def better(placed, volume):
        return (placed, volume) > (best["placed"], best["used_volume"])

    def visit(i, boxes, volume):
        nonlocal nodes, complete, cutoff_upper_bound
        nodes += 1
        if nodes > node_limit or time.perf_counter() - start > time_limit:
            complete = False
            cutoff_upper_bound = max(cutoff_upper_bound, len(boxes) + (len(ordered) - i))
            return
        if i == len(ordered):
            if better(len(boxes), volume):
                best.update(placed=len(boxes), used_volume=volume,
                            boxes=[dict(b) for b in boxes])
            return
        if len(boxes) + (len(ordered) - i) < best["placed"]:
            return
        signature = (i, tuple(sorted((b["x"], b["y"], b["z"], b["l"], b["w"], b["h"])
                                     for b in boxes)))
        if signature in memo:
            return
        memo.add(signature)
        item = ordered[i]
        actions = []
        for dims in _orientations(item):
            l, w, h = dims
            for x, y, z in _candidate_origins(boxes, dims, container):
                box = dict(item, x=x, y=y, z=z, l=l, w=w, h=h)
                if _fits(box, boxes):
                    actions.append(box)
        actions.sort(key=lambda b: (b["z"], b["y"], b["x"], -b["l"] * b["w"] * b["h"]))
        seen = set()
        for box in actions:
            key = (box["x"], box["y"], box["z"], box["l"], box["w"], box["h"])
            if key in seen:
                continue
            seen.add(key)
            boxes.append(box)
            visit(i + 1, boxes, volume + box["l"] * box["w"] * box["h"])
            boxes.pop()
        # The skip branch is required when the full item set is infeasible.
        visit(i + 1, boxes, volume)

    visit(0, [], 0)
    elapsed = time.perf_counter() - start
    status = "optimal" if complete else "time_limit"
    upper_bound = best["placed"] if complete else min(len(ordered), cutoff_upper_bound)
    return SearchResult(status, tuple(container), best["placed"], best["used_volume"],
                        best["boxes"], nodes, upper_bound, elapsed)

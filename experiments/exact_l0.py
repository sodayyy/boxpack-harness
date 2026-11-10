# -*- coding: utf-8 -*-
"""Exhaustive small L0 referee on an explicitly finite integer grid.

Positive integer dimensions, one container, prescribed axis-aligned rotations,
no support, weight, fragility or load constraints. Every feasible integer
origin is considered independently of insertion order. See the project model
notes for the self-checked difference-constraint justification for integer
coordinates when all lengths are integral.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from numbers import Integral


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
    volume_upper_bound: int
    objective: str
    termination: str


def _overlap(a, b):
    return (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
            a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
            a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"])


def _positive_int_dims(raw):
    dims = tuple(raw)
    if len(dims) != 3 or any(isinstance(v, bool) or not isinstance(v, Integral)
                             or v <= 0 for v in dims):
        raise ValueError("dimensions must be three positive integers")
    return tuple(int(v) for v in dims)


def _volume(dims):
    return dims[0] * dims[1] * dims[2]


def _orientations(item):
    base = _positive_int_dims(item["dims"])
    raw = item.get("allowed")
    if raw is None:
        raw = [base]
    out = []
    for dims in raw:
        dims = _positive_int_dims(dims)
        if sorted(dims) != sorted(base):
            raise ValueError("allowed orientations must be permutations of dims")
        if dims not in out:
            out.append(dims)
    if not out:
        raise ValueError("allowed orientations cannot be empty")
    return out


def _candidate_origins(dims, container):
    L, W, H = container
    l, w, h = dims
    for z in range(H - h + 1):
        for y in range(W - w + 1):
            for x in range(L - l + 1):
                yield x, y, z


def solve_exact(items, container, time_limit=10.0, node_limit=500_000,
                objective="volume_then_count"):
    """Exhaust finite grid; certify only exhaustion or all-item upper bounds.

    The default matches B2's calibrated final objective. The alternative is
    ``count_then_volume``. On a budget limit, bounds are conservative global
    bounds, not estimates based on only the currently visited branch.
    """
    start = time.perf_counter()
    container = _positive_int_dims(container)
    if time_limit <= 0 or not isinstance(node_limit, Integral) or node_limit < 1:
        raise ValueError("time_limit and node_limit must be positive")
    if objective not in {"volume_then_count", "count_then_volume"}:
        raise ValueError("unknown lexicographic objective")
    ordered = list(items)
    ordered.sort(key=lambda it: (-_volume(_positive_int_dims(it["dims"])),
                                 str(it.get("serial", ""))))
    rotations = [_orientations(it) for it in ordered]
    serials = [it["serial"] for it in ordered]
    if len(set(serials)) != len(serials):
        raise ValueError("item serials must be unique")
    volumes = [_volume(it["dims"]) for it in ordered]
    suffix_volume = [0] * (len(ordered) + 1)
    for i in range(len(ordered) - 1, -1, -1):
        suffix_volume[i] = suffix_volume[i + 1] + volumes[i]
    capacity = _volume(container)
    total_volume = suffix_volume[0]
    best = {"placed": 0, "used_volume": 0, "boxes": []}
    nodes = 0
    memo = set()

    class StopSearch(Exception):
        pass

    def key(count, volume):
        return ((volume, count) if objective == "volume_then_count"
                else (count, volume))

    def check_budget():
        if time.perf_counter() - start >= time_limit:
            raise StopSearch("time_limit")

    def visit(i, boxes, volume):
        nonlocal nodes
        check_budget()
        if nodes >= node_limit:
            raise StopSearch("node_limit")
        nodes += 1
        if key(len(boxes), volume) > key(best["placed"], best["used_volume"]):
            best.update(placed=len(boxes), used_volume=volume,
                        boxes=[dict(b) for b in boxes])
        if len(boxes) == len(ordered):
            # A feasible full-item layout attains BOTH trivial global bounds.
            raise StopSearch("all_items_upper_bound_attained")
        if i == len(ordered):
            return
        optimistic = key(len(boxes) + len(ordered) - i,
                         min(capacity, volume + suffix_volume[i]))
        if optimistic <= key(best["placed"], best["used_volume"]):
            return
        signature = (i, tuple(sorted((b["x"], b["y"], b["z"], b["l"], b["w"], b["h"])
                                     for b in boxes)))
        if signature in memo:
            return
        memo.add(signature)
        item = ordered[i]
        for dims in rotations[i]:
            for x, y, z in _candidate_origins(dims, container):
                check_budget()
                box = dict(item, x=x, y=y, z=z, l=dims[0], w=dims[1], h=dims[2])
                if any(_overlap(box, old) for old in boxes):
                    continue
                boxes.append(box)
                visit(i + 1, boxes, volume + volumes[i])
                boxes.pop()
        visit(i + 1, boxes, volume)  # Required subset-selection branch.

    termination = "exhausted_integer_grid"
    try:
        visit(0, [], 0)
    except StopSearch as stop:
        termination = str(stop)
    optimal = termination in {"exhausted_integer_grid", "all_items_upper_bound_attained"}
    count_bound = (best["placed"] if optimal and objective == "count_then_volume"
                   else len(ordered))
    volume_bound = (best["used_volume"] if optimal and objective == "volume_then_count"
                    else min(capacity, total_volume))
    return SearchResult(
        "optimal" if optimal else "time_limit", container, best["placed"],
        best["used_volume"], best["boxes"], nodes, count_bound,
        time.perf_counter() - start, volume_bound, objective, termination,
    )

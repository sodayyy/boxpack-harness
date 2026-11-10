"""Maximal-empty-space (MES) beam search for L0 geometric packing.

This module intentionally implements only the single-container, axis-aligned
geometry layer. It is a B2 research component, not a full reproduction of any
paper and not a solver for the project's fragile/support/load-bearing rules.

State invariant: every stored placement is inside the container and disjoint
from the other placements. Empty spaces are candidate regions, not a proof of
maximality; placement is always checked against all stored boxes.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Space:
    x: int
    y: int
    z: int
    l: int
    w: int
    h: int


@dataclass
class BeamState:
    boxes: list
    spaces: list
    placed: int = 0
    skipped: int = 0
    used_volume: int = 0

    def copy(self):
        return BeamState(list(self.boxes), list(self.spaces), self.placed,
                         self.skipped, self.used_volume)


def _overlap(a, b):
    return (a["x"] < b["x"] + b["l"] and b["x"] < a["x"] + a["l"] and
            a["y"] < b["y"] + b["w"] and b["y"] < a["y"] + a["w"] and
            a["z"] < b["z"] + b["h"] and b["z"] < a["z"] + a["h"])


def _space_overlap(s, b):
    return (s.x < b["x"] + b["l"] and b["x"] < s.x + s.l and
            s.y < b["y"] + b["w"] and b["y"] < s.y + s.w and
            s.z < b["z"] + b["h"] and b["z"] < s.z + s.h)


def _valid_space(s):
    return s.l > 0 and s.w > 0 and s.h > 0


def _contains(a, b):
    return (a.x <= b.x and a.y <= b.y and a.z <= b.z and
            a.x + a.l >= b.x + b.l and a.y + a.w >= b.y + b.w and
            a.z + a.h >= b.z + b.h)


def _prune_spaces(spaces):
    unique = {(s.x, s.y, s.z, s.l, s.w, s.h): s for s in spaces if _valid_space(s)}
    values = list(unique.values())
    return [s for i, s in enumerate(values)
            if not any(i != j and _contains(t, s) for j, t in enumerate(values))]


def _subtract_space(s, b):
    """Subtract an axis-aligned box from one space into disjoint slabs."""
    if not _space_overlap(s, b):
        return [s]
    sx0, sy0, sz0 = s.x, s.y, s.z
    sx1, sy1, sz1 = s.x + s.l, s.y + s.w, s.z + s.h
    bx0, by0, bz0 = max(sx0, b["x"]), max(sy0, b["y"]), max(sz0, b["z"])
    bx1 = min(sx1, b["x"] + b["l"])
    by1 = min(sy1, b["y"] + b["w"])
    bz1 = min(sz1, b["z"] + b["h"])
    out = [
        Space(sx0, sy0, sz0, bx0 - sx0, s.w, s.h),
        Space(bx1, sy0, sz0, sx1 - bx1, s.w, s.h),
        Space(bx0, sy0, sz0, bx1 - bx0, by0 - sy0, s.h),
        Space(bx0, by1, sz0, bx1 - bx0, sy1 - by1, s.h),
        Space(bx0, by0, sz0, bx1 - bx0, by1 - by0, bz0 - sz0),
        Space(bx0, by0, bz1, bx1 - bx0, by1 - by0, sz1 - bz1),
    ]
    return [s for s in out if _valid_space(s)]


def _remaining_spaces(spaces, box):
    out = []
    for space in spaces:
        out.extend(_subtract_space(space, box))
    return _prune_spaces(out)


def _fits_at(state, space, dims, container):
    l, w, h = dims
    if l > space.l or w > space.w or h > space.h:
        return False
    box = {"x": space.x, "y": space.y, "z": space.z,
           "l": l, "w": w, "h": h}
    return not any(_overlap(box, old) for old in state.boxes)


def _state_key(state):
    # Volume is the primary objective; item count can favor many tiny pieces
    # over one large piece and therefore must not be the first key.
    return (state.used_volume, state.placed, -state.skipped, -len(state.spaces))


def _candidate_origins(space, dims):
    """Return the deterministic lower-front-left MES anchor.

    The first B2 revision used all eight corners. On the calibration set that
    increased branching without improving the score and made the beam lose
    useful layouts. The lower-front-left anchor keeps the component bounded and
    comparable to the EP insertion order; richer corner actions belong to a
    later ablation rather than silently changing the baseline.
    """
    l, w, h = dims
    if l <= space.l and w <= space.w and h <= space.h:
        return {(space.x, space.y, space.z)}
    return set()


def _candidate_states(state, item, container, space_cap):
    orientations = item.get("allowed") or [tuple(item["dims"])]
    seen = set()
    spaces = sorted(state.spaces, key=lambda s: (-s.l * s.w * s.h, s.z, s.y, s.x))
    for space in spaces[:space_cap]:
        for dims in orientations:
            dims = tuple(dims)
            for x, y, z in _candidate_origins(space, dims):
                key = (x, y, z, dims)
                if key in seen:
                    continue
                box = {"x": x, "y": y, "z": z,
                       "l": dims[0], "w": dims[1], "h": dims[2]}
                if not _fits_at(state, space, dims, container):
                    continue
                if any(_overlap(box, old) for old in state.boxes):
                    continue
                seen.add(key)
                child = state.copy()
                child.boxes.append(dict(item, **box))
                child.spaces = _remaining_spaces(state.spaces, box)
                child.placed += 1
                child.used_volume += dims[0] * dims[1] * dims[2]
                yield child


def beam_pack(items, container, beam_width=8, space_cap=80):
    """Pack one container at L0 using bounded beam search.

    Parameters
    ----------
    items: iterable of item dictionaries with ``dims`` and optional ``allowed``.
    container: ``(L, W, H)``; the height is already the effective height.
    beam_width: number of partial layouts retained after each item.
    space_cap: maximum candidate spaces considered per partial layout.

    Returns a dictionary with the best layout and explicit search parameters.
    It is a bounded heuristic result; no optimality claim is made.
    """
    if beam_width < 1 or space_cap < 1:
        raise ValueError("beam_width and space_cap must be positive")
    L, W, H = container
    initial = BeamState([], [Space(0, 0, 0, L, W, H)])
    beam = [initial]
    for item in items:
        children = []
        for state in beam:
            children.extend(_candidate_states(state, item, container, space_cap))
            skipped = state.copy()
            skipped.skipped += 1
            children.append(skipped)
        # Deduplicate by the placed box coordinates/dimensions and retain the
        # strongest state. This keeps repeated-item branches manageable.
        unique = {}
        for state in children:
            signature = tuple((b["serial"], b["x"], b["y"], b["z"],
                               b["l"], b["w"], b["h"]) for b in state.boxes)
            old = unique.get(signature)
            if old is None or _state_key(state) > _state_key(old):
                unique[signature] = state
        beam = sorted(unique.values(), key=_state_key, reverse=True)[:beam_width]
    best = max(beam, key=_state_key)
    return dict(boxes=best.boxes, placed=best.placed, skipped=best.skipped,
                used_volume=best.used_volume, remaining_spaces=len(best.spaces),
                beam_width=beam_width, space_cap=space_cap,
                container=container, status="bounded_heuristic_not_optimal")

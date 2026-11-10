"""Versioned EP construction with full contact checks and chain_area_v1.

The legacy Truck remains unchanged. This search implementation calculates its
own contact graph and vertical load transfers; independent acceptance uses
src.constraints, never this module. No moment-equilibrium claim is made.
"""
import math

from src.pack_lib import Truck, _ep_one, orients


def area_xy(a, b):
    return max(0, min(a["x"] + a["l"], b["x"] + b["l"]) - max(a["x"], b["x"])) * max(
        0, min(a["y"] + a["w"], b["y"] + b["w"]) - max(a["y"], b["y"]))


def rests(upper, lower):
    return upper["z"] == lower["z"] + lower["h"] and area_xy(upper, lower) > 0


def vertical_load_state(boxes, max_pressure=500.0):
    """Solver-side fixed-area vertical model; no independent validator calls."""
    loads = [float(b["weight"]) for b in boxes]
    supports = [[] for _ in boxes]
    for i, upper in enumerate(boxes):
        if upper["z"] > 0:
            supports[i] = [(j, area_xy(upper, lower)) for j, lower in enumerate(boxes)
                           if i != j and rests(upper, lower)]
            if not supports[i]:
                return None
    reactions = 0.0
    for i in sorted(range(len(boxes)), key=lambda i: boxes[i]["z"], reverse=True):
        b = boxes[i]
        external = loads[i] - b["weight"]
        if external / (b["l"] * b["w"] * 1e-4) > max_pressure + 1e-6:
            return None
        if b["kind"] == "fragile" and external > 1e-9:
            return None
        if b["z"] == 0:
            reactions += loads[i]
        else:
            total_area = sum(area for _, area in supports[i])
            for j, area in supports[i]:
                loads[j] += loads[i] * area / total_area
    weight = sum(b["weight"] for b in boxes)
    if abs(reactions - weight) > 1e-7 * max(1, weight):
        return None
    return {"total_load_kg": loads, "floor_reaction_kg": reactions,
            "residual_kg": reactions - weight}


class ChainTruck(Truck):
    """Integer-grid EP truck with versioned chain pressure and bidirectional contacts."""
    def __init__(self, spec, level=4, clearance=None, support_ratio=0.0):
        if type(level) is not int or level not in range(5):
            raise ValueError("invalid constraint level")
        if (isinstance(support_ratio, bool) or not isinstance(support_ratio, (int, float))
                or not math.isfinite(support_ratio) or not 0 <= support_ratio <= 1):
            raise ValueError("invalid support ratio")
        super().__init__(spec, clearance=clearance, level=level)
        self.support_ratio = support_ratio
        self.pressure_model = "chain_area_v1"

    def feasible(self, x, y, z, l, w, h, kind, weight):
        # Preserve old geometric fast path, but never use legacy pressure here.
        level = self.level
        try:
            self.level = 0
            if not super().feasible(x, y, z, l, w, h, kind, weight):
                return False
        finally:
            self.level = level
        candidate = dict(x=x, y=y, z=z, l=l, w=w, h=h, kind=kind, weight=weight)
        below = [b for b in self.boxes if rests(candidate, b)]
        if level >= 1 and z > 0 and not below:
            return False
        if level >= 2:
            if z > 0:
                supported = sum(area_xy(candidate, b) for b in below)
                need = 1.0 if kind == "fragile" else self.support_ratio
                if supported + 1e-9 < need * l * w:
                    return False
                if any(b["kind"] == "fragile" or (kind == "fragile" and b["kind"] != "standard")
                       for b in below):
                    return False
            # Inserting a box below a previously placed overhang creates NEW
            # contact edges. Checking only the new box's bottom misses these.
            for upper in self.boxes:
                if not rests(upper, candidate):
                    continue
                if kind == "fragile" or (upper["kind"] == "fragile" and kind != "standard"):
                    return False
                if level >= 3 and kind == "oriented":
                    cx, cy = upper["x"] + upper["l"] / 2, upper["y"] + upper["w"] / 2
                    if not (x <= cx <= x + l and y <= cy <= y + w):
                        return False
        if level >= 3:
            cx, cy = x + l / 2, y + w / 2
            if any(b["kind"] == "oriented" and not
                   (b["x"] <= cx <= b["x"] + b["l"] and b["y"] <= cy <= b["y"] + b["w"])
                   for b in below):
                return False
        if level >= 4 and vertical_load_state(self.boxes + [candidate]) is None:
            return False
        return True

    def put(self, meta, x, y, z, l, w, h):
        # Public placement refuses invalid mutations; the base Truck assumes its
        # caller already checked. Rechecking here also protects direct callers.
        if ((l, w, h) not in orients(meta["kind"], meta["dims"], meta.get("allowed"))
                or any(b["serial"] == meta["serial"] for b in self.boxes)):
            raise ValueError("invalid orientation or duplicate identity")
        if not self.feasible(x, y, z, l, w, h, meta["kind"], meta["weight"]):
            raise ValueError("placement rejected by versioned constraints")
        super().put(meta, x, y, z, l, w, h)


def pack_fixed_fleet(items, specs, level=4, ep_cap=1500, support_ratio=0.0):
    """First-fit in a FIXED finite fleet; never opens an undeclared vehicle.

    Returns serializable nonempty vehicles and all unplaced original items.
    Failure is only a heuristic result, not a feasibility certificate.
    """
    trucks = [ChainTruck(spec, level=level, support_ratio=support_ratio) for spec in specs]
    rest = []
    for item in items:
        if not any(_ep_one(truck, item, ep_cap) for truck in trucks):
            rest.append(item)
    return [{"truck_type": truck.spec.name, "boxes": truck.boxes}
            for truck in trucks if truck.boxes], rest

"""Exact parameter thresholds for already-verified full layouts, not a solver.

No imports from the packing solver. Thresholds describe fixed-layout regions;
absence of a saved witness NEVER proves original-instance infeasibility.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json


def fraction(value):
    if isinstance(value, bool):
        raise ValueError("boolean parameter rejected")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError("finite rational parameter required") from exc


def overlap(a, b):
    return max(0, min(a["x"] + a["l"], b["x"] + b["l"]) - max(a["x"], b["x"])) * max(
        0, min(a["y"] + a["w"], b["y"] + b["w"]) - max(a["y"], b["y"]))


def canonical_digest(fleet):
    """Identity/pose preserving; invariant only to box/identical-truck order."""
    vehicles = [dict(truck_type=tr["truck_type"], boxes=sorted(tr["boxes"], key=lambda b: b["serial"]))
                for tr in fleet]
    vehicles.sort(key=lambda tr: json.dumps(tr, sort_keys=True, ensure_ascii=True))
    return hashlib.sha256(json.dumps(vehicles, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def exact_thresholds(fleet, trucks, catalog):
    """Recheck every nonparametric rule using integer geometry and exact loads.

    Assumes actual input in integral centimeters/kg; validates metadata,
    original poses, complete identities, overlap, support types/fragile caps,
    C8, and exact force conservation. Rejects any non-parametric violation.
    """
    if not isinstance(fleet, list) or not fleet:
        raise ValueError("nonempty fleet required")
    expected = {f"{name}-{i:03d}": name for name, spec in catalog.items() for i in range(spec["qty"])}
    boxes_all = [b for tr in fleet for b in tr["boxes"]]
    if Counter(b["serial"] for b in boxes_all) != Counter(expected.keys()):
        raise ValueError("full identity conservation failed")
    alpha_max = Fraction(1)
    pressure_min = Fraction(0)
    clearance_max = None
    height_by_vehicle, reactions, critical = [], [], []
    for index, tr in enumerate(fleet):
        spec = trucks[tr["truck_type"]]
        boxes = tr["boxes"]
        if not boxes:
            raise ValueError("empty vehicle")
        if sum(b["weight"] for b in boxes) > spec["cap_weight"]:
            raise ValueError("weight capacity exceeded")
        high = max(b["z"] + b["h"] for b in boxes)
        slack = Fraction(spec["dims"][2] - high)
        if slack < 0:
            raise ValueError("box exceeds nominal height")
        clearance_max = slack if clearance_max is None else min(clearance_max, slack)
        height_by_vehicle.append(dict(vehicle_index=index, highest_cm=high, clearance_max=str(slack)))
        for b in boxes:
            if any(type(b[k]) is not int for k in ("x", "y", "z", "l", "w", "h", "weight")):
                raise ValueError("integral geometry and kg required")
            if (min(b["x"], b["y"], b["z"]) < 0 or min(b["l"], b["w"], b["h"]) <= 0 or
                    b["x"] + b["l"] > spec["dims"][0] or b["y"] + b["w"] > spec["dims"][1]):
                raise ValueError("invalid geometry/boundary")
            if expected[b["serial"]] != b["name"]:
                raise ValueError("serial/type mismatch")
            item = catalog[b["name"]]
            pose = (b["l"], b["w"], b["h"])
            if (b["kind"] != item["kind"] or b["weight"] != item["weight"] or
                    pose not in ([tuple(item["dims"])] if item["kind"] == "oriented" else itertools.permutations(item["dims"]))):
                raise ValueError("catalog/orientation mismatch")
        for i, a in enumerate(boxes):
            for b in boxes[:i]:
                if overlap(a, b) > 0 and max(a["z"], b["z"]) < min(a["z"] + a["h"], b["z"] + b["h"]):
                    raise ValueError("3D overlap")
        loads = [Fraction(b["weight"]) for b in boxes]
        ground = Fraction(0)
        for i in sorted(range(len(boxes)), key=lambda i: boxes[i]["z"], reverse=True):
            b = boxes[i]
            p = (loads[i] - b["weight"]) * Fraction(10000, b["l"] * b["w"])
            if p > pressure_min:
                pressure_min, critical = p, [b["serial"]]
            elif p == pressure_min:
                critical.append(b["serial"])
            if b["kind"] == "fragile" and loads[i] != b["weight"]:
                raise ValueError("fragile receives external load")
            if b["z"] == 0:
                ground += loads[i]
                continue
            contacts = [(j, overlap(b, base)) for j, base in enumerate(boxes)
                        if base["z"] + base["h"] == b["z"] and overlap(b, base) > 0]
            area = sum(a for _, a in contacts)
            if not area:
                raise ValueError("floating box")
            ratio = Fraction(area, b["l"] * b["w"])
            if b["kind"] == "fragile":
                if ratio != 1:
                    raise ValueError("fragile incomplete support")
            else:
                alpha_max = min(alpha_max, ratio)
            for j, a in contacts:
                base = boxes[j]
                if base["kind"] == "fragile" or (b["kind"] == "fragile" and base["kind"] != "standard"):
                    raise ValueError("invalid support type")
                if base["kind"] == "oriented" and not (
                        2 * base["x"] <= 2 * b["x"] + b["l"] <= 2 * (base["x"] + base["l"]) and
                        2 * base["y"] <= 2 * b["y"] + b["w"] <= 2 * (base["y"] + base["w"])):
                    raise ValueError("oriented support center failure")
                loads[j] += loads[i] * Fraction(a, area)
        if ground != sum(b["weight"] for b in boxes):
            raise ValueError("exact vertical force conservation failure")
        reactions.append(str(ground))
    return dict(alpha_max=str(alpha_max), pressure_min=str(pressure_min), clearance_max=str(clearance_max),
                critical_pressure_serials=sorted(critical), floor_reactions_kg=reactions,
                height_by_vehicle=height_by_vehicle, vehicles=len(fleet),
                cost=sum(trucks[tr["truck_type"]]["cost"] for tr in fleet), items=len(boxes_all))


def accepts(threshold, alpha, pressure, clearance):
    alpha, pressure, clearance = map(fraction, (alpha, pressure, clearance))
    if not 0 <= alpha <= 1 or pressure < 0 or clearance < 0:
        raise ValueError("parameter outside physical domain")
    return (alpha <= Fraction(threshold["alpha_max"]) and
            pressure >= Fraction(threshold["pressure_min"]) and
            clearance <= Fraction(threshold["clearance_max"]))


def check_parameter_fleet(fleet, trucks, catalog, alpha, pressure, clearance):
    """Original independent L0-L3 checker + parametrized L4 chain checker.

    No global mutation, error filtering or solver-side code. H'=H+3-delta
    exactly compensates the legacy fixed 3cm clearance in check_bounds.
    """
    from src.constraints import check_fleet, audit_load_chain
    alpha, pressure, clearance = map(fraction, (alpha, pressure, clearance))
    if not 0 <= alpha <= 1 or pressure < 0 or clearance < 0:
        raise ValueError("parameter outside physical domain")
    modified = {name: dict(spec, dims=(*spec["dims"][:2], float(spec["dims"][2] + 3 - clearance)))
                for name, spec in trucks.items()}
    errors = check_fleet(fleet, modified, catalog, level=3, support_ratio=float(alpha),
                         pressure_model="chain_area_v1", require_complete=True)
    if errors:
        return errors
    for tr in fleet:
        errors.extend(audit_load_chain(tr["boxes"], max_pressure=float(pressure))["errors"])
    return errors


def boundary_cases(threshold):
    p, d = Fraction(threshold["pressure_min"]), Fraction(threshold["clearance_max"])
    return [dict(name="p_below", alpha="1", pressure=str(max(0, p - Fraction(1, 1000))), clearance=str(d)),
            dict(name="p_equal", alpha="1", pressure=str(p), clearance=str(d)),
            dict(name="p_above", alpha="1", pressure=str(p + Fraction(1, 1000)), clearance=str(d)),
            dict(name="clearance_above", alpha="1", pressure=str(p), clearance=str(d + 1))]

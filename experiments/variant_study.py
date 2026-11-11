"""R8 derived quantity catalogs and capacity-only bounds; not a packing solver."""
from fractions import Fraction
import itertools
import math

BASE_QUANTITIES = (80, 100, 30, 40, 50)
FLEETS = ((1, 0), (2, 0), (3, 0), (4, 0), (0, 1), (0, 2))
ORDERS = ("area", "long", "volume", "height")


def cases():
    out = [dict(id="base", family="base", factor="1", quantities=list(BASE_QUANTITIES))]
    for factor in ("1/2", "3/2", "2"):
        counts = [Fraction(factor) * n for n in BASE_QUANTITIES]
        if any(q.denominator != 1 for q in counts):
            raise ValueError("quantity scaling must be integral")
        out.append(dict(id="scale_" + factor.replace("/", "_"), family="scale", factor=factor,
                        quantities=[int(q) for q in counts]))
    for count in (0, 15, 45, 60):
        out.append(dict(id=f"fragile_{count}", family="fragile", factor=str(Fraction(count, 30)),
                        quantities=[80, 100, count, 40, 50]))
    for factor in ("0", "1/2", "3/2", "2"):
        out.append(dict(id="oriented_" + factor.replace("/", "_"), family="oriented", factor=factor,
                        quantities=[80, 100, 30, int(Fraction(factor) * 40), int(Fraction(factor) * 50)]))
    return out


def derived_catalog(base, counts):
    if len(base) != 5 or len(counts) != 5 or any(type(q) is not int or q < 0 for q in counts) or not sum(counts):
        raise ValueError("five nonnegative integral quantities and nonempty shipment required")
    return {name: dict(spec, qty=q) for (name, spec), q in zip(base.items(), counts)}


def expand_catalog(catalog):
    return [dict(name=name, kind=s["kind"], dims=tuple(s["dims"]), weight=s["weight"],
                 serial=f"{name}-{i:03d}") for name, s in catalog.items() for i in range(s["qty"])]


def totals(catalog):
    count = sum(s["qty"] for s in catalog.values())
    return dict(items=count, volume_cm3=sum(math.prod(s["dims"]) * s["qty"] for s in catalog.values()),
                weight_kg=sum(s["weight"] * s["qty"] for s in catalog.values()),
                fragile_count=sum(s["qty"] for s in catalog.values() if s["kind"] == "fragile"),
                oriented_count=sum(s["qty"] for s in catalog.values() if s["kind"] == "oriented"))


def planned_runs():
    return [dict(case=c["id"], combination=list(combo), capped=True, order=order, axis="yx", rotation="original")
            for c, combo, order in itertools.product(cases(), FLEETS, ORDERS)]


def capacity_bounds(catalog, trucks):
    """All vehicle types including mixed fleets; volume+weight is a relaxation."""
    t = totals(catalog)
    specs = list(trucks.values())
    capacities = [math.prod(s["dims"][:2]) * (s["dims"][2] - 3) for s in specs]
    if any(v <= 0 for v in capacities) or any(s["cap_weight"] <= 0 or s["cost"] <= 0 for s in specs):
        raise ValueError("positive capacities/costs required")
    ceildiv = lambda a, b: (a + b - 1) // b
    # A homogeneous fleet is always feasible in this relaxation, not geometry.
    limits = [max(ceildiv(t["volume_cm3"], v), ceildiv(t["weight_kg"], s["cap_weight"]))
              for v, s in zip(capacities, specs)]
    count_limit = min(limits)
    cost_limit = min(n * s["cost"] for n, s in zip(limits, specs))
    # Any improving P1 has <=count_limit vehicles; any improving P2 costs
    # <=cost_limit and hence has <=cost_limit/min_cost vehicles.
    max_count = max(count_limit, cost_limit // min(s["cost"] for s in specs))
    feasible = []
    for quantities in itertools.product(range(max_count + 1), repeat=len(specs)):
        if sum(quantities) > max_count:
            continue
        volume = sum(q * v for q, v in zip(quantities, capacities))
        weight = sum(q * s["cap_weight"] for q, s in zip(quantities, specs))
        if volume >= t["volume_cm3"] and weight >= t["weight_kg"]:
            feasible.append(dict(combination=list(quantities), vehicles=sum(quantities),
                                 cost=sum(q * s["cost"] for q, s in zip(quantities, specs))))
    return dict(P1=min(r["vehicles"] for r in feasible), P2=min(r["cost"] for r in feasible),
                scope="all_types_including_mixed_volume_weight_relaxation", enumeration_count_limit=max_count)


def summarize(records, catalog, trucks):
    valid = [r for r in records if r["complete"] and not r["errors"]]
    bounds = capacity_bounds(catalog, trucks)
    result = dict(totals=totals(catalog), capacity_lower_bounds=bounds, complete_runs=len(valid),
                  P1=None, P2=None, status="no_complete_witness_not_infeasible")
    if not valid:
        return result
    for goal, first, second in (("P1", "vehicles", "cost"), ("P2", "cost", "vehicles")):
        row = min(valid, key=lambda r: (r[first], r[second], r["label"]))
        result[goal] = dict(lower_bound=bounds[goal], upper_bound=row[first], witness=row["label"],
                            proven_optimal=bounds[goal] == row[first])
    result["status"] = "both_objectives_proven" if all(result[k]["proven_optimal"] for k in ("P1", "P2")) else "verified_bounds_gap_remaining"
    return result

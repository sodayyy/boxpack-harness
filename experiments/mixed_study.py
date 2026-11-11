"""Frozen R9 matrix and separate objective merging; no solver import."""
import itertools
from experiments.variant_study import cases, capacity_bounds, totals

CASE_IDS = ("scale_3_2", "scale_2", "fragile_45", "fragile_60", "oriented_3_2", "oriented_2")


def selected_cases():
    lookup = {c["id"]: c for c in cases()}
    return [lookup[k] for k in CASE_IDS]


def planned_runs():
    return [dict(case=c, vehicle_order=list(v), capped=True, order=o, axis=a, rotation=r)
            for c, v, o, a, r in itertools.product(CASE_IDS, ((0, 1), (1, 0)),
                ("area", "long", "volume", "height"), ("xy", "yx"), ("original", "wide", "long"))]


def merged_summary(records, source_records, catalogs, trucks):
    result = {}
    for name, cat in catalogs.items():
        valid = [dict(r, source="R8") for r in source_records if r["config"]["case"] == name and r["complete"] and not r["errors"]]
        valid += [dict(r, source="R9") for r in records if r["config"]["case"] == name and r["complete"] and not r["errors"]]
        lower = capacity_bounds(cat, trucks)
        s = dict(totals=totals(cat), capacity_lower_bounds=lower,
                 r9_complete_runs=sum(r["complete"] and not r["errors"] for r in records if r["config"]["case"] == name))
        for goal, first, second in (("P1", "vehicles", "cost"), ("P2", "cost", "vehicles")):
            row = min(valid, key=lambda r: (r[first], r[second], r["source"], r["label"]))
            s[goal] = dict(lower_bound=lower[goal], upper_bound=row[first], witness=row["label"],
                           source=row["source"], proven_optimal=lower[goal] == row[first])
        result[name] = s
    return result

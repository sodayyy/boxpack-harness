"""Tiny finite-integer-grid single-truck exact reference for L0--L4.

Searches every allowed integer origin/orientation and every item subset. Only
geometry and weight prune partial states. Support/contact/load constraints are
evaluated on each candidate final layout; an unsupported partial state must
remain searchable because a later item can supply its missing support.
Constraint acceptance reuses the project's independent CSV-based checker;
this is an independent search reference, not a second physics implementation.
"""
import itertools
import math
from numbers import Integral
import time
from src.constraints import check_all


def solve(items, spec, catalog, level=4, support_ratio=0.0, time_limit=10, node_limit=1000000):
    if type(level) is not int or level not in range(5) or time_limit <= 0 or node_limit <= 0:
        raise ValueError("invalid search settings")
    container = (*spec["dims"][:2], spec["dims"][2]-3)
    if any(isinstance(v,bool) or not isinstance(v,Integral) or v <= 0 for v in container):
        raise ValueError("requires positive integer effective dimensions")
    serials = [it["serial"] for it in items]
    if len(set(serials)) != len(serials):
        raise ValueError("duplicate identities")
    if any(any(isinstance(v,bool) or not isinstance(v,Integral) or v <= 0 for v in it["dims"]) for it in items):
        raise ValueError("requires positive integer item dimensions")
    ordered = sorted(items, key=lambda it:(-math.prod(it["dims"]),it["serial"]))
    rotations = []
    for it in ordered:
        if level >= 3 and it["kind"] == "oriented":
            rotations.append([tuple(it["dims"])])
        else:
            rotations.append(sorted(set(itertools.permutations(it["dims"]))))
    suffix = [0]*(len(ordered)+1)
    for i in range(len(ordered)-1,-1,-1):
        suffix[i] = suffix[i+1]+math.prod(ordered[i]["dims"])
    start = time.perf_counter()
    best, best_key, nodes = [], (0,0), 0
    capacity = math.prod(container)

    class Stop(Exception):
        pass

    def overlap(a,b):
        return all(a[p] < b[p]+b[d] and b[p] < a[p]+a[d] for p,d in zip("xyz",("l","w","h")))

    def visit(index,boxes,volume,weight):
        nonlocal best,best_key,nodes
        if time.perf_counter()-start >= time_limit:
            raise Stop("time_limit")
        if nodes >= node_limit:
            raise Stop("node_limit")
        nodes += 1
        key = (volume,len(boxes))
        if key > best_key and not check_all(boxes,spec,catalog,level=level,strict_ids=True,
                                           support_ratio=support_ratio,pressure_model="chain_area_v1"):
            best,best_key = [dict(b) for b in boxes],key
            if len(best)==len(ordered):
                raise Stop("all_items_upper_bound_attained")
        if index==len(ordered) or (min(capacity,volume+suffix[index]),len(boxes)+len(ordered)-index) <= best_key:
            return
        item = ordered[index]
        if weight+item["weight"] <= spec["cap_weight"]:
            for l,w,h in rotations[index]:
                for z in range(container[2]-h+1):
                    for y in range(container[1]-w+1):
                        for x in range(container[0]-l+1):
                            if time.perf_counter()-start >= time_limit:
                                raise Stop("time_limit")
                            box = dict(name=item["name"],serial=item["serial"],kind=item["kind"],weight=item["weight"],
                                       x=x,y=y,z=z,l=l,w=w,h=h)
                            if not any(overlap(box,old) for old in boxes):
                                visit(index+1,boxes+[box],volume+l*w*h,weight+item["weight"])
        visit(index+1,boxes,volume,weight)

    termination = "exhausted_integer_grid"
    try:
        visit(0,[],0,0)
    except Stop as exc:
        termination = str(exc)
    optimal = termination in ("exhausted_integer_grid","all_items_upper_bound_attained")
    return dict(status="optimal" if optimal else termination,termination=termination,
                objective="volume_then_count",level=level,pressure_model="chain_area_v1",
                used_volume=best_key[0],placed=best_key[1],boxes=best,nodes=nodes,
                volume_upper_bound=best_key[0] if optimal else min(capacity,suffix[0]),
                seconds=time.perf_counter()-start,
                limitation="single_container_finite_integer_grid_only; acceptance_reuses_constraints_checker")

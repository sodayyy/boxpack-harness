"""Reverify all chain baseline bundles and compute conservative result bounds."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_constrained_fleet import verify_bundle
from src.constraints import load_catalog, load_trucks


def build_summary():
    results = ROOT / "experiments/results"
    names = [f"chain_single_L{i}_v1" for i in range(5)] + ["chain_mixed_L4_v1"]
    checks = {name:verify_bundle(results/name) for name in names}
    if not all(c["passed"] for c in checks.values()):
        raise ValueError("bundle verification failed")
    trucks = load_trucks(ROOT/"data/trucks.csv")
    catalog = load_catalog(ROOT/"data/items.csv")
    levels = {}
    for level in range(5):
        check = checks[f"chain_single_L{level}_v1"]
        levels[str(level)] = {}
        for name,best in check["best_single"].items():
            row = json.loads((results/f"chain_single_L{level}_v1"/(best["label"]+".json")).read_text(encoding="utf-8"))
            boxes = [b for tr in row["fleet"] for b in tr["boxes"]]
            weight = sum(b["weight"] for b in boxes)
            levels[str(level)][name] = {k:v for k,v in best.items() if k != "rest_serials"}
            levels[str(level)][name].update(used_volume_m3=best["used_volume_cm3"]/1e6,
                                            weight_kg=weight, weight_util=weight/trucks[name]["cap_weight"],
                                            rest_count=len(best["rest_serials"]))
    mixed = json.loads((results/"chain_mixed_L4_v1/manifest.json").read_text(encoding="utf-8"))["runs"]
    homogeneous = {}
    for index,name in enumerate(trucks):
        candidates = [r for r in mixed if r["complete"] and not r["errors"] and
                      all(q==0 for j,q in enumerate(r["combination"]) if j!=index)]
        row = min(candidates,key=lambda r:(r["vehicles"],r["cost"],r["label"]))
        # This is a valid capacity bound on the fixed-type original task.
        import math
        volume_bound = math.ceil(28735000/(trucks[name]["dims"][0]*trucks[name]["dims"][1]*(trucks[name]["dims"][2]-3)))
        homogeneous[name] = dict(label=row["label"],vehicles=row["vehicles"],cost=row["cost"],
                                 vehicle_lower_bound=volume_bound,
                                 status="verified_upper_bound_no_infeasibility_proof_for_smaller_fleets")
    # With 1150 incumbent only {one large=700,two small=900} can be cheaper:
    # one small=450 has insufficient volume; all other nonempty positive-cost
    # combinations cost at least 1150. Both lower alternatives remain unresolved.
    objectives = checks["chain_mixed_L4_v1"]["independent_objectives"]
    row = next(r for r in mixed if r["label"]==objectives["P1"]["label"])
    witness = json.loads((results/"chain_mixed_L4_v1"/row["file"]).read_text(encoding="utf-8"))
    vehicle_metrics = []
    for truck in witness["fleet"]:
        spec = trucks[truck["truck_type"]]
        l,w,h = spec["dims"]
        volume = sum(b["l"]*b["w"]*b["h"] for b in truck["boxes"])
        weight = sum(b["weight"] for b in truck["boxes"])
        vehicle_metrics.append(dict(truck_type=truck["truck_type"],placed=len(truck["boxes"]),
                                    volume_m3=volume/1e6,weight_kg=weight,
                                    nominal_space_util=volume/(l*w*h),
                                    effective_space_util=volume/(l*w*(h-3)),weight_util=weight/spec["cap_weight"]))
    return dict(passed=True, evidence_checks=checks, runs=sum(c["runs"] for c in checks.values()),
                hashed_files=sum(c["hashed_files"] for c in checks.values()),
                single_by_level=levels, homogeneous_L4=homogeneous, mixed_L4=objectives,
                mixed_witness_vehicle_metrics=vehicle_metrics,
                mixed_objective_bounds=dict(P1=dict(lower=1,upper=2), P2=dict(lower=700,upper=1150),
                                            unresolved_cheaper_fleets=[dict(combination=[0,1],cost=700),dict(combination=[2,0],cost=900)]),
                evidence_hash_manifests_sha256={name:hashlib.sha256((results/name/"sha256.json").read_bytes()).hexdigest() for name in names},
                limitations=["Best of five fixed orders, two vehicle sequences and a finite fleet domain.",
                             "Heuristic failure does not prove a fleet infeasible.",
                             "Constraint-layer output differences are algorithm observations, not optimal constraint costs.",
                             "Chain model conserves vertical load; no moment equilibrium or local peak pressure guarantee."])


if __name__ == "__main__":
    target = ROOT/"experiments/results/r5_chain_baseline_summary.json"
    if target.exists():
        raise SystemExit("preserve existing summary")
    summary = build_summary()
    target.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("evidence_checks","evidence_hash_manifests_sha256")},ensure_ascii=False,indent=2))

"""Finite-grid certificates for added constraints and late support insertion."""
import unittest
from experiments.exact_constrained import solve


def instance(kinds, dims=(2,2,2), weight=1):
    items = [dict(name=f"T{i}",serial=f"T{i}-000",kind=kind,dims=dims,weight=weight)
             for i,kind in enumerate(kinds)]
    catalog = {it["name"]:dict(kind=it["kind"],dims=dims,weight=weight,qty=1) for it in items}
    return items,catalog


class ExactConstrainedTests(unittest.TestCase):
    def test_all_levels_standard_stack(self):
        items,catalog = instance(["standard","standard"], weight=0.05)
        for level in range(5):
            result = solve(items,dict(dims=(2,2,7),cap_weight=10),catalog,level=level)
            self.assertEqual(result["status"],"optimal")
            self.assertEqual(result["placed"],2)

    def test_fragile_stack_impossible_but_standard_base_found_later(self):
        items,catalog = instance(["fragile","fragile"], weight=0.05)
        result = solve(items,dict(dims=(2,2,7),cap_weight=10),catalog,level=4)
        self.assertEqual(result["status"],"optimal")
        self.assertEqual(result["placed"],1)
        # First item is fragile, and must be placed aloft before later standard
        # support exists. Pruning unsupported partial states would miss this.
        items,catalog = instance(["fragile","standard"], weight=0.05)
        result = solve(items,dict(dims=(2,2,7),cap_weight=10),catalog,level=4)
        self.assertEqual(result["placed"],2)
        self.assertEqual(result["status"],"optimal")
        self.assertEqual(next(b for b in result["boxes"] if b["kind"]=="fragile")["z"],2)

    def test_chain_pressure_changes_exact_optimum(self):
        items,catalog = instance(["standard","standard"],weight=1)
        spec = dict(dims=(2,2,7),cap_weight=10)
        self.assertEqual(solve(items,spec,catalog,level=3)["placed"],2)
        self.assertEqual(solve(items,spec,catalog,level=4)["placed"],1)

    def test_budget_limit_not_optimal(self):
        items,catalog = instance(["standard","standard"],weight=0.05)
        result = solve(items,dict(dims=(2,2,7),cap_weight=10),catalog,node_limit=1)
        self.assertEqual(result["status"],"node_limit")


if __name__ == "__main__":
    unittest.main()

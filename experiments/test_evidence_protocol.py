"""Selection and run-matrix regressions; no solver or installation required."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.bench_guesser import select_instances
from experiments.verify_guesser_evidence import check_run_plan
from experiments.verify_linux_components import check_matrix, expected_config


def fixture():
    source = [{"pid": str(i)} for i in range(1, 101)]
    selection = {"source_name": "thpack1.txt", "split": "frozen",
                 "first_source_row": 11, "last_source_row": 20,
                 "pids": [str(i) for i in range(11, 21)],
                 "cpu_budgets_seconds": [5, 30]}
    planned = [{"pid": pid, "cpu_budget_seconds": budget}
               for budget in (5, 30) for pid in selection["pids"]]
    manifest = {"schema_version": 2, "selection": selection,
                "planned_runs": planned, "runs": copy.deepcopy(planned),
                "summary_by_budget": {"5": {}, "30": {}}}
    return source, manifest, {"selection": copy.deepcopy(selection)}


class EvidenceProtocolTests(unittest.TestCase):
    def test_source_rows_not_pid_numbers(self):
        source = [{"pid": "case-" + str(i)} for i in range(1, 101)]
        selected = select_instances(source, 11, 10, "frozen")
        self.assertEqual([r["pid"] for r in selected], ["case-" + str(i) for i in range(11, 21)])

    def test_selection_rejects_cross_split_and_bad_ranges(self):
        source, _, _ = fixture()
        for start, count, split in ((0, 10, "development"), (True, 1, "development"),
                                    (1, 0, "development"), (1, 11, "development"),
                                    (10, 2, "frozen"), (99, 3, "frozen"),
                                    (11, 10, "unknown")):
            with self.subTest(start=start, count=count, split=split):
                with self.assertRaises(ValueError):
                    select_instances(source, start, count, split)
        source[11]["pid"] = source[10]["pid"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_instances(source, 11, 10, "frozen")

    def test_valid_full_matrix(self):
        source, manifest, environment = fixture()
        self.assertFalse(check_run_plan(manifest, environment, source))

    def test_truncated_duplicated_or_wrong_budget_matrix_rejected(self):
        source, manifest, environment = fixture()
        for mode in ("truncate", "duplicate", "change_budget", "change_pid", "remove_summary", "bool_budget"):
            bad = copy.deepcopy(manifest)
            if mode == "truncate":
                bad["runs"].pop()
            elif mode == "duplicate":
                bad["runs"][-1] = copy.deepcopy(bad["runs"][0])
            elif mode == "change_budget":
                bad["runs"][-1]["cpu_budget_seconds"] = 6
            elif mode == "change_pid":
                bad["runs"][-1]["pid"] = "1"
            elif mode == "bool_budget":
                bad["runs"][-1]["cpu_budget_seconds"] = True
            else:
                del bad["summary_by_budget"]["30"]
            with self.subTest(mode=mode):
                self.assertTrue(check_run_plan(bad, environment, source))

    def test_false_selection_or_plan_rejected(self):
        source, manifest, environment = fixture()
        for mode in ("environment", "plan", "pids", "budget", "split"):
            bad, env = copy.deepcopy(manifest), copy.deepcopy(environment)
            if mode == "environment":
                env["selection"]["first_source_row"] = 12
            elif mode == "plan":
                bad["planned_runs"].pop()
            elif mode == "pids":
                bad["selection"]["pids"][0] = "1"
            elif mode == "budget":
                bad["selection"]["cpu_budgets_seconds"] = [5, 5]
            else:
                bad["selection"]["split"] = "development"
            with self.subTest(mode=mode):
                self.assertTrue(check_run_plan(bad, env, source))

    def test_legacy_r3_full_matrix_remains_supported(self):
        source, _, _ = fixture()
        rows = [{"pid": str(i), "cpu_budget_seconds": b}
                for b in (5, 30) for i in range(1, 11)]
        legacy = {"scope": "first 10 development instances, author defaults, no claim of blind test or paper replication",
                  "runs": rows, "summary_by_budget": {"5": {}, "30": {}}}
        self.assertFalse(check_run_plan(legacy, {}, source))
        legacy["runs"].pop()
        self.assertTrue(check_run_plan(legacy, {}, source))


class ComponentEvidenceTests(unittest.TestCase):
    def test_full_fixed_component_matrix(self):
        pids = [str(i) for i in range(1, 11)]
        rows = [{"method": method, "pid": pid} for method in ("ep", "b2") for pid in pids]
        manifest = {"status": "verified", "planned_runs": rows, "runs": copy.deepcopy(rows)}
        self.assertFalse(check_matrix(manifest, pids))
        for key in ("planned_runs", "runs"):
            bad = copy.deepcopy(manifest)
            bad[key].pop()
            self.assertTrue(check_matrix(bad, pids))
            bad = copy.deepcopy(manifest)
            bad[key][-1] = copy.deepcopy(bad[key][0])
            self.assertTrue(check_matrix(bad, pids))
        bad = copy.deepcopy(manifest)
        bad["status"] = "in_progress"
        self.assertTrue(check_matrix(bad, pids))

    def test_component_identity_types_and_fixed_configuration(self):
        pids = ["case-a"]
        rows = [{"method": method, "pid": "case-a"} for method in ("ep", "b2")]
        manifest = {"status": "verified", "planned_runs": rows, "runs": copy.deepcopy(rows)}
        self.assertFalse(check_matrix(manifest, pids))
        manifest["runs"][0]["pid"] = True
        self.assertTrue(check_matrix(manifest, pids))
        self.assertEqual(expected_config("ep")["stop_rule"], "one construction")
        self.assertEqual(expected_config("b2")["beam_width"], 8)
        self.assertEqual(expected_config("b2")["space_cap"], 80)


if __name__ == "__main__":
    unittest.main()

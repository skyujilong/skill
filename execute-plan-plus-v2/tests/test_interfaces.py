"""step.json 接口声明：schema 校验、接口审计、runing 依赖门禁、final_gate 透传。"""

from __future__ import annotations

import json
import unittest

from gitplan import make_repo_plan, read_steps, script, step
from test_update_step_state import make_plan

IFACE = ("depends_on", "produces", "exposes", "consumes")


def iface(name, state="pending", produces=(), exposes=(), consumes=(), **extra):
    return step(name, state, produces=list(produces), exposes=list(exposes),
                consumes=list(consumes), **extra)


def plan_of(steps):
    return make_repo_plan(steps, in_git=False)[1]


class SchemaValidationTest(unittest.TestCase):
    def assert_rejected(self, steps, needle):
        plan = plan_of(steps)
        result = script("update_step_state.py", plan / "step.json", steps[0]["step"], "runing")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(needle, result.stderr)

    def test_non_list_rejected(self):
        self.assert_rejected([step("01-a", produces="pkg:f")], "produces")

    def test_empty_string_entry_rejected(self):
        self.assert_rejected([step("01-a", consumes=["ok", ""])], "consumes")

    def test_non_string_entry_rejected(self):
        self.assert_rejected([step("01-a", exposes=[3])], "exposes")

    def test_unknown_depends_on_rejected(self):
        self.assert_rejected([step("01-a", depends_on=["99-x"])], "99-x")

    def test_later_depends_on_rejected(self):
        self.assert_rejected([step("01-a", depends_on=["02-b"]), step("02-b")], "earlier")

    def test_self_depends_on_rejected(self):
        self.assert_rejected([step("01-a", depends_on=["01-a"])], "itself")

    def test_valid_fields_accepted(self):
        plan = plan_of([step("01-a", produces=["p:f"]),
                        step("02-b", depends_on=["01-a"], consumes=["existing:z", "p:f"])])
        result = script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)


class InterfaceAuditTest(unittest.TestCase):
    def audit(self, steps):
        return script("audit_coverage.py", plan_of(steps))

    def test_no_declarations_warns_but_passes(self):
        result = self.audit([step("01-a"), step("02-b")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[WARN] no interface declarations; orphan risk unmanaged", result.stdout)

    def test_missing_keys_fail_naming_step(self):
        result = self.audit([iface("01-a", exposes=["p:f"]), step("02-b", depends_on=["01-a"])])
        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL]", result.stdout)
        self.assertIn("02-b", result.stdout)
        self.assertIn("produces", result.stdout)

    def test_consumer_without_earlier_producer_fails(self):
        result = self.audit([iface("01-a", consumes=["p:ghost"])])
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-a", result.stdout)
        self.assertIn("p:ghost", result.stdout)

    def test_producer_in_later_step_fails_for_consumer(self):
        result = self.audit([iface("01-a", consumes=["p:f"]),
                             iface("02-b", produces=["p:f"], exposes=["p:f2"])])
        self.assertEqual(result.returncode, 1)
        self.assertIn("consumes p:f", result.stdout)

    def test_existing_prefix_needs_no_producer(self):
        result = self.audit([iface("01-a", consumes=["existing:lib:util"], exposes=["p:f"])])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_orphan_produce_fails_with_hint(self):
        result = self.audit([iface("01-a", produces=["p:f"]), iface("02-b")])
        self.assertEqual(result.returncode, 1)
        self.assertIn("orphan risk: p:f produced by 01-a has no later consumer "
                      "(declare it in exposes if it is a public entry point)", result.stdout)

    def test_exposed_symbol_needs_no_consumer(self):
        result = self.audit([iface("01-a", exposes=["p:api"]), iface("02-b")])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[PASS]", result.stdout)

    def test_consumer_must_be_later_not_earlier(self):
        result = self.audit([iface("01-a", consumes=["x"]), iface("02-b", produces=["x"])])
        self.assertEqual(result.returncode, 1)

    def test_duplicate_producer_fails(self):
        result = self.audit([iface("01-a", produces=["p:f"]), iface("02-b", produces=["p:f"]),
                             iface("03-c", consumes=["p:f"])])
        self.assertEqual(result.returncode, 1)
        self.assertIn("p:f", result.stdout)
        self.assertIn("01-a", result.stdout)
        self.assertIn("02-b", result.stdout)

    def test_happy_chain_passes(self):
        result = self.audit([iface("01-a", produces=["p:f"]),
                             iface("02-b", consumes=["p:f"], exposes=["p:main"])])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_runs_in_upstream_linked_mode_too(self):
        plan = make_plan()
        steps = read_steps(plan)
        steps[0].update(produces=["p:f"], exposes=[], consumes=[])
        steps[1].update(produces=[], exposes=[], consumes=[])
        (plan / "step.json").write_text(json.dumps(steps), encoding="utf-8")
        result = script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("orphan risk: p:f", result.stdout)
        steps[0]["exposes"] = ["p:f"]
        steps[0]["produces"] = []
        (plan / "step.json").write_text(json.dumps(steps), encoding="utf-8")
        self.assertEqual(script("audit_coverage.py", plan).returncode, 0)

    def test_linked_mode_without_declarations_warns(self):
        result = script("audit_coverage.py", make_plan())
        self.assertEqual(result.returncode, 0)
        self.assertIn("[WARN] no interface declarations", result.stdout)


class FinalGateSurfaceTest(unittest.TestCase):
    def test_generic_final_gate_fails_on_orphan(self):
        plan = plan_of([iface("01-a", "complate", produces=["p:f"]), iface("02-b", "complate")])
        result = script("final_gate.py", plan)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("orphan risk: p:f", result.stdout)

    def test_generic_final_gate_surfaces_warn(self):
        plan = plan_of([step("01-a", "complate")])
        result = script("final_gate.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("[WARN] no interface declarations", result.stdout)


class DependencyGateTest(unittest.TestCase):
    def run_state(self, plan, name, *extra):
        return script("update_step_state.py", plan / "step.json", name, "runing", *extra)

    def test_depends_on_incomplete_refused(self):
        plan = plan_of([step("01-a"), step("02-b", depends_on=["01-a"])])
        result = self.run_state(plan, "02-b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-a", result.stderr)
        self.assertIn("depends_on", result.stderr)

    def test_symbol_producer_incomplete_refused_and_named(self):
        plan = plan_of([iface("01-a", exposes=["p:f"]), iface("02-b", consumes=["p:f"])])
        result = self.run_state(plan, "02-b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-a", result.stderr)
        self.assertIn("p:f", result.stderr)

    def test_force_does_not_bypass_dependency_gate(self):
        plan = plan_of([step("00-z"), iface("01-a", exposes=["p:f"]),
                        iface("02-b", consumes=["p:f"])])
        result = self.run_state(plan, "02-b", "--force", "--reason", "reorder")
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-a", result.stderr)
        self.assertEqual(read_steps(plan)[2]["state"], "pending")

    def test_force_reorder_still_works_when_prereqs_complete(self):
        plan = plan_of([step("00-z"), iface("01-a", "complate", exposes=["p:f"]),
                        iface("02-b", consumes=["p:f", "existing:x"])])
        result = self.run_state(plan, "02-b", "--force", "--reason", "reorder")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_passes_when_prereqs_complate(self):
        plan = plan_of([iface("01-a", "complate", exposes=["p:f"]),
                        iface("02-b", depends_on=["01-a"], consumes=["p:f"])])
        self.assertEqual(self.run_state(plan, "02-b").returncode, 0)

    def test_absent_fields_add_no_constraint(self):
        plan = plan_of([step("01-a", "complate"), step("02-b")])
        self.assertEqual(self.run_state(plan, "02-b").returncode, 0)


if __name__ == "__main__":
    unittest.main()

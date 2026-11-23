"""resume_check.py：步骤提交锚点校验与预期孤儿清单（只读）。"""

from __future__ import annotations

import json
import unittest

from gitplan import commit_file, git, head, make_repo_plan, script, step


def finish(root, plan, name, rel):
    sj = plan / "step.json"
    assert script("update_step_state.py", sj, name, "runing").returncode == 0
    commit_file(root, rel)
    done = script("update_step_state.py", sj, name, "complate", "--covers-none", "--reason", "x")
    assert done.returncode == 0, done.stderr


def iface(name, produces=(), exposes=(), consumes=()):
    return step(name, produces=list(produces), exposes=list(exposes), consumes=list(consumes))


class ResumeCheckTest(unittest.TestCase):
    def test_usage_error_exits_2(self):
        self.assertEqual(script("resume_check.py").returncode, 2)
        self.assertEqual(script("resume_check.py", "/nonexistent/plan").returncode, 2)

    def test_ok_and_changes_after_last_step(self):
        root, plan = make_repo_plan([step("01-a"), step("02-b")])
        finish(root, plan, "01-a", "a.py")
        finish(root, plan, "02-b", "b.py")
        commit_file(root, "later.py")
        commit_file(root, "docs/x.md")
        result = script("resume_check.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("changes after last step", result.stdout)
        self.assertIn(": 1 file(s)", result.stdout)
        self.assertIn("later.py", result.stdout)
        self.assertNotIn("docs/x.md", result.stdout)

    def test_reset_hard_makes_step_stale(self):
        root, plan = make_repo_plan([step("01-a"), step("02-b")])
        finish(root, plan, "01-a", "a.py")
        keep = head(root)
        finish(root, plan, "02-b", "b.py")
        git(root, "reset", "--hard", "-q", keep)
        result = script("resume_check.py", plan)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("STALE", result.stdout)
        self.assertIn("02-b", result.stdout)
        self.assertNotIn("STALE 01-a", result.stdout)

    def test_legacy_complate_without_commit_warns(self):
        root, plan = make_repo_plan([step("01-a", "complate")])
        result = script("resume_check.py", plan)
        self.assertEqual(result.returncode, 0)
        self.assertIn("[WARN]", result.stdout)
        self.assertIn("01-a", result.stdout)

    def test_non_git_skips_anchor_checks(self):
        _, plan = make_repo_plan([step("01-a")], in_git=False)
        result = script("resume_check.py", plan)
        self.assertEqual(result.returncode, 0)
        self.assertIn("skipped", result.stdout)

    def test_expected_orphans_list_pending_consumers(self):
        root, plan = make_repo_plan([
            iface("01-a", produces=["p:f", "p:g"]), iface("02-b", consumes=["p:f"]),
            iface("03-c", consumes=["p:g"], exposes=["p:main"])])
        finish(root, plan, "01-a", "a.py")
        finish(root, plan, "02-b", "b.py")
        out = script("resume_check.py", plan).stdout
        self.assertIn("EXPECTED ORPHANS", out)
        expected = out.split("EXPECTED ORPHANS")[1].split("UNEXPECTED")[0]
        self.assertIn("p:g", expected)
        self.assertIn("01-a", expected)
        self.assertIn("03-c", expected)
        self.assertNotIn("p:f", expected)

    def test_unexpected_orphan_listed(self):
        root, plan = make_repo_plan([iface("01-a", produces=["p:lost"]), iface("02-b")])
        out = script("resume_check.py", plan).stdout
        self.assertIn("UNEXPECTED", out)
        self.assertIn("p:lost", out.split("UNEXPECTED")[1])

    def test_exposed_not_unexpected(self):
        root, plan = make_repo_plan([iface("01-a", produces=["p:f"], exposes=["p:f"])])
        out = script("resume_check.py", plan).stdout
        self.assertNotIn("p:f", out.split("UNEXPECTED")[1])


if __name__ == "__main__":
    unittest.main()

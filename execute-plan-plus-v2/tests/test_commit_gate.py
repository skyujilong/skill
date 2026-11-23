"""final_gate.py 的步骤提交门禁。"""

from __future__ import annotations

import unittest

from gitplan import commit_file, make_repo_plan, script, step


class CommitGateTest(unittest.TestCase):
    def test_legacy_plan_without_commit_fields_warns_only(self):
        _, plan = make_repo_plan([step("01-a", "complate")])
        result = script("final_gate.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("commit", result.stdout)
        self.assertIn("[WARN]", result.stdout)

    def test_mixed_plan_fails(self):
        _, plan = make_repo_plan([step("01-a", "complate", commit="abc1234"),
                                  step("02-b", "complate")])
        result = script("final_gate.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("02-b", result.stdout)

    def test_no_code_change_counts(self):
        _, plan = make_repo_plan([step("01-a", "complate", commit="abc1234"),
                                  step("02-b", "complate", no_code_change=True)])
        self.assertEqual(script("final_gate.py", plan).returncode, 0)

    def test_non_git_has_no_commit_gate(self):
        _, plan = make_repo_plan([step("01-a", "complate", commit="x"),
                                  step("02-b", "complate")], in_git=False)
        result = script("final_gate.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_end_to_end_scripted_steps_pass(self):
        root, plan = make_repo_plan([step("01-a")])
        sj = plan / "step.json"
        script("update_step_state.py", sj, "01-a", "runing")
        commit_file(root, "a.py")
        script("update_step_state.py", sj, "01-a", "complate", "--covers-none", "--reason", "x")
        self.assertEqual(script("final_gate.py", plan).returncode, 0)


if __name__ == "__main__":
    unittest.main()

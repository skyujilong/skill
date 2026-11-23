"""步骤与 git 提交绑定：runing 记录 base_commit，complate 要求干净树 + 新提交。"""

from __future__ import annotations

import unittest

from gitplan import commit_file, head, make_repo_plan, read_steps, script, step


def sj(plan):
    return plan / "step.json"


class CommitBindingTest(unittest.TestCase):
    def setUp(self):
        self.root, self.plan = make_repo_plan([step("01-a"), step("02-b")])

    def start(self, name="01-a"):
        result = script("update_step_state.py", sj(self.plan), name, "runing")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def complate(self, name="01-a", *extra):
        return script("update_step_state.py", sj(self.plan), name, "complate",
                      "--covers-none", "--reason", "infra", *extra)

    def test_runing_records_base_commit(self):
        base = head(self.root)
        self.start()
        self.assertEqual(read_steps(self.plan)[0]["base_commit"], base)

    def test_dirty_tree_blocks_complate_and_lists_paths(self):
        self.start()
        (self.root / "src.py").write_text("x\n", encoding="utf-8")
        result = self.complate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit this step's changes first", result.stderr)
        self.assertIn("src.py", result.stderr)
        self.assertEqual(read_steps(self.plan)[0]["state"], "runing")

    def test_modified_tracked_file_blocks(self):
        self.start()
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.complate().returncode, 1)

    def test_dirty_list_capped_at_ten(self):
        self.start()
        for i in range(13):
            (self.root / f"f{i:02d}.py").write_text("x\n", encoding="utf-8")
        result = self.complate()
        self.assertIn("f09.py", result.stderr)
        self.assertNotIn("f10.py", result.stderr)

    def test_clean_with_new_commit_passes_and_records(self):
        self.start()
        base = read_steps(self.plan)[0]["base_commit"]
        new = commit_file(self.root, "src.py")
        result = self.complate()
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = read_steps(self.plan)[0]
        self.assertEqual(entry["commit"], new)
        self.assertEqual(entry["base_commit"], base)
        self.assertNotEqual(entry["commit"], base)

    def test_no_new_commit_blocks(self):
        self.start()
        result = self.complate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no new commit", result.stderr)
        self.assertIn("--no-code-change", result.stderr)

    def test_no_code_change_with_reason_passes(self):
        self.start()
        result = self.complate("01-a", "--no-code-change", "--reason", "docs only")
        # --reason given twice: last wins; covers-none reason satisfied as well
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = read_steps(self.plan)[0]
        self.assertTrue(entry["no_code_change"])
        self.assertEqual(entry["commit"], head(self.root))

    def test_no_code_change_requires_reason(self):
        self.start()
        result = script("update_step_state.py", sj(self.plan), "01-a", "complate",
                        "--no-code-change")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--no-code-change requires a non-empty --reason", result.stderr)

    def test_no_code_change_only_for_complate(self):
        result = script("update_step_state.py", sj(self.plan), "01-a", "runing",
                        "--no-code-change", "--reason", "x")
        self.assertEqual(result.returncode, 1)

    def test_top_level_docs_dirt_does_not_block(self):
        self.start()
        commit_file(self.root, "src.py")
        (self.root / "docs" / "notes.md").write_text("n\n", encoding="utf-8")
        self.assertEqual(self.complate().returncode, 0)

    def test_nested_docs_dirt_blocks(self):
        self.start()
        commit_file(self.root, "src.py")
        (self.root / "pkg" / "docs").mkdir(parents=True)
        (self.root / "pkg" / "docs" / "n.md").write_text("n\n", encoding="utf-8")
        result = self.complate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("pkg/docs/n.md", result.stderr)

    def test_forced_runing_also_records_base_commit(self):
        result = script("update_step_state.py", sj(self.plan), "02-b", "runing",
                        "--force", "--reason", "reorder")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_steps(self.plan)[1]["base_commit"], head(self.root))

    def test_complate_step_keeps_recorded_fields(self):
        self.start()
        commit_file(self.root, "src.py")
        self.assertEqual(self.complate().returncode, 0)
        before = read_steps(self.plan)[0]
        commit_file(self.root, "other.py")
        again = script("update_step_state.py", sj(self.plan), "01-a", "complate")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(read_steps(self.plan)[0], before)

    def test_dirty_tree_refusal_records_no_commit(self):
        self.start()
        commit_file(self.root, "src.py")
        (self.root / "untracked.py").write_text("x\n", encoding="utf-8")
        result = self.complate()
        self.assertEqual(result.returncode, 1)
        entry = read_steps(self.plan)[0]
        self.assertEqual(entry["state"], "runing")
        self.assertNotIn("commit", entry)

    def test_non_git_skips_with_note(self):
        _, plan = make_repo_plan([step("01-a")], in_git=False)
        result = script("update_step_state.py", sj(plan), "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not in a git repo", result.stdout)
        self.assertNotIn("base_commit", read_steps(plan)[0])
        done = script("update_step_state.py", sj(plan), "01-a", "complate",
                      "--covers-none", "--reason", "x")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("commit", read_steps(plan)[0])


if __name__ == "__main__":
    unittest.main()

"""评审修复：审计一致性、base_commit 补录、git 失败显式化、declare、符号规范化。"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from gitplan import SCRIPTS, commit_file, git, head, make_repo_plan, read_steps, script, step
from test_interfaces import iface, plan_of

sys.path.insert(0, str(SCRIPTS))

import final_gate  # noqa: E402
import interfaces  # noqa: E402
import resume_check  # noqa: E402
import update_step_state  # noqa: E402


def sj(plan):
    return plan / "step.json"


def run_main(module_main, argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            result = module_main(argv)
            code = result if isinstance(result, int) else 0
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ProducesAndExposesTest(unittest.TestCase):
    def audit(self, steps):
        return script("audit_coverage.py", plan_of(steps))

    def test_produces_and_exposes_same_symbol_is_not_orphan(self):
        result = self.audit([iface("01-a", produces=["p:f"], exposes=["p:f"])])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("orphan risk", result.stdout)

    def test_exposed_by_other_step_is_not_orphan(self):
        result = self.audit([iface("01-a", produces=["p:f"]), iface("02-b", exposes=["p:f"])])
        self.assertNotIn("orphan risk", result.stdout)

    def test_pure_produces_still_orphan(self):
        result = self.audit([iface("01-a", produces=["p:f"])])
        self.assertEqual(result.returncode, 1)
        self.assertIn("orphan risk", result.stdout)
        self.assertIn("declare", result.stdout)


class BackfillBaseCommitTest(unittest.TestCase):
    def runing(self, plan, name):
        return script("update_step_state.py", sj(plan), name, "runing")

    def complate(self, plan, name):
        return script("update_step_state.py", sj(plan), name, "complate",
                      "--covers-none", "--reason", "x")

    def test_non_legacy_plan_runing_without_base_commit_fails(self):
        root, plan = make_repo_plan([step("01-a", "complate", commit="abc1234"),
                                     step("02-b", "runing")])
        commit_file(root, "src.py")
        result = self.complate(plan, "02-b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("base_commit", result.stderr)
        self.assertEqual(read_steps(plan)[1]["state"], "runing")

    def test_reissued_runing_backfills_then_complate_passes(self):
        root, plan = make_repo_plan([step("01-a", "complate", commit="abc1234"),
                                     step("02-b", "runing")])
        again = self.runing(plan, "02-b")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("base_commit", again.stdout)
        self.assertEqual(read_steps(plan)[1]["base_commit"], head(root))
        new = commit_file(root, "src.py")
        done = self.complate(plan, "02-b")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(read_steps(plan)[1]["commit"], new)

    def test_reissued_runing_never_overwrites_base_commit(self):
        root, plan = make_repo_plan([step("01-a", "runing", base_commit="old1234")])
        commit_file(root, "src.py")
        again = self.runing(plan, "01-a")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(read_steps(plan)[0]["base_commit"], "old1234")

    def test_legacy_plan_skips_binding_with_note(self):
        root, plan = make_repo_plan([step("01-a", "runing")])
        commit_file(root, "src.py")
        done = self.complate(plan, "01-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("commit binding skipped", done.stdout)
        entry = read_steps(plan)[0]
        self.assertNotIn("commit", entry)
        self.assertNotIn("base_commit", entry)


class GitStatusFailureTest(unittest.TestCase):
    def failing_status(self, returncode=128, result_none=False):
        real = interfaces.run_git

        def fake(cwd, *args):
            if args and args[0] == "status":
                if result_none:
                    return None
                return subprocess.CompletedProcess(args, returncode, "", "fatal: boom")
            return real(cwd, *args)
        return fake

    def start_plan(self):
        root, plan = make_repo_plan([step("01-a")])
        self.assertEqual(script("update_step_state.py", sj(plan), "01-a", "runing").returncode, 0)
        commit_file(root, "src.py")
        return plan

    def test_status_nonzero_fails_loudly(self):
        plan = self.start_plan()
        with mock.patch.object(interfaces, "run_git", self.failing_status()):
            code, _, err = run_main(update_step_state.main,
                                    [str(sj(plan)), "01-a", "complate", "--covers-none",
                                     "--reason", "x"])
        self.assertEqual(code, 1)
        self.assertIn("git status", err)
        self.assertEqual(read_steps(plan)[0]["state"], "runing")

    def test_status_cannot_execute_fails_loudly(self):
        plan = self.start_plan()
        with mock.patch.object(interfaces, "run_git", self.failing_status(result_none=True)):
            code, _, err = run_main(update_step_state.main,
                                    [str(sj(plan)), "01-a", "complate", "--covers-none",
                                     "--reason", "x"])
        self.assertEqual(code, 1)
        self.assertIn("git status", err)

    def test_dirty_paths_raises(self):
        root, _ = make_repo_plan([step("01-a")])
        with mock.patch.object(interfaces, "run_git", self.failing_status()):
            with self.assertRaises(interfaces.GitError):
                interfaces.dirty_paths(root)


class DeclareTest(unittest.TestCase):
    def setUp(self):
        self.root, self.plan = make_repo_plan(
            [iface("01-a", produces=["p:f"]), iface("02-b", consumes=["p:f"]),
             step("03-c", "runing", produces=[], exposes=[], consumes=[])])

    def declare(self, name, *args):
        return script("update_step_state.py", sj(self.plan), name, "declare", *args)

    def test_declare_replaces_given_fields_only(self):
        result = self.declare("02-b", "--exposes", "POST /x, GET /y", "--consumes", "p:f",
                              "--reason", "fix audit")
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = read_steps(self.plan)[1]
        self.assertEqual(entry["exposes"], ["POST /x", "GET /y"])
        self.assertEqual(entry["consumes"], ["p:f"])
        self.assertEqual(entry["produces"], [])
        self.assertEqual(entry["state"], "pending")

    def test_declare_fixes_audit_failure(self):
        self.declare("01-a", "--produces", "p:f,p:orphan", "--reason", "add")
        before = script("audit_coverage.py", self.plan)
        self.assertEqual(before.returncode, 1)
        self.assertIn("p:orphan", before.stdout)
        self.declare("01-a", "--exposes", "p:orphan", "--reason", "public entry")
        after = script("audit_coverage.py", self.plan)
        self.assertEqual(after.returncode, 0, after.stdout)

    def test_declare_empty_value_clears_field(self):
        result = self.declare("01-a", "--produces", "", "--reason", "drop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_steps(self.plan)[0]["produces"], [])

    def test_declare_depends_on_revalidated(self):
        bad = self.declare("01-a", "--depends-on", "02-b", "--reason", "x")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("earlier", bad.stderr)
        ok = self.declare("02-b", "--depends-on", "01-a", "--reason", "x")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(read_steps(self.plan)[1]["depends_on"], ["01-a"])

    def test_declare_refused_on_runing(self):
        result = self.declare("03-c", "--produces", "p:g", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("decisions.md", result.stderr)
        self.assertEqual(read_steps(self.plan)[2]["produces"], [])

    def test_declare_refused_on_complate(self):
        root, plan = make_repo_plan([iface("01-a", "complate")])
        result = script("update_step_state.py", sj(plan), "01-a", "declare",
                        "--produces", "p:g", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("decisions.md", result.stderr)

    def test_declare_requires_reason(self):
        for extra in ([], ["--reason", "  "]):
            result = self.declare("01-a", "--exposes", "p:f", *extra)
            self.assertEqual(result.returncode, 1)
            self.assertIn("--reason", result.stderr)

    def test_declare_requires_a_field_flag(self):
        result = self.declare("01-a", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("at least one", result.stderr)

    def test_declare_rejects_bad_names(self):
        for args in (["--produces", "a,,b"], ["--exposes", "existing:x"],
                     ["--depends-on", "99-zz"]):
            result = self.declare("01-a", *args, "--reason", "x")
            self.assertEqual(result.returncode, 1, args)
        self.assertEqual(read_steps(self.plan)[0]["produces"], ["p:f"])

    def test_declare_unknown_flag_rejected(self):
        result = self.declare("01-a", "--bogus", "x", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown option", result.stderr)

    def test_field_flags_rejected_outside_declare(self):
        result = script("update_step_state.py", sj(self.plan), "01-a", "runing",
                        "--produces", "p:f")
        self.assertEqual(result.returncode, 1)
        self.assertIn("declare", result.stderr)

    def test_declare_missing_step(self):
        result = self.declare("99-x", "--exposes", "p:f", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("step not found", result.stderr)


class LaterProducerPrerequisiteTest(unittest.TestCase):
    def test_consumer_can_start_before_later_producer(self):
        plan = plan_of([iface("01-a", consumes=["p:f"]),
                        iface("02-b", produces=["p:f"], exposes=["p:g"])])
        started = script("update_step_state.py", sj(plan), "01-a", "runing")
        self.assertEqual(started.returncode, 0, started.stderr)
        audit = script("audit_coverage.py", plan)
        self.assertEqual(audit.returncode, 1)
        self.assertIn("no earlier step produces", audit.stdout)

    def test_earlier_producer_still_required(self):
        plan = plan_of([iface("01-a", produces=["p:f"]), iface("02-b", consumes=["p:f"])])
        result = script("update_step_state.py", sj(plan), "02-b", "runing", "--force",
                        "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("01-a", result.stderr)


class MissingGitBinaryTest(unittest.TestCase):
    def test_run_git_returns_none_on_oserror(self):
        with mock.patch.object(interfaces.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(interfaces.run_git(Path("."), "status"))

    def test_resume_check_degrades_when_git_missing(self):
        _, plan = make_repo_plan([step("01-a", "complate", commit="abc1234")])
        with mock.patch.object(interfaces.subprocess, "run", side_effect=FileNotFoundError):
            code, out, err = run_main(resume_check.main, [str(plan)])
        self.assertEqual(code, 0, err)
        self.assertIn("anchor checks skipped", out)

    def test_resume_check_git_vanishes_mid_run_exits_2(self):
        root, plan = make_repo_plan([step("01-a", "complate", commit="abc1234")])
        real = interfaces.run_git

        def fake(cwd, *args):
            return None if args[0] in ("cat-file", "merge-base") else real(cwd, *args)
        with mock.patch.object(interfaces, "run_git", fake):
            code, _, err = run_main(resume_check.main, [str(plan)])
        self.assertEqual(code, 2)
        self.assertIn("git", err)
        self.assertNotIn("Traceback", err)

    def test_commit_gate_skips_when_git_missing(self):
        _, plan = make_repo_plan([step("01-a", "complate", commit="abc1234")])
        real = final_gate.subprocess.run

        def fake(cmd, *a, **k):
            if cmd[0] == "git":
                raise FileNotFoundError("git")
            return real(cmd, *a, **k)
        out = io.StringIO()
        with mock.patch.object(final_gate.subprocess, "run", fake), \
                contextlib.redirect_stdout(out):
            self.assertIsNone(final_gate.commit_gate(plan, read_steps(plan)))

    def test_run_gate_oserror_is_fail(self):
        out = io.StringIO()
        with mock.patch.object(final_gate.subprocess, "run", side_effect=OSError("boom")), \
                contextlib.redirect_stdout(out):
            self.assertFalse(final_gate.run_gate("x", ["nope"]))
        self.assertIn("[FAIL] x", out.getvalue())
        self.assertIn("boom", out.getvalue())


class SymbolNormalizationTest(unittest.TestCase):
    def audit(self, steps):
        return script("audit_coverage.py", plan_of(steps))

    def test_whitespace_ignored_when_matching(self):
        result = self.audit([iface("01-a", produces=["p:f "]),
                             iface("02-b", consumes=[" p:f"], exposes=["p:g"])])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_existing_prefix_case_insensitive_for_consumes(self):
        for prefix in ("EXISTING:", "Existing:", " existing:"):
            result = self.audit([iface("01-a", consumes=[prefix + "app.db:x"])])
            self.assertEqual(result.returncode, 0, (prefix, result.stdout))

    def test_existing_prefix_rejected_in_produces_and_exposes(self):
        for key in ("produces", "exposes"):
            plan = plan_of([step("01-a", **{key: ["Existing:x"]})])
            result = script("update_step_state.py", sj(plan), "01-a", "runing")
            self.assertEqual(result.returncode, 1, key)
            self.assertIn(key, result.stderr)
            self.assertIn("existing:", result.stderr)

    def test_prerequisites_ignore_existing_case(self):
        data = [iface("01-a", produces=["p:f"]), iface("02-b", consumes=["EXISTING:p:f"])]
        self.assertEqual(interfaces.prerequisites(data, 1), {})


if __name__ == "__main__":
    unittest.main()

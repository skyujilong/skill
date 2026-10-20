"""Phase 2：脚本可检查的证据与审核——code_fingerprint / close-ac 执行验证 / record-review / strict 门禁。

诚实边界：脚本证明不了命令有意义、审核者真独立，只能执行命令并记录退出码与代码版本，
把审核绑定到代码版本，并在证据/审核缺失或过期时拒绝收尾。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _fixture import make_run, run_script  # noqa: E402
import _artifacts  # noqa: E402
from _artifacts import ArtifactError, code_fingerprint, git_toplevel  # noqa: E402

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def git(root: Path, *args):
    subprocess.run(["git", *GIT_ID, "-C", str(root), *args], check=True, capture_output=True)


def make_git_root() -> Path:
    root = Path(tempfile.mkdtemp())
    git(root, "init", "-q")
    (root / "src.py").write_text("print(1)\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def read(run: Path, name: str = "acceptance.md") -> str:
    return (run / name).read_text(encoding="utf-8")


def al(*args):
    return run_script("align_state.py", *args)


def review(run, scope="final", verdict="approved", reviewer="bob", author="alice", summary="ok"):
    return al("record-review", run, "--reviewer", reviewer, "--author", author, "--scope", scope,
              "--verdict", verdict, "--summary", summary)


def strict(run):
    return run_script("check_alignment.py", run, "--strict-closure")


def close_all(run, cmd="true"):
    al("sync", run)
    extra = [] if git_toplevel(run) else ["--cwd", run.parent.parent]
    for ac in ("AC-1", "AC-2"):
        r = al("close-ac", run, ac, "--run-cmd", cmd, *extra)
        assert r.returncode == 0, r.stderr
    al("resolve-risk", run, "RISK-1", "--decision", "d", "--reason", "r", "--impact", "i")


class FingerprintTest(unittest.TestCase):
    def test_same_code_same_fingerprint_and_hex(self):
        root = make_git_root()
        a = code_fingerprint(root)
        self.assertRegex(a, r"^[0-9a-f]{64}$")
        self.assertEqual(a, code_fingerprint(root))

    def test_source_change_differs(self):
        root = make_git_root()
        a = code_fingerprint(root)
        (root / "src.py").write_text("print(2)\n", encoding="utf-8")
        b = code_fingerprint(root)
        self.assertNotEqual(a, b)
        (root / "new.py").write_text("x\n", encoding="utf-8")
        self.assertNotEqual(b, code_fingerprint(root))
        (root / "src.py").unlink()
        self.assertNotEqual(code_fingerprint(root), b)

    def test_docs_change_does_not_change_fingerprint(self):
        root = make_git_root()
        a = code_fingerprint(root)
        (root / "docs" / "req-align-x").mkdir(parents=True)
        (root / "docs" / "req-align-x" / "acceptance.md").write_text("a", encoding="utf-8")
        self.assertEqual(a, code_fingerprint(root))
        (root / "docs" / "req-align-x" / "acceptance.md").write_text("b", encoding="utf-8")
        self.assertEqual(a, code_fingerprint(root))

    def test_works_from_subdirectory_and_no_commits(self):
        root = Path(tempfile.mkdtemp())
        git(root, "init", "-q")
        (root / "a").mkdir()
        (root / "a" / "f.py").write_text("1", encoding="utf-8")
        self.assertEqual(code_fingerprint(root), code_fingerprint(root / "a"))
        self.assertRegex(code_fingerprint(root), r"^[0-9a-f]{64}$")

    def test_non_git_dir(self):
        self.assertEqual(code_fingerprint(Path(tempfile.mkdtemp())), "no-git")

    def test_ignore_excludes_run_dir_outside_docs(self):
        root = make_git_root()
        run = make_run(root, container="run")
        a = code_fingerprint(root, ignore=run)
        self.assertNotEqual(a, code_fingerprint(root))
        (run / "acceptance.md").write_text("changed", encoding="utf-8")
        (run / "reviews.json").write_text("[]", encoding="utf-8")
        self.assertEqual(a, code_fingerprint(root, ignore=run))
        (root / "src.py").write_text("print(5)\n", encoding="utf-8")
        self.assertNotEqual(a, code_fingerprint(root, ignore=run))

    def test_ignore_outside_repo_is_harmless(self):
        root = make_git_root()
        other = Path(tempfile.mkdtemp())
        self.assertEqual(code_fingerprint(root), code_fingerprint(root, ignore=other))

    def test_nested_docs_change_does_change_fingerprint(self):
        root = make_git_root()
        (root / "sub" / "docs").mkdir(parents=True)
        (root / "sub" / "docs" / "x.txt").write_text("a", encoding="utf-8")
        a = code_fingerprint(root)
        (root / "sub" / "docs" / "x.txt").write_text("b", encoding="utf-8")
        self.assertNotEqual(a, code_fingerprint(root))

    def test_rename_is_detected(self):
        root = make_git_root()
        a = code_fingerprint(root)
        git(root, "mv", "src.py", "moved.py")
        b = code_fingerprint(root)
        self.assertNotEqual(a, b)
        git(root, "mv", "moved.py", "moved2.py")
        self.assertNotEqual(b, code_fingerprint(root))

    def test_path_with_spaces_and_non_ascii(self):
        root = make_git_root()
        a = code_fingerprint(root)
        target = root / "我的 文件.py"
        target.write_text("1", encoding="utf-8")
        b = code_fingerprint(root)
        self.assertNotEqual(a, b)
        target.write_text("2", encoding="utf-8")
        self.assertNotEqual(b, code_fingerprint(root))

    def test_gitignored_file_excluded(self):
        root = make_git_root()
        (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
        git(root, "add", ".gitignore")
        git(root, "commit", "-q", "-m", "ignore")
        a = code_fingerprint(root)
        (root / "noise.log").write_text("x", encoding="utf-8")
        self.assertEqual(a, code_fingerprint(root))

    def test_no_commits_repo_tracks_changes(self):
        root = Path(tempfile.mkdtemp())
        git(root, "init", "-q")
        (root / "f.py").write_text("1", encoding="utf-8")
        a = code_fingerprint(root)
        self.assertRegex(a, r"^[0-9a-f]{64}$")
        (root / "f.py").write_text("2", encoding="utf-8")
        self.assertNotEqual(a, code_fingerprint(root))

    def test_status_failure_raises_instead_of_head_only(self):
        root = make_git_root()
        real = _artifacts._git

        def fake(start, *args):
            if args and args[0] == "status":
                return None
            return real(start, *args)

        with mock.patch.object(_artifacts, "_git", fake):
            with self.assertRaises(ArtifactError) as ctx:
                code_fingerprint(root)
        self.assertIn("git status", str(ctx.exception))


class CloseAcRunCmdTest(unittest.TestCase):
    def setUp(self):
        self.root = make_git_root()
        self.run_dir = make_run(self.root)
        al("sync", self.run_dir)

    def test_run_cmd_success_records_verified_evidence(self):
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "echo hello", "--step", "s1")
        self.assertEqual(r.returncode, 0, r.stderr)
        fp = code_fingerprint(self.root)[:16]
        self.assertRegex(read(self.run_dir), rf"- AC-1 \| s1 \| \[run exit=0 rev={fp} out=[0-9a-f]{{8}}\] echo hello\n")
        self.assertNotIn("hello\n- AC-1", read(self.run_dir))
        data = json.loads(read(self.run_dir, "handoff.json"))
        ev = next(a for a in data["acceptance"] if a["id"] == "AC-1")["evidence"]
        self.assertTrue(ev.startswith("[run exit=0 rev="))

    def test_run_cmd_with_note(self):
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true", "--evidence", "line1\nline2")
        text = read(self.run_dir)
        self.assertRegex(text, r"\] true \| note: line1 line2\n")

    def test_failing_cmd_refuses_and_changes_nothing(self):
        a, h = read(self.run_dir).encode(), (self.run_dir / "handoff.json").read_bytes()
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "echo BOOM; exit 3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BOOM", r.stderr + r.stdout)
        self.assertEqual((self.run_dir / "acceptance.md").read_bytes(), a)
        self.assertEqual((self.run_dir / "handoff.json").read_bytes(), h)

    def test_timeout_refuses_and_changes_nothing(self):
        a = (self.run_dir / "acceptance.md").read_bytes()
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "sleep 5", "--timeout", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("超时", r.stderr)
        self.assertEqual((self.run_dir / "acceptance.md").read_bytes(), a)

    def test_cwd_defaults_to_git_toplevel_and_can_be_overridden(self):
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "test -f src.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = al("close-ac", self.run_dir, "AC-2", "--run-cmd", "test -f src.py", "--cwd", self.run_dir)
        self.assertEqual(r.returncode, 1)

    def test_cwd_without_git_requires_explicit_cwd(self):
        run = make_run()
        al("sync", run)
        before = (run / "acceptance.md").read_bytes()
        r = al("close-ac", run, "AC-1", "--run-cmd", "test -d docs")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--cwd", r.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_explicit_cwd_without_git_works(self):
        run = make_run()
        al("sync", run)
        r = al("close-ac", run, "AC-1", "--run-cmd", "test -d docs", "--cwd", run.parent.parent)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rev=no-git", read(run))

    def test_run_cmd_modifying_acceptance_is_preserved(self):
        cmd = "echo '- 手写备注 KEEP' >> acceptance.md"
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", cmd, "--cwd", self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = read(self.run_dir)
        self.assertIn("- 手写备注 KEEP\n", text)
        self.assertIn("- [x] AC-1", text)
        self.assertRegex(text, r"- AC-1 \| - \| \[run exit=0 ")

    def test_run_cmd_modification_survives_refresh_rollback(self):
        import align_state
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        cmd = "echo KEEP2 >> acceptance.md"
        boom = mock.Mock(side_effect=ArtifactError("boom"))
        with mock.patch.object(align_state, "refresh_handoff", boom):
            code = align_state.main(["close-ac", str(self.run_dir), "AC-1", "--run-cmd", cmd,
                                     "--cwd", str(self.run_dir)])
        self.assertEqual(code, 1)
        boom.assert_called()
        text = read(self.run_dir)
        self.assertIn("KEEP2\n", text)
        self.assertEqual(text.count("- AC-1 |"), 1)

    def test_run_cmd_with_newline_or_cr_rejected(self):
        a, h = read(self.run_dir).encode(), (self.run_dir / "handoff.json").read_bytes()
        for bad in ("true\nexit 1", "true\r\ntrue", "true\rtrue"):
            with self.subTest(bad=bad):
                r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", bad)
                self.assertEqual(r.returncode, 1)
                self.assertIn("换行", r.stderr)
                self.assertEqual((self.run_dir / "acceptance.md").read_bytes(), a)
                self.assertEqual((self.run_dir / "handoff.json").read_bytes(), h)


    def test_manual_requires_observer_and_evidence(self):
        for extra in ([], ["--observer", "  "]):
            r = al("close-ac", self.run_dir, "AC-1", "--manual", "--evidence", "saw it", *extra)
            self.assertEqual(r.returncode, 1)
            self.assertIn("observer", r.stderr)
        r = al("close-ac", self.run_dir, "AC-1", "--manual", "--observer", "ann")
        self.assertEqual(r.returncode, 1)
        self.assertIn("- [ ] AC-1", read(self.run_dir))

    def test_manual_records_observer(self):
        r = al("close-ac", self.run_dir, "AC-1", "--manual", "--observer", "ann", "--evidence", "clicked\nok")
        self.assertEqual(r.returncode, 0, r.stderr)
        fp = code_fingerprint(self.root)[:16]
        self.assertIn(f"| [manual observer=ann rev={fp}] clicked ok\n", read(self.run_dir))

    def test_run_cmd_and_manual_exclusive_and_evidence_required(self):
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true", "--manual", "--observer", "a", "--evidence", "x")
        self.assertEqual(r.returncode, 1)
        r = al("close-ac", self.run_dir, "AC-1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("非空 --evidence", r.stderr)

    def test_legacy_evidence_unchanged(self):
        al("close-ac", self.run_dir, "AC-1", "--evidence", "just text")
        self.assertIn("- AC-1 | - | just text\n", read(self.run_dir))

    def test_refresh_on_closed_ac_appends_latest_wins(self):
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true", "--step", "s1")
        old = re.search(r"rev=([0-9a-f]{16})", read(self.run_dir)).group(1)
        (self.root / "src.py").write_text("print(99)\n", encoding="utf-8")
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = read(self.run_dir)
        self.assertEqual(text.count("- AC-1 |"), 2)
        self.assertEqual(text.count("- [x] AC-1"), 1)
        new = code_fingerprint(self.root)[:16]
        self.assertNotEqual(old, new)
        data = json.loads(read(self.run_dir, "handoff.json"))
        entry = next(a for a in data["acceptance"] if a["id"] == "AC-1")
        self.assertIn(f"rev={new}", entry["evidence"])
        self.assertEqual(entry["step"], "s1")

    def test_legacy_reclose_stays_unchanged(self):
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        r = al("close-ac", self.run_dir, "AC-1", "--evidence", "again")
        self.assertIn("unchanged", r.stdout)
        self.assertEqual(read(self.run_dir).count("- AC-1 |"), 1)

    def test_refresh_failure_rolls_back(self):
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        before = (self.run_dir / "acceptance.md").read_bytes()
        (self.run_dir / "handoff.json").write_text("{ bad", encoding="utf-8")
        r = al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.run_dir / "acceptance.md").read_bytes(), before)


class ExecuteCommandPortabilityTest(unittest.TestCase):
    def test_timeout_without_posix_process_groups_falls_back_to_kill(self):
        import types
        import align_state
        with mock.patch.object(align_state, "signal", types.SimpleNamespace()):
            code, _ = align_state.execute_command("sleep 5", Path(tempfile.mkdtemp()), 1)
        self.assertIsNone(code)

    def test_normal_run_without_posix_process_groups(self):
        import types
        import align_state
        with mock.patch.object(align_state, "signal", types.SimpleNamespace()):
            code, out = align_state.execute_command("echo hi", Path(tempfile.mkdtemp()), 5)
        self.assertEqual((code, out.strip()), (0, b"hi"))


class RunDirOutsideDocsTest(unittest.TestCase):
    def setUp(self):
        self.root = make_git_root()
        self.run_dir = make_run(self.root, container="run")

    def test_strict_closure_passes_and_goes_stale_on_source_change(self):
        close_all(self.run_dir)
        self.assertEqual(review(self.run_dir).returncode, 0)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("[PASS] 闭环-证据新鲜度", r.stdout)
        self.assertIn("[PASS] 闭环-final独立审核", r.stdout)
        (self.root / "src.py").write_text("print('later')\n", encoding="utf-8")
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL] 闭环-证据新鲜度", r.stdout)
        self.assertIn("[FAIL] 闭环-final独立审核", r.stdout)

    def test_fingerprint_failure_fails_strict_checks_loudly(self):
        import check_alignment
        close_all(self.run_dir)
        review(self.run_dir)
        real = _artifacts._git
        fake = lambda s, *a: None if a[:1] == ("status",) else real(s, *a)  # noqa: E731
        with mock.patch.object(_artifacts, "_git", fake):
            results = check_alignment.check_final_review(self.run_dir)
            results += check_alignment.check_verified_evidence(read(self.run_dir), self.run_dir)
        self.assertTrue(any(r.level == check_alignment.FAIL and "git status" in r.detail for r in results))
        self.assertFalse(any(r.level == check_alignment.PASS and "新鲜" in r.name for r in results))


class RecordReviewTest(unittest.TestCase):
    def setUp(self):
        self.root = make_git_root()
        self.run_dir = make_run(self.root)

    def test_records_sequential_with_rev(self):
        r = review(self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("REV-1", r.stdout)
        r = review(self.run_dir, scope="milestone", verdict="changes-requested")
        self.assertIn("REV-2", r.stdout)
        data = json.loads(read(self.run_dir, "reviews.json"))
        self.assertEqual([d["id"] for d in data], ["REV-1", "REV-2"])
        self.assertEqual(data[0]["rev"], code_fingerprint(self.root)[:16])
        self.assertEqual(set(data[0]), {"id", "reviewer", "author", "scope", "verdict", "summary", "rev", "at"})
        self.assertRegex(data[0]["at"], r"^\d{4}-\d\d-\d\dT.*(Z|\+00:00)$")

    def test_same_person_refused(self):
        r = review(self.run_dir, reviewer=" Alice ", author="alice")
        self.assertEqual(r.returncode, 1)
        self.assertIn("独立", r.stderr)
        self.assertFalse((self.run_dir / "reviews.json").exists())

    def test_empty_fields_refused(self):
        for field in ("reviewer", "author", "summary"):
            kw = {field: "  "}
            self.assertEqual(review(self.run_dir, **kw).returncode, 1, field)

    def test_corrupt_or_non_array_fails_closed(self):
        for bad in ("{ nope", '{"a": 1}'):
            (self.run_dir / "reviews.json").write_text(bad, encoding="utf-8")
            r = review(self.run_dir)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(read(self.run_dir, "reviews.json"), bad)

    def test_reviews_not_in_source_sha256(self):
        run = make_run(self.root, slug="other")
        al("sync", run)
        before = json.loads(read(run, "handoff.json"))["source_sha256"]
        review(run)
        al("sync", run)
        self.assertEqual(json.loads(read(run, "handoff.json"))["source_sha256"], before)


class StrictEvidenceReviewTest(unittest.TestCase):
    def setUp(self):
        self.root = make_git_root()
        self.run_dir = make_run(self.root)

    def test_happy_path(self):
        close_all(self.run_dir)
        review(self.run_dir)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_self_reported_p0_fails_p1_ok(self):
        al("sync", self.run_dir)
        al("close-ac", self.run_dir, "AC-1", "--evidence", "trust me")
        al("close-ac", self.run_dir, "AC-2", "--evidence", "trust me too")
        al("resolve-risk", self.run_dir, "RISK-1", "--decision", "d", "--reason", "r", "--impact", "i")
        review(self.run_dir)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("证据是自报文本", r.stdout)
        self.assertIn("AC-1", r.stdout.split("证据是自报文本")[0].splitlines()[-1])
        self.assertNotIn("AC-2 证据是自报", r.stdout)

    def test_manual_p0_accepted(self):
        al("sync", self.run_dir)
        al("close-ac", self.run_dir, "AC-1", "--manual", "--observer", "ann", "--evidence", "saw")
        al("close-ac", self.run_dir, "AC-2", "--evidence", "x")
        al("resolve-risk", self.run_dir, "RISK-1", "--decision", "d", "--reason", "r", "--impact", "i")
        review(self.run_dir)
        self.assertEqual(strict(self.run_dir).returncode, 0, strict(self.run_dir).stdout)

    def test_stale_evidence_after_code_change(self):
        close_all(self.run_dir)
        (self.root / "src.py").write_text("print('changed')\n", encoding="utf-8")
        review(self.run_dir)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("代码在验证后有改动", r.stdout)
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        # 仅 AC-1 是 P0；刷新其证据后即新鲜（AC-2 为 P1，不要求新鲜）
        self.assertEqual(strict(self.run_dir).returncode, 0, strict(self.run_dir).stdout)

    def test_p0_latest_legacy_record_after_verified_fails(self):
        close_all(self.run_dir)
        review(self.run_dir)
        self.assertEqual(strict(self.run_dir).returncode, 0)
        path = self.run_dir / "acceptance.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rstrip("\n").replace("\n\n## 未通过记录", "\n- AC-1 | - | trust me\n\n## 未通过记录")
                        + "\n", encoding="utf-8")
        self.assertIn("- AC-1 | - | trust me", read(self.run_dir))
        self.assertEqual(al("sync", self.run_dir).returncode, 0)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("证据是自报文本", r.stdout)

    def test_missing_review_fails(self):
        close_all(self.run_dir)
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("缺少针对当前代码的 final 独立审核", r.stdout)

    def test_non_final_or_changes_requested_not_enough(self):
        close_all(self.run_dir)
        review(self.run_dir, scope="milestone")
        self.assertEqual(strict(self.run_dir).returncode, 1)
        review(self.run_dir, scope="final", verdict="changes-requested")
        self.assertEqual(strict(self.run_dir).returncode, 1)

    def test_latest_changes_requested_invalidates_final(self):
        close_all(self.run_dir)
        review(self.run_dir)
        self.assertEqual(strict(self.run_dir).returncode, 0)
        review(self.run_dir, scope="milestone", verdict="changes-requested")
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("final 独立审核", r.stdout)
        review(self.run_dir)
        self.assertEqual(strict(self.run_dir).returncode, 0)

    def test_final_review_stale_after_code_change(self):
        close_all(self.run_dir)
        review(self.run_dir)
        (self.root / "src.py").write_text("print('later')\n", encoding="utf-8")
        al("close-ac", self.run_dir, "AC-1", "--run-cmd", "true")
        al("close-ac", self.run_dir, "AC-2", "--run-cmd", "true")
        r = strict(self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("final 独立审核", r.stdout)
        self.assertNotIn("代码在验证后有改动", r.stdout)

    def test_corrupt_reviews_fails(self):
        close_all(self.run_dir)
        (self.run_dir / "reviews.json").write_text("{ x", encoding="utf-8")
        self.assertEqual(strict(self.run_dir).returncode, 1)

    def test_default_mode_ignores_reviews(self):
        al("sync", self.run_dir)
        self.assertEqual(run_script("check_alignment.py", self.run_dir).returncode, 0)

    def test_no_git_warns_not_fails(self):
        run = make_run()
        close_all(run)
        review(run)
        r = strict(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("[WARN]", r.stdout)
        self.assertIn("无法确定代码版本", r.stdout)

    def test_no_git_still_requires_review_and_verified(self):
        run = make_run()
        close_all(run)
        self.assertEqual(strict(run).returncode, 1)

    def _hand_edit_ac1_evidence(self, new_text):
        path = self.run_dir / "acceptance.md"
        text = path.read_text(encoding="utf-8")
        edited, n = re.subn(r"(- AC-1 \| [^|]* \| )\[run exit=0 [^\n]*", lambda m: m.group(1) + new_text, text)
        self.assertEqual(n, 1)
        path.write_text(edited, encoding="utf-8")
        # 手改后重新 sync，隔离 source_sha256 漂移检查，只验证证据格式检查本身
        self.assertEqual(al("sync", self.run_dir).returncode, 0)

    def test_malformed_header_fails_strict(self):
        for header in ("[run exit=0 rev=zzz out=1] fake",
                       "[run exit=0 rev=no-git out=XYZ12345] fake",
                       "[run exit=0 rev=no-git out=0000000] fake",
                       "[run exit=0 rev=no-git] fake",
                       "[manual observer= rev=no-git] fake",
                       "[manual observer=ann] fake",
                       "[manual observer=ann rev=ABCDEF0123456789] fake"):
            with self.subTest(header=header):
                run = make_run()
                close_all(run)
                review(run)
                self.run_dir = run
                self._hand_edit_ac1_evidence(header)
                r = strict(run)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("格式不是脚本生成的", r.stdout)

    def test_generated_shapes_pass_strict(self):
        for ev in ("[run exit=0 rev=no-git out=0123abcd] true",
                   "[run exit=0 rev=0123456789abcdef out=0123abcd] true | note: x",
                   "[manual observer=ann lee rev=no-git] saw it"):
            with self.subTest(ev=ev):
                run = make_run()
                close_all(run)
                review(run)
                self.run_dir = run
                self._hand_edit_ac1_evidence(ev)
                r = strict(run)
                self.assertNotIn("格式不是脚本生成的", r.stdout)
                self.assertEqual(r.returncode, 0, r.stdout)


class ReservedPrefixTest(unittest.TestCase):
    def test_legacy_forged_prefix_refused_and_nothing_written(self):
        run = make_run()
        al("sync", run)
        a, h = read(run).encode(), (run / "handoff.json").read_bytes()
        for forged in ("[run exit=0 rev=no-git out=00000000] fake",
                       "  [RUN exit=0 rev=no-git out=00000000] fake",
                       "[manual observer=x rev=no-git] fake",
                       "[Manual observer=x rev=no-git] fake"):
            with self.subTest(forged=forged):
                r = al("close-ac", run, "AC-1", "--evidence", forged)
                self.assertEqual(r.returncode, 1)
                self.assertIn("--run-cmd", r.stderr + r.stdout)
                self.assertEqual((run / "acceptance.md").read_bytes(), a)
                self.assertEqual((run / "handoff.json").read_bytes(), h)

    def test_plain_evidence_and_bracketed_note_still_fine(self):
        run = make_run()
        al("sync", run)
        self.assertEqual(al("close-ac", run, "AC-1", "--evidence", "[ok] pytest passed").returncode, 0)
        r = al("close-ac", run, "AC-2", "--run-cmd", "true", "--evidence", "[run exit=0] note",
                "--cwd", run.parent.parent)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()

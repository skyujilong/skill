"""align_state.py 与 check_alignment.py 的行为契约测试。

重点覆盖那些"本该由脚本兜住、否则会退化成事后自觉"的行为：
证据非空、状态列与决议段原子同步、契约与 Markdown 一致、收尾门禁。
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fixture import make_run, run_script  # noqa: E402


class SyncTest(unittest.TestCase):
    def test_sync_derives_contract_from_markdown(self):
        run = make_run()
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(data["slug"], "demo")
        self.assertEqual(data["date"], "2026-09-02")
        self.assertEqual(data["next_stage"], "exec-plan")
        self.assertEqual([a["id"] for a in data["acceptance"]], ["AC-1", "AC-2"])
        self.assertEqual(len(data["risks"]), 6)
        self.assertTrue(all(not a["closed"] for a in data["acceptance"]))

    def test_sync_writes_source_sha256_of_current_bytes(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        hashes = data["source_sha256"]
        self.assertEqual(set(hashes), {"align.md", "arch-risk.md", "acceptance.md"})
        for name, digest in hashes.items():
            self.assertEqual(digest,
                             hashlib.sha256((run / name).read_bytes()).hexdigest())

    def test_duplicate_ac_id_is_rejected(self):
        run = make_run()
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- AC-2 (P1)", "- AC-1 (P1)"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("重复", result.stderr)

    def test_ac_set_mismatch_between_align_and_acceptance_is_rejected(self):
        run = make_run()
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [ ] AC-2", "- [ ] AC-9"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("不一致", result.stderr)

    def test_bad_directory_name_is_rejected(self):
        run = make_run(slug="demo")
        renamed = run.parent / "req-align-demo"
        run.rename(renamed)
        result = run_script("align_state.py", "sync", renamed)
        self.assertEqual(result.returncode, 1)
        self.assertIn("目录名不合规范", result.stderr)


class CloseAcTest(unittest.TestCase):
    def test_evidence_is_mandatory(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "   ")
        self.assertEqual(result.returncode, 1)
        self.assertIn("非空 --evidence", result.stderr)
        self.assertIn("- [ ] AC-1", (run / "acceptance.md").read_text(encoding="utf-8"))

    def test_close_ticks_box_records_evidence_and_updates_contract(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "close-ac", run, "AC-1",
                            "--evidence", "pytest tests/test_x.py", "--step", "03-core")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (run / "acceptance.md").read_text(encoding="utf-8")
        self.assertIn("- [x] AC-1", text)
        self.assertIn("- AC-1 | 03-core | pytest tests/test_x.py", text)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        entry = next(a for a in data["acceptance"] if a["id"] == "AC-1")
        self.assertTrue(entry["closed"])
        self.assertEqual(entry["evidence"], "pytest tests/test_x.py")
        self.assertEqual(entry["step"], "03-core")

    def test_close_is_idempotent(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "first")
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "second")
        self.assertEqual(result.returncode, 0)
        self.assertIn("unchanged", result.stdout)
        text = (run / "acceptance.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("- AC-1 |"), 1)

    def test_unknown_ac_is_rejected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "close-ac", run, "AC-99", "--evidence", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("找不到 AC-99", result.stderr)

    def test_fail_ac_unticks_and_records(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        result = run_script("align_state.py", "fail-ac", run, "AC-1", "--observed", "行为不符")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (run / "acceptance.md").read_text(encoding="utf-8")
        self.assertIn("- [ ] AC-1", text)
        self.assertIn("- AC-1 | 行为不符", text)


class ClosedContractGuardTest(unittest.TestCase):
    """已勾选关闭的 AC 改了优先级或文本 → sync 拒绝，须先 fail-ac 重开。"""

    def _close_ac1(self, run: Path):
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_text_change_on_closed_ac_blocks_sync(self):
        run = make_run()
        self._close_ac1(run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("fail-ac", result.stderr)

    def test_priority_change_on_closed_ac_blocks_sync(self):
        run = make_run()
        self._close_ac1(run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- AC-1 (P0)", "- AC-1 (P2)"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("fail-ac", result.stderr)

    def test_fail_ac_reopen_then_sync_keeps_open(self):
        run = make_run()
        self._close_ac1(run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        result = run_script("align_state.py", "fail-ac", run, "AC-1",
                            "--observed", "验收描述已变更")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        entry = next(a for a in data["acceptance"] if a["id"] == "AC-1")
        self.assertFalse(entry["closed"])
        self.assertEqual(entry["text"], "输入 X1 → 输出 Z1")

    def test_new_ac_id_is_allowed(self):
        run = make_run()
        self._close_ac1(run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- AC-2 (P1) 输入 X2 → 输出 Y2",
            "- AC-2 (P1) 输入 X2 → 输出 Y2\n- AC-3 (P2) 输入 X3 → 输出 Y3"),
            encoding="utf-8")
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [ ] AC-2 输入 X2 → 输出 Y2",
            "- [ ] AC-2 输入 X2 → 输出 Y2\n- [ ] AC-3 输入 X3 → 输出 Y3"),
            encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual([a["id"] for a in data["acceptance"]], ["AC-1", "AC-2", "AC-3"])


class PreflightDriftTest(unittest.TestCase):
    """任一写命令前都必须先过"已关闭 AC 漂移"门卫：另一个 AC 漂移时，
    本次写操作整体拒绝且目标文件字节级不变。"""

    def _run_with_drifted_closed_ac(self) -> Path:
        run = make_run()
        run_script("align_state.py", "sync", run)
        for ac in ("AC-1", "AC-2"):
            result = run_script("align_state.py", "close-ac", run, ac,
                                "--evidence", f"e-{ac}")
            self.assertEqual(result.returncode, 0, result.stderr)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        return run

    def test_fail_other_ac_rejected_with_files_unchanged(self):
        run = self._run_with_drifted_closed_ac()
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "fail-ac", run, "AC-2",
                            "--observed", "现象")
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("fail-ac", result.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_close_other_ac_rejected_with_files_unchanged(self):
        run = self._run_with_drifted_closed_ac()
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "close-ac", run, "AC-2",
                            "--evidence", "again")
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_resolve_risk_rejected_with_risk_file_unchanged(self):
        run = self._run_with_drifted_closed_ac()
        before = (run / "arch-risk.md").read_bytes()
        result = run_script("align_state.py", "resolve-risk", run, "RISK-1",
                            "--decision", "d", "--reason", "r", "--impact", "i")
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertEqual((run / "arch-risk.md").read_bytes(), before)

    def test_fail_drifted_ac_itself_succeeds_and_updates_handoff(self):
        run = self._run_with_drifted_closed_ac()
        result = run_script("align_state.py", "fail-ac", run, "AC-1",
                            "--observed", "验收描述已变更")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        entry = next(a for a in data["acceptance"] if a["id"] == "AC-1")
        self.assertFalse(entry["closed"])
        self.assertEqual(entry["text"], "输入 X1 → 输出 Z1")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_corrupt_handoff_fails_sync_without_overwrite(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        handoff = run / "handoff.json"
        handoff.write_text("{ not json", encoding="utf-8")
        before = handoff.read_bytes()
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON", result.stderr)
        self.assertEqual(handoff.read_bytes(), before)

    def test_non_object_handoff_fails_sync(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        (run / "handoff.json").write_text("[]\n", encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("对象", result.stderr)

    def test_corrupt_handoff_rejects_close_ac_before_write(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        (run / "handoff.json").write_text("{ not json", encoding="utf-8")
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON", result.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_corrupt_handoff_rejects_fail_ac_before_write(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        (run / "handoff.json").write_text("{ not json", encoding="utf-8")
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "fail-ac", run, "AC-1", "--observed", "y")
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON", result.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_evidence_after_second_separator_is_preserved(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        for ac in ("AC-1", "AC-2"):
            result = run_script("align_state.py", "close-ac", run, ac,
                                "--evidence", "pytest -q | tee log.txt",
                                "--step", "03-a")
            self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        for entry in data["acceptance"]:
            self.assertEqual(entry["evidence"], "pytest -q | tee log.txt")
            self.assertEqual(entry["step"], "03-a")
        run_script("align_state.py", "resolve-risk", run, "RISK-1",
                   "--decision", "d", "--reason", "r", "--impact", "i")
        # P0 证据需脚本验证 + final 独立审核，strict 才放行
        run_script("align_state.py", "close-ac", run, "AC-1", "--run-cmd", "true",
                   "--cwd", run.parent.parent)
        run_script("align_state.py", "record-review", run, "--reviewer", "bob", "--author", "alice",
                   "--scope", "final", "--verdict", "approved", "--summary", "ok")
        strict = run_script("check_alignment.py", run, "--strict-closure")
        self.assertEqual(strict.returncode, 0, strict.stdout)


class ResolveRiskTest(unittest.TestCase):
    def test_status_column_and_decision_block_move_together(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "resolve-risk", run, "RISK-1",
                            "--decision", "归 gateway", "--reason", "职责单一",
                            "--impact", "下游只消费")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (run / "arch-risk.md").read_text(encoding="utf-8")
        self.assertIn("| RISK-1 | 数据流边界 | 生产者消费者未定 | — | 架构发现 | 已决议 |", text)
        self.assertIn("### RISK-1 — 数据流边界", text)
        self.assertIn("- 决议: 归 gateway", text)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(next(r for r in data["risks"] if r["id"] == "RISK-1")["state"], "已决议")

    def test_unhit_risk_cannot_be_resolved(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "resolve-risk", run, "RISK-2",
                            "--decision", "d", "--reason", "r", "--impact", "i")
        self.assertEqual(result.returncode, 1)
        self.assertIn("未命中", result.stderr)

    def test_second_resolution_is_rejected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "resolve-risk", run, "RISK-1",
                   "--decision", "d", "--reason", "r", "--impact", "i")
        result = run_script("align_state.py", "resolve-risk", run, "RISK-1",
                            "--decision", "d2", "--reason", "r2", "--impact", "i2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("已决议", result.stderr)


class StageAddTest(unittest.TestCase):
    def _sdd(self, run: Path, name: str, files=("README.md", "01-overview.md",
                                                "acceptance-matrix.md")) -> Path:
        target = run.parent / name
        target.mkdir(parents=True, exist_ok=True)
        for filename in files:
            (target / filename).write_text("x\n", encoding="utf-8")
        return target

    def test_registers_valid_stage(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "sdd-2026-09-02-demo")
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((run / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stages"][0]["stage"], "sdd")

    def test_rejects_directory_without_upstream_slug(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "sdd-2026-09-02-other")
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 1)
        self.assertIn("未继承上游 slug", result.stderr)

    def test_rejects_missing_mandatory_files(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "sdd-2026-09-02-demo", files=("README.md",))
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 1)
        self.assertIn("缺少强制文件", result.stderr)

    def test_rejects_slug_suffix_directory(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "sdd-2026-09-02-demo-extra")
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 1)
        self.assertIn("目录名不合规范", result.stderr)

    def test_rejects_stage_dir_not_sibling_of_run_dir(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = run.parent.parent / "elsewhere" / "sdd-2026-09-02-demo"
        stage.mkdir(parents=True)
        for filename in ("README.md", "01-overview.md", "acceptance-matrix.md"):
            (stage / filename).write_text("x\n", encoding="utf-8")
        handoff_before = (run / "handoff.json").read_bytes()
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 1)
        self.assertIn("同级", result.stderr)
        self.assertEqual((run / "handoff.json").read_bytes(), handoff_before)

    def test_accepts_slug_ending_with_increment(self):
        run = make_run(slug="demo-2")
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "sdd-2026-09-02-demo-2")
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_wrong_prefix(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        stage = self._sdd(run, "spec-2026-09-02-demo")
        result = run_script("align_state.py", "stage-add", run, "--stage", "sdd",
                            "--dir", stage)
        self.assertEqual(result.returncode, 1)
        self.assertIn("目录名不合规范", result.stderr)


class HandoffHistoryGuardTest(unittest.TestCase):
    """handoff.json 缺失/被手动回退时，sync 不得静默重置"已关闭"历史。"""

    def _closed_run(self) -> Path:
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        self.assertEqual(result.returncode, 0, result.stderr)
        return run

    def test_deleted_handoff_with_ticked_box_refuses_sync(self):
        run = self._closed_run()
        (run / "handoff.json").unlink()
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("handoff.json", result.stderr)
        self.assertFalse((run / "handoff.json").exists())

    def test_fresh_run_without_handoff_still_syncs(self):
        run = make_run()
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hand_unchecked_closed_ac_with_edited_text_refuses_sync(self):
        run = self._closed_run()
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [x] AC-1", "- [ ] AC-1"), encoding="utf-8")
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        before = (run / "handoff.json").read_bytes()
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("fail-ac", result.stderr)
        self.assertEqual((run / "handoff.json").read_bytes(), before)

    def test_fail_ac_edit_sync_flow_still_succeeds(self):
        run = self._closed_run()
        result = run_script("align_state.py", "fail-ac", run, "AC-1", "--observed", "o")
        self.assertEqual(result.returncode, 0, result.stderr)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)


class RollbackOnRefreshFailureTest(unittest.TestCase):
    """Markdown 写入后 refresh_handoff 失败 → 回滚到原字节并报错。"""

    def _broken_run(self) -> Path:
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace("去向: 执行计划\n", ""),
                        encoding="utf-8")
        return run

    def test_close_ac_rolls_back(self):
        run = self._broken_run()
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("去向", result.stderr)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_fail_ac_rolls_back(self):
        run = self._broken_run()
        before = (run / "acceptance.md").read_bytes()
        result = run_script("align_state.py", "fail-ac", run, "AC-1", "--observed", "o")
        self.assertEqual(result.returncode, 1)
        self.assertEqual((run / "acceptance.md").read_bytes(), before)

    def test_resolve_risk_rolls_back(self):
        run = self._broken_run()
        before = (run / "arch-risk.md").read_bytes()
        result = run_script("align_state.py", "resolve-risk", run, "RISK-1",
                            "--decision", "d", "--reason", "r", "--impact", "i")
        self.assertEqual(result.returncode, 1)
        self.assertEqual((run / "arch-risk.md").read_bytes(), before)


class CheckAlignmentTest(unittest.TestCase):
    def test_fresh_run_passes_default_but_fails_strict_closure(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        default = run_script("check_alignment.py", run)
        self.assertEqual(default.returncode, 0, default.stdout)
        strict = run_script("check_alignment.py", run, "--strict-closure")
        self.assertEqual(strict.returncode, 1)
        self.assertIn("闭环-验收勾选", strict.stdout)

    def test_strict_closure_passes_when_fully_closed(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        for ac in ("AC-1", "AC-2"):
            run_script("align_state.py", "close-ac", run, ac, "--run-cmd", "true",
                       "--cwd", run.parent.parent)
        run_script("align_state.py", "resolve-risk", run, "RISK-1",
                   "--decision", "d", "--reason", "r", "--impact", "i")
        run_script("align_state.py", "record-review", run, "--reviewer", "bob", "--author", "alice",
                   "--scope", "final", "--verdict", "approved", "--summary", "ok")
        strict = run_script("check_alignment.py", run, "--strict-closure")
        self.assertEqual(strict.returncode, 0, strict.stdout)

    def test_category_coverage_is_warn_not_fail(self):
        """六类覆盖实测已达 ~97%，因此只提示不阻断——不给已被遵守的规则加硬门禁。

        行数硬门槛是另一回事：6 行齐备但类别命名不同义 → WARN；少于 6 行 → FAIL。
        """
        run = make_run()
        path = run / "arch-risk.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "| RISK-6 | 可验证性 |", "| RISK-6 | 成本与配额 |"), encoding="utf-8")
        run_script("align_state.py", "sync", run)
        result = run_script("check_alignment.py", run)
        self.assertIn("[WARN] 清单类别覆盖", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_fewer_than_six_scan_rows_fails(self):
        run = make_run()
        path = run / "arch-risk.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "| RISK-6 | 可验证性 | 未命中 | — | — | 未命中 |\n", ""), encoding="utf-8")
        run_script("align_state.py", "sync", run)
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("边界风险扫描", result.stdout)

    def test_six_scan_rows_pass_count_gate(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("扫描表列出 6 条边界", result.stdout)

    def test_hand_edited_status_column_is_detected_as_drift(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "arch-risk.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "| 架构发现 | 待验证 |", "| 架构发现 | 已决议 |"), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("状态为「已决议」但无决议段", result.stdout)

    def test_stale_handoff_is_detected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [ ] AC-1", "- [x] AC-1"), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("契约与 Markdown 一致", result.stdout)

    def test_handoff_text_drift_is_detected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "输入 X1 → 输出 Y1", "输入 X1 → 输出 Z1"), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("契约与 Markdown 一致", result.stdout)

    def test_handoff_priority_drift_is_detected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "align.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- AC-1 (P0)", "- AC-1 (P2)"), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("契约与 Markdown 一致", result.stdout)

    def test_checkbox_text_drift_is_detected(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- [ ] AC-1 输入 X1 → 输出 Y1",
            "- [ ] AC-1 输入 X1 → 输出 W1"), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC 文本一致", result.stdout)

    def test_strict_closure_rejects_blank_evidence_content(self):
        run = make_run()
        path = run / "acceptance.md"
        text = path.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
        text = text.replace("## 证据\n",
                            "## 证据\n\n- AC-1 |\n- AC-2 | 03-x |\n")
        path.write_text(text, encoding="utf-8")
        result = run_script("check_alignment.py", run, "--strict-closure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("闭环-证据", result.stdout)

    def test_strict_closure_accepts_two_part_evidence_record(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "acceptance.md"
        text = path.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
        text = text.replace("## 证据\n",
                            "## 证据\n\n- AC-1 | [run exit=0 rev=no-git out=00000000] pytest ok\n- AC-2 | 03-x | manual ok\n")
        path.write_text(text, encoding="utf-8")
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "resolve-risk", run, "RISK-1",
                   "--decision", "d", "--reason", "r", "--impact", "i")
        run_script("align_state.py", "record-review", run, "--reviewer", "bob", "--author", "alice",
                   "--scope", "final", "--verdict", "approved", "--summary", "ok")
        result = run_script("check_alignment.py", run, "--strict-closure")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_unsynced_acceptance_edit_fails_hash_gate(self):
        """仅注释级改动也会改变字节——hash 门禁必须抓住解析层面看不出的漂移。"""
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- comment -->\n",
                        encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_sha256", result.stdout)
        self.assertIn("sync", result.stdout)

    def test_unsynced_arch_risk_edit_fails_hash_gate(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "arch-risk.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- comment -->\n",
                        encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_sha256", result.stdout)

    def test_handoff_missing_source_sha256_fails(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "handoff.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("source_sha256")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_sha256", result.stdout)

    def test_resync_after_edit_makes_checker_pass(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "acceptance.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- comment -->\n",
                        encoding="utf-8")
        run_script("align_state.py", "sync", run)
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 0, result.stdout)

    def _check_with_handoff_patch(self, **patch):
        run = make_run()
        run_script("align_state.py", "sync", run)
        path = run / "handoff.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(patch)
        path.write_text(json.dumps(data), encoding="utf-8")
        return run_script("check_alignment.py", run)

    def test_non_dict_acceptance_entries_fail_cleanly(self):
        result = self._check_with_handoff_patch(acceptance=["AC-1"])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_list_risks_fail_cleanly(self):
        result = self._check_with_handoff_patch(risks="oops")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_dict_risk_entries_fail_cleanly(self):
        result = self._check_with_handoff_patch(risks=[1, 2])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_object_handoff_fails_cleanly(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        (run / "handoff.json").write_text("[]", encoding="utf-8")
        result = run_script("check_alignment.py", run)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_history_dir_degrades_with_warn(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = run_script("check_alignment.py", run)
        self.assertIn("已降级跳过 stale 检测", result.stdout)
        self.assertEqual(result.returncode, 0)


class MetricsTest(unittest.TestCase):
    def test_events_are_appended_and_never_break_the_flow(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        jsonl = run.parent.parent / "docs" / ".skill-metrics" / "runs.jsonl"
        self.assertTrue(jsonl.is_file())
        record = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["skill"], "req-align-v2")
        self.assertEqual(record["event"], "align_landed")

    def test_unwritable_metrics_dir_does_not_fail_the_command(self):
        """埋点是唯一允许静默降级的地方：观测绝不能弄挂主流程。"""
        run = make_run()
        metrics_dir = run.parent.parent / "docs" / ".skill-metrics"
        metrics_dir.parent.mkdir(parents=True, exist_ok=True)
        metrics_dir.write_text("not a directory\n", encoding="utf-8")
        result = run_script("align_state.py", "sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("synced", result.stdout)


if __name__ == "__main__":
    unittest.main()

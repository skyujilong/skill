"""final_gate.py 的行为契约测试：steps 门禁、上游链路门禁、缺参数、通用模式。

上游端到端用例通过子进程调用 req-align-v2 的脚本（不跨包 import）搭建真实 run。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REQ_ALIGN = Path(__file__).resolve().parent.parent.parent / "req-align-v2" / "scripts"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]

ALIGN = """# 需求对齐：demo

## 🎯 目标

目标。

## 📦 范围

✅ 支持:
- 能力一

⛔ 暂不支持:
- 排除项

## 🔼 优先级

- P0（必须）: 能力一

## ✅ 验收标准

- AC-1 (P0) 输入 X1 → 输出 Y1
- AC-2 (P1) 输入 X2 → 输出 Y2

## ➡️ 下一阶段

判定: 直接推进
去向: 执行计划
"""
RISK_ROWS = "\n".join(
    f"| RISK-{i} | {b} | 未命中 | — | — | {'待验证' if i == 1 else '未命中'} |"
    for i, b in enumerate(["数据流边界", "时序 / 事件流", "跨服务 / 跨模块",
                           "持久化与领域模型", "多 Agent / 外部 API 契约", "可验证性"], 1))
RISK = f"""# 风险

## 🧱 边界风险扫描

| ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
{RISK_ROWS}

## 📌 决议记录

<!-- append-only -->
"""
ACCEPT = """# 验收清单

- [ ] AC-1 输入 X1 → 输出 Y1
- [ ] AC-2 输入 X2 → 输出 Y2

## 证据

## 未通过记录
"""


def run_script(name: str, *args, scripts: Path = SCRIPTS, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(scripts / name), *[str(a) for a in args]],
                          capture_output=True, text=True, **kwargs)


def ra(name: str, *args):
    r = run_script(name, *args, scripts=REQ_ALIGN)
    assert r.returncode == 0, (name, args, r.stdout, r.stderr)


def make_generic(states=("complate", "complate")) -> Path:
    plan = Path(tempfile.mkdtemp()) / "docs" / "exec-plan-2026-09-02-demo"
    plan.mkdir(parents=True)
    steps = [{"step": f"0{i}-s", "state": s, "covers": [f"AC-{i}"]} for i, s in enumerate(states, 1)]
    (plan / "step.json").write_text(json.dumps(steps), encoding="utf-8")
    return plan


def make_linked(git: bool, states=("complate", "complate")) -> tuple:
    """真实 req-align run（经其脚本推进到可收尾）+ 链接的 plan；返回 (plan, run, root)。"""
    root = Path(tempfile.mkdtemp())
    if git:
        for cmd in (["init", "-q"],):
            subprocess.run(["git", *GIT_ID, "-C", str(root), *cmd], check=True, capture_output=True)
        (root / "src.py").write_text("print(1)\n", encoding="utf-8")
        subprocess.run(["git", *GIT_ID, "-C", str(root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", *GIT_ID, "-C", str(root), "commit", "-q", "-m", "i"],
                       check=True, capture_output=True)
    run = root / "docs" / "req-align-2026-09-02-demo"
    run.mkdir(parents=True)
    for name, text in (("align.md", ALIGN), ("arch-risk.md", RISK), ("acceptance.md", ACCEPT)):
        (run / name).write_text(text, encoding="utf-8")
    plan = root / "docs" / "exec-plan-2026-09-02-demo"
    plan.mkdir()
    steps = [{"step": f"0{i}-s", "state": s, "covers": [f"AC-{i}"]} for i, s in enumerate(states, 1)]
    (plan / "step.json").write_text(json.dumps(steps), encoding="utf-8")
    (plan / "upstream.json").write_text(json.dumps({
        "source": "req-align-v2", "contract_version": "1",
        "run_dir": f"../{run.name}", "slug": "demo"}), encoding="utf-8")
    (plan / "requirements.md").write_text(
        "# R\n\n## R1 a\n- Covers: AC-1\n\n## R2 b\n- Covers: AC-2\n", encoding="utf-8")
    ra("align_state.py", "sync", run)
    for ac in ("AC-1", "AC-2"):
        ra("align_state.py", "close-ac", run, ac, "--run-cmd", "true", "--cwd", root)
    ra("align_state.py", "resolve-risk", run, "RISK-1", "--decision", "d", "--reason", "r",
       "--impact", "i")
    return plan, run, root


def record_final_review(run: Path) -> None:
    ra("align_state.py", "record-review", run, "--reviewer", "bob", "--author", "alice",
       "--scope", "final", "--verdict", "approved", "--summary", "ok")


class GenericModeTest(unittest.TestCase):
    def test_all_complate_passes_and_is_labelled_generic(self):
        r = run_script("final_gate.py", make_generic())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("GENERIC", r.stdout)
        self.assertIn("[PASS] steps", r.stdout)
        self.assertIn("result: PASS", r.stdout)
        self.assertIn("does NOT run the project's own lint", r.stdout)

    def test_incomplete_steps_fail(self):
        r = run_script("final_gate.py", make_generic(("complate", "runing")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL] steps", r.stdout)
        self.assertIn("02-s", r.stdout)
        self.assertIn("result: FAIL", r.stdout)
        self.assertIn("does NOT run the project's own lint", r.stdout)

    def test_bad_arguments_exit_2(self):
        self.assertEqual(run_script("final_gate.py").returncode, 2)
        self.assertEqual(run_script("final_gate.py", "/nonexistent-dir-xyz").returncode, 2)


class LinkedModeTest(unittest.TestCase):
    def test_missing_req_align_scripts_exits_2(self):
        plan, run, _ = make_linked(git=False)
        r = run_script("final_gate.py", plan)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--req-align-scripts", r.stderr)

    def test_bad_req_align_scripts_dir_exits_2(self):
        plan, _, _ = make_linked(git=False)
        r = run_script("final_gate.py", plan, "--req-align-scripts", tempfile.mkdtemp())
        self.assertEqual(r.returncode, 2)

    def test_happy_path_in_git_repo(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for label in ("steps", "coverage", "strict-closure", "history-sync"):
            self.assertIn(f"[PASS] {label}", r.stdout)
        self.assertIn("result: PASS", r.stdout)

    def test_missing_final_review_fails_strict_closure(self):
        plan, run, _ = make_linked(git=True)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL] strict-closure", r.stdout)
        self.assertIn("final 独立审核", r.stdout)

    def test_code_change_after_verification_fails(self):
        plan, run, root = make_linked(git=True)
        record_final_review(run)
        (root / "src.py").write_text("print(2)\n", encoding="utf-8")
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL] strict-closure", r.stdout)

    def test_incomplete_steps_fail_even_if_upstream_ok(self):
        plan, run, _ = make_linked(git=True, states=("complate", "runing"))
        record_final_review(run)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL] steps", r.stdout)
        self.assertIn("[PASS] strict-closure", r.stdout)

    def test_no_git_warns_but_passes(self):
        plan, run, _ = make_linked(git=False)
        record_final_review(run)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        direct = run_script("check_alignment.py", run, "--strict-closure", scripts=REQ_ALIGN)
        self.assertIn("无法确定代码版本", direct.stdout)
        self.assertIn("[PASS] strict-closure", r.stdout)
        self.assertIn("WARN", r.stdout)
        self.assertIn("无法确定代码版本", r.stdout)

    def test_freshness_warn_not_printed_when_git_repo_is_fresh(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("无法确定代码版本", r.stdout)

    def test_unlocatable_run_dir_fails_upstream_line(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        shutil.rmtree(run)
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("[FAIL] upstream: cannot locate run dir", r.stdout)
        self.assertIn("result: FAIL", r.stdout)

    def test_req_align_scripts_without_boundary_state_fails_cleanly(self):
        plan, run, _ = make_linked(git=True)
        scripts = Path(tempfile.mkdtemp())
        shutil.copy(REQ_ALIGN / "check_alignment.py", scripts / "check_alignment.py")
        r = run_script("final_gate.py", plan, "--req-align-scripts", scripts)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("boundary_state.py", r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_works_from_a_different_cwd_absolute_and_relative_paths(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        other = Path(tempfile.mkdtemp()).resolve()
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN, cwd=str(other))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run_script("final_gate.py", os.path.relpath(plan, other),
                       "--req-align-scripts", os.path.relpath(REQ_ALIGN, other), cwd=str(other))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_decoy_run_dir_outside_sibling_is_refused(self):
        plan, run, root = make_linked(git=True)
        record_final_review(run)
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        moved = elsewhere / run.name
        shutil.move(str(run), str(moved))
        for value in (str(moved), f"../../elsewhere/{run.name}"):
            with self.subTest(run_dir=value):
                upstream = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
                upstream["run_dir"] = value
                (plan / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
                r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("[FAIL] upstream: cannot locate run dir", r.stdout)

    def test_gate_timeout_reports_fail_instead_of_hanging(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        scripts = Path(tempfile.mkdtemp())
        shutil.copy(REQ_ALIGN / "boundary_state.py", scripts / "boundary_state.py")
        (scripts / "check_alignment.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        env = dict(os.environ, FINAL_GATE_TIMEOUT="1")
        r = run_script("final_gate.py", plan, "--req-align-scripts", scripts, env=env, timeout=25)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("[FAIL] strict-closure", r.stdout)
        self.assertIn("timed out", r.stdout)
        self.assertIn("result: FAIL", r.stdout)

    def test_bad_contract_version_in_upstream_json_rejected(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        upstream = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
        upstream["contract_version"] = "2"
        (plan / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("contract_version", r.stderr)

    def test_absent_contract_version_in_upstream_json_accepted(self):
        plan, run, _ = make_linked(git=True)
        record_final_review(run)
        upstream = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
        upstream.pop("contract_version")
        (plan / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
        r = run_script("final_gate.py", plan, "--req-align-scripts", REQ_ALIGN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

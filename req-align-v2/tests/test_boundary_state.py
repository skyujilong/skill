"""boundary_state.py 的行为契约测试。

重点：覆盖必须**双向**可见——新 run 标记了覆盖，旧 run 也必须留下失效横幅。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fixture import make_run, run_script  # noqa: E402


def add_boundary(run: Path, module="服务归属", statement="旧模型：审批时填写服务配置", **kw):
    args = ["boundary_state.py", "add", "--run", run, "--module", module,
            "--statement", statement, "--confirmed-by", "human",
            "--gate-outcome", "adopted"]
    for key, value in kw.items():
        args += [f"--{key.replace('_', '-')}", value]
    return run_script(*args)


class GateTest(unittest.TestCase):
    def test_confirmed_by_and_gate_outcome_are_mandatory(self):
        """闸门结果做成必填参数：跳过闸门就写不进台账，不依赖事后自觉上报。"""
        run = make_run()
        result = run_script("boundary_state.py", "add", "--run", run,
                            "--module", "M", "--statement", "S")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirmed-by", result.stderr)

    def test_long_statement_is_rejected(self):
        run = make_run()
        result = add_boundary(run, statement="很长的结论" * 30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("一句话", result.stderr)


class AddTest(unittest.TestCase):
    def test_add_allocates_sequential_ids_and_links_risk(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        first = add_boundary(run, from_risk="RISK-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("BND-1", first.stdout)
        ledger = (run.parent / "req-align-history" / "boundaries.md").read_text(encoding="utf-8")
        self.assertIn("| BND-1 | 服务归属 |", ledger)
        self.assertIn("| 生效 | 2026-09-02-demo | — |", ledger)
        # --from-risk 会把风险行的「关联边界」列指向新 BND
        self.assertIn("| RISK-1 | 数据流边界 | 生产者消费者未定 | BND-1 |",
                      (run / "arch-risk.md").read_text(encoding="utf-8"))
        second = add_boundary(run, module="日志", statement="统一走 Winston")
        self.assertIn("BND-2", second.stdout)

    def test_bad_from_risk_creates_no_ledger(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        result = add_boundary(run, from_risk="RISK-99")
        self.assertEqual(result.returncode, 1)
        self.assertIn("RISK-99", result.stderr)
        self.assertFalse((run.parent / "req-align-history" / "boundaries.md").exists())


class SupersedeTest(unittest.TestCase):
    def _two_runs(self):
        root = Path(tempfile.mkdtemp())
        old = make_run(root, date="2026-09-02", slug="approval")
        new = make_run(root, date="2026-09-05", slug="catalog")
        run_script("align_state.py", "sync", old)
        run_script("align_state.py", "sync", new)
        add_boundary(old)
        return old, new

    def test_supersede_marks_both_sides(self):
        old, new = self._two_runs()
        result = run_script("boundary_state.py", "supersede", "BND-1", "--by", new,
                            "--new-statement", "服务是全局台账，先配置再挂钩租户",
                            "--reason", "用户明确要求先建全局台账",
                            "--confirmed-by", "human", "--gate-outcome", "adopted")
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = (old.parent / "req-align-history" / "boundaries.md").read_text(encoding="utf-8")
        self.assertIn("| BND-1 | 服务归属 | 旧模型：审批时填写服务配置 | 已被覆盖 "
                      "| 2026-09-02-approval | BND-2 |", ledger)
        self.assertIn("| BND-2 | 服务归属 | 服务是全局台账，先配置再挂钩租户 | 生效 "
                      "| 2026-09-05-catalog | — |", ledger)
        # 旧 run 里必须留下失效横幅——否则下次扫描会把它当成仍然生效
        old_text = (old / "arch-risk.md").read_text(encoding="utf-8")
        self.assertIn("> ⚠️ 已被 BND-2（2026-09-05-catalog）覆盖：", old_text)
        self.assertIn("（原 BND-1）", old_text)

    def test_old_run_without_decision_section_leaves_ledger_untouched(self):
        old, new = self._two_runs()
        ledger = old.parent / "req-align-history" / "boundaries.md"
        risk_path = old / "arch-risk.md"
        good = risk_path.read_text(encoding="utf-8")
        risk_path.write_text(good.split("## 📌 决议记录")[0], encoding="utf-8")
        before = ledger.read_bytes()
        args = ["boundary_state.py", "supersede", "BND-1", "--by", new,
                "--new-statement", "新结论", "--reason", "理由",
                "--confirmed-by", "human", "--gate-outcome", "adopted"]
        result = run_script(*args)
        self.assertEqual(result.returncode, 1)
        self.assertIn("决议记录", result.stderr)
        self.assertEqual(ledger.read_bytes(), before)
        risk_path.write_text(good, encoding="utf-8")
        retry = run_script(*args)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertIn("已被覆盖", ledger.read_text(encoding="utf-8"))

    def test_missing_banner_is_detected_by_check_alignment(self):
        old, new = self._two_runs()
        run_script("boundary_state.py", "supersede", "BND-1", "--by", new,
                   "--new-statement", "新结论", "--reason", "理由",
                   "--confirmed-by", "human", "--gate-outcome", "adopted")
        path = old / "arch-risk.md"
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                                  if "⚠️" not in line) + "\n", encoding="utf-8")
        result = run_script("check_alignment.py", old)
        self.assertEqual(result.returncode, 1)
        self.assertIn("无失效横幅", result.stdout)

    def test_double_supersede_is_rejected(self):
        old, new = self._two_runs()
        run_script("boundary_state.py", "supersede", "BND-1", "--by", new,
                   "--new-statement", "新结论", "--reason", "理由",
                   "--confirmed-by", "human", "--gate-outcome", "adopted")
        again = run_script("boundary_state.py", "supersede", "BND-1", "--by", new,
                           "--new-statement", "再来", "--reason", "理由",
                           "--confirmed-by", "human", "--gate-outcome", "adopted")
        self.assertEqual(again.returncode, 1)
        self.assertIn("已被覆盖", again.stderr)

    def test_unknown_boundary_is_rejected(self):
        _, new = self._two_runs()
        result = run_script("boundary_state.py", "supersede", "BND-99", "--by", new,
                            "--new-statement", "x", "--reason", "y",
                            "--confirmed-by", "human", "--gate-outcome", "adopted")
        self.assertEqual(result.returncode, 1)
        self.assertIn("找不到 BND-99", result.stderr)


class PitfallTest(unittest.TestCase):
    def test_same_class_increments_count_instead_of_growing_the_ledger(self):
        run = make_run()
        history = run.parent / "req-align-history"
        add_boundary(run)
        base = ["boundary_state.py", "pitfall-add", "--boundary", "BND-1",
                "--phenomenon", "SSE 非流式跨层歧义", "--root-cause", "未区分两层",
                "--guard", "范围决策先声明影响哪一层", "--history-dir", history]
        self.assertIn("PIT-1", run_script(*base).stdout)
        merged = run_script(*base)
        self.assertIn("count 1 -> 2", merged.stdout)
        rows = [line for line in (history / "pitfalls.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("| PIT-")]
        self.assertEqual(len(rows), 1)

    def test_different_pitfall_gets_new_id(self):
        run = make_run()
        history = run.parent / "req-align-history"
        add_boundary(run)
        run_script("boundary_state.py", "pitfall-add", "--boundary", "BND-1",
                   "--phenomenon", "A", "--root-cause", "a", "--guard", "ga",
                   "--history-dir", history)
        second = run_script("boundary_state.py", "pitfall-add", "--boundary", "BND-1",
                            "--phenomenon", "B", "--root-cause", "b", "--guard", "gb",
                            "--history-dir", history)
        self.assertIn("PIT-2", second.stdout)


class ScanTest(unittest.TestCase):
    def test_scan_returns_only_matching_rows_with_their_pitfalls(self):
        """台账会线性增长，所以检索必须在脚本侧过滤——调用方拿不到全量。"""
        run = make_run()
        history = run.parent / "req-align-history"
        add_boundary(run, module="服务归属", statement="服务挂在租户下")
        add_boundary(run, module="日志", statement="统一走 Winston 输出 JSON")
        run_script("boundary_state.py", "pitfall-add", "--boundary", "BND-1",
                   "--phenomenon", "时区换算踩坑", "--root-cause", "默认 UTC",
                   "--guard", "统一 Asia/Shanghai", "--history-dir", history)
        result = run_script("boundary_state.py", "scan", "--keywords", "服务",
                            "--history-dir", history)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[BND-1]", result.stdout)
        self.assertIn("时区换算踩坑", result.stdout)
        self.assertNotIn("Winston", result.stdout)

    def test_no_hit_is_quiet(self):
        run = make_run()
        history = run.parent / "req-align-history"
        add_boundary(run)
        result = run_script("boundary_state.py", "scan", "--keywords", "毫不相关",
                            "--history-dir", history)
        self.assertEqual(result.stdout.strip(), "no-hit")

    def test_superseded_entries_are_flagged_in_scan_output(self):
        root = Path(tempfile.mkdtemp())
        old = make_run(root, date="2026-09-02", slug="approval")
        new = make_run(root, date="2026-09-05", slug="catalog")
        run_script("align_state.py", "sync", old)
        run_script("align_state.py", "sync", new)
        add_boundary(old)
        run_script("boundary_state.py", "supersede", "BND-1", "--by", new,
                   "--new-statement", "新结论关于服务", "--reason", "理由",
                   "--confirmed-by", "human", "--gate-outcome", "adopted")
        result = run_script("boundary_state.py", "scan", "--keywords", "服务归属",
                            "--history-dir", old.parent / "req-align-history")
        self.assertIn("⚠️ 已被覆盖", result.stdout)
        self.assertIn("被 BND-2 覆盖", result.stdout)


class HistorySyncTest(unittest.TestCase):
    def test_recomputes_closure_numbers(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        run_script("align_state.py", "resolve-risk", run, "RISK-1",
                   "--decision", "d", "--reason", "r", "--impact", "i")
        result = run_script("boundary_state.py", "history-sync", run)
        self.assertEqual(result.returncode, 0, result.stderr)
        index = (run.parent / "req-align-history" / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 2026-09-02 | demo | exec-plan | 1/2 | 1/1 |", index)

    def test_rerun_updates_the_same_row(self):
        run = make_run()
        run_script("align_state.py", "sync", run)
        run_script("boundary_state.py", "history-sync", run)
        run_script("align_state.py", "close-ac", run, "AC-1", "--evidence", "x")
        run_script("boundary_state.py", "history-sync", run)
        index = (run.parent / "req-align-history" / "index.md").read_text(encoding="utf-8")
        rows = [line for line in index.splitlines() if line.startswith("| 2026-09-02 |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("| 1/2 |", rows[0])


if __name__ == "__main__":
    unittest.main()

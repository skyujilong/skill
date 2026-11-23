import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_fixture import make_run, run_script  # noqa: E402


class ListRisksTests(unittest.TestCase):
    def test_lists_pending_only_with_arch_risk_details(self):
        run = make_run(risks=[("RISK-1", "待验证"), ("RISK-2", "未命中"), ("RISK-3", "已决议")])
        (run / "arch-risk.md").write_text(
            "## 🧱 边界风险扫描\n\n| ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| RISK-1 | 时序 | 乱序会丢帧 | — | 架构发现 | 待验证 |\n", encoding="utf-8")
        r = run_script("list_risks.py", run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("RISK-1", r.stdout)
        self.assertIn("乱序会丢帧", r.stdout)
        self.assertIn("架构发现", r.stdout)
        self.assertNotIn("RISK-2", r.stdout)
        self.assertNotIn("RISK-3", r.stdout)

    def test_works_without_arch_risk(self):
        run = make_run()
        r = run_script("list_risks.py", run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("RISK-1", r.stdout)

    def test_none_pending(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = run_script("list_risks.py", run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("无待验证", r.stdout)

    def test_bad_input_exit2(self):
        run = make_run()
        (run / "handoff.json").write_text("{", encoding="utf-8")
        self.assertEqual(run_script("list_risks.py", run).returncode, 2)
        self.assertEqual(run_script("list_risks.py", run.parent / "x").returncode, 2)


if __name__ == "__main__":
    unittest.main()

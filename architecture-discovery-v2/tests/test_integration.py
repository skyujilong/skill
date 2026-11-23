"""用真实 req-align-v2 脚本走完 待验证 → resolve-risk → stage-add。"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RA = HERE.parent.parent / "req-align-v2"
import importlib.util  # noqa: E402
import subprocess  # noqa: E402

_spec = importlib.util.spec_from_file_location("arch_fixture_integration", HERE / "arch_fixture.py")
mine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mine)


def align(*args):
    return subprocess.run([sys.executable, str(RA / "scripts" / "align_state.py"),
                           *[str(a) for a in args]], capture_output=True, text=True)


class IntegrationTests(unittest.TestCase):
    def test_full_chain(self):
        spec = importlib.util.spec_from_file_location("req_align_v2_fixture_for_arch", RA / "tests" / "_fixture.py")
        ra_fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ra_fixture)  # req-align-v2 的 make_run 产出 RISK-1 待验证模板
        run = ra_fixture.make_run()
        self.assertEqual(align("sync", run).returncode, 0)
        disc = mine.make_disc(run, [mine.section(已回写=None)],
                              files={"flows-and-boundaries.md": "## 边界\nRISK-1\n" + mine.LONG})
        r = mine.run_script("check_arch_discovery.py", disc, "--run-dir", run)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("resolve-risk", r.stdout)
        done = align("resolve-risk", run, "RISK-1", "--decision", "采用方案 A",
                     "--reason", "代码证据", "--impact", "SDD 引用", "--confirmed-by", "human")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = (disc / "decisions.md").read_text(encoding="utf-8")
        (disc / "decisions.md").write_text(text.rstrip() + "\n- 已回写: yes\n", encoding="utf-8")
        r = mine.run_script("check_arch_discovery.py", disc, "--run-dir", run)
        self.assertEqual(r.returncode, 0, r.stdout)
        added = align("stage-add", run, "--stage", "arch-discovery", "--dir", disc)
        self.assertEqual(added.returncode, 0, added.stderr)


if __name__ == "__main__":
    unittest.main()

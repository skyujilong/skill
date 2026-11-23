import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdd_fixture import (MATRIX_HEADER, OVERVIEW, P0_NOTE, default_rows, make_handoff_run,  # noqa: E402
                      make_sdd, resync, row, run_check)

REQ_ALIGN = Path(__file__).resolve().parents[2] / "req-align-v2"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = make_handoff_run(self.root)

    def check(self, **kw):
        sdd = make_sdd(self.run_dir, **kw)
        return run_check(sdd, self.run_dir)

    def assertFails(self, proc, text):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("result: FAIL", proc.stdout)
        self.assertIn(text, proc.stdout)


class HandoffTests(Base):
    def test_pass(self):
        p = self.check()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("result: PASS", p.stdout)
        self.assertIn("stage-add", p.stdout)

    def test_missing_handoff_exit2(self):
        sdd = make_sdd(self.run_dir)
        (self.run_dir / "handoff.json").unlink()
        p = run_check(sdd, self.run_dir)
        self.assertEqual(p.returncode, 2)

    def test_bad_json_exit2(self):
        sdd = make_sdd(self.run_dir)
        (self.run_dir / "handoff.json").write_text("{", encoding="utf-8")
        self.assertEqual(run_check(sdd, self.run_dir).returncode, 2)

    def test_not_object_and_missing_keys_exit2(self):
        sdd = make_sdd(self.run_dir)
        for body in ("[]", '{"slug":"demo"}', '{"acceptance":[]}',
                     '{"slug":"demo","acceptance":[{"id":"AC-1"}]}',
                     '{"slug":"demo","acceptance":"x"}'):
            (self.run_dir / "handoff.json").write_text(body, encoding="utf-8")
            self.assertEqual(run_check(sdd, self.run_dir).returncode, 2, body)

    def test_missing_sdd_dir_exit2(self):
        p = run_check(self.root / "docs" / "nope", self.run_dir)
        self.assertEqual(p.returncode, 2)


class NamingTests(Base):
    def test_extra_suffix_rejected(self):
        self.assertFails(self.check(name="sdd-2026-09-03-demo-extra"), "目录名")

    def test_bad_prefix_rejected(self):
        self.assertFails(self.check(name="spec-2026-09-03-demo"), "目录名")

    def test_bad_date_rejected(self):
        self.assertFails(self.check(name="sdd-2026-9-3-demo"), "目录名")

    def test_slug_ending_dash2_accepted_when_upstream(self):
        run = make_handoff_run(self.root, slug="demo-2")
        p = run_check(make_sdd(run), run)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_sdd_dash2_when_upstream_plain_rejected(self):
        self.assertFails(self.check(name="sdd-2026-09-03-demo-2"), "目录名")

    def test_sibling_requirement(self):
        other = self.root / "other"
        other.mkdir()
        sdd = other / "sdd-2026-09-03-demo"
        sdd.mkdir()
        for f in ("README.md", "01-overview.md", "acceptance-matrix.md"):
            (sdd / f).write_text("x", encoding="utf-8")
        self.assertFails(run_check(sdd, self.run_dir), "同级")


class FilesTests(Base):
    def test_missing_files(self):
        for f in ("README.md", "01-overview.md", "acceptance-matrix.md"):
            with self.subTest(f=f):
                shutil.rmtree(self.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)
                self.assertFails(self.check(skip=(f,)), f)

    def test_empty_file(self):
        self.assertFails(self.check(readme="  \n"), "README.md")


class MatrixTests(Base):
    def test_missing_ac(self):
        self.assertFails(self.check(rows=[row("AC-1", note=P0_NOTE)]), "AC-2")

    def test_duplicate_ac(self):
        rows = default_rows() + [row("AC-2")]
        self.assertFails(self.check(rows=rows), "重复")

    def test_unknown_ac(self):
        rows = default_rows() + [row("AC-9")]
        p = self.check(rows=rows)
        self.assertFails(p, "AC-9")
        self.assertIn("req-align-v2", p.stdout)

    def test_bad_ac_cell(self):
        self.assertFails(self.check(rows=default_rows() + [row("R1")]), "R1")

    def test_fenced_table_ignored(self):
        text = "# m\n\n```markdown\n" + MATRIX_HEADER + "\n".join(default_rows()) + "\n```\n"
        self.assertFails(self.check(matrix_text=text), "表格")

    def test_fenced_rows_not_counted(self):
        real = [row("AC-1", note=P0_NOTE)]
        text = ("# m\n\n" + MATRIX_HEADER + "\n".join(real) + "\n\n```\n"
                + row("AC-2") + "\n```\n")
        self.assertFails(self.check(matrix_text=text), "AC-2")

    def test_bad_header(self):
        text = "| AC | 规格 | 模块 | 备注 |\n| --- | --- | --- | --- |\n" + "\n".join(default_rows()) + "\n"
        self.assertFails(self.check(matrix_text=text), "表头")

    def test_spec_prefix_header_ok(self):
        text = "| AC | 规格 | 覆盖模块 | 备注 |\n| --- | --- | --- | --- |\n" + "\n".join(default_rows()) + "\n"
        self.assertEqual(self.check(matrix_text=text).returncode, 0)

    def test_missing_gwt(self):
        for spec in ("Given x / When y", "When y / Then z", "Given x / Then z", "做某事"):
            with self.subTest(spec=spec):
                shutil.rmtree(self.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)
                self.assertFails(self.check(rows=[row("AC-1", spec, note=P0_NOTE), row("AC-2")]), "AC-1")

    def test_chinese_gwt_and_case(self):
        rows = [row("AC-1", "给定 甲 / 当 乙 / 则 丙", note=P0_NOTE),
                row("AC-2", "GIVEN a, when b, THEN c")]
        self.assertEqual(self.check(rows=rows).returncode, 0)

    def test_placeholder_spec(self):
        for spec in ("TBD", "待定", "略", "Given a When b Then TODO", "—"):
            with self.subTest(spec=spec):
                shutil.rmtree(self.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)
                self.assertFails(self.check(rows=[row("AC-1", note=P0_NOTE), row("AC-2", spec)]), "AC-2")

    def test_module_empty_or_placeholder(self):
        for mod in ("", "TBD", "N/A"):
            with self.subTest(mod=mod):
                shutil.rmtree(self.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)
                self.assertFails(self.check(rows=[row("AC-1", note=P0_NOTE), row("AC-2", module=mod)]), "覆盖模块")

    def test_p0_needs_failure_case(self):
        self.assertFails(self.check(rows=[row("AC-1"), row("AC-2")]), "AC-1")

    def test_p0_failure_case_in_spec(self):
        rows = [row("AC-1", "Given a / When b / Then c<br>Given a / When 超时 / Then 错误码"), row("AC-2")]
        self.assertEqual(self.check(rows=rows).returncode, 0)

    def test_p1_needs_no_failure_case(self):
        self.assertEqual(self.check().returncode, 0)

    def test_crlf(self):
        p = self.check(eol="\r\n")
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_trailing_spaces(self):
        rows = [r + "   " for r in default_rows()]
        text = "# m\n\n" + MATRIX_HEADER.replace("|\n", "|  \n") + "\n".join(rows) + "\n"
        self.assertEqual(self.check(matrix_text=text).returncode, 0)


class OverviewTests(Base):
    def test_missing_heading(self):
        for kw in ("目标", "范围", "功能需求", "非功能需求", "错误与边界"):
            with self.subTest(kw=kw):
                shutil.rmtree(self.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)
                ov = OVERVIEW.replace(kw, "XX")
                self.assertFails(self.check(overview=ov), kw)

    def test_heading_in_fence_ignored(self):
        ov = OVERVIEW.replace("## 5. 错误与边界场景", "```\n## 5. 错误与边界场景\n```")
        self.assertFails(self.check(overview=ov), "错误与边界")

    def test_uncited_ac_warns(self):
        p = self.check(overview=OVERVIEW.replace("AC-2", "AC-x"))
        self.assertEqual(p.returncode, 0)
        self.assertIn("[WARN]", p.stdout)
        self.assertIn("AC-2", p.stdout)

    def test_readme_without_run_warns(self):
        p = self.check(readme="# SDD\n没有上游\n")
        self.assertEqual(p.returncode, 0)
        self.assertIn("[WARN]", p.stdout)

    def test_open_questions_owner(self):
        ov = OVERVIEW + "\n## 6. 假设与开放问题\n\n- 问题一\n- 问题二 负责人: 张三\n- 问题三 @li\n- Q4 owner: x\n"
        p = self.check(overview=ov)
        self.assertEqual(p.returncode, 0)
        self.assertIn("问题一", p.stdout)
        self.assertNotIn("问题二", p.stdout)
        self.assertNotIn("问题三", p.stdout)
        self.assertNotIn("Q4", p.stdout)

    def test_open_questions_all_owned_no_warn(self):
        ov = OVERVIEW + "\n## 6. 开放问题\n\n- 问题 @a\n"
        self.assertNotIn("[WARN]", self.check(overview=ov).stdout)


def _cleanup_sdd(t):
    shutil.rmtree(t.root / "docs" / "sdd-2026-09-03-demo", ignore_errors=True)


class FreshnessTests(Base):
    def test_fresh_passes(self):
        self.assertEqual(self.check().returncode, 0)

    def test_stale_align_md_fails(self):
        sdd = make_sdd(self.run_dir)
        (self.run_dir / "align.md").write_text("# 改过\n", encoding="utf-8")
        p = run_check(sdd, self.run_dir)
        self.assertFails(p, "align_state.py sync")
        self.assertNotIn("result: PASS", p.stdout)

    def test_resync_after_edit_passes(self):
        sdd = make_sdd(self.run_dir)
        (self.run_dir / "align.md").write_text("# 改过\n", encoding="utf-8")
        resync(self.run_dir)
        self.assertEqual(run_check(sdd, self.run_dir).returncode, 0)

    def test_legacy_handoff_without_hash_fails(self):
        run = make_handoff_run(self.root, slug="old", fresh=False)
        self.assertFails(run_check(make_sdd(run), run), "source_sha256")

    def test_bad_hash_map_fails(self):
        sdd = make_sdd(self.run_dir)
        path = self.run_dir / "handoff.json"
        base = json.loads(path.read_text(encoding="utf-8"))
        for bad in ({"align.md": "0" * 64}, {**base["source_sha256"], "extra": "0" * 64},
                    {**base["source_sha256"], "align.md": "A" * 64}, "x"):
            path.write_text(json.dumps({**base, "source_sha256": bad}), encoding="utf-8")
            self.assertFails(run_check(sdd, self.run_dir), "sync")

    def test_missing_source_file_fails(self):
        sdd = make_sdd(self.run_dir)
        (self.run_dir / "acceptance.md").unlink()
        self.assertFails(run_check(sdd, self.run_dir), "sync")


class SlugTests(Base):
    def test_handoff_slug_differs_from_dirname(self):
        sdd = make_sdd(self.run_dir)
        path = self.run_dir / "handoff.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["slug"] = "other"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertFails(run_check(sdd, self.run_dir), "slug differs from run dir name")

    def test_naming_uses_run_dir_slug_not_handoff(self):
        sdd = make_sdd(self.run_dir)
        path = self.run_dir / "handoff.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["slug"] = "other"
        path.write_text(json.dumps(data), encoding="utf-8")
        p = run_check(sdd, self.run_dir)
        self.assertIn("[PASS] 目录名", p.stdout)
        sdd2 = make_sdd(self.run_dir, name="sdd-2026-09-03-other")
        self.assertIn("[FAIL] 目录名", run_check(sdd2, self.run_dir).stdout)

    def test_unparsable_run_dir_name_exit2(self):
        bad = self.root / "docs" / "run-demo"
        shutil.copytree(self.run_dir, bad)
        sdd = make_sdd(self.run_dir)
        self.assertEqual(run_check(sdd, bad).returncode, 2)


class GwtStrictTests(Base):
    def test_ordinary_chinese_words_do_not_count(self):
        spec = "系统给定超时阈值，用户应当在超时后收到提示，否则重试"
        self.assertFails(self.check(rows=[row("AC-1", spec, note=P0_NOTE), row("AC-2")]), "AC-1")

    def test_out_of_order_fails(self):
        self.assertFails(self.check(rows=[row("AC-1", "Then c / When b / Given a", note=P0_NOTE),
                                          row("AC-2")]), "AC-1")

    def test_english_embedded_words_fail(self):
        for spec in ("Givenx Whenx Thenx", "given a / whenever b / then c"):
            with self.subTest(spec=spec):
                _cleanup_sdd(self)
                self.assertFails(self.check(rows=[row("AC-1", note=P0_NOTE), row("AC-2", spec)]), "AC-2")

    def test_valid_english_chinese_and_mixed(self):
        for spec in ("Given a, When b, Then c", "给定 甲，当 乙，则 丙", "Given a, 当 乙, Then c",
                     "给定 甲，规则：当 乙，则 丙"):
            with self.subTest(spec=spec):
                _cleanup_sdd(self)
                self.assertEqual(self.check(rows=[row("AC-1", note=P0_NOTE), row("AC-2", spec)]).returncode, 0)


class FailureKeywordTests(Base):
    def test_weak_keywords_do_not_satisfy_p0(self):
        for spec in ("Given a / When 忽略空行 / Then ok", "Given a / When reboundary / Then ok",
                     "Given a / When 输入空格 / Then ok"):
            with self.subTest(spec=spec):
                _cleanup_sdd(self)
                self.assertFails(self.check(rows=[row("AC-1", spec), row("AC-2")]), "AC-1")

    def test_strong_keywords_satisfy_p0(self):
        for spec in ("Given a / When 为空时拒绝 / Then ok", "Given a / When invalid input / Then ok",
                     "Given a / When timeout / Then ok", "Given a / When 无权 / Then ok"):
            with self.subTest(spec=spec):
                _cleanup_sdd(self)
                self.assertEqual(self.check(rows=[row("AC-1", spec), row("AC-2")]).returncode, 0)


class PriorityTests(Base):
    def test_bad_priority_exit2_names_id(self):
        sdd = make_sdd(self.run_dir)
        path = self.run_dir / "handoff.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["acceptance"][1]["priority"] = "P9"
        path.write_text(json.dumps(data), encoding="utf-8")
        p = run_check(sdd, self.run_dir)
        self.assertEqual(p.returncode, 2)
        self.assertIn("AC-2", p.stderr)


class MultiTableTests(Base):
    def _second(self, extra_rows):
        return ("# m\n\n" + MATRIX_HEADER + "\n".join(default_rows()) + "\n\n## 附录\n\n"
                + MATRIX_HEADER + "\n".join(extra_rows) + "\n")

    def test_invented_id_in_second_table_fails(self):
        self.assertFails(self.check(matrix_text=self._second([row("AC-9")])), "AC-9")

    def test_duplicate_across_tables_fails(self):
        self.assertFails(self.check(matrix_text=self._second([row("AC-2")])), "重复")

    def test_ac_split_across_tables_passes(self):
        text = ("# m\n\n" + MATRIX_HEADER + row("AC-1", note=P0_NOTE) + "\n\n## 二\n\n"
                + MATRIX_HEADER + row("AC-2") + "\n")
        self.assertEqual(self.check(matrix_text=text).returncode, 0)

    def test_extra_separator_row_not_reported(self):
        text = "# m\n\n" + MATRIX_HEADER + row("AC-1", note=P0_NOTE) + "\n| --- | --- | --- | --- |\n" + row("AC-2") + "\n"
        p = self.check(matrix_text=text)
        self.assertEqual(p.returncode, 0, p.stdout)


class UnreadableTests(Base):
    def test_latin1_file_clean_fail(self):
        sdd = make_sdd(self.run_dir)
        (sdd / "01-overview.md").write_bytes("caf\xe9 \xff\xfe".encode("latin-1"))
        p = run_check(sdd, self.run_dir)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("[FAIL]", p.stdout)


class IntegrationTests(unittest.TestCase):
    def test_real_req_align_chain(self):
        spec = importlib.util.spec_from_file_location("req_align_v2_fixture_for_sdd", REQ_ALIGN / "tests" / "_fixture.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        make_run = mod.make_run
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        run = make_run(root, slug="chain")
        align = [sys.executable, str(REQ_ALIGN / "scripts" / "align_state.py")]
        p = subprocess.run(align + ["sync", str(run)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rows = [row("AC-1", note=P0_NOTE), row("AC-2")]
        sdd = make_sdd(run, rows=rows)
        c = run_check(sdd, run)
        self.assertEqual(c.returncode, 0, c.stdout)
        s = subprocess.run(align + ["stage-add", str(run), "--stage", "sdd", "--dir", str(sdd)],
                           capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        bad = make_sdd(run, rows=rows[:1], name="sdd-2026-09-04-chain")
        self.assertEqual(run_check(bad, run).returncode, 1)


if __name__ == "__main__":
    unittest.main()

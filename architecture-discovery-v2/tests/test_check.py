import json
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arch_fixture import LONG, make_disc, make_run, resync, run_script, section  # noqa: E402


def check(disc, run):
    return run_script("check_arch_discovery.py", disc, "--run-dir", run)


class CheckTests(unittest.TestCase):
    def good(self, **kw):
        run = make_run(**kw)
        return run, make_disc(run)

    def test_pass(self):
        run, disc = self.good(risks=[("RISK-1", "已决议"), ("RISK-2", "未命中")])
        r = check(disc, run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("result: PASS", r.stdout)
        self.assertIn("stage-add", r.stdout)

    def test_name_extra_suffix_rejected(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run, dirname="architecture-discovery-2026-09-03-demo-extra")
        r = check(disc, run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FAIL]", r.stdout)

    def test_name_upstream_slug_dash2_accepted(self):
        run = make_run(slug="demo-2", risks=[("RISK-1", "已决议")])
        r = check(make_disc(run), run)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_name_dropping_dash2_rejected(self):
        run = make_run(slug="demo-2", risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, dirname="architecture-discovery-2026-09-03-demo"), run)
        self.assertEqual(r.returncode, 1)

    def test_sibling_check(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run)
        other = make_run().parent  # 另一个 docs/
        moved = other / disc.name
        import shutil
        shutil.copytree(disc, moved)
        r = check(moved, run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("同级", r.stdout)

    def test_missing_and_empty_files(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run, files={"architecture.md": None, "flows-and-boundaries.md": "  \n"})
        r = check(disc, run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("architecture.md", r.stdout)
        self.assertIn("flows-and-boundaries.md", r.stdout)

    def test_missing_section(self):
        run = make_run(risks=[("RISK-1", "已决议"), ("RISK-3", "待验证")])
        r = check(make_disc(run), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("RISK-3", r.stdout)

    def test_extra_section(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(), section("RISK-9")]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("RISK-9", r.stdout)

    def test_duplicate_section(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(), section()]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("重复", r.stdout)

    def test_section_for_untouched_risk(self):
        run = make_run(risks=[("RISK-1", "已决议"), ("RISK-2", "未命中")])
        r = check(make_disc(run, [section(), section("RISK-2")]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("未命中", r.stdout)

    def test_bad_evidence_type(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据类型="guess")]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("证据类型", r.stdout)

    def test_missing_field(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(影响=None)]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("影响", r.stdout)

    def test_placeholders(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        for ph in ("TBD", "todo", "待定", "略", "…", "..."):
            r = check(make_disc(run, [section(结论=ph)]), run)
            self.assertEqual(r.returncode, 1, ph)
            self.assertIn("占位", r.stdout)

    def test_code_evidence_without_line_warns(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据="src/a.py")]), run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("[WARN]", r.stdout)

    def test_doc_evidence_without_url_warns(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据类型="doc", 证据="官方文档")]), run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("http", r.stdout)

    def test_doc_with_url_ok(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据类型="doc", 证据="https://x.dev/a")]), run)
        self.assertNotIn("[WARN] RISK-1", r.stdout)

    def test_script_short_result_warns(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据类型="script", 证据="ok")]), run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("[WARN]", r.stdout)

    def test_script_with_result_ok(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        ev = "python3 t.py → exit 0, 输出 3 行事件按序到达"
        r = check(make_disc(run, [section(证据类型="script", 证据=ev)]), run)
        self.assertNotIn("[WARN]", r.stdout)

    def test_user_evidence_ok(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, [section(证据类型="user", 证据="用户: 确认按 A")]), run)
        self.assertEqual(r.returncode, 0)

    def test_writeback_mismatch(self):
        run = make_run(risks=[("RISK-1", "待验证")])
        r = check(make_disc(run, [section(已回写=None)]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("resolve-risk", r.stdout)
        self.assertIn("RISK-1", r.stdout)

    def test_writeback_lie(self):
        run = make_run(risks=[("RISK-1", "待验证")])
        r = check(make_disc(run, [section(已回写="yes")]), run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("不一致", r.stdout)

    def test_files_without_h2_or_short(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run, files={"architecture.md": "# 只有标题\n" + LONG,
                                     "flows-and-boundaries.md": "## 短\nRISK-1\n"})
        r = check(disc, run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("二级标题", r.stdout)
        self.assertIn("[WARN]", r.stdout)

    def test_flows_missing_risk_id_warns(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run, files={"flows-and-boundaries.md": "## 流\n" + LONG})
        r = check(disc, run)
        self.assertEqual(r.returncode, 0)
        self.assertIn("RISK-1", r.stdout)
        self.assertIn("[WARN]", r.stdout)

    def test_malformed_handoff_exit2(self):
        run = make_run()
        disc = make_disc(run)
        for bad in ("{", "[]", json.dumps({"slug": "demo"}),
                    json.dumps({"slug": "demo", "risks": [{"id": "RISK-1", "state": "怪"}]})):
            (run / "handoff.json").write_text(bad, encoding="utf-8")
            self.assertEqual(check(disc, run).returncode, 2, bad)

    def test_usage_errors_exit2(self):
        run = make_run()
        self.assertEqual(check(run.parent / "nope", run).returncode, 2)
        self.assertEqual(check(make_disc(run), run.parent / "nope").returncode, 2)


def set_handoff(run, **over):
    path = run / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(over)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.run = make_run(risks=[("RISK-1", "已决议")])
        self.disc = make_disc(self.run)

    def test_fresh_passes(self):
        self.assertEqual(check(self.disc, self.run).returncode, 0)

    def test_stale_source_fails(self):
        (self.run / "align.md").write_text("# 改过\n", encoding="utf-8")
        r = check(self.disc, self.run)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("align_state.py sync", r.stdout)
        self.assertNotIn("result: PASS", r.stdout)

    def test_resync_passes(self):
        (self.run / "align.md").write_text("# 改过\n", encoding="utf-8")
        resync(self.run)
        self.assertEqual(check(self.disc, self.run).returncode, 0)

    def test_legacy_handoff_fails(self):
        run = make_run(slug="old", risks=[("RISK-1", "已决议")], fresh=False)
        r = check(make_disc(run), run)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("source_sha256", r.stdout)

    def test_bad_map_and_missing_file_fail(self):
        base = json.loads((self.run / "handoff.json").read_text(encoding="utf-8"))["source_sha256"]
        for bad in ({"align.md": "0" * 64}, {**base, "extra": "0" * 64}, {**base, "align.md": "A" * 64}, "x"):
            set_handoff(self.run, source_sha256=bad)
            r = check(self.disc, self.run)
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("sync", r.stdout)
        resync(self.run)
        (self.run / "acceptance.md").unlink()
        r = check(self.disc, self.run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("sync", r.stdout)


class SlugTests(unittest.TestCase):
    def test_handoff_slug_differs(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run)
        set_handoff(run, slug="other")
        r = check(disc, run)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("slug differs from run dir name", r.stdout)
        self.assertIn("[PASS] 目录名", r.stdout)  # 命名裁决以 run 目录名为准

    def test_unparsable_run_dir_exit2(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run)
        bad = run.parent / "run-demo"
        shutil.copytree(run, bad)
        self.assertEqual(check(disc, bad).returncode, 2)


class StructureWarnTests(unittest.TestCase):
    def run_with(self, files):
        run = make_run(risks=[("RISK-1", "已决议")])
        r = check(make_disc(run, files=files), run)
        self.assertEqual(r.returncode, 0, r.stdout)
        return r.stdout

    def test_default_has_no_heading_warn(self):
        self.assertNotIn("建议含", self.run_with({}))

    def test_architecture_missing_headings_warn(self):
        out = self.run_with({"architecture.md": "# a\n## 组件\n" + LONG})
        self.assertIn("[WARN] architecture.md 建议含标题包含「分层」或「依赖」", out)
        self.assertIn("[WARN] architecture.md 建议含标题包含「选型」", out)

    def test_flows_missing_headings_warn(self):
        out = self.run_with({"flows-and-boundaries.md": "# f\n## 杂项\nRISK-1\n" + LONG})
        self.assertIn("[WARN] flows-and-boundaries.md 建议含标题包含「数据流」「时序」或「边界」", out)

    def test_heading_only_in_fence_still_warns(self):
        out = self.run_with({"architecture.md": "# a\n## 组件\n```\n## 分层与依赖\n## 选型\n```\n" + LONG})
        self.assertIn("「选型」", out)
        self.assertIn("「分层」", out)

    def test_discovery_guide_example_has_expected_headings(self):
        guide = (Path(__file__).resolve().parent.parent / "references" / "discovery-guide.md"
                 ).read_text(encoding="utf-8")
        example = guide.split("## 6. 最小示例")[1].split("## 7.")[0]
        chunks = re.split(r"^# (\S+\.md)\s*$", example, flags=re.M)
        parts = {chunks[i]: chunks[i + 1] for i in range(1, len(chunks), 2)}
        self.assertEqual(set(parts), {"decisions.md", "architecture.md", "flows-and-boundaries.md"})
        run = make_run(risks=[("RISK-1", "已决议")])
        files = {k: v for k, v in parts.items() if k != "decisions.md"}
        r = check(make_disc(run, [parts["decisions.md"]], files=files), run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("建议含", r.stdout)

    def test_guide_marks_warn_only_lists_as_suggestion(self):
        guide = (Path(__file__).resolve().parent.parent / "references" / "discovery-guide.md"
                 ).read_text(encoding="utf-8")
        self.assertNotIn("必含二级标题", guide)
        self.assertIn("建议", guide.split("## 4.")[1].split("## 5.")[0])
        self.assertIn("建议", guide.split("## 5.")[1].split("## 6.")[0])


class FenceAndFieldTests(unittest.TestCase):
    def one(self, decisions_body, **kw):
        run = make_run(risks=[("RISK-1", "已决议")])
        return check(make_disc(run, [decisions_body], **kw), run)

    def test_tilde_fence_ignored(self):
        body = section() + "~~~\n## RISK-9 伪\n- 结论: x\n~~~\n"
        r = self.one(body)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_fence_chars_symmetric(self):
        # ``` 打开后 ~~~ 不能关闭：其后的 RISK-9 仍在围栏内
        body = section() + "```\n~~~\n## RISK-9 伪\n- 结论: x\n```\n"
        self.assertEqual(self.one(body).returncode, 0)
        # ~~~ 打开后 ``` 不能关闭
        body = section() + "~~~\n```\n## RISK-9 伪\n~~~\n"
        self.assertEqual(self.one(body).returncode, 0)

    def test_tilde_block_closed_by_tilde_only(self):
        r = self.one(section() + "~~~\n```\n~~~\n## RISK-9 真段\n- 结论: x\n")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("RISK-9", r.stdout)

    def test_h2_check_ignores_fenced_headings(self):
        r = self.one(section(), files={"architecture.md": "# a\n```\n## 分层\n```\n" + LONG})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("二级标题", r.stdout)

    def test_emphasis_and_fullwidth_colon_labels(self):
        body = ("## RISK-1 标题\n- **结论**: 采用 A\n- **证据类型**：code\n- _证据_: src/a.py:1-2\n"
                "- **影响:** SDD\n- 已回写: yes\n")
        r = self.one(body)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_h3_risk_heading_fails_and_ends_section(self):
        body = section() + "\n### RISK-1 子段\n- 结论: 另一个\n"
        r = self.one(body)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("RISK sections must use level-2 headings", r.stdout)

    def test_h3_risk_fields_not_merged(self):
        body = section(影响=None) + "\n### RISK-1 子段\n- 影响: 偷偷并入\n"
        r = self.one(body)
        self.assertEqual(r.returncode, 1)
        self.assertIn("缺字段「影响」", r.stdout)


class UnreadableTests(unittest.TestCase):
    def test_latin1_artifact_clean_fail(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run)
        (disc / "decisions.md").write_bytes("caf\xe9 \xff".encode("latin-1"))
        r = check(disc, run)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("[FAIL]", r.stdout)

    def test_latin1_handoff_exit2(self):
        run = make_run(risks=[("RISK-1", "已决议")])
        disc = make_disc(run)
        (run / "handoff.json").write_bytes(b"\xff\xfe{")
        r = check(disc, run)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()

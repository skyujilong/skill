"""update_step_state.py 与 audit_coverage.py 的行为契约测试。

两条主线：
1. 没有 upstream.json 时进入通用模式（保住无上游场景的可用性）。
2. 有 upstream.json 时，把"事后回写上游验收"变成"推进状态的前置条件"。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run_script(name: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
        capture_output=True, text=True,
    )


def make_plan(with_upstream: bool = True, slug: str = "demo-feature",
              plan_name: str = None, closed=(), covers=None,
              next_stage: str = "exec-plan", stages=None, risks=None) -> Path:
    """构造 <tmp>/docs/exec-plan-.../ ，可选带一个最小上游 handoff.json。"""
    root = Path(tempfile.mkdtemp())
    docs = root / "docs"
    plan_dir = docs / (plan_name or f"exec-plan-2026-09-02-{slug}")
    plan_dir.mkdir(parents=True)
    covers = covers if covers is not None else [["AC-1"], ["AC-2"]]
    steps = [{"step": "01-a", "state": "pending", "covers": covers[0]},
             {"step": "02-b", "state": "pending", "covers": covers[1]}]
    (plan_dir / "step.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")
    if with_upstream:
        run_dir = docs / f"req-align-2026-09-02-{slug}"
        run_dir.mkdir(parents=True, exist_ok=True)
        handoff = {
            "contract_version": "1", "slug": slug, "date": "2026-09-02",
            "next_stage": next_stage, "stages": stages or [],
            "acceptance": [
                {"id": "AC-1", "priority": "P0", "text": "输入 X → 输出 Y",
                 "closed": "AC-1" in closed, "evidence": None, "step": None},
                {"id": "AC-2", "priority": "P1", "text": "当 C 时 → 行为 D",
                 "closed": "AC-2" in closed, "evidence": None, "step": None},
            ],
            "risks": risks or [], "boundaries_touched": [],
        }
        # 上游契约要求 source_sha256 指纹：三份源 Markdown 的字节级 sha256
        acceptance_md = f"# acceptance {slug}\n"
        if closed:
            acceptance_md += "".join(f"\n- [x] {ac} 输入 X → 输出 Y" for ac in closed)
            acceptance_md += "\n\n## 证据\n\n" + "".join(
                f"- {ac} | 01-a | observed ok\n" for ac in closed)
        sources = {
            "align.md": f"# align {slug}\n",
            "arch-risk.md": f"# arch-risk {slug}\n",
            "acceptance.md": acceptance_md,
        }
        for name, text in sources.items():
            (run_dir / name).write_text(text, encoding="utf-8")
        handoff["source_sha256"] = {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in sources.items()
        }
        (run_dir / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        (plan_dir / "upstream.json").write_text(json.dumps({
            "source": "req-align-v2", "contract_version": "1",
            "run_dir": f"../{run_dir.name}", "slug": slug,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        # 上游有 AC 时 requirements.md 是审计硬要求：为每个 R 声明 Covers: AC-N
        (plan_dir / "requirements.md").write_text(
            "# Requirements\n\n## R1 a\n- Covers: AC-1\n\n## R2 b\n- Covers: AC-2\n",
            encoding="utf-8")
    return plan_dir


def make_stage_dir(plan_dir: Path, name: str, files) -> Path:
    """在 plan 的同级 docs/ 下建一个中间层阶段目录。"""
    stage_dir = plan_dir.parent / name
    stage_dir.mkdir(parents=True, exist_ok=True)
    for filename in files:
        (stage_dir / filename).write_text("x\n", encoding="utf-8")
    return stage_dir


def states(plan_dir: Path) -> dict:
    return {s["step"]: s for s in json.loads((plan_dir / "step.json").read_text(encoding="utf-8"))}


def rewrite_handoff(plan_dir: Path, slug: str = "demo-feature", **patch) -> None:
    """就地改写上游 handoff.json 的字段，用于注入畸形契约数据。"""
    path = plan_dir.parent / f"req-align-2026-09-02-{slug}" / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(patch)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_handoff_slug(plan_dir: Path, new_slug: str, slug: str = "demo-feature") -> None:
    path = plan_dir.parent / f"req-align-2026-09-02-{slug}" / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["slug"] = new_slug
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rewrite_acceptance_md(plan_dir: Path, text: str, slug: str = "demo-feature") -> None:
    """改写上游 acceptance.md 并重算 handoff 的 source_sha256（保持新鲜度门禁通过）。"""
    run_dir = plan_dir.parent / f"req-align-2026-09-02-{slug}"
    (run_dir / "acceptance.md").write_text(text, encoding="utf-8")
    path = run_dir / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source_sha256"]["acceptance.md"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def forge_closed(plan_dir: Path, slug: str = "demo-feature") -> None:
    """只改 handoff.json 的 closed 标志（源 Markdown 与哈希不动）。"""
    path = plan_dir.parent / f"req-align-2026-09-02-{slug}" / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["acceptance"]:
        entry["closed"] = True
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def start_step(plan: Path, name: str = "01-a") -> None:
    assert run_script("update_step_state.py", plan / "step.json", name, "runing").returncode == 0


class GenericModeTest(unittest.TestCase):
    """无 upstream.json 时进入通用模式。"""

    def test_full_cycle_without_upstream(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        self.assertEqual(run_script("update_step_state.py", step_json, "01-a", "runing").returncode, 0)
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "complate")

    def test_illegal_transition_rejected(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "pending")
        self.assertEqual(result.returncode, 1)
        self.assertIn("illegal transition", result.stderr)

    def test_out_of_order_start_rejected(self):
        plan = make_plan(with_upstream=False)
        result = run_script("update_step_state.py", plan / "step.json", "02-b", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("before previous steps are complate", result.stderr)

    def test_timestamp_folder_name_is_fine_without_upstream(self):
        plan = make_plan(with_upstream=False, plan_name="exec-plan-2026-09-02_14-30-00")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_force_requires_reason(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        self.assertEqual(
            run_script("update_step_state.py", step_json, "02-b", "runing", "--force").returncode, 1)
        result = run_script("update_step_state.py", step_json, "02-b", "runing",
                            "--force", "--reason", "UI mock must precede API")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(states(plan)["02-b"]["override_reason"], "UI mock must precede API")


class SlugGateTest(unittest.TestCase):
    def test_plan_folder_must_carry_upstream_slug(self):
        plan = make_plan(plan_name="exec-plan-2026-09-02_14-30-00")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not carry the upstream slug", result.stderr)

    def test_matching_slug_passes(self):
        plan = make_plan()
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_folder_with_extra_suffix_rejected(self):
        plan = make_plan(plan_name="exec-plan-2026-09-02-demo-feature-extra")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not carry the upstream slug", result.stderr)

    def test_upstream_slug_ending_with_increment_accepted(self):
        plan = make_plan(slug="demo-2")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_incremented_slug_still_rejects_extra_suffix(self):
        plan = make_plan(slug="demo-2",
                         plan_name="exec-plan-2026-09-02-demo-2-extra")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not carry the upstream slug", result.stderr)


class CoversGateTest(unittest.TestCase):
    def test_covers_none_rejected_when_step_lists_covers(self):
        plan = make_plan(closed=("AC-1",))
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate",
                            "--covers-none", "--reason", "skip")
        self.assertEqual(result.returncode, 1)
        self.assertIn("only for steps with empty", result.stderr)
        self.assertNotIn("covers_none", states(plan)["01-a"])

    def test_open_ac_hint_recommends_run_cmd(self):
        plan = make_plan()
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertIn("--run-cmd", result.stderr)

    def test_complate_blocked_while_upstream_acceptance_open(self):
        plan = make_plan()
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("upstream acceptance not closed (AC-1)", result.stderr)
        self.assertIn("close-ac", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "runing")

    def test_complate_allowed_once_closed_upstream(self):
        plan = make_plan(closed=("AC-1",))
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_covers_rejected(self):
        plan = make_plan(covers=[[], ["AC-2"]])
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no 'covers'", result.stderr)

    def test_covers_none_escape_hatch_requires_reason(self):
        plan = make_plan(covers=[[], ["AC-2"]])
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        self.assertEqual(run_script("update_step_state.py", step_json, "01-a",
                                    "complate", "--covers-none").returncode, 1)
        result = run_script("update_step_state.py", step_json, "01-a", "complate",
                            "--covers-none", "--reason", "tooling only")
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = states(plan)["01-a"]
        self.assertTrue(entry["covers_none"])
        self.assertEqual(entry["covers_none_reason"], "tooling only")

    def test_unknown_ac_in_covers_rejected(self):
        plan = make_plan(covers=[["AC-9"], ["AC-2"]])
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown acceptance ids: AC-9", result.stderr)

    def test_missing_upstream_handoff_is_reported(self):
        plan = make_plan()
        (plan.parent / "req-align-2026-09-02-demo-feature" / "handoff.json").unlink()
        step_json = plan / "step.json"
        result = run_script("update_step_state.py", step_json, "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot locate upstream handoff.json", result.stderr)


class UpstreamReadinessTest(unittest.TestCase):
    """有 upstream 时，runing/complate 都要求上游就绪：中间层已登记、无待验证风险。"""

    def test_pending_upstream_risk_blocks_runing(self):
        plan = make_plan(risks=[{"id": "RISK-1", "boundary": "b", "risk": "r",
                                 "state": "待验证", "boundary_ref": None}])
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("待验证", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "pending")

    def test_intermediate_next_stage_without_registration_blocks(self):
        plan = make_plan(next_stage="sdd")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("stage-add", result.stderr)

    def test_registered_but_deleted_stage_dir_blocks(self):
        plan = make_plan(next_stage="sdd",
                         stages=[{"stage": "sdd", "dir": "docs/sdd-2026-09-02-demo-feature"}])
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing", result.stderr)

    def test_stage_dir_with_slug_suffix_does_not_satisfy_contract(self):
        plan = make_plan(next_stage="sdd",
                         stages=[{"stage": "sdd",
                                  "dir": "docs/sdd-2026-09-02-demo-feature-extra"}])
        make_stage_dir(plan, "sdd-2026-09-02-demo-feature-extra",
                       files=("README.md", "01-overview.md", "acceptance-matrix.md"))
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)

    def test_registered_stage_missing_required_files_blocks(self):
        plan = make_plan(next_stage="sdd",
                         stages=[{"stage": "sdd", "dir": "docs/sdd-2026-09-02-demo-feature"}])
        make_stage_dir(plan, "sdd-2026-09-02-demo-feature", files=("README.md",))
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("required files", result.stderr)

    def test_registered_stage_with_files_allows_runing(self):
        plan = make_plan(next_stage="sdd",
                         stages=[{"stage": "sdd", "dir": "docs/sdd-2026-09-02-demo-feature"}])
        make_stage_dir(plan, "sdd-2026-09-02-demo-feature",
                       files=("README.md", "01-overview.md", "acceptance-matrix.md"))
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_next_stage_is_rejected(self):
        plan = make_plan(next_stage="mystery")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("next_stage", result.stderr)

    def test_unknown_risk_state_is_rejected(self):
        plan = make_plan(risks=[{"id": "RISK-1", "boundary": "b", "risk": "r",
                                 "state": "resolved", "boundary_ref": None}])
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown state", result.stderr)

    def test_malformed_risk_entry_is_rejected(self):
        plan = make_plan(risks=["RISK-1"])
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be an object", result.stderr)

    def test_risk_entry_without_id_is_rejected(self):
        plan = make_plan(risks=[{"id": "  ", "state": "已决议"}])
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("non-empty 'id'", result.stderr)

    def test_risks_must_be_a_list(self):
        plan = make_plan()
        rewrite_handoff(plan, risks={"RISK-1": "待验证"})
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a list", result.stderr)

    def test_readiness_also_gates_complate(self):
        plan = make_plan(risks=[{"id": "RISK-1", "boundary": "b", "risk": "r",
                                 "state": "待验证", "boundary_ref": None}],
                         closed=("AC-1",))
        steps_path = plan / "step.json"
        steps = json.loads(steps_path.read_text(encoding="utf-8"))
        steps[0]["state"] = "runing"
        steps_path.write_text(json.dumps(steps, indent=2), encoding="utf-8")
        result = run_script("update_step_state.py", steps_path, "01-a", "complate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("待验证", result.stderr)


class FreshnessGateTest(unittest.TestCase):
    """源 Markdown 在契约生成后有任何字节改动 → handoff.json 陈旧，
    runing/complate（含 forced runing）一律拒绝，直到重新 sync。"""

    def _edit_source(self, plan: Path, name: str) -> Path:
        path = plan.parent / "req-align-2026-09-02-demo-feature" / name
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- comment -->\n",
                        encoding="utf-8")
        return path

    def _assert_runing_blocked(self, plan: Path):
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("align_state.py sync", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "pending")

    def test_unsynced_align_edit_blocks_runing(self):
        plan = make_plan()
        self._edit_source(plan, "align.md")
        self._assert_runing_blocked(plan)

    def test_unsynced_arch_risk_edit_blocks_runing(self):
        plan = make_plan()
        self._edit_source(plan, "arch-risk.md")
        self._assert_runing_blocked(plan)

    def test_unsynced_acceptance_edit_blocks_runing(self):
        plan = make_plan()
        self._edit_source(plan, "acceptance.md")
        self._assert_runing_blocked(plan)

    def test_unsynced_edit_blocks_forced_runing(self):
        plan = make_plan()
        self._edit_source(plan, "align.md")
        result = run_script("update_step_state.py", plan / "step.json", "02-b",
                            "runing", "--force", "--reason", "reorder")
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_sha256", result.stderr)
        self.assertEqual(states(plan)["02-b"]["state"], "pending")

    def test_legacy_handoff_without_hashes_blocks_runing(self):
        plan = make_plan()
        handoff_path = plan.parent / "req-align-2026-09-02-demo-feature" / "handoff.json"
        data = json.loads(handoff_path.read_text(encoding="utf-8"))
        data.pop("source_sha256")
        handoff_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_sha256", result.stderr)
        self.assertIn("sync", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "pending")

    def test_recomputed_hashes_allow_runing(self):
        plan = make_plan()
        edited = self._edit_source(plan, "align.md")
        handoff_path = plan.parent / "req-align-2026-09-02-demo-feature" / "handoff.json"
        data = json.loads(handoff_path.read_text(encoding="utf-8"))
        data["source_sha256"]["align.md"] = hashlib.sha256(edited.read_bytes()).hexdigest()
        handoff_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)


class ForceGateTest(unittest.TestCase):
    """--force 只允许 pending -> runing 的依赖重排，且永远不跳过上游就绪门禁。"""

    def test_force_cannot_complate(self):
        plan = make_plan(closed=("AC-1",))
        result = run_script("update_step_state.py", plan / "step.json", "01-a",
                            "complate", "--force", "--reason", "skip ahead")
        self.assertEqual(result.returncode, 1)
        self.assertIn("pending -> runing", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "pending")

    def test_force_cannot_bypass_upstream_readiness(self):
        plan = make_plan(next_stage="sdd")
        result = run_script("update_step_state.py", plan / "step.json", "02-b",
                            "runing", "--force", "--reason", "reorder")
        self.assertEqual(result.returncode, 1)
        self.assertIn("stage-add", result.stderr)
        self.assertEqual(states(plan)["02-b"]["state"], "pending")

    def test_force_rejected_even_when_state_already_matches(self):
        plan = make_plan(closed=("AC-1",))
        step_json = plan / "step.json"
        self.assertEqual(run_script("update_step_state.py", step_json, "01-a",
                                    "runing").returncode, 0)
        self.assertEqual(run_script("update_step_state.py", step_json, "01-a",
                                    "complate").returncode, 0)
        result = run_script("update_step_state.py", step_json, "01-a",
                            "complate", "--force", "--reason", "again")
        self.assertEqual(result.returncode, 1)
        self.assertIn("pending -> runing", result.stderr)

    def test_force_still_allows_dependency_reorder_when_ready(self):
        plan = make_plan()
        result = run_script("update_step_state.py", plan / "step.json", "02-b",
                            "runing", "--force", "--reason", "UI mock must precede API")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(states(plan)["02-b"]["state"], "runing")


class BlockTest(unittest.TestCase):
    def test_block_requires_pitfall_stance(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        result = run_script("update_step_state.py", step_json, "01-a", "block",
                            "--reason", "3 consecutive failures")
        self.assertEqual(result.returncode, 1)
        self.assertIn("explicit stance on the lesson", result.stderr)

    def test_block_with_pitfall_id(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        result = run_script("update_step_state.py", step_json, "01-a", "block",
                            "--reason", "3 fails", "--pitfall", "PIT-4")
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = states(plan)["01-a"]
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["pitfall"], "PIT-4")
        self.assertEqual(entry["state"], "pending")

    def test_block_with_explicit_no_pitfall(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        result = run_script("update_step_state.py", step_json, "01-a", "block",
                            "--reason", "3 fails", "--no-pitfall", "one-off env issue")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(states(plan)["01-a"]["no_pitfall_reason"], "one-off env issue")

    def test_blocked_pending_step_cannot_start_even_forced(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "block",
                   "--reason", "3 fails", "--pitfall", "PIT-4")
        result = run_script("update_step_state.py", step_json, "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("blocked", result.stderr)
        forced = run_script("update_step_state.py", step_json, "01-a", "runing",
                            "--force", "--reason", "push through")
        self.assertEqual(forced.returncode, 1)
        self.assertIn("blocked", forced.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "pending")

    def test_blocked_runing_step_cannot_complate_until_unblock(self):
        plan = make_plan(closed=("AC-1",))
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        run_script("update_step_state.py", step_json, "01-a", "block",
                   "--reason", "3 fails", "--pitfall", "PIT-4")
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("blocked", result.stderr)
        self.assertEqual(run_script("update_step_state.py", step_json, "01-a",
                                    "unblock").returncode, 0)
        result = run_script("update_step_state.py", step_json, "01-a", "complate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unblock_clears_all_failure_fields(self):
        plan = make_plan(with_upstream=False)
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "block",
                   "--reason", "3 fails", "--pitfall", "PIT-4")
        result = run_script("update_step_state.py", step_json, "01-a", "unblock")
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = states(plan)["01-a"]
        for key in ("blocked", "block_reason", "pitfall", "no_pitfall_reason"):
            self.assertNotIn(key, entry)


class ClosedEvidenceGateTest(unittest.TestCase):
    """handoff.json 的 closed 标志可手改且不影响源哈希：complate 还要核对
    acceptance.md 本身（勾选 + 非空证据）。"""

    def _complate(self, plan):
        return run_script("update_step_state.py", plan / "step.json", "01-a", "complate")

    def test_forged_closed_flag_with_unticked_acceptance_is_rejected(self):
        plan = make_plan()
        start_step(plan)
        forge_closed(plan)
        result = self._complate(plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("acceptance.md", result.stderr)
        self.assertIn("close-ac", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "runing")

    def test_ticked_box_without_evidence_is_rejected(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(plan, "# acceptance demo-feature\n\n- [x] AC-1 输入 X → 输出 Y\n"
                                    "\n## 证据\n\n- AC-1 | 01-a |  \n")
        result = self._complate(plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-1", result.stderr)
        self.assertIn("close-ac", result.stderr)

    def test_evidence_without_ticked_box_is_rejected(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(plan, "# acceptance demo-feature\n\n- [ ] AC-1 输入 X → 输出 Y\n"
                                    "\n## 证据\n\n- AC-1 | 01-a | ok\n")
        self.assertEqual(self._complate(plan).returncode, 1)

    def test_ticked_box_with_evidence_passes(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        self.assertEqual(self._complate(plan).returncode, 0)

    def test_legacy_two_part_evidence_counts(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(plan, "# acceptance demo-feature\n\n- [X] AC-1 输入 X → 输出 Y\n"
                                    "\n## 证据\n\n- AC-1 | pytest ok\n")
        self.assertEqual(self._complate(plan).returncode, 0)


class CanonicalAcceptanceParsingTest(unittest.TestCase):
    """complate 对 acceptance.md 的解析必须镜像 req-align-v2：跳过代码块，证据只认「证据」小节。"""

    def _complate(self, plan):
        return run_script("update_step_state.py", plan / "step.json", "01-a", "complate")

    def test_fenced_example_tick_does_not_count(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(
            plan, "# acceptance demo-feature\n\n```\n- [x] AC-1 输入 X → 输出 Y\n```\n\n"
                  "- [ ] AC-1 输入 X → 输出 Y\n\n## 证据\n\n- AC-1 | 01-a | ok\n")
        result = self._complate(plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance.md does not show AC-1", result.stderr)
        self.assertEqual(states(plan)["01-a"]["state"], "runing")

    def test_evidence_under_other_heading_does_not_count(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(
            plan, "# acceptance demo-feature\n\n- [x] AC-1 输入 X → 输出 Y\n\n"
                  "## 证据\n\n## 备注\n\n- AC-1 | 01-a | looks like evidence\n")
        self.assertEqual(self._complate(plan).returncode, 1)

    def test_evidence_in_h1_or_before_section_does_not_count(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(
            plan, "# 证据\n\n- AC-1 | 01-a | not in a ## section\n\n"
                  "- [x] AC-1 输入 X → 输出 Y\n\n## 证据\n")
        self.assertEqual(self._complate(plan).returncode, 1)

    def test_evidence_pipes_preserved_and_real_section_passes(self):
        plan = make_plan(closed=("AC-1",))
        start_step(plan)
        rewrite_acceptance_md(
            plan, "# acceptance demo-feature\n\n- [x] AC-1 输入 X → 输出 Y\n\n"
                  "## 证据\n\n- AC-1 | 01-a | pytest -q | tee log\n")
        self.assertEqual(self._complate(plan).returncode, 0)


class UpstreamLocationTest(unittest.TestCase):
    """upstream.json 的 run_dir 只相对 plan 目录解析，当前工作目录里的同名目录不得胜出。"""

    def _bare_run_dir(self, plan: Path) -> None:
        (plan / "upstream.json").write_text(json.dumps({
            "source": "req-align-v2", "contract_version": "1",
            "run_dir": "req-align-2026-09-02-demo-feature", "slug": "demo-feature",
        }), encoding="utf-8")

    def _decoy_cwd(self, **handoff_patch) -> Path:
        cwd = Path(tempfile.mkdtemp())
        decoy = cwd / "req-align-2026-09-02-demo-feature"
        decoy.mkdir()
        (decoy / "handoff.json").write_text(json.dumps(handoff_patch), encoding="utf-8")
        return cwd

    def _run_in(self, cwd: Path, name: str, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
                              capture_output=True, text=True, cwd=str(cwd))

    def test_update_step_state_ignores_cwd_decoy(self):
        plan = make_plan()
        self._bare_run_dir(plan)
        cwd = self._decoy_cwd(next_stage="mystery")
        result = self._run_in(cwd, "update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_audit_coverage_ignores_cwd_decoy(self):
        plan = make_plan()
        self._bare_run_dir(plan)
        cwd = self._decoy_cwd(acceptance=[{"id": "AC-9"}])
        result = self._run_in(cwd, "audit_coverage.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_decoy_alone_is_refused(self):
        plan = make_plan()
        self._bare_run_dir(plan)
        import shutil
        shutil.rmtree(plan.parent / "req-align-2026-09-02-demo-feature")
        cwd = self._decoy_cwd(next_stage="exec-plan")
        result = self._run_in(cwd, "update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot locate upstream handoff.json", result.stderr)
        result = self._run_in(cwd, "audit_coverage.py", plan)
        self.assertEqual(result.returncode, 2)


class RunDirSiblingTest(unittest.TestCase):
    """run_dir 解析后必须是 plan 目录的同级 req-align-<date>-<slug>；`..` 本身合法。"""

    def _move_run_elsewhere(self, plan: Path) -> Path:
        run = plan.parent / "req-align-2026-09-02-demo-feature"
        elsewhere = plan.parent.parent / "elsewhere"
        elsewhere.mkdir()
        shutil.move(str(run), str(elsewhere / run.name))
        return elsewhere / run.name

    def _set_run_dir(self, plan: Path, value: str) -> None:
        upstream = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
        upstream["run_dir"] = value
        (plan / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")

    def test_decoy_outside_sibling_refused_everywhere(self):
        plan = make_plan()
        moved = self._move_run_elsewhere(plan)
        for value in (str(moved), f"../../elsewhere/{moved.name}"):
            with self.subTest(run_dir=value):
                self._set_run_dir(plan, value)
                r = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
                self.assertEqual(r.returncode, 1)
                self.assertIn("cannot locate upstream handoff.json", r.stderr)
                r = run_script("audit_coverage.py", plan)
                self.assertEqual(r.returncode, 2)
                self.assertIn("cannot locate", r.stderr)

    def test_non_matching_name_refused(self):
        plan = make_plan()
        run = plan.parent / "req-align-2026-09-02-demo-feature"
        odd = plan.parent / "my-run"
        shutil.copytree(run, odd)
        shutil.rmtree(run)
        self._set_run_dir(plan, "../my-run")
        r = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot locate upstream handoff.json", r.stderr)
        self.assertEqual(run_script("audit_coverage.py", plan).returncode, 2)

    def test_standard_relative_and_absolute_sibling_still_work(self):
        plan = make_plan()
        run = plan.parent / "req-align-2026-09-02-demo-feature"
        for value in (f"../{run.name}", str(run)):
            with self.subTest(run_dir=value):
                self._set_run_dir(plan, value)
                self.assertEqual(run_script("audit_coverage.py", plan).returncode, 0)
                r = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
                self.assertIn(r.returncode, (0,), r.stderr)
                (plan / "step.json").write_text(json.dumps(
                    [{"step": "01-a", "state": "pending", "covers": ["AC-1"]},
                     {"step": "02-b", "state": "pending", "covers": ["AC-2"]}]), encoding="utf-8")


class ContractVersionTest(unittest.TestCase):
    def _set(self, plan: Path, **patch) -> None:
        path = plan / "upstream.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(patch)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_wrong_upstream_contract_version_rejected(self):
        for bad in ("2", 1, ""):
            with self.subTest(bad=bad):
                plan = make_plan()
                self._set(plan, contract_version=bad)
                r = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
                self.assertEqual(r.returncode, 1)
                self.assertIn("contract_version", r.stderr)
                r = run_script("audit_coverage.py", plan)
                self.assertEqual(r.returncode, 2)
                self.assertIn("contract_version", r.stderr)

    def test_absent_upstream_contract_version_accepted(self):
        plan = make_plan()
        data = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
        data.pop("contract_version")
        (plan / "upstream.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(run_script("update_step_state.py", plan / "step.json", "01-a",
                                    "runing").returncode, 0)
        self.assertEqual(run_script("audit_coverage.py", plan).returncode, 0)


class HandoffIdentityTest(unittest.TestCase):
    """handoff 必须是 contract_version "1" 且 slug 与 upstream.json 一致。"""

    def test_bad_contract_version_blocks_runing(self):
        plan = make_plan()
        rewrite_handoff(plan, contract_version="2")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("contract_version", result.stderr)

    def test_slug_mismatch_blocks_runing(self):
        plan = make_plan()
        set_handoff_slug(plan, "other")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("slug", result.stderr)

    def test_bad_contract_version_fails_audit(self):
        plan = make_plan()
        rewrite_handoff(plan, contract_version="2")
        result = run_script("audit_coverage.py", plan)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contract_version", result.stdout + result.stderr)

    def test_slug_mismatch_fails_audit(self):
        plan = make_plan()
        set_handoff_slug(plan, "other")
        result = run_script("audit_coverage.py", plan)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("slug", result.stdout + result.stderr)

    def test_audit_requires_run_dir_and_slug_in_upstream(self):
        for missing in ("run_dir", "slug"):
            plan = make_plan()
            upstream = json.loads((plan / "upstream.json").read_text(encoding="utf-8"))
            upstream.pop(missing)
            (plan / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
            result = run_script("audit_coverage.py", plan)
            self.assertEqual(result.returncode, 2, missing)
            self.assertIn(missing, result.stderr)


class AuditCoverageTest(unittest.TestCase):
    def test_upstream_without_acceptance_fails_even_without_requirements(self):
        plan = make_plan()
        rewrite_handoff(plan, acceptance=[])
        (plan / "requirements.md").unlink()
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("upstream has no acceptance criteria", result.stdout)
        self.assertIn("requirements.md missing", result.stdout)

    def test_no_op_without_upstream(self):
        plan = make_plan(with_upstream=False)
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 0)
        self.assertIn("generic mode", result.stdout)

    def test_full_coverage_passes(self):
        plan = make_plan()
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_gap_is_reported(self):
        plan = make_plan(covers=[["AC-1"], []])
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance not covered by any step: AC-2", result.stdout)

    def test_requirements_covers_must_agree_with_steps(self):
        plan = make_plan()
        (plan / "requirements.md").write_text(
            "# Requirements\n\n## R1 a\n- Covers: AC-1\n", encoding="utf-8")
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("disagree", result.stdout)

    def test_missing_requirements_md_fails(self):
        plan = make_plan()
        (plan / "requirements.md").unlink()
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requirements.md missing", result.stdout)

    def test_requirements_without_covers_annotation_fails(self):
        plan = make_plan()
        (plan / "requirements.md").write_text(
            "# Requirements\n\n## R1 a\n- Intent: build a thing\n", encoding="utf-8")
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no `Covers: AC-N` annotations", result.stdout)

    def test_requirements_covers_agreeing_passes(self):
        plan = make_plan()
        (plan / "requirements.md").write_text(
            "# Requirements\n\n## R1 a\n- Covers: AC-1\n\n## R2 b\n- Covers: AC-2\n",
            encoding="utf-8")
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 0, result.stdout)


class CoversTypeTest(unittest.TestCase):
    def test_non_list_covers_is_a_clear_fail(self):
        plan = make_plan()
        steps = [{"step": "01-a", "state": "pending", "covers": "AC-1"},
                 {"step": "02-b", "state": "pending", "covers": ["AC-2"]}]
        (plan / "step.json").write_text(json.dumps(steps), encoding="utf-8")
        result = run_script("audit_coverage.py", plan)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("covers must be a list", result.stdout)
        self.assertIn("01-a", result.stdout)
        self.assertNotIn("unknown acceptance ids: A", result.stdout)


class MetricsTest(unittest.TestCase):
    def test_state_changes_are_retained_as_jsonl(self):
        plan = make_plan(closed=("AC-1",))
        step_json = plan / "step.json"
        run_script("update_step_state.py", step_json, "01-a", "runing")
        run_script("update_step_state.py", step_json, "01-a", "complate")
        jsonl = plan.parent / ".skill-metrics" / "runs.jsonl"
        self.assertTrue(jsonl.is_file())
        records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(r["skill"] == "execute-plan-plus-v2" for r in records))
        self.assertEqual([r["to"] for r in records], ["runing", "complate"])
        self.assertEqual(records[-1]["covers"], ["AC-1"])

    def test_unwritable_metrics_dir_does_not_fail_the_command(self):
        plan = make_plan(with_upstream=False)
        (plan.parent / ".skill-metrics").write_text("not a directory\n", encoding="utf-8")
        result = run_script("update_step_state.py", plan / "step.json", "01-a", "runing")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

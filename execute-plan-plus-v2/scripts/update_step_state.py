#!/usr/bin/env python3
"""Safely update execute-plan-plus-v2 step.json state.

Usage:
  python3 scripts/update_step_state.py <step.json> <step> runing
  python3 scripts/update_step_state.py <step.json> <step> complate
  python3 scripts/update_step_state.py <step.json> <step> complate --covers-none --reason TEXT
  python3 scripts/update_step_state.py <step.json> <step> runing --force --reason TEXT
  python3 scripts/update_step_state.py <step.json> <step> block --reason TEXT \
      (--pitfall PIT-N | --no-pitfall REASON)
  python3 scripts/update_step_state.py <step.json> <step> unblock

The intentionally misspelled states match the execute-plan-plus contract.

Design rationale:

- When the plan folder has `upstream.json`, `complate` requires every AC-N in the
  step's `covers` to be already closed upstream. Ticking the upstream acceptance
  checklist used to be a *deferred* obligation performed after execution finished;
  making it a precondition of state progress turns it into an in-flow action.
- `block` requires an explicit stance on whether the failure is worth recording as
  a project-level pitfall. "Remember to log the lesson afterwards" has no trigger
  point once the context moves on.
- The plan folder name must carry the upstream slug, so `ls docs/` alone shows
  which req-align run an exec-plan implements. Enforced here rather than in prose.

Without `upstream.json` it operates in generic mode (no upstream checks).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402

SKILL = "execute-plan-plus-v2"

VALID_STATES = {"pending", "runing", "complate"}
LEGAL_TRANSITIONS = {
    ("pending", "runing"),
    ("runing", "complate"),
}
UPSTREAM_FILE = "upstream.json"

# next_stage 指向中间层时，执行计划起步前该阶段必须已登记且强制文件齐全。
KNOWN_NEXT_STAGES = ("sdd", "arch-discovery", "exec-plan")
STAGE_REQUIRED_FILES = {
    "sdd": ("README.md", "01-overview.md", "acceptance-matrix.md"),
    "arch-discovery": ("architecture.md", "flows-and-boundaries.md", "decisions.md"),
}
STAGE_DIR_PREFIX = {
    "sdd": "sdd-",
    "arch-discovery": "architecture-discovery-",
}
RUN_DIRNAME_RE = re.compile(r"req-align-\d{4}-\d{2}-\d{2}-.+")
VALID_RISK_STATES = {"未命中", "待验证", "已决议"}
# 上游契约的新鲜度指纹键——与 req-align-v2 的 source_sha256 约定保持一致，
# 此处为镜像计算，不跨包导入
UPSTREAM_SOURCE_FILES = ("align.md", "arch-risk.md", "acceptance.md")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def load_json_file(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def load_steps(path: Path) -> list:
    data = load_json_file(path)
    if not isinstance(data, list):
        fail("step.json must be a JSON array")
    return data


def validate_steps(data: list) -> None:
    seen = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            fail(f"entry {index} must be an object")
        if "step" not in item or "state" not in item:
            fail(f"entry {index} must contain 'step' and 'state'")
        if not isinstance(item["step"], str) or not item["step"]:
            fail(f"entry {index} step must be a non-empty string")
        if not isinstance(item["state"], str):
            fail(f"entry {index} state must be a string")
        if item["state"] not in VALID_STATES:
            fail(f"entry {index} has invalid state: {item['state']}")
        if "blocked" in item and not isinstance(item["blocked"], bool):
            fail(f"entry {index} blocked must be a boolean")
        if "block_reason" in item and not isinstance(item["block_reason"], str):
            fail(f"entry {index} block_reason must be a string")
        if "covers" in item and not isinstance(item["covers"], list):
            fail(f"entry {index} covers must be an array of AC ids")
        if item["step"] in seen:
            fail(f"duplicate step name found: {item['step']}")
        seen.add(item["step"])


def atomic_write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent),
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        fail(f"cannot write {path}: {exc}")


# --------------------------------------------------------------- upstream link


def load_upstream(plan_dir: Path) -> Optional[dict]:
    path = plan_dir / UPSTREAM_FILE
    if not path.is_file():
        return None
    data = load_json_file(path)
    if not isinstance(data, dict):
        fail(f"{path} must be a JSON object")
    for key in ("run_dir", "slug"):
        if not data.get(key):
            fail(f"{path} must contain a non-empty '{key}'")
    if "contract_version" in data and data["contract_version"] != "1":
        fail(f"{path} contract_version is {data['contract_version']!r}, expected \"1\"")
    return data


def dirname_matches_contract(dirname: str, prefix: str, slug: str) -> bool:
    """目录名契约：`<prefix><yyyy-mm-dd>-<slug>` 精确匹配（slug 里可含 -2 等后缀）。"""
    return bool(re.fullmatch(
        rf"{re.escape(prefix)}\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}", dirname))


def check_slug(plan_dir: Path, upstream: dict) -> None:
    slug = upstream["slug"]
    if not dirname_matches_contract(plan_dir.resolve().name, "exec-plan-", slug):
        fail(
            f"plan folder '{plan_dir.name}' does not carry the upstream slug '{slug}'.\n"
            f"  Rename it to docs/exec-plan-<yyyy-mm-dd>-{slug}/ so `ls docs/` shows the chain."
        )


def is_sibling_run_dir(plan_dir: Path, candidate: Path) -> bool:
    """候选 run 目录必须与 plan 目录同级（同一 docs/）且目录名为 req-align-<date>-<slug>。"""
    return (RUN_DIRNAME_RE.fullmatch(candidate.name) is not None
            and candidate.resolve().parent == plan_dir.resolve().parent)


def locate_handoff_file(plan_dir: Path, upstream: dict) -> Path:
    """只相对 plan 目录解析 run_dir——绝不用进程 CWD，否则 CWD 里的同名目录会顶替真上游。
    绝对路径仅在目录名符合 req-align-<date>-<slug> 形态时沿用。"""
    run_dir = Path(upstream["run_dir"])
    candidates = [plan_dir.parent / run_dir.name]
    if not run_dir.is_absolute() or RUN_DIRNAME_RE.fullmatch(run_dir.name):
        candidates.insert(0, plan_dir / run_dir)
    for candidate in candidates:
        if not is_sibling_run_dir(plan_dir, candidate):
            continue
        path = candidate / "handoff.json"
        if path.is_file():
            return path
    fail(
        f"cannot locate upstream handoff.json via '{upstream['run_dir']}'. "
        "Fix upstream.json, or run `align_state.py sync <run_dir>` first."
    )
    return path  # unreachable — fail() exits


def resolve_handoff(plan_dir: Path, upstream: dict) -> tuple:
    """返回 (handoff.json 路径, 契约数据)——路径用于校验同目录源文件哈希。"""
    path = locate_handoff_file(plan_dir, upstream)
    data = load_json_file(path)
    if not isinstance(data, dict):
        fail(f"{path} must be a JSON object")
    return path, data


AC_CHECKBOX_RE = re.compile(r"^-\s+\[([ xX])\]\s+(AC-\d+)\s+(.+?)\s*$")


def acceptance_md_closed_with_evidence(text: str, ac: str) -> bool:
    """acceptance.md 是否同时有 `- [x] AC-N` 勾选行（跳过代码块）与「证据」小节里的
    非空证据记录（`- AC-N | step | evidence` 或旧式 `- AC-N | evidence`）。
    逐条镜像 req-align-v2 `_artifacts.parse_acceptance_items` / `parse_evidence_records`。"""
    in_fence = has_tick = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = AC_CHECKBOX_RE.match(stripped)
        if match and match.group(2) == ac and match.group(1).lower() == "x":
            has_tick = True
    return has_tick and ac in parse_evidence_ids(text)


def parse_evidence_ids(text: str) -> set:
    """镜像 `_artifacts.split_sections` + `find_section(.., "证据")` + `parse_evidence_records`。"""
    lines = text.splitlines()
    heading = None
    start = 0
    body = None
    for index, raw in enumerate(lines):
        if re.match(r"^#{2,3}\s+\S", raw.strip()):
            if heading is not None and "证据" in heading:
                body = lines[start:index]
                break
            heading = raw.strip().lstrip("#").strip()
            start = index + 1
    else:
        if heading is not None and "证据" in heading:
            body = lines[start:]
    result = set()
    for line in body or []:
        stripped = line.strip()
        if not stripped.startswith("- AC-"):
            continue
        parts = [p.strip() for p in stripped[2:].split("|", 2)]
        if len(parts) >= 3:
            evidence = parts[2]
        elif len(parts) == 2:
            evidence = parts[1]
        else:
            continue
        if evidence:
            result.add(parts[0])
    return result


def check_covers_closed(target: dict, handoff: dict, covers_none: bool, reason: str,
                        run_dir: str, handoff_path: Path = None) -> None:
    """Gate `complate` on the upstream acceptance items this step claims to cover."""
    covers = target.get("covers") or []
    if covers and covers_none:
        fail(f"step '{target['step']}' lists covers {covers}: --covers-none is only for "
             "steps with empty 'covers'; drop the flag or empty the list in step.json")
    if not covers:
        if covers_none:
            if not reason.strip():
                fail("--covers-none requires a non-empty --reason")
            return
        fail(
            f"step '{target['step']}' has no 'covers': list the AC-N it satisfies in step.json,\n"
            "  or pass --covers-none --reason TEXT for pure-infrastructure steps."
        )
    known = {item.get("id"): item for item in handoff.get("acceptance", [])}
    unknown = [ac for ac in covers if ac not in known]
    if unknown:
        fail(
            f"step '{target['step']}' covers unknown acceptance ids: {', '.join(unknown)}. "
            f"Upstream defines: {', '.join(sorted(known)) or '(none)'}"
        )
    open_items = [ac for ac in covers if not known[ac].get("closed")]
    if open_items:
        listing = "\n".join(
            f"  python3 <req-align-v2>/scripts/align_state.py close-ac {run_dir} {ac} "
            f'--run-cmd "<verification command>" --step {target["step"]}'
            for ac in open_items
        )
        fail(
            f"step '{target['step']}' cannot be complate: upstream acceptance not closed "
            f"({', '.join(open_items)}).\nClose them with evidence first:\n{listing}"
        )
    if handoff_path is not None:
        # handoff.json 的 closed 标志可手改且不影响源哈希——以已过新鲜度校验的
        # acceptance.md 为准：必须有勾选行和非空证据
        text = (handoff_path.parent / "acceptance.md").read_text(encoding="utf-8")
        unproven = [ac for ac in covers if not acceptance_md_closed_with_evidence(text, ac)]
        if unproven:
            fail(
                f"step '{target['step']}' cannot be complate: acceptance.md does not show "
                f"{', '.join(unproven)} closed with evidence (ticked box + evidence record). "
                f"Use `align_state.py close-ac {run_dir} <AC-N> --evidence ...` "
                "instead of editing handoff.json."
            )


def check_upstream_freshness(handoff_path: Path, handoff: dict) -> None:
    """新鲜度门禁：handoff.json 必须是三份源 Markdown 当前字节的派生。

    只证明"契约是新的"，不证明任何验证结果——spec 变更须先 `fail-ac` 重开再 sync。
    """
    recorded = handoff.get("source_sha256")
    sync_hint = "re-run `align_state.py sync <run_dir>` to regenerate the contract"
    if not isinstance(recorded, dict) or set(recorded) != set(UPSTREAM_SOURCE_FILES):
        fail(
            "upstream handoff.json lacks a valid 'source_sha256' map "
            f"(expected keys: {', '.join(UPSTREAM_SOURCE_FILES)}). {sync_hint}."
        )
    run_dir = handoff_path.parent
    for name in UPSTREAM_SOURCE_FILES:
        source = run_dir / name
        if not source.is_file():
            fail(f"upstream source file missing: {source}. {sync_hint}.")
        stored = recorded[name]
        if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
            fail(f"upstream handoff.json source_sha256['{name}'] is not a valid "
                 f"sha256 hex. {sync_hint}.")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if stored != actual:
            fail(
                f"upstream {name} changed after handoff.json was generated "
                "(source_sha256 mismatch). If the AC spec changed, reopen it with "
                "`fail-ac` first; otherwise " + sync_hint + "."
            )


def check_upstream_readiness(plan_dir: Path, upstream: dict, handoff_path: Path,
                             handoff: dict) -> None:
    """起步前置：契约新鲜、中间层阶段已登记且文件齐全、无 `待验证` 遗留风险。

    检查的是"上游是否准备好开工"，不是审计中间层内容本身——文件存在性
    由 `stage-add` 在登记时校验过，这里只确认登记与实际文件仍在。
    """
    if handoff.get("contract_version") != "1":
        fail(f"upstream handoff.json contract_version is "
             f"{handoff.get('contract_version')!r}, expected \"1\"")
    if handoff.get("slug") != upstream["slug"]:
        fail(f"upstream handoff.json slug {handoff.get('slug')!r} does not match "
             f"upstream.json slug {upstream['slug']!r}")
    check_upstream_freshness(handoff_path, handoff)
    next_stage = handoff.get("next_stage")
    if next_stage not in KNOWN_NEXT_STAGES:
        fail(f"upstream handoff.json has unknown next_stage: {next_stage!r} "
             f"(expected one of: {', '.join(KNOWN_NEXT_STAGES)})")
    if next_stage in STAGE_REQUIRED_FILES:
        stages = handoff.get("stages") or []
        entry = next(
            (s for s in stages if isinstance(s, dict) and s.get("stage") == next_stage),
            None,
        )
        if entry is None or not entry.get("dir"):
            fail(
                f"upstream next_stage is '{next_stage}' but handoff.json registers no such "
                f"stage. Finish that stage and run `align_state.py stage-add` first."
            )
        # 契约要求各阶段共用同一 docs/ 目录；登记路径只取 basename 在此解析。
        # 目录名必须与契约精确一致：<prefix><yyyy-mm-dd>-<slug>——子串匹配会让
        # `sdd-…-<slug>-extra` 这类名字混过去
        stage_dir = plan_dir.parent / Path(entry["dir"]).name
        if not dirname_matches_contract(
                stage_dir.name, STAGE_DIR_PREFIX[next_stage], upstream["slug"]):
            fail(
                f"registered {next_stage} stage dir '{stage_dir.name}' does not match "
                f"`{STAGE_DIR_PREFIX[next_stage]}<yyyy-mm-dd>-{upstream['slug']}` under docs/"
            )
        if not stage_dir.is_dir():
            fail(f"registered {next_stage} stage dir is missing: {stage_dir}")
        missing = [name for name in STAGE_REQUIRED_FILES[next_stage]
                   if not (stage_dir / name).is_file()]
        if missing:
            fail(
                f"{next_stage} stage {stage_dir.name} is missing required files: "
                f"{', '.join(missing)}"
            )
    risks = handoff.get("risks")
    if not isinstance(risks, list):
        fail("upstream handoff.json 'risks' must be a list "
             "(re-run `align_state.py sync <run_dir>` to rebuild the contract)")
    for index, risk in enumerate(risks):
        if not isinstance(risk, dict):
            fail(f"upstream handoff.json risks[{index}] must be an object, "
                 f"got {type(risk).__name__}")
        risk_id = risk.get("id")
        if not isinstance(risk_id, str) or not risk_id.strip():
            fail(f"upstream handoff.json risks[{index}] has no non-empty 'id'")
        if risk.get("state") not in VALID_RISK_STATES:
            fail(
                f"upstream handoff.json risk {risk_id} has unknown state: "
                f"{risk.get('state')!r} (expected one of: "
                f"{' / '.join(sorted(VALID_RISK_STATES))})"
            )
    pending = [r["id"] for r in risks if r["state"] == "待验证"]
    if pending:
        fail(
            f"upstream risks still 待验证: {', '.join(pending)}. "
            "Resolve them with `align_state.py resolve-risk` before stepping."
        )


# -------------------------------------------------------------------- cli glue


def parse_args(argv: list) -> dict:
    options = {
        "force": False, "reason": None, "covers_none": False,
        "pitfall": None, "no_pitfall": None,
    }
    positionals = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--force":
            options["force"] = True
        elif arg == "--covers-none":
            options["covers_none"] = True
        elif arg in ("--reason", "--pitfall", "--no-pitfall"):
            index += 1
            if index >= len(argv):
                fail(f"{arg} requires a value")
            options[arg[2:].replace("-", "_")] = argv[index]
        elif arg.startswith("--"):
            fail(f"unknown option: {arg}")
        else:
            positionals.append(arg)
        index += 1
    if len(positionals) != 3:
        fail(
            "usage: update_step_state.py <step.json> <step> "
            "runing|complate|block|unblock [options]"
        )
    options["step_json"], options["step_name"], options["new_state"] = positionals
    return options


def main(argv: list = None) -> None:
    options = parse_args(sys.argv[1:] if argv is None else argv)
    new_state = options["new_state"]
    step_name = options["step_name"]
    step_json = Path(options["step_json"])
    reason = options["reason"] or ""

    if new_state not in VALID_STATES and new_state not in ("block", "unblock"):
        fail(f"state must be one of: {', '.join(sorted(VALID_STATES))}, block, unblock")
    if not step_json.exists():
        fail(f"step.json not found: {step_json}")

    plan_dir = step_json.resolve().parent
    upstream = load_upstream(plan_dir)
    if upstream is not None:
        check_slug(plan_dir, upstream)

    data = load_steps(step_json)
    validate_steps(data)

    target_index = next((i for i, item in enumerate(data) if item["step"] == step_name), None)
    if target_index is None:
        fail(f"step not found: {step_name}")
    target = data[target_index]
    old_state = target["state"]

    if new_state == "block":
        if not reason.strip():
            fail("block requires a non-empty --reason")
        if not options["pitfall"] and not options["no_pitfall"]:
            fail(
                "block requires an explicit stance on the lesson:\n"
                "  --pitfall PIT-N        the root cause is recorded in the project pitfall ledger\n"
                "  --no-pitfall REASON    why this failure is not worth recording\n"
                "(Recording the lesson 'later' has no trigger point once the context moves on.)"
            )
        target["blocked"] = True
        target["block_reason"] = reason
        if options["pitfall"]:
            target["pitfall"] = options["pitfall"]
            target.pop("no_pitfall_reason", None)
        else:
            if not options["no_pitfall"].strip():
                fail("--no-pitfall requires a non-empty reason")
            target["no_pitfall_reason"] = options["no_pitfall"]
            target.pop("pitfall", None)
        atomic_write_json(step_json, data)
        metrics.emit(SKILL, "step_blocked", run=plan_dir, step=step_name,
                     pitfall_id=options["pitfall"], no_pitfall_reason=options["no_pitfall"])
        print(f"blocked {step_name} (state stays {target['state']}; reason: {reason})")
        return

    if new_state == "unblock":
        if "blocked" not in target and "block_reason" not in target:
            print(f"unchanged {step_name} (not blocked)")
            return
        for key in ("blocked", "block_reason", "pitfall", "no_pitfall_reason"):
            target.pop(key, None)
        atomic_write_json(step_json, data)
        print(f"unblocked {step_name}")
        return

    # blocked 步骤只有 `unblock` 能解锁——runing/complate（含 --force）一律拒绝
    if target.get("blocked"):
        fail(
            f"step '{step_name}' is blocked: {target.get('block_reason', '')}. "
            "Resume only after the user's decision, then run `unblock`."
        )

    if options["force"]:
        if not reason.strip():
            fail("--force requires a non-empty --reason")
        if (old_state, new_state) != ("pending", "runing"):
            fail(
                f"--force is only allowed for pending -> runing dependency reordering, "
                f"not {old_state} -> {new_state}"
            )
        if upstream is not None:
            # --force 只放宽步骤顺序，上游就绪门禁一律不跳过
            handoff_path, handoff = resolve_handoff(plan_dir, upstream)
            check_upstream_readiness(plan_dir, upstream, handoff_path, handoff)
        target["state"] = new_state
        target["override_reason"] = reason
        atomic_write_json(step_json, data)
        metrics.emit(SKILL, "step_state", run=plan_dir, step=step_name,
                     **{"from": old_state}, to=new_state, forced=True,
                     covers=target.get("covers") or [],
                     covers_none=bool(target.get("covers_none")),
                     slug_ok=upstream is not None)
        print(f"override {step_name}: {old_state} -> {new_state} (reason: {reason})")
        return

    if old_state == new_state:
        print(f"unchanged {step_name} -> {new_state}")
        return

    if (old_state, new_state) not in LEGAL_TRANSITIONS:
        fail(f"illegal transition for {step_name}: {old_state} -> {new_state}")

    if new_state == "runing":
        incomplete = [item["step"] for item in data[:target_index]
                      if item["state"] != "complate"]
        if incomplete:
            fail("cannot start step before previous steps are complate: "
                 + ", ".join(incomplete))

    handoff = None
    if upstream is not None and new_state in ("runing", "complate"):
        handoff_path, handoff = resolve_handoff(plan_dir, upstream)
        check_upstream_readiness(plan_dir, upstream, handoff_path, handoff)

    if new_state == "complate" and upstream is not None:
        check_covers_closed(target, handoff, options["covers_none"], reason,
                            upstream["run_dir"], handoff_path)
        if options["covers_none"]:
            target["covers_none"] = True
            target["covers_none_reason"] = reason

    target["state"] = new_state
    atomic_write_json(step_json, data)
    metrics.emit(SKILL, "step_state", run=plan_dir, step=step_name,
                 **{"from": old_state}, to=new_state, forced=False,
                 covers=target.get("covers") or [],
                 covers_none=bool(target.get("covers_none")),
                 slug_ok=upstream is not None)
    print(f"updated {step_name}: {old_state} -> {new_state}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""req-align-v2 单个 run 内的写操作唯一入口。

用法:
  python3 scripts/align_state.py sync <run_dir>
  python3 scripts/align_state.py close-ac <run_dir> AC-N --evidence TEXT [--step NAME]
  python3 scripts/align_state.py close-ac <run_dir> AC-N --run-cmd CMD [--cwd DIR] [--timeout SEC] \
      [--evidence NOTE] [--step NAME]
  python3 scripts/align_state.py close-ac <run_dir> AC-N --manual --observer NAME --evidence TEXT
  python3 scripts/align_state.py record-review <run_dir> --reviewer NAME --author NAME \
      --scope milestone|time-backstop|final --verdict approved|changes-requested --summary TEXT
  python3 scripts/align_state.py fail-ac <run_dir> AC-N --observed TEXT
  python3 scripts/align_state.py resolve-risk <run_dir> RISK-N \
      --decision TEXT --reason TEXT --impact TEXT [--confirmed-by human|agent]
  python3 scripts/align_state.py stage-add <run_dir> --stage sdd|arch-discovery|exec-plan --dir PATH

为什么所有写操作必须走脚本：`arch-risk.md` 的「状态」列与「决议记录」段是同一事实的
两处记录，手改必然漂移（状态列与决议段数目不符）。本脚本把这两处
放进同一次原子写，人手没有机会写歪。`acceptance.md` 的勾选同理，且强制带证据。

证据诚实边界：--run-cmd 由脚本自己执行并记录退出码与代码版本（rev）；--manual 记录观察者；
裸 --evidence 仅是自报文本。脚本证明不了命令有意义、审核者真独立，只能让缺失/过期可被拒绝。

退出码: 0 成功 / 1 校验失败 / 2 参数或路径错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402
from _artifacts import (  # noqa: E402
    ACCEPTANCE_FILE,
    ALIGN_FILE,
    ARCH_RISK_FILE,
    CONTRACT_VERSION,
    HANDOFF_FILE,
    NEXT_STAGES,
    REVIEWS_FILE,
    RISK_STATES,
    STAGE_DIR_PREFIX,
    STAGE_REQUIRED_FILES,
    ArtifactError,
    append_to_level2_section,
    atomic_write,
    build_row,
    code_fingerprint,
    dump_handoff,
    find_section,
    git_toplevel,
    next_id,
    load_reviews,
    parse_acceptance_items,
    parse_align_acceptance,
    parse_decisions,
    parse_evidence_records,
    parse_risk_table,
    parse_run_dirname,
    read_text,
    require_dir,
    split_row,
    split_sections,
    source_sha256,
)

SKILL = "req-align-v2"

STAGE_KEYWORDS = (
    ("exec-plan", ("执行计划", "exec-plan", "execute-plan")),
    ("arch-discovery", ("架构发现", "arch-discovery", "architecture-discovery")),
    ("sdd", ("SDD", "sdd", "规格")),
)


# --------------------------------------------------------------------- helpers


def detect_next_stage(align_text: str) -> str:
    """从 align.md「➡️ 下一阶段」小节的「去向:」行判定下一阶段。"""
    section = find_section(split_sections(align_text), "下一阶段")
    if section is None:
        raise ArtifactError("align.md 缺「➡️ 下一阶段」小节")
    target_line = ""
    for line in section.body.splitlines():
        if line.strip().startswith("去向"):
            target_line = line
            break
    if not target_line:
        raise ArtifactError("align.md「下一阶段」小节缺「去向:」行")
    for stage, keywords in STAGE_KEYWORDS:
        if any(keyword in target_line for keyword in keywords):
            return stage
    raise ArtifactError(
        f"无法从「{target_line.strip()}」判定下一阶段，需含 执行计划/架构发现/SDD 之一"
    )


def detect_title(align_text: str) -> str:
    for line in align_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def load_run(run_dir: Path):
    """读取三份 Markdown，并做跨文件的 ID 一致性校验。"""
    align_text = read_text(run_dir / ALIGN_FILE)
    risk_text = read_text(run_dir / ARCH_RISK_FILE)
    acceptance_text = read_text(run_dir / ACCEPTANCE_FILE)

    align_items = parse_align_acceptance(align_text)
    if not align_items:
        raise ArtifactError(
            "align.md 没有解析到验收条目：每条须写成 `- AC-1 (P0) 输入 X → 输出 Y`"
        )
    align_ids = [item.id for item in align_items]
    duplicates = {i for i in align_ids if align_ids.count(i) > 1}
    if duplicates:
        raise ArtifactError(f"align.md 验收 ID 重复: {', '.join(sorted(duplicates))}")

    checkbox_items = [item for item, _ in parse_acceptance_items(acceptance_text)]
    checkbox_ids = [item.id for item in checkbox_items]
    dup_cb = {i for i in checkbox_ids if checkbox_ids.count(i) > 1}
    if dup_cb:
        raise ArtifactError(f"acceptance.md 验收 ID 重复: {', '.join(sorted(dup_cb))}")
    if set(align_ids) != set(checkbox_ids):
        missing = sorted(set(align_ids) - set(checkbox_ids))
        extra = sorted(set(checkbox_ids) - set(align_ids))
        raise ArtifactError(
            "align.md 与 acceptance.md 的 AC 集合不一致"
            + (f"；acceptance 缺: {', '.join(missing)}" if missing else "")
            + (f"；acceptance 多出: {', '.join(extra)}" if extra else "")
        )

    risks = parse_risk_table(risk_text)
    risk_ids = [risk.id for risk in risks]
    dup_risk = {i for i in risk_ids if risk_ids.count(i) > 1}
    if dup_risk:
        raise ArtifactError(f"arch-risk.md 风险 ID 重复: {', '.join(sorted(dup_risk))}")
    for risk in risks:
        if risk.state not in RISK_STATES:
            raise ArtifactError(
                f"{risk.id} 状态「{risk.state}」非法，只允许 {' / '.join(RISK_STATES)}"
            )
    return align_items, checkbox_items, risks, align_text, risk_text, acceptance_text


def drifted_closed_acs(align_items, closed_map, existing) -> list:
    """共用判定：仍勾选关闭、但 align.md 的优先级/文本已偏离既有 handoff 的 AC。

    closed_map 是「写入后」的勾选状态——写命令在落盘前把目标 AC 的拟定状态
    叠进去做预检，sync 时直接用文件里读到的状态。
    """
    prior = {
        entry.get("id"): entry
        for entry in (existing or {}).get("acceptance", []) or []
        if isinstance(entry, dict) and entry.get("id")
    }
    return [
        item.id for item in align_items
        if (item.id in prior
            and prior[item.id].get("closed")
            and closed_map.get(item.id, False)
            and (prior[item.id].get("priority") != item.priority
                 or prior[item.id].get("text") != item.text))
    ]


def drifted_ac_error(drifted: list) -> ArtifactError:
    return ArtifactError(
        f"{', '.join(drifted)} 仍勾选关闭，但 align.md 的优先级或验收文本已变更——"
        "旧证据不能证明新契约。先 `fail-ac` 重开并记录原因，再改文，最后 sync"
    )


def failed_ac_ids(acceptance_text: str) -> set:
    """「## 未通过记录」里出现过的 AC——fail-ac 的写入痕迹，合法重开的唯一凭据。"""
    section = find_section(split_sections(acceptance_text), "未通过记录")
    if section is None:
        return set()
    return {m.group(1) for m in (re.match(r"^-\s+(AC-\d+)\b", line.strip())
                                 for line in section.body.splitlines()) if m}


def reopened_without_record(closed_map, existing, acceptance_text, exempt=()) -> list:
    """既有 handoff 记为已关闭、acceptance.md 却变成未勾选、又无未通过记录的 AC。

    手动取消勾选会绕过 drifted_closed_acs（它只看仍勾选的），必须走 fail-ac 留痕。
    exempt: 本次 fail-ac 的目标（记录尚未写入）。
    """
    recorded = failed_ac_ids(acceptance_text)
    return [
        entry["id"] for entry in (existing or {}).get("acceptance", []) or []
        if isinstance(entry, dict) and entry.get("id") and entry.get("closed")
        and entry["id"] in closed_map and not closed_map[entry["id"]]
        and entry["id"] not in recorded and entry["id"] not in exempt
    ]


def reopened_error(reopened: list) -> ArtifactError:
    return ArtifactError(
        f"{', '.join(reopened)} 在既有 handoff.json 中已关闭，但 acceptance.md 现为未勾选且"
        "「未通过记录」无对应条目——手动取消勾选会抹掉证据。请用 "
        "`align_state.py fail-ac` 重开并记录原因"
    )


def load_existing_handoff(run_dir: Path) -> dict:
    """读取既有 handoff.json。缺失视为无历史（首次 sync 前合法）；
    文件存在却损坏必须 fail closed——静默当空会把已关闭 AC 的防漂移保护一并重置。"""
    path = run_dir / HANDOFF_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ArtifactError(
            f"{path} 不是合法 JSON: {exc}。损坏的契约不能当作无历史继续——"
            "请从备份恢复或人工修复该文件后重试"
        ) from exc
    if not isinstance(data, dict):
        raise ArtifactError(f"{path} 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def require_handoff_for_ticked(run_dir: Path, closed_map: dict) -> None:
    """handoff.json 缺失却已有勾选：全新 run 不可能有勾选，说明契约被删——
    静默重建会把防漂移历史清零，必须 fail closed。"""
    ticked = sorted(i for i, closed in closed_map.items() if closed)
    if ticked and not (run_dir / HANDOFF_FILE).is_file():
        raise ArtifactError(
            f"{HANDOFF_FILE} 缺失，但 acceptance.md 已勾选 {', '.join(ticked)}——"
            "全新 run 不会有勾选，契约历史可能被删除。请从版本控制恢复 handoff.json，"
            "或确认后取消这些勾选再 sync"
        )


def preflight_closed_ac_drift(run_dir: Path, overrides: dict = None) -> None:
    """写 Markdown 前的门卫：按「写入后的勾选状态」判定漂移，全程不碰文件。

    overrides: {ac_id: bool}——close-ac 目标视为勾选、fail-ac 目标视为重开。
    若仍有别的已关闭 AC 与 align.md 漂移，本次写操作整体拒绝。
    """
    align_items, checkbox_items, _, _, _, acceptance_text = load_run(run_dir)
    existing = load_existing_handoff(run_dir)
    file_map = {item.id: item.closed for item in checkbox_items}
    require_handoff_for_ticked(run_dir, file_map)
    reopened = reopened_without_record(file_map, existing, acceptance_text, overrides or {})
    if reopened:
        raise reopened_error(reopened)
    closed_map = dict(file_map)
    closed_map.update(overrides or {})
    drifted = drifted_closed_acs(align_items, closed_map, existing)
    if drifted:
        raise drifted_ac_error(drifted)


def build_handoff(run_dir: Path, existing: dict = None) -> dict:
    date, slug = parse_run_dirname(run_dir)
    align_items, checkbox_items, risks, align_text, _, acceptance_text = load_run(run_dir)
    closed_map = {item.id: item.closed for item in checkbox_items}
    evidence_map = collect_evidence(acceptance_text)

    reopened = reopened_without_record(closed_map, existing, acceptance_text)
    if reopened:
        raise reopened_error(reopened)
    drifted = drifted_closed_acs(align_items, closed_map, existing)
    if drifted:
        raise drifted_ac_error(drifted)
    acceptance = []
    for item in align_items:
        evidence, step = evidence_map.get(item.id, (None, None))
        closed = closed_map.get(item.id, False)
        acceptance.append({
            "id": item.id,
            "priority": item.priority,
            "text": item.text,
            "closed": closed,
            "evidence": evidence,
            "step": step,
        })

    touched = sorted({r.boundary_ref for r in risks
                      if r.boundary_ref and r.boundary_ref.startswith("BND-")})
    return {
        "contract_version": CONTRACT_VERSION,
        "slug": slug,
        "date": date,
        "title": detect_title(align_text),
        "next_stage": detect_next_stage(align_text),
        "stages": (existing or {}).get("stages", []),
        "acceptance": acceptance,
        "risks": [{"id": r.id, "boundary": r.boundary, "state": r.state,
                   "boundary_ref": r.boundary_ref if r.boundary_ref.startswith("BND-") else None}
                  for r in risks],
        "boundaries_touched": touched,
        # 新鲜度指纹：下游据此识别"源文件改动后未重新 sync"的陈旧契约
        "source_sha256": source_sha256(run_dir),
    }


def collect_evidence(acceptance_text: str) -> dict:
    """从「## 证据」小节读取 AC-N | step | evidence。"""
    return parse_evidence_records(acceptance_text)


def refresh_handoff(run_dir: Path) -> dict:
    data = build_handoff(run_dir, load_existing_handoff(run_dir))
    dump_handoff(run_dir, data)
    return data


def refresh_or_rollback(run_dir: Path, path: Path, original: str) -> dict:
    """Markdown 已改写后重建契约；失败则把该 Markdown 原样恢复再抛原错误，
    避免留下"Markdown 已改、handoff 未跟上"的半写状态。"""
    try:
        return refresh_handoff(run_dir)
    except Exception:
        atomic_write(path, original)
        raise



# -------------------------------------------------------------------- commands


def cmd_sync(args) -> int:
    run_dir = require_dir(args.run_dir)
    _, checkbox_items, _, _, _, _ = load_run(run_dir)
    require_handoff_for_ticked(run_dir, {i.id: i.closed for i in checkbox_items})
    data = refresh_handoff(run_dir)
    risk_hit = sum(1 for r in data["risks"] if r["state"] != "未命中")
    metrics.emit(SKILL, "align_landed", run=run_dir,
                 ac_total=len(data["acceptance"]), risk_hit=risk_hit,
                 risk_total=len(data["risks"]),
                 bnd_touched=data["boundaries_touched"])
    print(f"synced {run_dir}/handoff.json: "
          f"{len(data['acceptance'])} AC, {len(data['risks'])} RISK "
          f"({risk_hit} 命中), next_stage={data['next_stage']}")
    return 0


def one_line(text: str) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " ", text).strip()


def execute_command(cmd: str, cwd: Path, timeout: float) -> tuple:
    """执行验证命令，返回 (exit_code | None=超时, 合并输出字节)。

    shell=True：验证命令通常是带管道/&&/环境变量的整行 shell 命令（如 `pytest -q && ruff .`），
    由调用者（人或 agent）显式提供，与直接在终端敲入同等信任。新会话便于超时时杀整个进程组。
    """
    posix = hasattr(os, "killpg") and hasattr(signal, "SIGKILL")
    proc = subprocess.Popen(cmd, shell=True, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=posix)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        try:
            if not posix:
                raise OSError("no process groups")
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, _ = proc.communicate()
        return None, out


def output_tail(out: bytes, lines: int = 20) -> str:
    return "\n".join(out.decode("utf-8", "replace").splitlines()[-lines:])


RESERVED_EVIDENCE_PREFIXES = ("[run ", "[manual ")


def build_evidence(args, run_dir: Path) -> str:
    """按模式生成单行证据：run-cmd / manual / 旧式自报（原样）。"""
    note = one_line(args.evidence or "")
    if args.run_cmd is not None and args.manual:
        raise ArtifactError("close-ac 的 --run-cmd 与 --manual 互斥")
    if args.observer is not None and not args.manual:
        raise ArtifactError("--observer 只能与 --manual 一起使用")
    if args.manual:
        observer = one_line(args.observer or "")
        if not observer:
            raise ArtifactError("--manual 需要非空 --observer NAME：说明是谁亲眼观察的")
        if not note:
            raise ArtifactError("--manual 需要非空 --evidence：写下观察到了什么")
        return f"[manual observer={observer} rev={code_fingerprint(run_dir, ignore=run_dir)[:16]}] {note}"
    if args.run_cmd is not None:
        if "\n" in args.run_cmd or "\r" in args.run_cmd:
            raise ArtifactError("--run-cmd 不能含换行或回车：记录的命令必须与实际执行的完全一致")
        cmd = one_line(args.run_cmd)
        if not cmd:
            raise ArtifactError("--run-cmd 不能为空")
        cwd = Path(args.cwd) if args.cwd else git_toplevel(run_dir)
        if cwd is None:
            raise ArtifactError("run 目录不在 git 仓库内：--run-cmd 必须显式给出 --cwd DIR")
        if not cwd.is_dir():
            raise ArtifactError(f"--cwd 目录不存在: {cwd}")
        code, out = execute_command(args.run_cmd, cwd, args.timeout)
        if code != 0:
            why = f"超时（>{args.timeout:g}s）" if code is None else f"退出码 {code}"
            raise ArtifactError(f"验证命令失败，{why}，未改动任何文件: {cmd}\n"
                                f"--- 输出末尾 ---\n{output_tail(out)}")
        # 命令跑完再取指纹：命令本身可能生成文件，记录的是它跑完后的代码状态
        text = (f"[run exit=0 rev={code_fingerprint(run_dir, ignore=run_dir)[:16]} "
                f"out={hashlib.sha256(out).hexdigest()[:8]}] {cmd}")
        return f"{text} | note: {note}" if note else text
    if not note:
        raise ArtifactError("close-ac 需要非空 --evidence：打勾必须有证据")
    return note


def reject_reserved_prefix(evidence: str) -> None:
    """裸 --evidence 不得以保留前缀开头：这些前缀只属于脚本生成的验证证据。

    run-cmd/manual 的 note 拼在 ` | note: ` 之后，不会成为记录开头，故无需检查。
    """
    if evidence.strip().lower().startswith(RESERVED_EVIDENCE_PREFIXES):
        raise ArtifactError("--evidence 以 `[run ` / `[manual ` 开头：这些前缀保留给脚本生成的验证证据，"
                            "自报文本不可使用；请改用 --run-cmd，或 --manual --observer NAME")


def cmd_close_ac(args) -> int:
    run_dir = require_dir(args.run_dir)
    verified = args.run_cmd is not None or args.manual
    if not verified and not (args.evidence or "").strip():
        raise ArtifactError("close-ac 需要非空 --evidence：打勾必须有证据")
    if not verified:
        reject_reserved_prefix(args.evidence or "")
    path = run_dir / ACCEPTANCE_FILE
    text = read_text(path)
    lines = text.splitlines()
    items = parse_acceptance_items(text)
    target = next(((item, idx) for item, idx in items if item.id == args.ac_id), None)
    if target is None:
        raise ArtifactError(f"acceptance.md 中找不到 {args.ac_id}")
    item, line_index = target
    preflight_closed_ac_drift(run_dir, {args.ac_id: True})
    if item.closed and not verified:
        print(f"unchanged {args.ac_id} (已勾选)")
        return 0
    evidence = build_evidence(args, run_dir)
    if args.run_cmd is not None:
        text = read_text(path)
        lines = text.splitlines()
        target = next(((i, idx) for i, idx in parse_acceptance_items(text) if i.id == args.ac_id), None)
        if target is None:
            raise ArtifactError(f"验证命令执行后 acceptance.md 中找不到 {args.ac_id}")
        item, line_index = target
        preflight_closed_ac_drift(run_dir, {args.ac_id: True})
    if not item.closed:
        lines[line_index] = lines[line_index].replace("- [ ]", "- [x]", 1)
    # 刷新已关闭 AC：不改勾选，追加新记录（同 AC 以最新一条为准），沿用先前 step
    step = args.step or (parse_evidence_records(text).get(args.ac_id, (None, None))[1]) or "-"
    lines = append_to_level2_section(lines, ("证据",), [f"- {args.ac_id} | {step} | {evidence}"])
    original = path.read_bytes().decode("utf-8")
    atomic_write(path, "\n".join(lines) + "\n")
    refresh_or_rollback(run_dir, path, original)
    metrics.emit(SKILL, "ac_closed", run=run_dir, ac_id=args.ac_id,
                 step=args.step, has_evidence=True)
    print(f"{'refreshed' if item.closed else 'closed'} {args.ac_id} (evidence: {evidence[:60]})")
    return 0


def cmd_record_review(args) -> int:
    run_dir = require_dir(args.run_dir)
    fields = {n: one_line(getattr(args, n)) for n in ("reviewer", "author", "summary")}
    for name, value in fields.items():
        if not value:
            raise ArtifactError(f"record-review 需要非空 --{name}")
    if fields["reviewer"].casefold() == fields["author"].casefold():
        raise ArtifactError("审核必须独立：--reviewer 不能与 --author 是同一人")
    reviews = load_reviews(run_dir)
    ids = [r.get("id") for r in reviews if isinstance(r, dict) and isinstance(r.get("id"), str)]
    entry = {"id": next_id(ids, "REV"), **fields, "scope": args.scope, "verdict": args.verdict,
             "rev": code_fingerprint(run_dir, ignore=run_dir)[:16],
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    entry = {k: entry[k] for k in ("id", "reviewer", "author", "scope", "verdict", "summary", "rev", "at")}
    atomic_write(run_dir / REVIEWS_FILE, json.dumps(reviews + [entry], ensure_ascii=False, indent=2) + "\n")
    print(entry["id"])
    return 0


def cmd_fail_ac(args) -> int:
    run_dir = require_dir(args.run_dir)
    if not args.observed.strip():
        raise ArtifactError("fail-ac 需要非空 --observed")
    path = run_dir / ACCEPTANCE_FILE
    text = read_text(path)
    lines = text.splitlines()
    items = parse_acceptance_items(text)
    target = next(((item, idx) for item, idx in items if item.id == args.ac_id), None)
    if target is None:
        raise ArtifactError(f"acceptance.md 中找不到 {args.ac_id}")
    _, line_index = target
    preflight_closed_ac_drift(run_dir, {args.ac_id: False})
    # 验收失败会撤销先前的勾选：勾选代表"已验证通过"，不能与失败记录并存
    lines[line_index] = lines[line_index].replace("- [x]", "- [ ]", 1).replace("- [X]", "- [ ]", 1)
    lines = append_to_level2_section(lines, ("未通过记录",),
                              [f"- {args.ac_id} | {args.observed.strip()}"])
    original = path.read_bytes().decode("utf-8")
    atomic_write(path, "\n".join(lines) + "\n")
    refresh_or_rollback(run_dir, path, original)
    metrics.emit(SKILL, "ac_failed", run=run_dir, ac_id=args.ac_id, has_evidence=False)
    print(f"failed {args.ac_id}: {args.observed.strip()[:60]}")
    return 0


def cmd_resolve_risk(args) -> int:
    run_dir = require_dir(args.run_dir)
    for name in ("decision", "reason", "impact"):
        if not getattr(args, name).strip():
            raise ArtifactError(f"resolve-risk 需要非空 --{name}")
    path = run_dir / ARCH_RISK_FILE
    text = read_text(path)
    lines = text.splitlines()
    risks = parse_risk_table(text)
    risk = next((r for r in risks if r.id == args.risk_id), None)
    if risk is None:
        raise ArtifactError(f"arch-risk.md 扫描表中找不到 {args.risk_id}")
    if risk.state == "未命中":
        raise ArtifactError(f"{args.risk_id} 状态为「未命中」，无需决议")
    if risk.state == "已决议":
        raise ArtifactError(
            f"{args.risk_id} 已决议（决议记录 append-only）。若要推翻，用 "
            "boundary_state.py supersede 走台账变更闸门"
        )
    existing_decisions = {rid for rid, _ in parse_decisions(text)}
    if args.risk_id in existing_decisions:
        raise ArtifactError(f"{args.risk_id} 已有决议段但状态列不是「已决议」，请人工核对后修复")

    # 决议同样触发契约重建：先按当前勾选状态预检已关闭 AC 漂移，再动笔
    preflight_closed_ac_drift(run_dir)
    # 同一次原子写里同时改状态列与追加决议段——两处不可能再漂移
    cells = split_row(lines[risk.row_index])
    cells[5] = "已决议"
    lines[risk.row_index] = build_row(cells)
    block = [
        f"### {args.risk_id} — {risk.boundary}",
        f"- 决议: {args.decision.strip()}",
        f"- 理由: {args.reason.strip()}",
        f"- 影响: {args.impact.strip()}",
    ]
    if args.confirmed_by:
        block.append(f"- 确认方: {args.confirmed_by}")
    lines = append_to_level2_section(lines, ("决议记录",), block)
    original = path.read_bytes().decode("utf-8")
    atomic_write(path, "\n".join(lines) + "\n")
    refresh_or_rollback(run_dir, path, original)
    metrics.emit(SKILL, "risk_resolved", run=run_dir, risk_id=args.risk_id,
                 confirmed_by=args.confirmed_by)
    print(f"resolved {args.risk_id}: 状态列与决议段已同步更新")
    return 0


def cmd_stage_add(args) -> int:
    run_dir = require_dir(args.run_dir)
    stage_dir = Path(args.dir)
    if not stage_dir.is_dir():
        raise ArtifactError(f"阶段目录不存在: {stage_dir}")
    prefix = STAGE_DIR_PREFIX[args.stage]
    dirname = stage_dir.resolve().name
    if not dirname.startswith(prefix):
        raise ArtifactError(
            f"目录名不合规范: {dirname} 应以 `{prefix}` 开头"
            f"（形态 {prefix}<yyyy-mm-dd>-<slug>）"
        )
    _, slug = parse_run_dirname(run_dir)
    if slug not in dirname:
        raise ArtifactError(
            f"目录名 {dirname} 未继承上游 slug `{slug}`——"
            "同一链路各阶段必须共用 slug 才能一眼看出关系"
        )
    if not re.fullmatch(rf"{re.escape(prefix)}\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}",
                        dirname):
        raise ArtifactError(
            f"目录名不合规范: {dirname}（应为 `{prefix}<yyyy-mm-dd>-{slug}`——"
            "日期须为 8 位数字、slug 精确一致，不允许额外后缀）"
        )
    if stage_dir.resolve().parent != run_dir.resolve().parent:
        raise ArtifactError(
            f"阶段目录必须与 run 目录同级（共用 docs/）: {stage_dir} "
            f"应位于 {run_dir.resolve().parent} 下"
        )
    missing = [name for name in STAGE_REQUIRED_FILES[args.stage]
               if not (stage_dir / name).is_file()]
    if missing:
        raise ArtifactError(
            f"{args.stage} 阶段缺少强制文件: {', '.join(missing)}"
            "（见 references/downstream-contract.md）"
        )
    data = refresh_handoff(run_dir)
    stages = [s for s in data.get("stages", []) if s.get("stage") != args.stage]
    stages.append({"stage": args.stage, "dir": args.dir})
    order = {name: i for i, name in enumerate(NEXT_STAGES)}
    data["stages"] = sorted(stages, key=lambda s: order.get(s["stage"], 99))
    dump_handoff(run_dir, data)
    metrics.emit(SKILL, "stage_added", run=run_dir, stage=args.stage,
                 dir=args.dir, naming_ok=True)
    print(f"stage-add {args.stage} -> {args.dir}")
    return 0


# ------------------------------------------------------------------------ cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="req-align-v2 run 内状态写入（唯一入口）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="从 Markdown 派生 handoff.json")
    p_sync.add_argument("run_dir")
    p_sync.set_defaults(func=cmd_sync)

    p_close = sub.add_parser("close-ac", help="勾选一条验收（必须带证据）")
    p_close.add_argument("run_dir")
    p_close.add_argument("ac_id")
    p_close.add_argument("--evidence")
    p_close.add_argument("--step")
    p_close.add_argument("--run-cmd", dest="run_cmd", help="脚本自己执行验证命令并记录退出码与代码版本")
    p_close.add_argument("--cwd", help="命令工作目录（默认 git 顶层，否则 run 目录的上上级）")
    p_close.add_argument("--timeout", type=float, default=600, help="命令超时秒数（默认 600）")
    p_close.add_argument("--manual", action="store_true", help="人工观察证据（需 --observer 与 --evidence）")
    p_close.add_argument("--observer")
    p_close.set_defaults(func=cmd_close_ac)

    p_rev = sub.add_parser("record-review", help="记录绑定代码版本的独立审核")
    p_rev.add_argument("run_dir")
    p_rev.add_argument("--reviewer", required=True)
    p_rev.add_argument("--author", required=True)
    p_rev.add_argument("--scope", required=True, choices=("milestone", "time-backstop", "final"))
    p_rev.add_argument("--verdict", required=True, choices=("approved", "changes-requested"))
    p_rev.add_argument("--summary", required=True)
    p_rev.set_defaults(func=cmd_record_review)

    p_fail = sub.add_parser("fail-ac", help="记录一条验收未通过")
    p_fail.add_argument("run_dir")
    p_fail.add_argument("ac_id")
    p_fail.add_argument("--observed", required=True)
    p_fail.set_defaults(func=cmd_fail_ac)

    p_risk = sub.add_parser("resolve-risk", help="决议一条边界风险（状态列与决议段原子同步）")
    p_risk.add_argument("run_dir")
    p_risk.add_argument("risk_id")
    p_risk.add_argument("--decision", required=True)
    p_risk.add_argument("--reason", required=True)
    p_risk.add_argument("--impact", required=True)
    p_risk.add_argument("--confirmed-by", choices=("human", "agent"), dest="confirmed_by")
    p_risk.set_defaults(func=cmd_resolve_risk)

    p_stage = sub.add_parser("stage-add", help="登记下游阶段目录到 handoff.json")
    p_stage.add_argument("run_dir")
    p_stage.add_argument("--stage", required=True, choices=NEXT_STAGES)
    p_stage.add_argument("--dir", required=True)
    p_stage.set_defaults(func=cmd_stage_add)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

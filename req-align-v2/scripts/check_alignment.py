#!/usr/bin/env python3
"""req-align-v2 对齐产物自检。

用法:
    python3 scripts/check_alignment.py <run_dir> [--history-dir PATH] [--strict-closure]

两种模式:
- 默认：落盘后自检。允许验收全未勾选、风险未决议（那是后续阶段的事）。
- `--strict-closure`：收尾门禁。要求全部 AC 已勾选且带证据、无 `待验证` 遗留风险；
  P0 证据须经脚本验证（close-ac --run-cmd / --manual）且 rev 等于当前代码版本；
  reviews.json 的最新一条须是针对当前代码的 final approved 审核。
  默认模式允许验收未勾选、风险未决议（那是后续阶段的事）；strict 模式堵住"产物格式合法但闭环未完成"的漏洞。

WARN 不影响退出码。退出码: 0 无 FAIL / 1 有 FAIL / 2 参数或路径错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402
from _artifacts import (  # noqa: E402
    ACCEPTANCE_FILE,
    ALIGN_FILE,
    ARCH_RISK_FILE,
    BOUNDARIES_FILE,
    CONTRACT_VERSION,
    HANDOFF_FILE,
    REVIEWS_FILE,
    RISK_CHECKLIST_SIZE,
    RISK_STATES,
    ArtifactError,
    code_fingerprint,
    find_history_dir,
    find_section,
    parse_acceptance_items,
    parse_align_acceptance,
    parse_decisions,
    parse_evidence_records,
    parse_ledger,
    parse_risk_table,
    parse_run_dirname,
    read_text,
    split_sections,
    SUPERSEDED_BANNER_RE,
    has_trigger_shape,
    is_unobservable,
    load_reviews,
    source_sha256,
)

SKILL = "req-align-v2"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"

EVIDENCE_REV_RE = re.compile(r"^\[[^\]]*?\brev=([0-9a-f]{16}|no-git)[\] ]")
# 脚本生成的验证证据的精确头部形状（与 align_state.build_evidence 一致；rev 子模式同 EVIDENCE_REV_RE）
RUN_EVIDENCE_RE = re.compile(r"^\[run exit=0 rev=(?:[0-9a-f]{16}|no-git) out=[0-9a-f]{8}\] \S")
MANUAL_EVIDENCE_RE = re.compile(r"^\[manual observer=\S(?:[^\n]*?\S)? rev=(?:[0-9a-f]{16}|no-git)\] \S")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_FILES = (ALIGN_FILE, ARCH_RISK_FILE, ACCEPTANCE_FILE, HANDOFF_FILE, "cross-run")

# align.md 必备要素：小节名 -> 标题关键词 -> 是否要求正文非空
REQUIRED_SECTIONS = (
    ("目标", ("目标",), True),
    ("优先级", ("优先级",), False),
    ("验收标准", ("验收",), False),
    ("下一阶段", ("下一阶段",), True),
)

# risk-patterns.md §2 的六类边界。实测 6 个真实 run 的覆盖率约 97%，
# 所以这里只给 WARN 提示遗漏，不设 FAIL 门禁——对一条已被遵守的规则加硬拒绝是纯摩擦。
# 同义替换视为覆盖（如某 run 用「可观测性」代替「可验证性」）。
RISK_CATEGORIES = (
    ("数据流边界", ("数据流",)),
    ("时序 / 事件流", ("时序", "事件流")),
    ("跨服务 / 跨模块", ("跨服务", "跨模块")),
    ("持久化与领域模型", ("持久化", "领域模型")),
    ("多 Agent / 外部 API 契约", ("外部 API", "外部API", "API 契约", "多 Agent", "契约")),
    ("可验证性", ("可验证", "可观测")),
)


@dataclass
class Result:
    scope: str
    name: str
    level: str
    detail: str


def ok(scope: str, name: str, detail: str) -> Result:
    return Result(scope, name, PASS, detail)


def bad(scope: str, name: str, detail: str) -> Result:
    return Result(scope, name, FAIL, detail)


def warn(scope: str, name: str, detail: str) -> Result:
    return Result(scope, name, WARN, detail)


# ------------------------------------------------------------------ align.md


def check_align(text: str) -> list:
    results = []
    sections = split_sections(text)
    for name, keywords, needs_body in REQUIRED_SECTIONS:
        section = find_section(sections, *keywords)
        if section is None:
            results.append(bad(ALIGN_FILE, name, f"缺「{name}」小节"))
        elif needs_body and not section.body.strip():
            results.append(bad(ALIGN_FILE, name, f"「{name}」小节为空"))
        else:
            results.append(ok(ALIGN_FILE, name, f"「{name}」小节存在"))

    scope_section = find_section(sections, "范围")
    if scope_section is None:
        results.append(bad(ALIGN_FILE, "范围", "缺「📦 范围」小节"))
    else:
        for label, marker in (("范围-支持", "✅ 支持"), ("范围-暂不支持", "不支持")):
            bullets = bullets_after(scope_section.body, marker)
            if bullets:
                results.append(ok(ALIGN_FILE, label, f"列出 {len(bullets)} 项"))
            else:
                results.append(bad(
                    ALIGN_FILE, label,
                    f"「范围」小节缺「{marker}」条目"
                    + ("（显式边界是第一条工程沉淀，禁止留空）" if marker == "不支持" else ""),
                ))

    try:
        items = parse_align_acceptance(text)
    except ArtifactError as exc:
        results.append(bad(ALIGN_FILE, "验收 ID", str(exc)))
        return results
    if not items:
        results.append(bad(ALIGN_FILE, "验收 ID",
                           "没有解析到 `- AC-N (P?) ...` 形态的验收条目"))
        return results
    ids = [item.id for item in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        results.append(bad(ALIGN_FILE, "验收 ID", f"ID 重复: {', '.join(duplicates)}"))
    else:
        results.append(ok(ALIGN_FILE, "验收 ID", f"{len(ids)} 条 AC 编号唯一"))
    results.extend(check_observable(ALIGN_FILE, [(i.id, i.text) for i in items]))
    return results


def bullets_after(body: str, marker: str) -> list:
    lines = body.splitlines()
    index = next((i for i, line in enumerate(lines) if marker in line), -1)
    if index == -1:
        return []
    bullets = []
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped:
            break
        if stripped.startswith(("-", "*")):
            bullets.append(stripped)
        else:
            break
    return bullets


def check_observable(scope: str, items) -> list:
    for item_id, text in items:
        word = is_unobservable(text)
        if word:
            return [bad(scope, "验收可观察性",
                        f"{item_id} 含不可观察词「{word}」: {text[:50]}… 改写为可断言形式")]
        if not has_trigger_shape(text):
            return [bad(scope, "验收可观察性",
                        f"{item_id} 缺「→ / 当 / 若 / Given / When」触发形态，无法转成断言")]
    return [ok(scope, "验收可观察性", f"{len(items)} 条验收均可观察、可断言")]


# --------------------------------------------------------------- arch-risk.md


def check_arch_risk(text: str) -> list:
    results = []
    try:
        risks = parse_risk_table(text)
    except ArtifactError as exc:
        return [bad(ARCH_RISK_FILE, "边界风险扫描", str(exc))]
    if not risks:
        return [bad(ARCH_RISK_FILE, "边界风险扫描",
                    "扫描表没有数据行：逐项过完清单后至少写出一条结论")]
    if len(risks) < RISK_CHECKLIST_SIZE:
        return [bad(ARCH_RISK_FILE, "边界风险扫描",
                    f"扫描表仅 {len(risks)} 行，少于清单要求的 {RISK_CHECKLIST_SIZE} 行——"
                    "六类边界必须逐项过一遍并各写一行结论")]
    results.append(ok(ARCH_RISK_FILE, "边界风险扫描", f"扫描表列出 {len(risks)} 条边界"))

    ids = [r.id for r in risks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        results.append(bad(ARCH_RISK_FILE, "风险 ID", f"ID 重复: {', '.join(duplicates)}"))
    else:
        malformed = [i for i in ids if not i.startswith("RISK-")]
        if malformed:
            results.append(bad(ARCH_RISK_FILE, "风险 ID",
                               f"ID 形态非法: {', '.join(malformed)}（应为 RISK-<数字>）"))
        else:
            results.append(ok(ARCH_RISK_FILE, "风险 ID", f"{len(ids)} 条 RISK 编号唯一"))

    illegal = [f"{r.id}={r.state}" for r in risks if r.state not in RISK_STATES]
    if illegal:
        results.append(bad(ARCH_RISK_FILE, "风险状态",
                           f"状态非法: {', '.join(illegal)}；只允许 {' / '.join(RISK_STATES)}"))
    else:
        results.append(ok(ARCH_RISK_FILE, "风险状态", "状态列取值合法"))

    # 类别覆盖只提示不阻断（见 RISK_CATEGORIES 注释）
    boundaries_text = " ".join(r.boundary for r in risks)
    missing = [name for name, keys in RISK_CATEGORIES
               if not any(key in boundaries_text for key in keys)]
    if missing:
        results.append(warn(ARCH_RISK_FILE, "清单类别覆盖",
                            f"未见对应行的类别: {', '.join(missing)}"
                            "（同义命名也算覆盖；仅提示，不阻断）"))
    else:
        results.append(ok(ARCH_RISK_FILE, "清单类别覆盖", "六类边界均有对应行"))

    # 状态列与决议段必须一致——手改会导致状态列改了但决议段没追加（或反过来）
    decision_ids = [rid for rid, _ in parse_decisions(text)]
    if find_section(split_sections(text), "决议记录") is None:
        results.append(bad(ARCH_RISK_FILE, "决议记录",
                           "缺「## 📌 决议记录」小节：首次落盘允许无内容，但标题必须占位"))
    else:
        results.append(ok(ARCH_RISK_FILE, "决议记录", "「决议记录」小节存在"))
    unknown = sorted(set(decision_ids) - set(ids))
    resolved_rows = {r.id for r in risks if r.state == "已决议"}
    missing_block = sorted(resolved_rows - set(decision_ids))
    orphan_block = sorted(set(decision_ids) - resolved_rows)
    problems = []
    if unknown:
        problems.append(f"决议段引用了扫描表不存在的 ID: {', '.join(unknown)}")
    if missing_block:
        problems.append(f"状态为「已决议」但无决议段: {', '.join(missing_block)}")
    if orphan_block:
        problems.append(f"有决议段但状态列未改为「已决议」: {', '.join(orphan_block)}")
    if problems:
        results.append(bad(ARCH_RISK_FILE, "状态列与决议段一致",
                           "；".join(problems) + "。用 align_state.py resolve-risk 写入可避免此类漂移"))
    else:
        results.append(ok(ARCH_RISK_FILE, "状态列与决议段一致",
                          f"{len(resolved_rows)} 条已决议，两处记录一致"))
    return results


# -------------------------------------------------------------- acceptance.md


def check_acceptance(text: str, align_text: str) -> list:
    results = []
    items = parse_acceptance_items(text)
    if not items:
        return [bad(ACCEPTANCE_FILE, "勾选清单格式",
                    "没有 `- [ ] AC-N ...` 条目：每条验收应可被人工逐条核对")]
    results.append(ok(ACCEPTANCE_FILE, "勾选清单格式",
                      f"{len(items)} 条 checkbox（{sum(1 for i, _ in items if i.closed)} 已勾选）"))
    try:
        align_map = {item.id: item for item in parse_align_acceptance(align_text)}
    except ArtifactError:
        align_map = {}
    if align_map:
        own_ids = {item.id for item, _ in items}
        missing = sorted(set(align_map) - own_ids)
        extra = sorted(own_ids - set(align_map))
        if missing or extra:
            results.append(bad(
                ACCEPTANCE_FILE, "AC 集合一致",
                (f"缺: {', '.join(missing)}；" if missing else "")
                + (f"多出: {', '.join(extra)}" if extra else ""),
            ))
        else:
            results.append(ok(ACCEPTANCE_FILE, "AC 集合一致", "与 align.md 完全一致"))
        drifted = sorted(
            item.id for item, _ in items
            if item.id in align_map and item.text != align_map[item.id].text
        )
        if drifted:
            results.append(bad(
                ACCEPTANCE_FILE, "AC 文本一致",
                f"勾选条目文本与 align.md 漂移: {', '.join(drifted)}"
                "（勾选清单必须逐字跟随验收标准；改动已关闭条目须先 fail-ac 重开）",
            ))
        else:
            results.append(ok(ACCEPTANCE_FILE, "AC 文本一致", "勾选文本与 align.md 一致"))
    results.extend(check_observable(ACCEPTANCE_FILE, [(i.id, i.text) for i, _ in items]))
    return results


# ------------------------------------------------------------- handoff / cross


def check_handoff(run_dir: Path, align_text: str, risk_text: str, acceptance_text: str) -> list:
    path = run_dir / HANDOFF_FILE
    if not path.is_file():
        return [bad(HANDOFF_FILE, "契约存在",
                    f"缺 {HANDOFF_FILE}：跑 `align_state.py sync {run_dir}` 生成")]
    import json
    try:
        data = json.loads(read_text(path))
    except Exception as exc:  # noqa: BLE001 — JSON 损坏也要报成检查失败
        return [bad(HANDOFF_FILE, "契约存在", f"{HANDOFF_FILE} 解析失败: {exc}")]
    results = [ok(HANDOFF_FILE, "契约存在", f"{HANDOFF_FILE} 已落盘")]

    shape_problem = None
    if not isinstance(data, dict):
        shape_problem = f"顶层必须是对象，实际为 {type(data).__name__}"
    else:
        for key in ("acceptance", "risks"):
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
                shape_problem = f"{key} 必须是对象列表"
                break
    if shape_problem:
        results.append(bad(HANDOFF_FILE, "契约结构",
                           f"{shape_problem}。重跑 `align_state.py sync` 重新生成"))
        return results

    if data.get("contract_version") != CONTRACT_VERSION:
        results.append(bad(HANDOFF_FILE, "契约版本",
                           f"contract_version={data.get('contract_version')}，期望 {CONTRACT_VERSION}"))
    else:
        results.append(ok(HANDOFF_FILE, "契约版本", f"contract_version={CONTRACT_VERSION}"))

    try:
        date, slug = parse_run_dirname(run_dir)
    except ArtifactError as exc:
        results.append(bad(HANDOFF_FILE, "目录命名", str(exc)))
        date, slug = None, None
    if slug is not None:
        if data.get("slug") != slug or data.get("date") != date:
            results.append(bad(HANDOFF_FILE, "目录命名",
                               f"契约 {data.get('date')}-{data.get('slug')} 与目录名 {date}-{slug} 不符"))
        else:
            results.append(ok(HANDOFF_FILE, "目录命名", f"slug={slug} 与目录一致"))

    mismatches = []
    try:
        align_items = [(i.id, i.priority, i.text) for i in parse_align_acceptance(align_text)]
    except ArtifactError:
        align_items = []
    json_items = [(a.get("id"), a.get("priority"), a.get("text"))
                  for a in data.get("acceptance", [])]
    if json_items != align_items:
        mismatches.append("acceptance 与 align.md 不同步（id/优先级/文本）")
    closed_md = {i.id for i, _ in parse_acceptance_items(acceptance_text) if i.closed}
    closed_json = {a.get("id") for a in data.get("acceptance", []) if a.get("closed")}
    if closed_md != closed_json:
        mismatches.append("勾选状态与 acceptance.md 不同步")
    try:
        risk_pairs = [(r.id, r.state) for r in parse_risk_table(risk_text)]
    except ArtifactError:
        risk_pairs = []
    if [(r.get("id"), r.get("state")) for r in data.get("risks", [])] != risk_pairs:
        mismatches.append("risks 与 arch-risk.md 不同步")
    if mismatches:
        results.append(bad(HANDOFF_FILE, "契约与 Markdown 一致",
                           "；".join(mismatches) + "。重跑 `align_state.py sync` 修复"))
    else:
        results.append(ok(HANDOFF_FILE, "契约与 Markdown 一致", "三份 Markdown 与契约同步"))

    # 新鲜度指纹：契约必须派生自三份源文件当前字节——防"改了源文件忘 sync"
    expected_keys = {ALIGN_FILE, ARCH_RISK_FILE, ACCEPTANCE_FILE}
    recorded = data.get("source_sha256")
    if not isinstance(recorded, dict) or set(recorded) != expected_keys:
        results.append(bad(
            HANDOFF_FILE, "source_sha256",
            "handoff.json 缺合法 source_sha256（键须恰好为 "
            "align.md/arch-risk.md/acceptance.md）。重跑 `align_state.py sync` 生成",
        ))
    else:
        try:
            actual = source_sha256(run_dir)
        except ArtifactError as exc:
            results.append(bad(HANDOFF_FILE, "source_sha256", f"无法重算源文件哈希: {exc}"))
        else:
            problems = []
            for name, digest in actual.items():
                stored = recorded[name]
                if not isinstance(stored, str) or not SHA256_HEX_RE.match(stored):
                    problems.append(f"{name} 的记录值不是合法 sha256 hex")
                elif stored != digest:
                    problems.append(f"{name} 在契约生成后有改动")
            if problems:
                results.append(bad(
                    HANDOFF_FILE, "source_sha256",
                    "；".join(problems) + "。重跑 `align_state.py sync` 刷新契约",
                ))
            else:
                results.append(ok(HANDOFF_FILE, "source_sha256",
                                  "三份源文件哈希与契约一致"))

    if not data.get("stages") and data.get("next_stage") in ("sdd", "arch-discovery"):
        results.append(warn(HANDOFF_FILE, "中间层登记",
                            f"next_stage={data.get('next_stage')} 但 stages 为空："
                            "中间层产物落盘后应跑 `align_state.py stage-add` 登记"))
    return results


def check_cross_run(run_dir: Path, risk_text: str, history_dir) -> list:
    """stale 检测：台账里标为已被覆盖、且来源是本 run 的 BND，必须有失效横幅。"""
    if history_dir is None:
        return [warn("cross-run", "跨 run 检查",
                     "未找到 req-align-history/，已降级跳过 stale 检测（用 --history-dir 指定）")]
    ledger = parse_ledger(Path(history_dir) / BOUNDARIES_FILE)
    if not ledger:
        return [ok("cross-run", "跨 run 检查", "台账为空，无 stale 风险")]
    try:
        date, slug = parse_run_dirname(run_dir)
        label = f"{date}-{slug}"
    except ArtifactError:
        label = run_dir.name
    banners = {match.group(1) for match in
               (SUPERSEDED_BANNER_RE.match(line.strip()) for line in risk_text.splitlines())
               if match}
    results = []
    superseded_here = [b for b in ledger
                       if b.lifecycle == "已被覆盖" and b.source_run == label]
    unmarked = [b for b in superseded_here if b.superseded_by not in banners]
    if unmarked:
        results.append(bad("cross-run", "失效标记",
                           "以下决议已被覆盖但本 run 无失效横幅: "
                           + ", ".join(f"{b.id}→{b.superseded_by}" for b in unmarked)
                           + "。用 boundary_state.py supersede 可自动双向标记"))
    else:
        results.append(ok("cross-run", "失效标记",
                          f"{len(superseded_here)} 条被覆盖决议均已标记"))

    ids = {b.id for b in ledger}
    dangling = sorted({b.superseded_by for b in ledger
                       if b.superseded_by not in ("", "—") and b.superseded_by not in ids})
    if dangling:
        results.append(bad("cross-run", "台账双向一致",
                           f"「被谁覆盖」指向不存在的 ID: {', '.join(dangling)}"))
    else:
        results.append(ok("cross-run", "台账双向一致", "台账 supersedes 指向均有效"))
    return results


def check_strict_closure(acceptance_text: str, risk_text: str, run_dir: Path) -> list:
    """收尾门禁：全部 AC 已勾选且带证据、无 `待验证` 遗留。"""
    results = []
    items = parse_acceptance_items(acceptance_text)
    unchecked = [item.id for item, _ in items if not item.closed]
    if unchecked:
        results.append(bad("cross-run", "闭环-验收勾选",
                           f"{len(unchecked)}/{len(items)} 条未勾选: {', '.join(unchecked[:8])}"
                           + ("…" if len(unchecked) > 8 else "")))
    else:
        results.append(ok("cross-run", "闭环-验收勾选", f"全部 {len(items)} 条已勾选"))

    # 证据必须是 `|` 之后的非空内容——仅有一行 `- AC-N` 不算留下证据
    evidence_ids = set(parse_evidence_records(acceptance_text))
    closed_ids = {item.id for item, _ in items if item.closed}
    without_evidence = sorted(closed_ids - evidence_ids)
    if without_evidence:
        results.append(bad("cross-run", "闭环-证据",
                           f"已勾选但无有效证据记录: {', '.join(without_evidence)}"
                           "（需 `- AC-N | step | 非空证据`）"))
    else:
        results.append(ok("cross-run", "闭环-证据", "已勾选条目均有证据"))

    try:
        pending = [r.id for r in parse_risk_table(risk_text) if r.state == "待验证"]
    except ArtifactError:
        pending = []
    if pending:
        results.append(bad("cross-run", "闭环-风险决议",
                           f"仍有待验证风险: {', '.join(pending)}。用 align_state.py resolve-risk 决议"))
    else:
        results.append(ok("cross-run", "闭环-风险决议", "无待验证遗留"))
    results.extend(check_verified_evidence(acceptance_text, run_dir))
    results.extend(check_final_review(run_dir))
    return results


def check_verified_evidence(acceptance_text: str, run_dir: Path) -> list:
    """P0 证据须为脚本验证过的记录（run/manual），且 rev 与当前代码版本一致。

    诚实边界：这只能证明「脚本执行过某命令且当时代码版本如此」，证明不了命令有意义。
    """
    try:
        priority = {i.id: i.priority for i in parse_align_acceptance(read_text(run_dir / ALIGN_FILE))}
    except ArtifactError:
        priority = {}
    closed = {i.id for i, _ in parse_acceptance_items(acceptance_text) if i.closed}
    records = parse_evidence_records(acceptance_text)
    p0 = sorted(i for i in closed if priority.get(i) == "P0" and i in records)
    legacy, unparsable, recorded = [], [], {}
    for ac in p0:
        text = records[ac][0]
        if not text.startswith(("[run exit=0 ", "[manual observer=")):
            legacy.append(ac)
            continue
        match = EVIDENCE_REV_RE.match(text)
        if match and (RUN_EVIDENCE_RE.match(text) or MANUAL_EVIDENCE_RE.match(text)):
            recorded[ac] = match.group(1)
        else:
            unparsable.append(ac)
    results = []
    if legacy:
        results.append(bad("cross-run", "闭环-P0证据已验证",
                           f"{', '.join(legacy)} 证据是自报文本；用 close-ac --run-cmd 让脚本执行验证，"
                           "或 --manual --observer"))
    elif unparsable:
        results.append(bad("cross-run", "闭环-P0证据已验证",
                           f"{', '.join(unparsable)} 的验证证据头部格式不是脚本生成的（缺/错 rev、out 等），"
                           "用 close-ac --run-cmd 或 --manual --observer 重新记录"))
    else:
        results.append(ok("cross-run", "闭环-P0证据已验证", f"{len(p0)} 条 P0 证据均为脚本验证/人工署名记录"))
    if recorded:
        try:
            current = code_fingerprint(run_dir, ignore=run_dir)[:16]
        except ArtifactError as exc:
            results.append(bad("cross-run", "闭环-证据新鲜度", str(exc)))
            return results
        if current == "no-git":
            results.append(warn("cross-run", "闭环-证据新鲜度", "无法确定代码版本（非 git 仓库），已跳过新鲜度比较"))
        else:
            stale = sorted(ac for ac, rev in recorded.items() if rev != current)
            if stale:
                results.append(bad("cross-run", "闭环-证据新鲜度",
                                   f"{', '.join(stale)}: 代码在验证后有改动，重新 close-ac --run-cmd"))
            else:
                results.append(ok("cross-run", "闭环-证据新鲜度", "P0 证据的 rev 与当前代码一致"))
    return results


def check_final_review(run_dir: Path) -> list:
    """reviews.json 的最新一条必须是针对当前代码的 final approved——后来的任何审核都会使其失效。"""
    name, fix = "闭环-final独立审核", "缺少针对当前代码的 final 独立审核；用 record-review"
    try:
        reviews = load_reviews(run_dir)
    except ArtifactError as exc:
        return [bad("cross-run", name, f"{exc}。{fix}")]
    if not reviews:
        return [bad("cross-run", name, f"{REVIEWS_FILE} 缺失或为空。{fix}")]
    last = reviews[-1]
    if not isinstance(last, dict) or last.get("scope") != "final" or last.get("verdict") != "approved":
        return [bad("cross-run", name, f"最新一条审核不是 final approved（{last.get('id') if isinstance(last, dict) else '?'}）。{fix}")]
    try:
        current = code_fingerprint(run_dir, ignore=run_dir)[:16]
    except ArtifactError as exc:
        return [bad("cross-run", name, f"{exc}。{fix}")]
    if current == "no-git":
        return [warn("cross-run", name, "无法确定代码版本（非 git 仓库），已跳过审核 rev 比较")]
    if last.get("rev") != current:
        return [bad("cross-run", name, f"{last.get('id')} 绑定的代码版本已过期。{fix}")]
    return [ok("cross-run", name, f"{last.get('id')} 由 {last.get('reviewer')} 审核通过且绑定当前代码")]


# ----------------------------------------------------------------------- main


def run_checks(run_dir: Path, history_dir, strict: bool) -> list:
    results = []
    texts = {}
    for filename in (ALIGN_FILE, ARCH_RISK_FILE, ACCEPTANCE_FILE):
        path = run_dir / filename
        try:
            texts[filename] = read_text(path)
        except ArtifactError as exc:
            results.append(bad(filename, "文件存在", str(exc)))
            texts[filename] = ""
            continue
        results.append(ok(filename, "文件存在", f"{filename} 已落盘"))

    if texts[ALIGN_FILE]:
        results.extend(check_align(texts[ALIGN_FILE]))
    if texts[ARCH_RISK_FILE]:
        results.extend(check_arch_risk(texts[ARCH_RISK_FILE]))
    if texts[ACCEPTANCE_FILE]:
        results.extend(check_acceptance(texts[ACCEPTANCE_FILE], texts[ALIGN_FILE]))
    results.extend(check_handoff(run_dir, texts[ALIGN_FILE], texts[ARCH_RISK_FILE],
                                 texts[ACCEPTANCE_FILE]))
    results.extend(check_cross_run(run_dir, texts[ARCH_RISK_FILE], history_dir))
    if strict:
        results.extend(check_strict_closure(texts[ACCEPTANCE_FILE], texts[ARCH_RISK_FILE], run_dir))
    return results


def render(results: list) -> str:
    lines = []
    for scope in REQUIRED_FILES:
        scoped = [r for r in results if r.scope == scope]
        if not scoped:
            continue
        lines.append(f"── {scope} ──")
        lines.extend(f"[{r.level}] {r.name}: {r.detail}" for r in scoped)
    passed = sum(1 for r in results if r.level == PASS)
    failed = sum(1 for r in results if r.level == FAIL)
    warned = sum(1 for r in results if r.level == WARN)
    lines.append(f"\n检查结果: {passed} PASS / {failed} FAIL / {warned} WARN")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验 req-align-v2 对齐产物目录")
    parser.add_argument("run_dir", help="如 docs/req-align-2026-09-02-global-service-catalog/")
    parser.add_argument("--history-dir", dest="history_dir",
                        help="req-align-history/ 路径；缺省自动发现同级目录")
    parser.add_argument("--strict-closure", action="store_true", dest="strict",
                        help="收尾门禁：要求验收全勾选带证据、无待验证风险")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    if run_dir.suffix == ".md" or run_dir.is_file():
        print("[ERROR] 请传产物目录而非单个 Markdown 文件", file=sys.stderr)
        return 2
    if not run_dir.is_dir():
        print(f"[ERROR] 目录不存在: {run_dir}", file=sys.stderr)
        return 2

    history_dir = find_history_dir(run_dir, args.history_dir)
    results = run_checks(run_dir, history_dir, args.strict)
    print(render(results))
    failures = [r.name for r in results if r.level == FAIL]
    metrics.emit(SKILL, "align_check", run=run_dir, strict=args.strict,
                 passed=not failures, fail_names=failures,
                 stale_count=sum(1 for r in results
                                 if r.level == FAIL and r.name == "失效标记"),
                 degraded=history_dir is None)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

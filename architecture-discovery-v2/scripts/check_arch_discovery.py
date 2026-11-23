#!/usr/bin/env python3
"""architecture-discovery-v2 产物自检（只读）。

用法: python3 scripts/check_arch_discovery.py <discovery_dir> --run-dir <req-align run_dir>
先验证 handoff 新鲜度（source_sha256）；只证明：每个非「未命中」风险有带类型证据的决议段，且已经 resolve-risk 回写；
不证明证据内容为真或充分——需要独立审核。WARN 不影响退出码。
退出码: 0 无 FAIL / 1 有 FAIL / 2 参数或 handoff 错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED = ("architecture.md", "flows-and-boundaries.md", "decisions.md")
STATES = ("未命中", "待验证", "已决议")
EVIDENCE_TYPES = ("code", "script", "doc", "user")
FIELDS = ("结论", "证据类型", "证据", "影响")
PLACEHOLDERS = {"tbd", "todo", "待定", "略", "…", "...", "-", "—", "n/a"}
SECTION_RE = re.compile(r"^##\s+(RISK-\d+)\b\s*(.*)$")
FIELD_RE = re.compile(r"^[-*+]\s+([^:：]+?)\s*[:：]\s*(.*)$")
DEEP_RISK_RE = re.compile(r"^#{3,6}\s+RISK-\d+\b")
FENCE_RE = re.compile(r"^(```|~~~)")
RUN_DIRNAME_RE = re.compile(r"^req-align-(\d{4}-\d{2}-\d{2})-(.+)$")
SOURCE_FILES = ("align.md", "arch-risk.md", "acceptance.md")  # 与 req-align-v2 source_sha256 约定一致，镜像计算
# (文件, 标题关键词任一, 告警文案)：只 WARN，不影响退出码
HEADING_HINTS = (
    ("architecture.md", ("分层", "依赖"), "「分层」或「依赖」"),
    ("architecture.md", ("选型",), "「选型」"),
    ("flows-and-boundaries.md", ("数据流", "时序", "边界"), "「数据流」「时序」或「边界」"),
)
MIN_DOC_CHARS = 200


class Report:
    def __init__(self) -> None:
        self.fails = 0

    def ok(self, msg): print(f"[PASS] {msg}")
    def warn(self, msg): print(f"[WARN] {msg}")

    def fail(self, msg):
        self.fails += 1
        print(f"[FAIL] {msg}")


def outside_fences(text: str) -> list:
    """去掉围栏代码块（``` 与 ~~~，按围栏字符对称开合）后的行列表。"""
    out, fence = [], None
    for raw in text.splitlines():
        m = FENCE_RE.match(raw.strip())
        if m:
            if fence is None:
                fence = m.group(1)
            elif fence == m.group(1):
                fence = None
            continue
        if fence is None:
            out.append(raw)
    return out


def clean_label(label: str, value: str) -> tuple:
    """容忍强调标记：`**结论**` / `_证据_` / `**影响:**` 与 `结论` 等价。"""
    opened = label.count("**") % 2 == 1
    label = label.strip().strip("*_` ").strip()
    if opened and value.startswith("**"):
        value = value[2:].strip()
    return label, value


def usage_error(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def load_handoff(run_dir: Path) -> dict:
    path = run_dir / "handoff.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("slug"), str) or not data["slug"]:
        raise ValueError(f"{path} 必须是带 slug 的对象")
    risks = data.get("risks")
    if not isinstance(risks, list):
        raise ValueError(f"{path} 缺 risks 列表")
    for r in risks:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or r.get("state") not in STATES:
            raise ValueError(f"{path} 的 risks 项须含 id 与合法 state（{'/'.join(STATES)}）: {r!r}")
    return data


def parse_sections(text: str) -> list:
    """decisions.md → [(risk_id, {字段: 值})]；代码块内不解析；### RISK-N 终止当前段。"""
    sections, current = [], None
    for raw in outside_fences(text):
        line = raw.strip()
        match = SECTION_RE.match(line)
        if match:
            current = (match.group(1), {})
            sections.append(current)
        elif line.startswith("## ") or DEEP_RISK_RE.match(line):
            current = None
        elif current is not None:
            field = FIELD_RE.match(line)
            if field:
                label, value = clean_label(field.group(1), field.group(2).strip())
                current[1].setdefault(label, value)
    return sections


def deep_risk_headings(text: str) -> list:
    return [m.group(0).split()[1] for m in map(DEEP_RISK_RE.match, (l.strip() for l in outside_fences(text))) if m]


def is_placeholder(value: str) -> bool:
    return not value.strip() or value.strip().lower() in PLACEHOLDERS


def run_slug(run_dir: Path) -> str:
    """与 align_state.parse_run_dirname 同口径：slug 取自 run 目录名。"""
    m = RUN_DIRNAME_RE.match(run_dir.resolve().name)
    if not m:
        raise ValueError(f"run 目录名不合规范: {run_dir.resolve().name}（应为 req-align-<yyyy-mm-dd>-<slug>）")
    return m.group(2)


def check_freshness(run_dir: Path, recorded, rep: Report) -> None:
    """handoff.json 必须是三份源 Markdown 当前字节的派生，否则契约已陈旧。"""
    hint = f"先运行 `python3 <req-align-v2>/scripts/align_state.py sync {run_dir}`"
    if not isinstance(recorded, dict) or set(recorded) != set(SOURCE_FILES):
        rep.fail(f"handoff.json 缺少合法的 source_sha256（键须恰为 {', '.join(SOURCE_FILES)}）: {hint}")
        return
    before = rep.fails
    for name in SOURCE_FILES:
        stored, path = recorded[name], run_dir / name
        if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
            rep.fail(f"source_sha256[{name}] 不是 64 位小写十六进制: {hint}")
        elif not path.is_file():
            rep.fail(f"上游源文件缺失: {path}: {hint}")
        else:
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                rep.fail(f"无法读取 {path}: {exc}")
                continue
            if actual != stored:
                rep.fail(f"{name} 在 handoff.json 生成后被改动（source_sha256 不一致）: {hint}")
    if rep.fails == before:
        rep.ok("handoff.json 与三份源文件一致（新鲜）")


def check_name(disc: Path, run_dir: Path, slug: str, rep: Report, handoff_slug: str = None) -> None:
    if handoff_slug is not None and handoff_slug != slug:
        rep.fail(f"handoff.json slug differs from run dir name (handoff `{handoff_slug}` vs dir `{slug}`); "
                 f"sync: 先运行 `python3 <req-align-v2>/scripts/align_state.py sync {run_dir}`")
    name = disc.resolve().name
    pattern = rf"architecture-discovery-\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}"
    if re.fullmatch(pattern, name):
        rep.ok(f"目录名合规: {name}")
    else:
        rep.fail(f"目录名 {name} 不合规：应为 architecture-discovery-<yyyy-mm-dd>-{slug}（slug 精确一致，不允许额外后缀）")
    if disc.resolve().parent == run_dir.resolve().parent:
        rep.ok("与 run 目录同级")
    else:
        rep.fail(f"阶段目录必须与 run 目录同级（共用 docs/）: 应位于 {run_dir.resolve().parent} 下")


def check_files(disc: Path, run_ids: list, rep: Report) -> None:
    for name in REQUIRED:
        path = disc / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            rep.fail(f"{name} 缺失或为空")
    for name in REQUIRED[:2]:
        path = disc / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        heads = [l for l in outside_fences(text) if re.match(r"^##\s+\S", l)]
        if not heads:
            rep.fail(f"{name} 至少需要一个二级标题（## ...）")
        for fname, kws, label in HEADING_HINTS:
            if fname == name and not any(kw in h for h in heads for kw in kws):
                rep.warn(f"{name} 建议含标题包含{label}")
        if len(text.strip()) < MIN_DOC_CHARS:
            rep.warn(f"{name} 不足 {MIN_DOC_CHARS} 字，疑似占位")
    flows = disc / "flows-and-boundaries.md"
    if flows.is_file():
        text = flows.read_text(encoding="utf-8")
        for rid in run_ids:
            if rid not in text:
                rep.warn(f"flows-and-boundaries.md 未提及 {rid}（边界归属应覆盖每个待决风险）")


def check_sections(disc: Path, risks: list, rep: Report) -> None:
    path = disc / "decisions.md"
    if not path.is_file():
        return
    raw = path.read_text(encoding="utf-8")
    for rid in deep_risk_headings(raw):
        rep.fail(f"{rid} 的标题层级不对: RISK sections must use level-2 headings（`## {rid} ...`）")
    sections = parse_sections(raw)
    state = {r["id"]: r["state"] for r in risks}
    seen = set()
    for rid, fields in sections:
        if rid in seen:
            rep.fail(f"{rid} 决议段重复")
            continue
        seen.add(rid)
        if rid not in state:
            rep.fail(f"{rid} 不在 handoff.json 中（不得自造风险编号）")
            continue
        if state[rid] == "未命中":
            rep.fail(f"{rid} 在 handoff 中为「未命中」，无需决议段——删除该段")
            continue
        check_one(rid, fields, state[rid], rep)
    missing = [r["id"] for r in risks if r["state"] != "未命中" and r["id"] not in seen]
    if missing:
        rep.fail(f"decisions.md 缺少决议段: {', '.join(missing)}")


def check_one(rid: str, fields: dict, handoff_state: str, rep: Report) -> None:
    before = rep.fails
    for key in FIELDS:
        if key not in fields:
            rep.fail(f"{rid} 缺字段「{key}」")
        elif is_placeholder(fields[key]):
            rep.fail(f"{rid} 字段「{key}」为空或占位")
    etype = fields.get("证据类型", "").strip()
    if "证据类型" in fields and etype not in EVIDENCE_TYPES:
        rep.fail(f"{rid} 证据类型 `{etype}` 非法，须为 {'/'.join(EVIDENCE_TYPES)}")
    evidence = fields.get("证据", "")
    if evidence and not is_placeholder(evidence):
        if etype == "code" and not re.search(r"\S+:\d+", evidence):
            rep.warn(f"{rid} code 证据应形如 path:行号 或 path:起-止，当前: {evidence[:60]}")
        elif etype == "doc" and not re.search(r"https?://", evidence):
            rep.warn(f"{rid} doc 证据应含 http(s):// 链接")
        elif etype == "script" and len(evidence.strip()) < 10:
            rep.warn(f"{rid} script 证据应同时写命令与真实结果（太短）")
    claimed = fields.get("已回写", "").strip().lower() == "yes"
    if handoff_state == "已决议":
        rep.ok(f"{rid} 已在 handoff 决议") if rep.fails == before else None
    elif claimed:
        rep.fail(f"{rid} 声称「已回写: yes」但 handoff 仍为{handoff_state}——声明与事实不一致")
    else:
        rep.fail(f"{rid} 尚未回写上游，运行: python3 <req-align-v2>/scripts/align_state.py "
                 f"resolve-risk <run_dir> {rid} --decision ... --reason ... --impact ... --confirmed-by human|agent")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="架构发现产物自检（只读）")
    parser.add_argument("dir")
    parser.add_argument("--run-dir", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    disc, run_dir = Path(args.dir), Path(args.run_dir)
    if not disc.is_dir():
        return usage_error(f"目录不存在: {disc}")
    if not run_dir.is_dir():
        return usage_error(f"run 目录不存在: {run_dir}")
    try:
        data = load_handoff(run_dir)
    except ValueError as exc:
        return usage_error(str(exc))
    try:
        slug = run_slug(run_dir)
    except ValueError as exc:
        return usage_error(str(exc))
    rep = Report()
    check_freshness(run_dir, data.get("source_sha256"), rep)
    check_name(disc, run_dir, slug, rep, data["slug"])
    pending_ids = [r["id"] for r in data["risks"] if r["state"] != "未命中"]
    try:
        check_files(disc, pending_ids, rep)
        check_sections(disc, data["risks"], rep)
    except (UnicodeDecodeError, OSError) as exc:
        rep.fail(f"无法读取产物（须为 UTF-8 文本）: {exc}")
    if rep.fails:
        print("result: FAIL")
        return 1
    print("result: PASS")
    print(f"下一步: python3 <req-align-v2>/scripts/align_state.py stage-add {run_dir} "
          f"--stage arch-discovery --dir {disc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

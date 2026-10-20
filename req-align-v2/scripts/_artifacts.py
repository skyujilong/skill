#!/usr/bin/env python3
"""req-align-v2 产物的共享解析与原子写工具。

为什么单独一个模块：`align_state.py` / `boundary_state.py` / `check_alignment.py`
都要解析同一批 Markdown 表格与 ID。若各自抄一份正则，就会重演本 skill 正要修复的
「同一事实两处记录 → 漂移」失败模式。解析规则在此唯一定义。

约定：
- Markdown 是人类可读事实来源；`handoff.json` 由脚本从 Markdown 派生。
- 所有写入走 `atomic_write`（tempfile + os.replace），避免中断留下半截文件。
- 仅用标准库，兼容 Python 3.9。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ALIGN_FILE = "align.md"
ARCH_RISK_FILE = "arch-risk.md"
ACCEPTANCE_FILE = "acceptance.md"
HANDOFF_FILE = "handoff.json"
REVIEWS_FILE = "reviews.json"

HISTORY_DIRNAME = "req-align-history"
INDEX_FILE = "index.md"
BOUNDARIES_FILE = "boundaries.md"
PITFALLS_FILE = "pitfalls.md"

CONTRACT_VERSION = "1"

RISK_STATES = ("未命中", "待验证", "已决议")
BOUNDARY_LIFECYCLES = ("生效", "已被覆盖")
NEXT_STAGES = ("sdd", "arch-discovery", "exec-plan")
PRIORITIES = ("P0", "P1", "P2")

# risk-patterns.md §2 的边界清单共 6 项：扫描表数据行数不得少于它
RISK_CHECKLIST_SIZE = 6

UNOBSERVABLE_WORDS = (
    "要好", "稳定", "正常", "流畅", "自然",
    "合理", "高效", "完善", "可靠", "好看", "好用",
)

AC_LINE_RE = re.compile(r"^-\s+(AC-\d+)\s*\((P[012])\)\s*(.+?)\s*$")
AC_CHECKBOX_RE = re.compile(r"^-\s+\[([ xX])\]\s+(AC-\d+)\s+(.+?)\s*$")
DECISION_HEADING_RE = re.compile(r"^###\s+(RISK-\d+)\s*(?:—|-|–)?\s*(.*)$")
TABLE_SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")
SUPERSEDED_BANNER_RE = re.compile(r"^>\s*⚠️\s*已被\s+(BND-\d+)")
RUN_DIRNAME_RE = re.compile(r"^req-align-(\d{4}-\d{2}-\d{2})-(.+)$")

STAGE_REQUIRED_FILES = {
    "sdd": ("README.md", "01-overview.md", "acceptance-matrix.md"),
    "arch-discovery": ("architecture.md", "flows-and-boundaries.md", "decisions.md"),
    "exec-plan": ("step.json", "original-plan.md"),
}
STAGE_DIR_PREFIX = {
    "sdd": "sdd-",
    "arch-discovery": "architecture-discovery-",
    "exec-plan": "exec-plan-",
}


class ArtifactError(Exception):
    """产物格式或参数错误；由各脚本 main 捕获后以非零退出码报告。"""


@dataclass
class Acceptance:
    id: str
    priority: str
    text: str
    closed: bool = False
    evidence: Optional[str] = None
    step: Optional[str] = None


@dataclass
class Risk:
    id: str
    boundary: str
    risk: str
    boundary_ref: str
    phase: str
    state: str
    row_index: int = -1


@dataclass
class Boundary:
    id: str
    module: str
    statement: str
    lifecycle: str
    source_run: str
    superseded_by: str
    row_index: int = -1


@dataclass
class Pitfall:
    id: str
    boundary: str
    phenomenon: str
    root_cause: str
    guard: str
    count: int
    row_index: int = -1


@dataclass
class Section:
    heading: str
    body: str
    start: int
    end: int


@dataclass
class Table:
    """一张 Markdown 表格：header 行号、分隔行号与数据行号列表。"""

    header_index: int
    separator_index: int
    row_indices: list = field(default_factory=list)
    headers: list = field(default_factory=list)


# --------------------------------------------------------------------------- io


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactError(f"无法读取 {path}: {exc}") from exc


def atomic_write(path: Path, text: str) -> None:
    """原子写：先写同目录临时文件并 fsync，再 os.replace 覆盖。"""
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
        raise ArtifactError(f"无法写入 {path}: {exc}") from exc


def load_handoff(run_dir: Path) -> dict:
    path = run_dir / HANDOFF_FILE
    if not path.is_file():
        raise ArtifactError(
            f"缺少 {HANDOFF_FILE}: 先跑 `align_state.py sync {run_dir}` 生成机器契约"
        )
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{path} 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactError(f"{path} 顶层必须是对象")
    return data


def dump_handoff(run_dir: Path, data: dict) -> None:
    atomic_write(run_dir / HANDOFF_FILE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# ------------------------------------------------------- 代码版本与审核记录


def _git(start: Path, *args) -> Optional[bytes]:
    """在 start 下跑 git；git 缺失或失败返回 None。"""
    try:
        done = subprocess.run(["git", "-C", str(start), *args], capture_output=True)
    except (OSError, ValueError):
        return None
    return done.stdout if done.returncode == 0 else None


def git_toplevel(start: Path) -> Optional[Path]:
    out = _git(start, "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8", "replace").strip()) if out and out.strip() else None


def code_fingerprint(start: Path, ignore: Optional[Path] = None) -> str:
    """代码版本指纹：HEAD + 所有已改/暂存/未跟踪（未忽略）文件的路径与内容哈希。

    排除顶层 docs/ 与 ignore 目录（req-align run 目录）：close-ac/record-review 自身会写
    其中的文件，否则验证完立刻过期。
    非 git 仓库返回常量 "no-git"（调用方据此降级为 WARN）。记录里用前 16 位。
    git status 失败时抛 ArtifactError，不退化为只看 HEAD。
    """
    top = git_toplevel(start)
    if top is None:
        return "no-git"
    head = _git(top, "rev-parse", "--verify", "-q", "HEAD")
    digest = hashlib.sha256((head.decode().strip() if head and head.strip() else "no-commits").encode())
    status = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status is None:
        raise ArtifactError(f"无法计算代码版本：{top} 下 `git status` 执行失败")
    ignore_rel = None
    if ignore is not None:
        try:
            ignore_rel = ignore.resolve().relative_to(top.resolve()).as_posix()
        except ValueError:
            ignore_rel = None
    paths, entries = set(), status.split(b"\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:].decode("utf-8", "surrogateescape"))
        if entry[:1] in b"RC":  # 重命名/复制：下一段是原路径
            if index < len(entries) and entries[index]:
                paths.add(entries[index].decode("utf-8", "surrogateescape"))
            index += 1
    for rel in sorted(paths):
        if rel.split("/", 1)[0] == "docs":
            continue
        if ignore_rel and ignore_rel != "." and (rel == ignore_rel or rel.startswith(ignore_rel + "/")):
            continue
        try:
            content = hashlib.sha256((top / rel).read_bytes()).hexdigest() if (top / rel).is_file() else "deleted"
        except OSError:
            content = "deleted"
        digest.update(f"\n{rel}\0{content}".encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def load_reviews(run_dir: Path) -> list:
    """读 reviews.json：缺失视为空列表；损坏或非数组必须 fail closed，绝不当空。"""
    path = run_dir / REVIEWS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{path} 不是合法 JSON: {exc}。请人工修复后重试") from exc
    if not isinstance(data, list):
        raise ArtifactError(f"{path} 顶层必须是数组，实际为 {type(data).__name__}")
    return data


def find_history_dir(run_dir: Path, explicit: Optional[str] = None) -> Optional[Path]:
    """定位跨 run 沉淀目录：显式参数优先，否则找 run 目录的同级 req-align-history/。"""
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_dir() else None
    candidate = run_dir.resolve().parent / HISTORY_DIRNAME
    return candidate if candidate.is_dir() else None


def parse_run_dirname(run_dir: Path) -> tuple:
    """从目录名解出 (date, slug)；不合规范则抛错。"""
    match = RUN_DIRNAME_RE.match(run_dir.resolve().name)
    if not match:
        raise ArtifactError(
            f"目录名不合规范: {run_dir.name}（应为 req-align-<yyyy-mm-dd>-<slug>）"
        )
    return match.group(1), match.group(2)


# ------------------------------------------------------------------- markdown


def split_sections(text: str) -> list:
    """按 2/3 级标题切分，保留行号区间以便就地改写。"""
    lines = text.splitlines()
    sections: list = []
    current_heading = ""
    current_start = 0
    for index, raw in enumerate(lines):
        if re.match(r"^#{2,3}\s+\S", raw.strip()):
            if current_heading:
                sections.append(Section(current_heading, "\n".join(lines[current_start:index]),
                                        current_start, index))
            current_heading = raw.strip().lstrip("#").strip()
            current_start = index + 1
    if current_heading:
        sections.append(Section(current_heading, "\n".join(lines[current_start:]),
                                current_start, len(lines)))
    return sections


def find_section(sections: list, *keywords: str) -> Optional[Section]:
    for section in sections:
        if any(keyword in section.heading for keyword in keywords):
            return section
    return None


def level2_span(lines, *keywords) -> Optional[tuple]:
    """定位二级标题小节的 (正文起始行, 结束行)，结束于下一个二级标题。

    不能用 `split_sections` 代替：它把三级标题也当分节点，于是「决议记录」小节的
    end 会落在第一个 `### RISK-N` 上，把决议段本身排除在外（曾导致决议段永远扫不到）。
    """
    start = None
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped.startswith("## "):
            continue
        if start is None:
            if any(keyword in stripped for keyword in keywords):
                start = index + 1
        else:
            return (start, index)
    return (start, len(lines)) if start is not None else None


def append_to_level2_section(lines, keywords, new_lines) -> list:
    """在二级标题小节末尾追加内容（跳过尾部空行），保持 append-only 顺序。"""
    span = level2_span(lines, *keywords)
    if span is None:
        raise ArtifactError(f"缺少「{keywords[0]}」小节，无法追加")
    start, end = span
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[:end] + [""] + list(new_lines) + lines[end:]


def split_row(line: str) -> list:
    """把 `| a | b |` 拆成 ['a', 'b']。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def build_row(cells) -> str:
    return "| " + " | ".join(cells) + " |"


def find_table(lines, start: int = 0, end: Optional[int] = None) -> Optional[Table]:
    """在行区间内定位第一张表格（表头 + 分隔行 + 连续数据行）。"""
    limit = len(lines) if end is None else end
    index = start
    while index < limit - 1:
        line = lines[index].strip()
        nxt = lines[index + 1].strip()
        if line.startswith("|") and TABLE_SEPARATOR_RE.match(nxt):
            table = Table(header_index=index, separator_index=index + 1,
                          headers=split_row(lines[index]))
            cursor = index + 2
            while cursor < limit and lines[cursor].strip().startswith("|"):
                if not TABLE_SEPARATOR_RE.match(lines[cursor].strip()):
                    table.row_indices.append(cursor)
                cursor += 1
            return table
        index += 1
    return None


def strip_code_fences(body: str):
    """产出代码块外的行，避免把模板示例当成真实数据。"""
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield stripped


# ------------------------------------------------------------------ 产物解析


def parse_align_acceptance(text: str) -> list:
    """解析 align.md 的「✅ 验收标准」小节，返回 Acceptance 列表。"""
    sections = split_sections(text)
    section = find_section(sections, "验收")
    if section is None:
        raise ArtifactError("align.md 缺「✅ 验收标准」小节")
    items: list = []
    for line in strip_code_fences(section.body):
        match = AC_LINE_RE.match(line)
        if match:
            items.append(Acceptance(id=match.group(1), priority=match.group(2),
                                    text=match.group(3)))
    return items


def parse_acceptance_items(text: str) -> list:
    """解析 acceptance.md 的 checkbox 条目，返回 (Acceptance, 行号)。"""
    results: list = []
    in_fence = False
    for index, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = AC_CHECKBOX_RE.match(stripped)
        if match:
            results.append((
                Acceptance(id=match.group(2), priority="", text=match.group(3),
                           closed=match.group(1).lower() == "x"),
                index,
            ))
    return results


def parse_risk_table(text: str) -> list:
    """解析 arch-risk.md 的扫描表；列顺序固定见 templates.md §1b。"""
    lines = text.splitlines()
    sections = split_sections(text)
    section = find_section(sections, "边界风险扫描")
    if section is None:
        raise ArtifactError("arch-risk.md 缺「## 🧱 边界风险扫描」小节")
    table = find_table(lines, section.start, section.end)
    if table is None:
        return []
    risks: list = []
    for row_index in table.row_indices:
        cells = split_row(lines[row_index])
        if len(cells) < 6:
            raise ArtifactError(
                f"arch-risk.md 第 {row_index + 1} 行列数不足 6："
                "应为 ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态"
            )
        risks.append(Risk(id=cells[0], boundary=cells[1], risk=cells[2],
                          boundary_ref=cells[3], phase=cells[4], state=cells[5],
                          row_index=row_index))
    return risks


def parse_evidence_records(text: str) -> dict:
    """从「## 证据」小节解析 AC-N | step | evidence（兼容 AC-N | evidence 两段式）。

    返回 {ac_id: (evidence, step_or_None)}。仅当 `|` 之后的证据内容非空才计入——
    光有一行 `- AC-N` 或末尾空段不算留下证据。
    """
    section = find_section(split_sections(text), "证据")
    if section is None:
        return {}
    result = {}
    for line in section.body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- AC-"):
            continue
        # maxsplit=2：证据段本身可能含 `|`（如 `pytest ... | tee log`），
        # 第二个分隔符之后的内容必须整体保留，不能按第 3 段截断
        parts = [p.strip() for p in stripped[2:].split("|", 2)]
        if len(parts) >= 3:
            evidence, step = parts[2], (parts[1] if parts[1] != "-" else None)
        elif len(parts) == 2:
            evidence, step = parts[1], None
        else:
            continue
        if not evidence:
            continue
        result[parts[0]] = (evidence, step)
    return result


def parse_decisions(text: str) -> list:
    """返回决议记录小节里出现的 (risk_id, 行号)。"""
    lines = text.splitlines()
    span = level2_span(lines, "决议记录")
    if span is None:
        return []
    results: list = []
    for index in range(span[0], min(span[1], len(lines))):
        match = DECISION_HEADING_RE.match(lines[index].strip())
        if match:
            results.append((match.group(1), index))
    return results


def parse_ledger(path: Path) -> list:
    """解析 boundaries.md 台账。"""
    if not path.is_file():
        return []
    lines = read_text(path).splitlines()
    table = find_table(lines)
    if table is None:
        return []
    boundaries: list = []
    for row_index in table.row_indices:
        cells = split_row(lines[row_index])
        if len(cells) < 6:
            continue
        boundaries.append(Boundary(id=cells[0], module=cells[1], statement=cells[2],
                                   lifecycle=cells[3], source_run=cells[4],
                                   superseded_by=cells[5], row_index=row_index))
    return boundaries


def parse_pitfalls(path: Path) -> list:
    if not path.is_file():
        return []
    lines = read_text(path).splitlines()
    table = find_table(lines)
    if table is None:
        return []
    pitfalls: list = []
    for row_index in table.row_indices:
        cells = split_row(lines[row_index])
        if len(cells) < 6:
            continue
        try:
            count = int(cells[5])
        except ValueError:
            count = 1
        pitfalls.append(Pitfall(id=cells[0], boundary=cells[1], phenomenon=cells[2],
                                root_cause=cells[3], guard=cells[4], count=count,
                                row_index=row_index))
    return pitfalls


def next_id(existing, prefix: str) -> str:
    """在已有 ID 集合上分配下一个编号，从 1 起。"""
    numbers = []
    for item in existing:
        match = re.match(rf"^{prefix}-(\d+)$", item)
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}-{(max(numbers) + 1) if numbers else 1}"


def is_unobservable(text: str) -> Optional[str]:
    for word in UNOBSERVABLE_WORDS:
        if word in text:
            return word
    return None


def has_trigger_shape(text: str) -> bool:
    return ("→" in text or "->" in text or text.startswith("当") or text.startswith("若")
            or "Given" in text or "When" in text)


def source_sha256(run_dir: Path) -> dict:
    """三份源 Markdown 原始字节的 sha256——handoff.json 的新鲜度指纹。

    键固定为文件名本身；不含任何可变时间戳，同一批字节必得同一批哈希。
    """
    digests = {}
    for name in (ALIGN_FILE, ARCH_RISK_FILE, ACCEPTANCE_FILE):
        path = run_dir / name
        try:
            digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ArtifactError(f"无法读取 {path}: {exc}") from exc
    return digests


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_dir(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_dir():
        raise ArtifactError(f"目录不存在: {path}")
    return path

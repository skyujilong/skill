#!/usr/bin/env python3
"""req-align 对齐产物自检：校验 per-run 目录下三份文档的必填项与可观察性。

用法:
    python3 scripts/check_alignment.py <对齐产物目录>

退出码:
    0 = 全部通过
    1 = 存在对齐缺陷（缺文件 / 缺要素 / 验收不可观察 / 格式不符）
    2 = 参数或路径错误（目录不存在、传入的是单个 Markdown 文件）
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

ALIGN_FILE = "align.md"
ARCH_RISK_FILE = "arch-risk.md"
ACCEPTANCE_FILE = "acceptance.md"

# 产物目录里必须齐全的三份文档，顺序同时决定报告的分组顺序
REQUIRED_FILES: tuple[str, ...] = (ALIGN_FILE, ARCH_RISK_FILE, ACCEPTANCE_FILE)

# 验收条目里出现即视为"不可观察"的高频措辞，须改写为可断言形式
UNOBSERVABLE_WORDS: tuple[str, ...] = (
    "要好",
    "稳定",
    "正常",
    "流畅",
    "自然",
    "合理",
    "高效",
    "完善",
    "可靠",
    "好看",
    "好用",
)

# align.md 必备要素：小节名 -> 标题关键词 -> 是否要求正文非空
# 架构边界风险已迁出到 arch-risk.md，故不在此列
REQUIRED_SECTIONS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("目标", ("目标",), False),
    ("优先级", ("优先级",), False),
    ("验收标准", ("验收",), False),
    ("下一阶段", ("下一阶段",), True),
)

TABLE_SEPARATOR_PATTERN = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")
BULLET_PATTERN = re.compile(r"^(?:[-*]|\d+\.)\s+")
CHECKBOX_PATTERN = re.compile(r"^-\s\[[ xX]\]\s+")


@dataclass(frozen=True)
class Section:
    """Markdown 的一节：2/3 级标题与其下的正文。"""

    heading: str
    body: str


@dataclass(frozen=True)
class CheckResult:
    """单条检查结论，scope 记录归属文件以便分文件报告。"""

    scope: str
    name: str
    passed: bool
    detail: str


def extract_sections(text: str) -> list[Section]:
    """按 2/3 级标题把 Markdown 切成若干节，标题行不属于任何一节正文。"""
    sections: list[Section] = []
    current_heading = ""
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        heading_match = re.match(r"^#{2,3}\s+(.+)$", raw_line.strip())
        if heading_match:
            if current_heading:
                sections.append(Section(current_heading, "\n".join(current_lines)))
            current_heading = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(raw_line)
    if current_heading:
        sections.append(Section(current_heading, "\n".join(current_lines)))
    return sections


def find_section(sections: list[Section], keywords: tuple[str, ...]) -> Section | None:
    """按标题关键词定位小节，找不到返回 None。"""
    for section in sections:
        if any(keyword in section.heading for keyword in keywords):
            return section
    return None


def content_lines(body: str) -> Iterator[str]:
    """逐行产出代码块外的正文行（已 strip），避免各提取函数重复写围栏判断。"""
    in_code_block = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        yield stripped


def bullet_lines(body: str) -> list[str]:
    """提取正文中的列表条目（- / * / 1. 开头），含 `- [ ]` 勾选条目。"""
    return [line for line in content_lines(body) if BULLET_PATTERN.match(line)]


def checkbox_lines(body: str) -> list[str]:
    """提取 `- [ ]` / `- [x]` 勾选条目；勾选状态本身不参与校验。"""
    return [line for line in content_lines(body) if CHECKBOX_PATTERN.match(line)]


def table_rows(body: str) -> list[str]:
    """提取 Markdown 表格的数据行：排除代码块、`| --- |` 分隔行与表头行。"""
    rows = [
        line
        for line in content_lines(body)
        if line.startswith("|") and not TABLE_SEPARATOR_PATTERN.match(line)
    ]
    return rows[1:]


def bullets_after_marker(body: str, marker: str) -> list[str]:
    """返回某个条目标记行之后紧跟的列表条目，用于检查"✅ 支持 / ⛔ 暂不支持"下列出了什么。"""
    lines = body.splitlines()
    marker_index = next(
        (index for index, line in enumerate(lines) if marker in line),
        -1,
    )
    if marker_index == -1:
        return []
    bullets: list[str] = []
    for line in lines[marker_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            break
        if BULLET_PATTERN.match(stripped):
            bullets.append(stripped)
        else:
            break
    return bullets


def check_required_section(
    sections: list[Section],
    name: str,
    keywords: tuple[str, ...],
    needs_content: bool,
) -> CheckResult:
    """检查 align.md 某要素小节是否存在，必要时要求正文有实际内容。"""
    section = find_section(sections, keywords)
    if section is None:
        return CheckResult(ALIGN_FILE, name, False, f"缺「{name}」小节")
    if needs_content and not section.body.strip():
        return CheckResult(ALIGN_FILE, name, False, f"「{name}」小节为空：必须写出实际内容")
    return CheckResult(ALIGN_FILE, name, True, f"「{name}」小节存在")


def check_scope(sections: list[Section]) -> list[CheckResult]:
    """范围边界是独立小节内的条目：分别校验"✅ 支持"与"⛔ 暂不支持"及其下的列表。"""
    scope = find_section(sections, ("范围",))
    if scope is None:
        return [
            CheckResult(ALIGN_FILE, "范围-支持", False, "缺「范围」小节"),
            CheckResult(ALIGN_FILE, "范围-暂不支持", False, "缺「范围」小节"),
        ]
    support_bullets = bullets_after_marker(scope.body, "✅ 支持")
    support_result = (
        CheckResult(ALIGN_FILE, "范围-支持", True, f"「范围-支持」列出 {len(support_bullets)} 项")
        if support_bullets
        else CheckResult(ALIGN_FILE, "范围-支持", False, "「范围」小节缺少「✅ 支持」条目")
    )
    excluded_bullets = bullets_after_marker(scope.body, "不支持")
    excluded_result = (
        CheckResult(ALIGN_FILE, "范围-暂不支持", True, f"「范围-暂不支持」列出 {len(excluded_bullets)} 项")
        if excluded_bullets
        else CheckResult(
            ALIGN_FILE,
            "范围-暂不支持",
            False,
            "「范围」小节缺少「⛔ 暂不支持」边界（显式边界是第一条工程沉淀，禁止留空）",
        )
    )
    return [support_result, excluded_result]


def check_observability(acceptance: Section | None, scope: str) -> CheckResult:
    """验收条目必须可观察：有列表条目、无不可观察词、含输入输出触发形态。"""
    name = "验收可观察性"
    if acceptance is None:
        return CheckResult(scope, name, False, "缺「验收标准」小节（已在上方检出）")
    bullets = bullet_lines(acceptance.body)
    if not bullets:
        return CheckResult(scope, name, False, "没有验收条目，每条应以「输入 X → 输出 Y」写出")
    for bullet in bullets:
        for word in UNOBSERVABLE_WORDS:
            if word in bullet:
                return CheckResult(
                    scope,
                    name,
                    False,
                    f"验收条目含不可观察词「{word}」: {bullet[:60]}… 请改写为可断言形式",
                )
    shaped_bullets = [
        bullet
        for bullet in bullets
        if "→" in bullet or bullet.startswith("当") or bullet.startswith("若")
        or "Given" in bullet or "When" in bullet
    ]
    if not shaped_bullets:
        return CheckResult(scope, name, False, "验收条目缺少「→ / 当 / 若 / Given / When」触发形态，无法转成断言")
    return CheckResult(scope, name, True, f"{len(bullets)} 条验收均可观察、可断言")


def check_align(text: str) -> list[CheckResult]:
    """校验 align.md：六要素（除架构风险）齐全 + 范围显式边界 + 验收可观察。"""
    sections = extract_sections(text)
    results = [
        check_required_section(sections, name, keywords, needs_content)
        for name, keywords, needs_content in REQUIRED_SECTIONS
    ]
    results.extend(check_scope(sections))
    results.append(check_observability(find_section(sections, ("验收",)), ALIGN_FILE))
    return results


def check_arch_risk(text: str) -> list[CheckResult]:
    """校验 arch-risk.md：风险扫描表有数据行；决议记录小节占位即可（首次落盘为空是合法的）。"""
    sections = extract_sections(text)
    scan = find_section(sections, ("边界风险扫描",))
    if scan is None:
        scan_result = CheckResult(ARCH_RISK_FILE, "边界风险扫描", False, "缺「## 🧱 边界风险扫描」小节")
    else:
        rows = table_rows(scan.body)
        scan_result = (
            CheckResult(ARCH_RISK_FILE, "边界风险扫描", True, f"扫描表列出 {len(rows)} 条边界")
            if rows
            else CheckResult(
                ARCH_RISK_FILE,
                "边界风险扫描",
                False,
                "扫描表没有数据行：逐项过完清单后至少写出一条结论（未命中也要写一行）",
            )
        )
    decision = find_section(sections, ("决议记录",))
    decision_result = (
        CheckResult(ARCH_RISK_FILE, "决议记录", True, "「决议记录」小节存在（内容为空合法，决议在架构发现后追加）")
        if decision is not None
        else CheckResult(
            ARCH_RISK_FILE,
            "决议记录",
            False,
            "缺「## 📌 决议记录」小节：首次落盘允许无内容，但标题必须占位供后续 append",
        )
    )
    return [scan_result, decision_result]


def check_acceptance(text: str) -> list[CheckResult]:
    """校验 acceptance.md：条目为 `- [ ]` 勾选格式且可观察；不校验是否已勾选。"""
    checkboxes = checkbox_lines(text)
    bullets = bullet_lines(text)
    if not checkboxes:
        format_result = CheckResult(
            ACCEPTANCE_FILE,
            "勾选清单格式",
            False,
            "没有 `- [ ]` 勾选条目：每条验收应写成「- [ ] 输入 X → 输出 Y」供人工逐条核对",
        )
    else:
        non_checkbox = [bullet for bullet in bullets if not CHECKBOX_PATTERN.match(bullet)]
        format_result = (
            CheckResult(
                ACCEPTANCE_FILE,
                "勾选清单格式",
                False,
                f"存在非 checkbox 条目: {non_checkbox[0][:60]}… 请改写为「- [ ] ...」",
            )
            if non_checkbox
            else CheckResult(
                ACCEPTANCE_FILE,
                "勾选清单格式",
                True,
                f"全部 {len(checkboxes)} 条为 checkbox 格式（勾选状态不参与校验）",
            )
        )
    return [format_result, check_observability(Section("验收清单", text), ACCEPTANCE_FILE)]


def run_checks(run_dir: Path) -> list[CheckResult]:
    """按文件顺序执行全部检查；某文件缺失只记 FAIL 并跳过其内容检查。"""
    checkers: tuple[tuple[str, Callable[[str], list[CheckResult]]], ...] = (
        (ALIGN_FILE, check_align),
        (ARCH_RISK_FILE, check_arch_risk),
        (ACCEPTANCE_FILE, check_acceptance),
    )
    results: list[CheckResult] = []
    for filename, checker in checkers:
        document = run_dir / filename
        try:
            text = document.read_text(encoding="utf-8")
        except OSError as exc:
            results.append(CheckResult(filename, "文件存在", False, f"无法读取 {filename}: {exc}"))
            continue
        results.append(CheckResult(filename, "文件存在", True, f"{filename} 已落盘"))
        results.extend(checker(text))
    return results


def render(results: list[CheckResult]) -> str:
    """把检查结果按文件分组渲染成人类可读文本。"""
    lines: list[str] = []
    for filename in REQUIRED_FILES:
        scoped = [result for result in results if result.scope == filename]
        if not scoped:
            continue
        lines.append(f"── {filename} ──")
        lines.extend(
            f"[{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail}"
            for result in scoped
        )
    passed_count = sum(1 for result in results if result.passed)
    lines.append(f"\n检查结果: {passed_count}/{len(results)} 通过")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 req-align 对齐产物目录（align.md / arch-risk.md / acceptance.md）"
    )
    parser.add_argument(
        "run_dir",
        help="对齐产物目录路径，如 docs/req-align-2026-08-04-payment-sse/",
    )
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    if run_dir.suffix == ".md" or run_dir.is_file():
        print(
            "[ERROR] 产物格式已改为目录：请传 docs/req-align-<yyyy-mm-dd>-<slug>/ 而非单个 Markdown 文件",
            file=sys.stderr,
        )
        return 2
    if not run_dir.is_dir():
        print(f"[ERROR] 目录不存在: {run_dir}", file=sys.stderr)
        return 2
    results = run_checks(run_dir)
    print(render(results))
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

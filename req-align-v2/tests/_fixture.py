"""构造一个最小可用的 req-align-v2 产物目录，供单测使用。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

ALIGN = """# 需求对齐：{title}

日期: {date} | slug: {slug} | 状态: 草稿 | 来源: 单测

## 🎯 目标

单测用目标。

## 📦 范围

✅ 支持:
- 能力一

⛔ 暂不支持:
- 排除项（理由: 超出范围）

## 🔼 优先级

- P0（必须）: 能力一

## ✅ 验收标准

{acceptance}

## 🧱 架构边界风险

见 `arch-risk.md`。

## ➡️ 下一阶段

判定: 直接推进
去向: 执行计划
沿用的历史决策: 无
"""

ARCH_RISK = """# 架构边界风险与决议：{title}

## 🧱 边界风险扫描

| ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| RISK-1 | 数据流边界 | 生产者消费者未定 | — | 架构发现 | 待验证 |
| RISK-2 | 时序 / 事件流 | 未命中 | — | — | 未命中 |
| RISK-3 | 跨服务 / 跨模块 | 未命中 | — | — | 未命中 |
| RISK-4 | 持久化与领域模型 | 未命中 | — | — | 未命中 |
| RISK-5 | 多 Agent / 外部 API 契约 | 未命中 | — | — | 未命中 |
| RISK-6 | 可验证性 | 未命中 | — | — | 未命中 |

## 📌 决议记录

<!-- append-only -->
"""

ACCEPTANCE = """# 验收清单：{title}

来源: `align.md` 的「✅ 验收标准」

{checkboxes}

## 证据

## 未通过记录
"""


def make_run(root: Path = None, date: str = "2026-09-02", slug: str = "demo",
             ac_count: int = 2, container: str = "docs") -> Path:
    """在 <root>/<container>/req-align-<date>-<slug>/ 下写出三份 Markdown 并返回该目录。"""
    root = root or Path(tempfile.mkdtemp())
    run_dir = root / container / f"req-align-{date}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    acceptance = "\n".join(
        f"- AC-{i} (P{0 if i == 1 else 1}) 输入 X{i} → 输出 Y{i}" for i in range(1, ac_count + 1))
    checkboxes = "\n".join(
        f"- [ ] AC-{i} 输入 X{i} → 输出 Y{i}" for i in range(1, ac_count + 1))
    title = f"{slug} 单测"
    (run_dir / "align.md").write_text(
        ALIGN.format(title=title, date=date, slug=slug, acceptance=acceptance), encoding="utf-8")
    (run_dir / "arch-risk.md").write_text(ARCH_RISK.format(title=title), encoding="utf-8")
    (run_dir / "acceptance.md").write_text(
        ACCEPTANCE.format(title=title, checkboxes=checkboxes), encoding="utf-8")
    return run_dir


def run_script(name: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
        capture_output=True, text=True,
    )

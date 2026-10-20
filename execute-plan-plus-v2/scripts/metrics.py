#!/usr/bin/env python3
"""运行痕迹留存：把 skill 脚本的动作追加成 JSONL，供事后人工查看。

设计约束（与 skill 的核心原则一致）：
- **脚本写，LLM 不读**。`runs.jsonl` 不出现在任何 SKILL.md 的读取清单里，
  因此留存的上下文成本为 0。
- 只追加不改写；一行一事件；每行带 skill 版本与 run 目录，便于人工分组对照。
- 不做汇总、不算分、不设阈值——判断留给人。

**静默降级的豁免声明**：本模块是全流程唯一允许吞异常的地方。
理由：留存是旁路观测，绝不能因为磁盘只读、权限不足、路径异常等原因
反过来让主流程（对齐 / 执行）失败。其余任何模块都必须让错误尽早暴露。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

METRICS_DIRNAME = ".skill-metrics"
METRICS_FILENAME = "runs.jsonl"


def find_project_root(start: Path) -> Optional[Path]:
    """从 start 向上找含 docs/ 的目录作为项目根；找不到返回 None。"""
    try:
        current = start.resolve()
    except OSError:
        return None
    for candidate in [current, *current.parents]:
        if (candidate / "docs").is_dir():
            return candidate
    return None


def metrics_path(project_root: Path) -> Path:
    return project_root / "docs" / METRICS_DIRNAME / METRICS_FILENAME


def emit(skill: str, event: str, run: Any = None, **fields: Any) -> None:
    """追加一条事件。任何异常都吞掉——见模块 docstring 的豁免声明。"""
    try:
        anchor = Path(str(run)) if run else Path.cwd()
        if not anchor.is_dir():
            anchor = anchor.parent if anchor.parent.exists() else Path.cwd()
        project_root = find_project_root(anchor) or find_project_root(Path.cwd())
        if project_root is None:
            return
        record: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "skill": skill,
            "event": event,
            "run": _relative(run, project_root),
        }
        record.update(fields)
        target = metrics_path(project_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 见模块 docstring 的豁免声明
        return


def _relative(run: Any, project_root: Path) -> Optional[str]:
    if not run:
        return None
    try:
        return os.path.relpath(Path(str(run)).resolve(), project_root)
    except (OSError, ValueError):
        return str(run)

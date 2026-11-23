#!/usr/bin/env python3
"""列出 req-align-v2 run 中状态为「待验证」的风险（只读）。

用法: python3 scripts/list_risks.py <req-align run_dir>
数据源: handoff.json（状态）；arch-risk.md 扫描表存在时补充风险描述与建议验证阶段。
退出码: 0 成功 / 2 输入错误。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_handoff(run_dir: Path) -> dict:
    path = run_dir / "handoff.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: 无法读取 {path}: {exc}（先跑 req-align-v2 的 align_state.py sync）") from None
    if not isinstance(data, dict) or not isinstance(data.get("risks"), list):
        raise SystemExit(f"error: {path} 缺 risks 列表")
    return data


def table_details(run_dir: Path) -> dict:
    """arch-risk.md 扫描表：ID | 边界 | 风险 | 关联边界 | 建议验证阶段 | 状态。"""
    try:
        lines = (run_dir / "arch-risk.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    found = {}
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.strip().startswith("|") and len(cells) >= 6 and cells[0].startswith("RISK-"):
            found[cells[0]] = {"risk": cells[2], "phase": cells[4]}
    return found


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: list_risks.py <run_dir>", file=sys.stderr)
        return 2
    run_dir = Path(argv[1])
    if not run_dir.is_dir():
        print(f"error: 目录不存在: {run_dir}", file=sys.stderr)
        return 2
    try:
        data = load_handoff(run_dir)
    except SystemExit as exc:
        print(exc.code, file=sys.stderr)
        return 2
    details = table_details(run_dir)
    pending = [r for r in data["risks"] if isinstance(r, dict) and r.get("state") == "待验证"]
    if not pending:
        print("无待验证风险")
        return 0
    for r in pending:
        extra = details.get(r.get("id"), {})
        print(f"{r.get('id')} | {r.get('boundary', '')} | {extra.get('risk', '（见 arch-risk.md）')} "
              f"| 建议阶段: {extra.get('phase', '—')} | {r.get('state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

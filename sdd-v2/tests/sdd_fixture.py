"""手写最小 handoff.json 与 SDD 目录，供 check_sdd 单测使用（不依赖其他 skill）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_sdd.py"

MATRIX_HEADER = "| AC | 规格（Given/When/Then） | 覆盖模块 | 备注 |\n| --- | --- | --- | --- |\n"
GOOD_SPEC = "Given 已登录 / When 提交 / Then 返回 200"
P0_NOTE = "越权请求被拒绝"

OVERVIEW = """# 概览

## 1. 背景与目标

目标说明。

## 2. 范围

支持 A。

## 3. 功能需求

- AC-1 输入 → 输出
- AC-2 其它

## 4. 非功能需求

响应 < 200ms。

## 5. 错误与边界场景

越权拒绝。
"""


SOURCE_FILES = ("align.md", "arch-risk.md", "acceptance.md")


def source_hashes(run_dir: Path) -> dict:
    return {n: hashlib.sha256((run_dir / n).read_bytes()).hexdigest() for n in SOURCE_FILES}


def resync(run_dir: Path) -> None:
    """模拟 align_state.py sync：按当前三份源文件重写 handoff.json 的 source_sha256。"""
    path = run_dir / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source_sha256"] = source_hashes(run_dir)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_handoff_run(root: Path = None, slug: str = "demo",
                     acs=(("AC-1", "P0"), ("AC-2", "P1")), fresh: bool = True) -> Path:
    root = root or Path(tempfile.mkdtemp())
    run_dir = root / "docs" / f"req-align-2026-09-02-{slug}"
    run_dir.mkdir(parents=True)
    for n in SOURCE_FILES:
        (run_dir / n).write_text(f"# {n}\n原始内容\n", encoding="utf-8")
    data = {"slug": slug, "acceptance": [{"id": i, "priority": p} for i, p in acs]}
    if fresh:
        data["source_sha256"] = source_hashes(run_dir)
    (run_dir / "handoff.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return run_dir


def row(ac, spec=GOOD_SPEC, module="api", note=""):
    return f"| {ac} | {spec} | {module} | {note} |"


def default_rows():
    return [row("AC-1", note=P0_NOTE), row("AC-2")]


def make_sdd(run_dir: Path, rows=None, name: str = None, overview: str = OVERVIEW,
             readme: str = None, matrix_text: str = None, skip=(), eol: str = "\n") -> Path:
    slug = json.loads((run_dir / "handoff.json").read_text(encoding="utf-8"))["slug"]
    sdd = run_dir.parent / (name or f"sdd-2026-09-03-{slug}")
    sdd.mkdir(parents=True, exist_ok=True)
    if readme is None:
        readme = f"# SDD\n\n上游: {run_dir.name}\n"
    if matrix_text is None:
        matrix_text = "# 矩阵\n\n" + MATRIX_HEADER + "\n".join(rows if rows is not None else default_rows()) + "\n"
    files = {"README.md": readme, "01-overview.md": overview, "acceptance-matrix.md": matrix_text}
    for fname, text in files.items():
        if fname not in skip:
            (sdd / fname).write_bytes(text.replace("\n", eol).encode("utf-8"))
    return sdd


def run_check(sdd: Path, run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), str(sdd), "--run-dir", str(run_dir)],
                          capture_output=True, text=True)

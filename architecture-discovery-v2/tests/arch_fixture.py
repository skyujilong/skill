"""手写 handoff.json 与架构发现目录，供单测使用（不依赖 req-align-v2 脚本）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

LONG = "这是一段足够长的正文，用来说明分层、职责与约束，避免被当成占位文件。" * 10


SOURCE_FILES = ("align.md", "arch-risk.md", "acceptance.md")


def source_hashes(run_dir: Path) -> dict:
    return {n: hashlib.sha256((run_dir / n).read_bytes()).hexdigest() for n in SOURCE_FILES}


def resync(run_dir: Path) -> None:
    """模拟 align_state.py sync：按当前三份源文件重写 handoff.json 的 source_sha256。"""
    path = run_dir / "handoff.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source_sha256"] = source_hashes(run_dir)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_run(root: Path = None, slug: str = "demo", date: str = "2026-09-02", risks=None,
             fresh: bool = True) -> Path:
    """写 <root>/docs/req-align-<date>-<slug>/handoff.json。risks: [(id, state)]。"""
    root = root or Path(tempfile.mkdtemp())
    run_dir = root / "docs" / f"req-align-{date}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    risks = risks if risks is not None else [("RISK-1", "待验证"), ("RISK-2", "未命中")]
    data = {"slug": slug, "risks": [{"id": i, "boundary": f"边界{i}", "state": s} for i, s in risks]}
    for n in SOURCE_FILES:
        (run_dir / n).write_text(f"# {n}\n原始内容\n", encoding="utf-8")
    if fresh:
        data["source_sha256"] = source_hashes(run_dir)
    (run_dir / "handoff.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return run_dir


def section(rid="RISK-1", title="标题", **over) -> str:
    fields = {"结论": "采用方案 A", "证据类型": "code", "证据": "src/a.py:10-20",
              "影响": "SDD 需引用", "已回写": "yes"}
    fields.update(over)
    lines = [f"## {rid} {title}"]
    lines += [f"- {k}: {v}" for k, v in fields.items() if v is not None]
    return "\n".join(lines) + "\n"


def make_disc(run_dir: Path, sections=None, dirname: str = None, files=None) -> Path:
    """写讨论目录；sections 为 decisions.md 正文列表；files 覆盖其余文件内容。"""
    slug = json.loads((run_dir / "handoff.json").read_text(encoding="utf-8"))["slug"]
    disc = run_dir.parent / (dirname or f"architecture-discovery-2026-09-03-{slug}")
    disc.mkdir(parents=True, exist_ok=True)
    body = "\n".join(sections if sections is not None else [section()])
    content = {
        "architecture.md": "# 架构\n\n## 分层与依赖方向\n\n" + LONG + "\n## 技术选型与理由\n\n沿用标准方案。\n",
        "flows-and-boundaries.md": "# 流程\n\n## 边界归属\n\nRISK-1 归 api 层。\n" + LONG,
        "decisions.md": "# 决议\n\n" + body,
    }
    content.update(files or {})
    for name, text in content.items():
        if text is not None:
            (disc / name).write_text(text, encoding="utf-8")
    return disc


def run_script(name: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
                          capture_output=True, text=True)

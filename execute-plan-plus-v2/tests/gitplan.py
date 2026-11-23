"""测试辅助：真实临时 git 仓库里的 exec-plan（身份只经环境变量注入，不碰真实 git 配置）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def script(name: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
                          capture_output=True, text=True, env=ENV)


def git(root: Path, *args) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          env=ENV)
    assert done.returncode == 0, (args, done.stdout, done.stderr)
    return done.stdout.strip()


def head(root: Path) -> str:
    return git(root, "rev-parse", "--short", "HEAD")


def commit_file(root: Path, rel: str, text: str = "x\n", message: str = "c") -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(root, "add", "--", rel)
    git(root, "commit", "-q", "-m", message)
    return head(root)


def make_repo_plan(steps: list, in_git: bool = True) -> tuple:
    """返回 (root, plan_dir)；plan 位于顶层 docs/ 下且未被跟踪。"""
    root = Path(tempfile.mkdtemp())
    if in_git:
        git(root, "init", "-q")
        commit_file(root, "README.md", "init\n", "init")
    plan = root / "docs" / "exec-plan-2026-09-02-demo"
    plan.mkdir(parents=True)
    (plan / "step.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")
    return root, plan


def step(name: str, state: str = "pending", **extra) -> dict:
    return {"step": name, "state": state, **extra}


def read_steps(plan: Path) -> list:
    return json.loads((plan / "step.json").read_text(encoding="utf-8"))

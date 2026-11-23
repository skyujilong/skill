"""step.json 接口声明（depends_on/produces/exposes/consumes）与 git 锚点的共享逻辑。

只做声明层面的静态检查：符号是计划里自行声明的稳定字符串，这里不解析任何代码。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

LIST_KEYS = ("depends_on", "produces", "exposes", "consumes")
SYMBOL_KEYS = ("produces", "exposes", "consumes")
EXISTING_PREFIX = "existing:"


class GitError(RuntimeError):
    """git 已识别为仓库后仍执行失败；不能当作"工作区干净"。"""


def is_existing(symbol: str) -> bool:
    return symbol.strip().lower().startswith(EXISTING_PREFIX)


def field_errors(data: list) -> list:
    """校验 step.json 各条目的接口字段类型与 depends_on 引用；返回错误文案列表。"""
    errors = []
    names = {item["step"]: i for i, item in enumerate(data)
             if isinstance(item, dict) and isinstance(item.get("step"), str)}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        label = f"entry {index} ({item.get('step')})"
        for key in LIST_KEYS:
            if key not in item:
                continue
            value = item[key]
            if not isinstance(value, list) or not all(
                    isinstance(v, str) and v.strip() for v in value):
                errors.append(f"{label} {key} must be a list of non-empty strings")
            elif key in ("produces", "exposes") and any(is_existing(v) for v in value):
                errors.append(f"{label} {key} cannot use the `existing:` prefix "
                              "(it is only valid in consumes)")
        deps = item.get("depends_on")
        if isinstance(deps, list) and all(isinstance(v, str) for v in deps):
            for dep in deps:
                if dep == item.get("step"):
                    errors.append(f"{label} depends_on cannot reference itself")
                elif dep not in names:
                    errors.append(f"{label} depends_on unknown step: {dep}")
                elif names[dep] > index:
                    errors.append(f"{label} depends_on must reference an earlier step: {dep}")
    return errors


def symbols(item: dict, key: str) -> list:
    value = item.get(key)
    if not isinstance(value, list):
        return []
    return [v if key == "depends_on" else v.strip() for v in value if isinstance(v, str)]


def prerequisites(data: list, index: int) -> dict:
    """返回 {前置步骤名: 原因}：depends_on 以及产出/暴露了本步 consumes 符号的步骤。"""
    target = data[index]
    needed = {}
    for dep in symbols(target, "depends_on"):
        needed[dep] = "depends_on"
    wanted = {s for s in symbols(target, "consumes") if not is_existing(s)}
    for other_index, other in enumerate(data[:index]):
        for symbol in sorted(wanted & (set(symbols(other, "produces"))
                                       | set(symbols(other, "exposes")))):
            needed.setdefault(other["step"], f"provides {symbol}")
    return needed


def audit_interfaces(data: list) -> list:
    """返回 [(PASS|FAIL|WARN, 文案)]；不声明任何接口只给 WARN，不算失败。"""
    entries = [item for item in data if isinstance(item, dict)]
    declared = any(key in item for item in entries for key in LIST_KEYS)
    if not declared:
        return [("WARN", "no interface declarations; orphan risk unmanaged")]
    problems = [("FAIL", message) for message in field_errors(data)]
    for item in entries:
        missing = [key for key in SYMBOL_KEYS if key not in item]
        if missing:
            problems.append(("FAIL", f"step {item.get('step')} missing interface keys: "
                                     f"{', '.join(missing)} (empty lists are allowed)"))
    producers: dict = {}
    for position, item in enumerate(entries):
        for key in ("produces", "exposes"):
            for symbol in symbols(item, key):
                producers.setdefault(symbol, []).append((position, item.get("step")))
    for symbol, owners in sorted(producers.items()):
        steps = sorted({name for _, name in owners})
        if len(steps) > 1:
            problems.append(("FAIL", f"duplicate producer of {symbol}: {', '.join(steps)}"))
    for position, item in enumerate(entries):
        for symbol in symbols(item, "consumes"):
            if is_existing(symbol):
                continue
            if not any(pos < position for pos, _ in producers.get(symbol, [])):
                problems.append(("FAIL", f"step {item.get('step')} consumes {symbol} but no "
                                         "earlier step produces or exposes it (fix with `update_step_state.py "
                                         "<step.json> <step> declare ...` while pending)"))
    exposed = {s for item in entries for s in symbols(item, "exposes")}
    for position, item in enumerate(entries):
        for symbol in symbols(item, "produces"):
            if symbol in exposed:
                continue
            consumed_later = any(
                symbol in symbols(later, "consumes") for later in entries[position + 1:])
            if not consumed_later:
                problems.append(("FAIL", f"orphan risk: {symbol} produced by {item.get('step')} "
                                         "has no later consumer (declare it in exposes if it "
                                         "is a public entry point); fix with `update_step_state.py "
                                         f"<step.json> {item.get('step')} declare --exposes "
                                         "... --reason TEXT`"))
    return problems or [("PASS", f"interface declarations consistent across {len(entries)} steps")]


# ------------------------------------------------------------------------ git


def run_git(cwd: Path, *args) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    except OSError:
        return None


def repo_top(path: Path) -> Optional[Path]:
    done = run_git(path, "rev-parse", "--show-toplevel")
    if done is None or done.returncode != 0 or not done.stdout.strip():
        return None
    return Path(done.stdout.strip())


def short_head(top: Path) -> Optional[str]:
    done = run_git(top, "rev-parse", "--short", "HEAD")
    if done is None or done.returncode != 0:
        return None
    return done.stdout.strip()


def outside_top_docs(path: str) -> bool:
    return not (path == "docs" or path.startswith("docs/"))


def dirty_paths(top: Path) -> list:
    """工作区改动/未跟踪文件（排除仓库顶层 docs/），NUL 分隔解析以免转义路径。"""
    done = run_git(top, "status", "--porcelain", "-z", "--untracked-files=all")
    if done is None:
        raise GitError("git status could not be executed")
    if done.returncode != 0:
        raise GitError(f"git status failed (exit {done.returncode}): "
                       f"{done.stderr.strip() or 'no output'}")
    records = done.stdout.split("\0")
    paths = []
    i = 0
    while i < len(records):
        record = records[i]
        i += 1
        if len(record) < 4:
            continue
        paths.append(record[3:])
        if record[0] in "RC" or record[1] in "RC":
            if i < len(records) and records[i]:
                paths.append(records[i])
            i += 1
    return sorted({p for p in paths if outside_top_docs(p)})

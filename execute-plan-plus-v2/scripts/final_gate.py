#!/usr/bin/env python3
"""One-command final gate for an execute-plan-plus-v2 plan.

Usage:
    python3 scripts/final_gate.py <plan_dir> [--req-align-scripts DIR]

Gates (one PASS/FAIL line each, then `result: PASS|FAIL`):

1. steps: every step in step.json is `complate`.
2. If `<plan_dir>/upstream.json` exists (linked mode; `--req-align-scripts` required):
   - coverage: `audit_coverage.py <plan_dir>` (next to this file);
   - strict-closure: `check_alignment.py <run_dir> --strict-closure` from DIR
     (AC closure, script-verified P0 evidence, fresh evidence rev, final independent review);
   - history-sync: `boundary_state.py history-sync <run_dir>` from DIR.
   Without upstream.json it runs in generic mode: only the steps gate.

Each gate subprocess has a timeout (GATE_TIMEOUT_SECONDS = 900); a gate that exceeds it is
reported as FAIL. Override with the FINAL_GATE_TIMEOUT environment variable (seconds).
A passing gate whose output contains `[WARN]` lines (e.g. non-git repo: freshness skipped)
has those lines echoed under it as `    [WARN] ...`.

Honest limits: this script does NOT run the project's own lint / typecheck / regression
suites or the real user path — run those yourself. It also cannot prove a verification
command is meaningful or a reviewer is truly independent.

The run dir is resolved like update_step_state.py (relative to the plan dir, never the CWD);
the logic is copied, not imported, to keep the two skills decoupled.

Exit codes: 0 PASS / 1 FAIL / 2 bad arguments or unreadable plan.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
RUN_DIRNAME_RE = re.compile(r"req-align-\d{4}-\d{2}-\d{2}-.+")
GATE_TIMEOUT_SECONDS = 900
TIMEOUT_ENV = "FINAL_GATE_TIMEOUT"
REMINDER = ("reminder: this script does NOT run the project's own lint/typecheck/regression "
            "suites or the real user path — run them yourself")


def usage_error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def locate_run_dir(plan_dir: Path, upstream: dict) -> Optional[Path]:
    """Same resolution as update_step_state.locate_handoff_file, returning the run dir."""
    run_dir = Path(upstream["run_dir"])
    candidates = [plan_dir.parent / run_dir.name]
    if not run_dir.is_absolute() or RUN_DIRNAME_RE.fullmatch(run_dir.name):
        candidates.insert(0, plan_dir / run_dir)
    plan_parent = plan_dir.resolve().parent
    return next((c for c in candidates
                 if RUN_DIRNAME_RE.fullmatch(c.name) is not None
                 and c.resolve().parent == plan_parent
                 and (c / "handoff.json").is_file()), None)


def gate_timeout() -> float:
    try:
        value = float(os.environ.get(TIMEOUT_ENV, ""))
    except ValueError:
        return GATE_TIMEOUT_SECONDS
    return value if value > 0 else GATE_TIMEOUT_SECONDS


def run_gate(label: str, cmd: list, cwd: Optional[Path] = None) -> bool:
    timeout = gate_timeout()
    try:
        done = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {label}")
        print(f"    timed out after {timeout:g}s")
        return False
    passed = done.returncode == 0
    print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    if not passed:
        tail = (done.stdout + done.stderr).strip().splitlines()[-15:]
        print("\n".join(f"    {line}" for line in tail))
    else:
        for line in done.stdout.splitlines():
            if line.startswith("[WARN]"):
                print(f"    {line}")
    return passed


def main(argv: list = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    scripts_dir = None
    if "--req-align-scripts" in args:
        index = args.index("--req-align-scripts")
        if index + 1 >= len(args):
            return usage_error("--req-align-scripts needs a directory")
        scripts_dir = Path(args[index + 1])
        del args[index:index + 2]
    if len(args) != 1:
        return usage_error("usage: final_gate.py <plan_dir> [--req-align-scripts DIR]")
    plan_dir = Path(args[0])
    if not plan_dir.is_dir():
        return usage_error(f"plan dir not found: {plan_dir}")
    try:
        steps = read_json(plan_dir / "step.json")
        upstream_path = plan_dir / "upstream.json"
        upstream = read_json(upstream_path) if upstream_path.is_file() else None
    except ValueError as exc:
        return usage_error(str(exc))
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        return usage_error("step.json must be an array of objects")
    if upstream is not None and (not isinstance(upstream, dict) or not upstream.get("run_dir")):
        return usage_error(f"{upstream_path} must be an object with a non-empty 'run_dir'")
    if upstream is not None and upstream.get("contract_version", "1") != "1":
        return usage_error(f"{upstream_path} contract_version is "
                           f"{upstream['contract_version']!r}, expected \"1\"")
    if upstream is not None:
        if scripts_dir is None:
            return usage_error("upstream.json exists: --req-align-scripts DIR is required "
                               "(cannot verify upstream closure without it)")
        for name in ("check_alignment.py", "boundary_state.py"):
            if not (scripts_dir / name).is_file():
                return usage_error(f"{scripts_dir / name} not found")

    print(f"── final gate ({'upstream-linked' if upstream else 'GENERIC mode, no upstream'}): "
          f"{plan_dir} ──")
    results = []
    pending = [str(s.get("step")) for s in steps if s.get("state") != "complate"]
    if not steps:
        pending = ["(no steps)"]
    print(f"[{'FAIL' if pending else 'PASS'}] steps: "
          + (f"not complate: {', '.join(pending)}" if pending else f"all {len(steps)} complate"))
    results.append(not pending)

    if upstream is not None:
        results.append(run_gate("coverage (audit_coverage.py)",
                                [sys.executable, str(HERE / "audit_coverage.py"), str(plan_dir)]))
        run_dir = locate_run_dir(plan_dir, upstream)
        if run_dir is None:
            print(f"[FAIL] upstream: cannot locate run dir via '{upstream['run_dir']}'")
            results.append(False)
        else:
            results.append(run_gate(
                "strict-closure (check_alignment.py --strict-closure)",
                [sys.executable, str(scripts_dir.resolve() / "check_alignment.py"),
                 str(run_dir.resolve()), "--strict-closure"], cwd=scripts_dir))
            results.append(run_gate(
                "history-sync (boundary_state.py history-sync)",
                [sys.executable, str(scripts_dir.resolve() / "boundary_state.py"),
                 "history-sync", str(run_dir.resolve())], cwd=scripts_dir))
    print(REMINDER)
    passed = all(results)
    print(f"result: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

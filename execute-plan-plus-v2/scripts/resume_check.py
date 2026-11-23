#!/usr/bin/env python3
"""Read-only resume anchor check for an execute-plan-plus-v2 plan.

Usage:
    python3 scripts/resume_check.py <plan_dir>

In a git repo, every `complate` step with a recorded `commit` must still exist and be an
ancestor of HEAD (otherwise STALE: the code was reset/rebased away). Also lists files changed
since the last complate step's commit (excluding top-level `docs/`), complate steps with no
recorded commit (legacy), and the orphan picture declared in step.json:

- EXPECTED ORPHANS: produced symbols whose consumer steps are not all complate yet;
- UNEXPECTED: produced, never consumed and not exposed (the interface audit should fail).

It trusts the plan's declared symbols; it does not parse code.

Exit codes: 0 ok / 1 stale step commit / 2 bad arguments or unreadable plan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import interfaces  # noqa: E402


def orphan_report(steps: list) -> tuple:
    expected, unexpected = [], []
    exposed = {s for item in steps for s in interfaces.symbols(item, "exposes")}
    for position, item in enumerate(steps):
        for symbol in interfaces.symbols(item, "produces"):
            consumers = [later for later in steps[position + 1:]
                         if symbol in interfaces.symbols(later, "consumes")]
            pending = [c["step"] for c in consumers if c.get("state") != "complate"]
            if pending:
                expected.append((symbol, item["step"], pending))
            elif not consumers and symbol not in exposed:
                unexpected.append((symbol, item["step"]))
    return expected, unexpected


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: resume_check.py <plan_dir>", file=sys.stderr)
        return 2
    plan_dir = Path(args[0])
    if not plan_dir.is_dir():
        print(f"[ERROR] plan dir not found: {plan_dir}", file=sys.stderr)
        return 2
    try:
        steps = json.loads((plan_dir / "step.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ERROR] cannot read step.json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(steps, list) or not all(
            isinstance(s, dict) and isinstance(s.get("step"), str) for s in steps):
        print("[ERROR] step.json must be an array of step objects", file=sys.stderr)
        return 2

    print(f"── resume check: {plan_dir} ──")
    stale = []
    top = interfaces.repo_top(plan_dir.resolve())
    head = interfaces.short_head(top) if top else None
    if head is None:
        print("anchor checks skipped: plan is not in a git repo with commits")
    else:
        last_good = None
        for item in steps:
            if item.get("state") != "complate":
                continue
            commit = item.get("commit")
            if not commit:
                print(f"[WARN] {item['step']}: complate with no recorded commit (legacy)")
                continue
            exists = interfaces.run_git(top, "cat-file", "-e", f"{commit}^{{commit}}")
            ancestor = interfaces.run_git(top, "merge-base", "--is-ancestor", commit, "HEAD")
            if exists is None or ancestor is None:
                print("[ERROR] git could not be executed during the anchor check",
                      file=sys.stderr)
                return 2
            if exists.returncode != 0 or ancestor.returncode != 0:
                stale.append(item["step"])
                print(f"STALE {item['step']}: commit {commit} is missing or not an ancestor "
                      f"of HEAD ({head})")
            else:
                last_good = commit
                print(f"[OK] {item['step']}: {commit}")
        if last_good:
            diff = interfaces.run_git(top, "diff", "--name-only", "-z", last_good, "HEAD")
            if diff is None:
                print("[ERROR] git could not be executed during the anchor check",
                      file=sys.stderr)
                return 2
            files = sorted(f for f in diff.stdout.split("\0")
                           if f and interfaces.outside_top_docs(f))
            print(f"changes after last step ({last_good}..{head}): {len(files)} file(s)")
            for name in files[:30]:
                print(f"  {name}")
            if len(files) > 30:
                print(f"  ... and {len(files) - 30} more")

    expected, unexpected = orphan_report(steps)
    print(f"EXPECTED ORPHANS ({len(expected)}): produced, consumers not all complate yet")
    for symbol, producer, pending in expected:
        print(f"  {symbol}  produced by {producer}; pending consumers: {', '.join(pending)}")
    print(f"UNEXPECTED ({len(unexpected)}): produced, no consumer, not exposed")
    for symbol, producer in unexpected:
        print(f"  {symbol}  produced by {producer}")
    if stale:
        print(f"result: STALE ({', '.join(stale)}) - re-verify these steps before continuing")
        return 1
    print("result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

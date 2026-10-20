#!/usr/bin/env python3
"""Pre-execution gate: every upstream AC-N must be covered by some step.

Usage:
    python3 scripts/audit_coverage.py <plan_dir>

Checks (only when `<plan_dir>/upstream.json` exists; otherwise it is a no-op so
generic plans keep working):

1. Every acceptance id in the upstream `handoff.json` appears in some step's `covers`.
2. No step's `covers` references an unknown acceptance id.
3. Every `Covers: AC-...` annotation in `requirements.md` resolves to a known id,
   and the union of those annotations matches the union of step coverage.

Point 3 exists because re-deriving requirements from prose tends to invent
independent numbering schemes that don't map back to upstream AC ids. Here the
`R` grouping is still allowed, but it must map onto the upstream AC ids.

Exit codes: 0 pass / 1 coverage gap / 2 bad arguments or paths.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402

SKILL = "execute-plan-plus-v2"

COVERS_RE = re.compile(r"^[-*]?\s*Covers:\s*(.+)$", re.IGNORECASE)
AC_RE = re.compile(r"AC-\d+")
RUN_DIRNAME_RE = re.compile(r"req-align-\d{4}-\d{2}-\d{2}-.+")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"[ERROR] cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] invalid JSON in {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def locate_handoff(plan_dir: Path, run_dir_value: str) -> Path:
    """只相对 plan 目录解析 run_dir，不看进程 CWD（同名诱饵目录不得胜出）。
    绝对路径仅在目录名符合 req-align-<date>-<slug> 形态时沿用。"""
    plan_dir = plan_dir.resolve()
    run_dir = Path(run_dir_value)
    candidates = [plan_dir.parent / run_dir.name]
    if not run_dir.is_absolute() or RUN_DIRNAME_RE.fullmatch(run_dir.name):
        candidates.insert(0, plan_dir / run_dir)
    for candidate in candidates:
        if not (RUN_DIRNAME_RE.fullmatch(candidate.name) is not None
                and candidate.resolve().parent == plan_dir.parent):
            continue
        path = candidate / "handoff.json"
        if path.is_file():
            return path
    print(f"[ERROR] cannot locate upstream handoff.json via '{run_dir_value}'", file=sys.stderr)
    raise SystemExit(2)


def requirement_covers(plan_dir: Path) -> set:
    path = plan_dir / "requirements.md"
    if not path.is_file():
        return set()
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = COVERS_RE.match(line.strip())
        if match:
            found.update(AC_RE.findall(match.group(1)))
    return found


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: audit_coverage.py <plan_dir>", file=sys.stderr)
        return 2
    plan_dir = Path(args[0])
    if not plan_dir.is_dir():
        print(f"[ERROR] plan dir not found: {plan_dir}", file=sys.stderr)
        return 2

    upstream_path = plan_dir / "upstream.json"
    if not upstream_path.is_file():
        print("no upstream.json — generic mode, coverage audit skipped")
        return 0
    upstream = read_json(upstream_path)
    if not isinstance(upstream, dict):
        print(f"[ERROR] {upstream_path} must be a JSON object", file=sys.stderr)
        return 2
    for key in ("run_dir", "slug"):
        if not upstream.get(key):
            print(f"[ERROR] {upstream_path} must contain a non-empty '{key}'", file=sys.stderr)
            return 2
    if "contract_version" in upstream and upstream["contract_version"] != "1":
        print(f"[ERROR] {upstream_path} contract_version is "
              f"{upstream['contract_version']!r}, expected \"1\"", file=sys.stderr)
        return 2
    handoff_path = locate_handoff(plan_dir, upstream["run_dir"])
    handoff = read_json(handoff_path)
    if not isinstance(handoff, dict):
        print(f"[ERROR] {handoff_path} must be a JSON object", file=sys.stderr)
        return 2
    if handoff.get("contract_version") != "1":
        print(f"[ERROR] upstream handoff.json contract_version is "
              f"{handoff.get('contract_version')!r}, expected \"1\"", file=sys.stderr)
        return 2
    if handoff.get("slug") != upstream["slug"]:
        print(f"[ERROR] upstream handoff.json slug {handoff.get('slug')!r} does not match "
              f"upstream.json slug {upstream['slug']!r}", file=sys.stderr)
        return 2
    steps = read_json(plan_dir / "step.json")
    if not isinstance(steps, list):
        print("[ERROR] step.json must be a JSON array", file=sys.stderr)
        return 2

    upstream_ids = [item.get("id") for item in handoff.get("acceptance", [])]
    covered: dict = {}
    unknown: dict = {}
    bad_covers = []
    for entry in steps:
        entry_covers = entry.get("covers")
        if entry_covers is not None and not isinstance(entry_covers, list):
            bad_covers.append(str(entry.get("step")))
            continue
        for ac in entry_covers or []:
            bucket = covered if ac in upstream_ids else unknown
            bucket.setdefault(ac, []).append(entry.get("step"))

    problems = []
    if bad_covers:
        problems.append("covers must be a list of AC ids in step(s): " + ", ".join(bad_covers))
    uncovered = [ac for ac in upstream_ids if ac not in covered]
    if uncovered:
        problems.append("acceptance not covered by any step: " + ", ".join(uncovered))
    if unknown:
        problems.append("steps cover unknown acceptance ids: "
                        + ", ".join(f"{ac} (in {', '.join(s)})" for ac, s in sorted(unknown.items())))

    if not upstream_ids:
        problems.append("upstream has no acceptance criteria: a linked plan needs "
                        "at least one AC-N to trace back to")
    requirements_path = plan_dir / "requirements.md"
    req_ids = requirement_covers(plan_dir)
    if not requirements_path.is_file():
        problems.append("requirements.md missing: each requirement must declare "
                        "`Covers: AC-N` so the trace back to upstream stays auditable")
    elif not req_ids:
        problems.append("requirements.md has no `Covers: AC-N` annotations: each "
                        "requirement must declare the upstream AC ids it serves")
    else:
        req_unknown = sorted(req_ids - set(upstream_ids))
        if req_unknown:
            problems.append("requirements.md `Covers:` references unknown ids: "
                            + ", ".join(req_unknown))
        only_in_steps = sorted(set(covered) - req_ids)
        only_in_req = sorted(req_ids - set(covered))
        if only_in_steps or only_in_req:
            problems.append(
                "requirements.md `Covers:` and step coverage disagree"
                + (f"; only in steps: {', '.join(only_in_steps)}" if only_in_steps else "")
                + (f"; only in requirements: {', '.join(only_in_req)}" if only_in_req else "")
            )

    print(f"── coverage audit: {plan_dir} ──")
    print(f"upstream acceptance: {len(upstream_ids)}  covered: {len(covered)}  steps: {len(steps)}")
    for ac in upstream_ids:
        owners = covered.get(ac)
        print(f"[{'OK  ' if owners else 'GAP '}] {ac}: {', '.join(owners) if owners else '(no step)'}")
    for problem in problems:
        print(f"[FAIL] {problem}")
    print(f"\nresult: {'PASS' if not problems else 'FAIL'}")

    metrics.emit(SKILL, "coverage_audit", run=plan_dir, passed=not problems,
                 uncovered=uncovered)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Manage orchestrate-plan run directories and step.json state.

A run directory holds one orchestrated execution of a plan. Every new run gets
its own timestamped directory so runs never overwrite each other.

Usage:
  # Create a fresh, non-colliding run directory (seeds an empty step.json):
  python3 scripts/run_state.py init [--root docs]

  # Summarize every run under the root (progress + next step), newest first:
  python3 scripts/run_state.py list [--root docs]

  # Detailed state of one run (counts + first non-complete step + steps):
  python3 scripts/run_state.py status <run_dir>

  # Transition one step's state (the only sanctioned way to mutate step.json):
  python3 scripts/run_state.py update <step.json> <step> <state>

step.json is a JSON array of {"step": "NN-name", "state": "..."} objects.
Valid states: pending | running | complete | failed.
Legal transitions: pending->running, running->complete, running->failed.
A step may start (->running) only when all earlier steps are complete.
`failed` is terminal (a run that hits it is aborted).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

RUN_PREFIX = "orchestrate-plan-"
VALID_STATES = {"pending", "running", "complete", "failed"}
LEGAL_TRANSITIONS = {
    ("pending", "running"),
    ("running", "complete"),
    ("running", "failed"),
}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def timestamp() -> str:
    # datetime is imported lazily so the module stays importable for a syntax
    # check even in environments where a fixed clock is patched in.
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def load_json(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")

    if not isinstance(data, list):
        fail("step.json must be a JSON array")
    return data


def validate_steps(data: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            fail(f"entry {index} must be an object")
        if "step" not in item or "state" not in item:
            fail(f"entry {index} must contain 'step' and 'state'")
        if not isinstance(item["step"], str) or not item["step"]:
            fail(f"entry {index} step must be a non-empty string")
        if not isinstance(item["state"], str):
            fail(f"entry {index} state must be a string")
        if item["state"] not in VALID_STATES:
            fail(f"entry {index} has invalid state: {item['state']}")
        if item["step"] in seen:
            fail(f"duplicate step name found: {item['step']}")
        seen.add(item["step"])


def atomic_write_json(path: Path, data: list[dict[str, Any]]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    parent = path.parent
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        try:
            if "temp_name" in locals():
                Path(temp_name).unlink(missing_ok=True)
        finally:
            fail(f"cannot write {path}: {exc}")


def counts_of(data: list[dict[str, Any]]) -> dict[str, int]:
    result = {state: 0 for state in sorted(VALID_STATES)}
    for item in data:
        state = item.get("state")
        if state in result:
            result[state] += 1
    return result


def first_incomplete(data: list[dict[str, Any]]) -> dict[str, Any] | None:
    for index, item in enumerate(data):
        if item.get("state") != "complete":
            return {"index": index, "step": item["step"], "state": item["state"]}
    return None


def parse_root(args: list[str]) -> Path:
    root = "docs"
    rest = list(args)
    if "--root" in rest:
        pos = rest.index("--root")
        if pos + 1 >= len(rest):
            fail("--root requires a value")
        root = rest[pos + 1]
    return Path(root)


def cmd_init(args: list[str]) -> None:
    root = parse_root(args)
    root.mkdir(parents=True, exist_ok=True)

    base = root / f"{RUN_PREFIX}{timestamp()}"
    run_dir = base
    suffix = 2
    while True:
        try:
            run_dir.mkdir(exist_ok=False)
            break
        except FileExistsError:
            run_dir = Path(f"{base}-{suffix}")
            suffix += 1
        except OSError as exc:
            fail(f"cannot create run directory {run_dir}: {exc}")

    step_json = run_dir / "step.json"
    atomic_write_json(step_json, [])
    emit({"run_dir": str(run_dir), "step_json": str(step_json)})


def summarize_run(run_dir: Path) -> dict[str, Any]:
    step_json = run_dir / "step.json"
    summary: dict[str, Any] = {"run_dir": str(run_dir)}
    if not step_json.exists():
        summary["error"] = "no step.json"
        return summary
    try:
        data = json.loads(step_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        summary["error"] = f"unreadable step.json: {exc}"
        return summary
    if not isinstance(data, list):
        summary["error"] = "step.json is not an array"
        return summary

    counts = counts_of(data)
    nxt = first_incomplete(data)
    summary.update(
        {
            "total": len(data),
            "pending": counts["pending"],
            "running": counts["running"],
            "complete": counts["complete"],
            "failed": counts["failed"],
            "next_step": nxt["step"] if nxt else None,
            "aborted": counts["failed"] > 0,
            "done": len(data) > 0 and nxt is None,
        }
    )
    return summary


def cmd_list(args: list[str]) -> None:
    root = parse_root(args)
    if not root.exists():
        emit([])
        return
    runs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.startswith(RUN_PREFIX)),
        key=lambda p: p.name,
        reverse=True,
    )
    emit([summarize_run(p) for p in runs])


def cmd_status(args: list[str]) -> None:
    if not args:
        fail("usage: run_state.py status <run_dir>")
    run_dir = Path(args[0])
    step_json = run_dir / "step.json"
    if not step_json.exists():
        fail(f"step.json not found under: {run_dir}")

    data = load_json(step_json)
    validate_steps(data)
    emit(
        {
            "run_dir": str(run_dir),
            "step_json": str(step_json),
            "total": len(data),
            "counts": counts_of(data),
            "next_step": first_incomplete(data),
            "aborted": counts_of(data)["failed"] > 0,
            "steps": data,
        }
    )


def cmd_update(args: list[str]) -> None:
    if len(args) != 3:
        fail("usage: run_state.py update <step.json> <step> <state>")

    step_json = Path(args[0])
    step_name = args[1]
    new_state = args[2]

    if new_state not in VALID_STATES:
        fail(f"state must be one of: {', '.join(sorted(VALID_STATES))}")
    if not step_json.exists():
        fail(f"step.json not found: {step_json}")

    data = load_json(step_json)
    validate_steps(data)

    target_index = None
    for index, item in enumerate(data):
        if item["step"] == step_name:
            target_index = index
            break
    if target_index is None:
        fail(f"step not found: {step_name}")

    target = data[target_index]
    old_state = target["state"]
    if old_state == new_state:
        print(f"unchanged {step_name} -> {new_state}")
        return

    if (old_state, new_state) not in LEGAL_TRANSITIONS:
        fail(f"illegal transition for {step_name}: {old_state} -> {new_state}")

    if new_state == "running":
        incomplete_previous = [
            item["step"]
            for item in data[:target_index]
            if item["state"] != "complete"
        ]
        if incomplete_previous:
            fail(
                "cannot start step before previous steps are complete: "
                + ", ".join(incomplete_previous)
            )

    target["state"] = new_state
    atomic_write_json(step_json, data)
    print(f"updated {step_name}: {old_state} -> {new_state}")


COMMANDS = {
    "init": cmd_init,
    "list": cmd_list,
    "status": cmd_status,
    "update": cmd_update,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        fail(f"usage: run_state.py <{'|'.join(COMMANDS)}> [args]")
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Safely update execute-plan-plus step.json state.

Usage:
  python3 scripts/update_step_state.py <step.json> <step> runing
  python3 scripts/update_step_state.py <step.json> <step> complate

The intentionally misspelled states match the execute-plan-plus contract.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

VALID_STATES = {"pending", "runing", "complate"}
LEGAL_TRANSITIONS = {
    ("pending", "runing"),
    ("runing", "complate"),
}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


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


def main() -> None:
    if len(sys.argv) != 4:
        fail("usage: update_step_state.py <step.json> <step> <state>")

    step_json = Path(sys.argv[1])
    step_name = sys.argv[2]
    new_state = sys.argv[3]

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

    if new_state == "runing":
        incomplete_previous = [
            item["step"]
            for item in data[:target_index]
            if item["state"] != "complate"
        ]
        if incomplete_previous:
            fail(
                "cannot start step before previous steps are complate: "
                + ", ".join(incomplete_previous)
            )

    target["state"] = new_state
    atomic_write_json(step_json, data)
    print(f"updated {step_name}: {old_state} -> {new_state}")


if __name__ == "__main__":
    main()

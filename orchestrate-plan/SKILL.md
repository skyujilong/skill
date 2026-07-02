---
name: orchestrate-plan
description: Orchestrate autonomous execution of an approved plan. The main agent ONLY dispatches — it never writes code or runs verification itself. It first LLM-reviews the plan, then for each step spawns an independent executor sub-agent and a separate independent verifier sub-agent, retries fix+verify up to 3 rounds, and aborts the whole run with a detailed report if any step still fails (the plan is likely flawed). On full success it spawns an overall review sub-agent plus a codebase-graph validation sub-agent. State lives in docs/orchestrate-plan-*/ so runs never overwrite each other and are resumable. Use when the user wants to execute / drive a plan step by step with independent agents, verify each step (typecheck/tests/lint), cap fixes at 3 rounds, stop-and-report when a step can't pass, and finally review + validate against the codebase. Triggers on: execute plan, orchestrate plan, run this plan, dispatch execute, resume docs/orchestrate-plan-*, 执行 plan / 分步执行 / 派发子 agent 执行 / 每步独立验收 typecheck / 修复最多 3 轮 / 失败中止出报告 / 整体 review + 按 codebase 验证 / plan 执行 loop / 编排执行.
---

# Orchestrate Plan

An autonomous orchestration loop for executing an approved plan. The main agent is a **thin dispatcher**: it hands each step to an independent executor sub-agent, hands verification to a separate independent verifier sub-agent, drives a bounded fix/verify loop, and stops with a detailed report the moment the plan proves unworkable. Durable state on disk lets the independent (context-isolated) sub-agents each read exactly what they need, and lets a run resume after any interruption.

This skill owns **execution**. Requirement gathering and plan authoring happen upstream (plan mode / normal chat); the internal plan review (below) is done by an LLM sub-agent, not a human.

## Core rules

- **Rule 1 — the main agent only dispatches.** It plans the run, spawns sub-agents, collects their structured reports, updates state, and writes the final report. It **never edits code and never runs verification commands itself.** Every code change comes from an executor/fixer sub-agent; every pass/fail verdict comes from an independent verifier sub-agent.
- **Autonomy first.** Drive the loop end to end without pausing between steps for confirmation. Do **not** add compaction/checkpoint pauses. The main agent stays small precisely because the heavy work lives in sub-agents — so it can run long without human nodes. Only three human touchpoints exist: (a) plan review returns `fatal`, (b) the final report, (c) an abort report.
- **One call = one run directory.** Always create a fresh `docs/orchestrate-plan-<timestamp>/` via `scripts/run_state.py init`. Never reuse or overwrite an existing run directory. Only resume when the user explicitly asks.
- **Explicit paths always.** Record the chosen `run_dir` up front and pass it (and `step.json`) as an explicit path to every script call. Never rely on an implicit "latest" directory.
- **`step.json` is the single source of truth**, mutated only through `scripts/run_state.py update`.
- **Fixes are capped at 3 rounds per step.** If a step's verification still fails after 3 fix rounds, mark it `failed`, stop dispatching, and write an abort report — the plan (not just the code) is the likely cause.
- Execute steps in dependency/build order; verify each step immediately via its own verifier sub-agent.
- Quality gates are never skipped: per-step independent verification, the relevant `*-engineering` skill inside executor/fixer agents, plus a final overall review and codebase-graph validation.

## Roles (who does what)

| Role | Who | Does |
| --- | --- | --- |
| Orchestrator | main agent | dispatch, collect reports, update `step.json`, write reports. No code, no verification. |
| Plan reviewer | sub-agent | judge the plan's feasibility/coverage before any execution |
| Executor | sub-agent | implement exactly one step's scope; load the matching engineering skill |
| Verifier | sub-agent (separate from executor) | run the step's checks; return pass/fail only, never fix |
| Fixer | sub-agent | fix the smallest cause of a verification failure, in scope |
| Overall reviewer | sub-agent | review the full diff against the plan after all steps pass |
| Codebase validator | sub-agent | validate integration against the real codebase graph |

Spawn sub-agents with the Task/Agent tool (`general-purpose` for execute/fix; `general-purpose` or a review-oriented agent for review/validation). Copy the prompt + required report shape from `references/dispatch-prompts.md`.

## Run directory & state

Each run lives in `docs/orchestrate-plan-yyyy-mm-dd_hh-mm-ss/` (the `orchestrate-plan-` prefix keeps it distinct from `exec-plan-*`):

```text
docs/orchestrate-plan-yyyy-mm-dd_hh-mm-ss/
├── original-plan.md    # the approved plan, verbatim
├── step.json           # ordered progress index (single source of truth)
├── split-audit.md      # coverage map: does the step index cover the whole plan?
├── run-report.md       # plan-review verdict, then final summary or abort report
├── 01-foundation.md    # per-step mini-plan (self-contained for a fresh agent)
├── 02-core.md
└── ...
```

`step.json` is a JSON array of `{ "step": "NN-name", "state": "pending|running|complete|failed" }`.

```bash
python3 scripts/run_state.py init                          # -> {run_dir, step_json}; makes a fresh, non-colliding dir
python3 scripts/run_state.py list                          # summarize all runs (progress + next_step), newest first
python3 scripts/run_state.py status  <run_dir>             # counts + first non-complete step + steps
python3 scripts/run_state.py update  <step.json> <step> running
python3 scripts/run_state.py update  <step.json> <step> complete
python3 scripts/run_state.py update  <step.json> <step> failed
```

Legal transitions: `pending→running` (only when all earlier steps are `complete`), `running→complete` (after the verifier passes), `running→failed` (after 3 failed fix rounds). `failed` is terminal. `init` seeds an empty `step.json`; the main agent then writes the ordered index into it, and only `update` mutates state afterward.

## Mini-plan format

Each step's mini-plan must be **self-contained** — a fresh sub-agent with no shared context reads only this file plus `original-plan.md`.

```markdown
# NN-step-name

## Goal
what this step must achieve

## Depends on
- previous completed steps / files it builds on

## Do
1. concrete, in-scope actions

## Verify
1. command / observable check (typecheck, tests, lint, build)
2. at least one check tied specifically to this step

## Notes
- append: files changed, each fix round's attempt + verifier output, attempt=N/3
```

## Workflow (four phases)

### Phase 1 — Intake & step index (main agent, inline)

1. `run_state.py init` → record `run_dir`. Save the approved plan verbatim to `original-plan.md`.
2. Write the ordered `step.json` (all steps `pending`) in build order: discovery/constraints → tooling/config/deps → schemas/types/contracts → infrastructure/adapters → core logic → API/boundaries → UI → tests/docs → final integration.
3. Write `split-audit.md` comparing the plan to the step index; fix `step.json` before executing if anything is missing, duplicated, or misordered.
4. Expand the mini-plan for the first step (expand each step's mini-plan just before dispatch, or a small look-ahead window).

### Phase 2 — Automatic plan review (LLM self-review, quality gate before execution)

Dispatch a **plan-review sub-agent** over `original-plan.md` + `step.json` + `split-audit.md`. It judges correctness, technical feasibility, internal consistency, requirement coverage, and whether the decomposition/ordering is sound. It returns `{ verdict: ok|minor|fatal, findings[], suggested_fixes[] }`.

- `ok` / `minor` → record the verdict in `run-report.md` and **continue automatically** (apply obvious minor fixes to the affected mini-plans/`step.json` first).
- `fatal` (the approach can't work as written) → **stop and escalate to the user** with the findings. Do not burn execution on a doomed plan. This is the point of catching "the plan is wrong" *before* the work, not after 3 failed rounds.

### Phase 3 — Execution loop (per pending step, in order, fully autonomous)

For each step:

1. Ensure the mini-plan exists (expand it from `original-plan.md` + `split-audit.md` if missing).
2. `run_state.py update <step.json> <step> running`.
3. **Dispatch an executor sub-agent** (mini-plan path + `original-plan.md` path + relevant files). It implements only this step's scope, loads the matching `*-engineering` skill by file type, and reports `{ files_changed, summary, deviations }`.
4. **Dispatch a verifier sub-agent** (independent). It runs the step's `## Verify` checks and reports `{ pass: bool, checks[], failures[] }`. The verifier never fixes.
5. If `pass` → append notes, `run_state.py update <step> complete`, brief report, next step.
6. If not → run the **fix/verify loop** (max 3 rounds): dispatch a fixer sub-agent with the verifier's failure output → dispatch the verifier again → repeat. Append each round's attempt + verifier output to the mini-plan `## Notes` as `attempt=N/3`.
7. If still failing after round 3 → `run_state.py update <step> failed`, **stop the whole run**, go to Abort report.

### Phase 4 — Final review & codebase validation (only if every step is `complete`)

1. **Dispatch an overall review sub-agent** over the full diff vs `original-plan.md`: correctness, completeness, cross-step integration, engineering-standard adherence (may use `adversarial-reviewer` / `code-reviewer`).
2. **Dispatch a codebase-validation sub-agent** using the codebase-memory graph tools (`trace_path`, `search_graph`, `search_code`, `get_code_snippet`, `get_architecture`) or the `codebase-memory` skill: confirm the new code is wired into the real codebase — callers connected, contracts consistent, no dead code, matches existing architecture.
3. Consolidate both into `run-report.md` and present it. Surface any findings; whether to feed them back as new steps is the user's call.

## Abort report

When a step hits `failed`, write `run-report.md` and stop all further dispatch. Include: which step, its goal, what each of the 3 fix rounds attempted, the exact verifier errors per round, the main agent's hypothesis for **why the plan (not just the code) is likely at fault**, and concrete recommended plan revisions. Present it to the user.

## Resume flow

Default: a new invocation is a **new run**. Only resume when the user explicitly says to continue an existing `docs/orchestrate-plan-*`.

1. `run_state.py list` → show unfinished runs; let the user pick, or use the `run_dir` they name. Do **not** `init` a new directory.
2. Read in order: `original-plan.md` → `run-report.md` → `split-audit.md` → `step.json` → the first non-`complete` step's mini-plan.
3. First non-`complete` step is:
   - `pending` → dispatch it normally.
   - `running` (interrupted mid-step) → read `## Notes` for the used `attempt=N/3`, dispatch a verifier first to learn the current real state, then continue the fix loop from that attempt count. **Do not reset the 3-round budget.**
   - `failed` → the run is already aborted; present the historical abort report and stop, unless the user explicitly asks to redo it.

## Keep it thin

The orchestrator's context should hold only mini-plan summaries and the sub-agents' structured reports — that is what lets it run autonomously without compaction pauses. Push all reading, writing, and verifying into sub-agents. Do not restate this skill's rules into every dispatch; point sub-agents at their mini-plan and the templates in `references/dispatch-prompts.md`.

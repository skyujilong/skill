---
name: execute-plan-plus
description: Use this skill when the user wants to execute a large/long implementation plan, split a plan into resumable chunks, avoid context loss, continue from docs/exec-plan-* state, or checkpoint with /compact. Keep it lightweight: persist the original plan, create an ordered step index, audit coverage, expand only the next small batch of steps, verify every step immediately, update step.json only via script, and pause after each 3-step checkpoint.
---

# Execute Plan Plus

A lightweight resumable execution workflow for large plans. The skill's job is not to create a huge planning document; it is to leave just enough durable state on disk that work can continue safely after `/compact`.

## When to use this skill

Use this workflow only when at least one condition applies:

- Estimated work touches more than ~3 files or crosses several layers.
- The task is expected to span multiple sessions or a `/compact`.
- The task would take more than ~30 minutes of agent work.
- The user explicitly asks to plan, split, resume, or checkpoint the work.
- A significant architecture or technology decision is required.

For small, single-shot tasks (a one-line fix, a single function, a localized
change), do not create `docs/exec-plan-*` — just do the work. This protocol pays
for itself only when durable state prevents real context loss.

## Core rules

- Store execution state in `docs/exec-plan-yyyy-mm-dd_hh-mm-ss/`.
- Save the original user plan verbatim as `original-plan.md` before rewriting or summarizing it.
- Keep `step.json` as the progress source of truth: an array of `{ "step": "NN-name", "state": "pending|runing|complate" }`.
- Preserve the requested state spellings: `runing` and `complate`.
- A step is an execution unit, not a business module: it must fit in one agent
  context window and be independently verifiable. Prefer fine-grained steps
  (`03-create-user-domain`) over coarse ones (`03-core`).
- Extract a structured requirement tree into `requirements.md` and log
  significant technical decisions in `decisions.md` (append-only).
- After creating the step index, audit it against `original-plan.md` and `requirements.md` before implementation.
- Expand detailed mini-plan files only for the current 3-step window unless the user asks for a full expansion.
- Execute steps in dependency/build order.
- Verify the current step immediately after implementing it; do not defer verification to a final step.
- Update `step.json` only with `scripts/update_step_state.py`.
- After every 3 completed steps, persist notes and ask the user to run `/compact`.

## Minimal folder layout

```text
docs/exec-plan-yyyy-mm-dd_hh-mm-ss/
├── original-plan.md          # verbatim source of truth
├── requirements.md           # extracted requirement tree (audit basis)
├── decisions.md              # append-only decision log (ADR-lite)
├── README.md                 # short resume guide + next step
├── split-audit.md            # concise coverage map and audit fixes
├── checkpoint.json           # last checkpoint + git/verification anchor
├── step.json                 # progress index
├── 01-foundation.md          # detailed only for current/near window
├── 02-contracts.md
└── 03-core.md
```

Keep artifacts concise. Prefer short tables and bullet lists over repeated boilerplate.

## Initial setup

1. Create the timestamped execution folder.
2. Write `original-plan.md` with the user's large plan verbatim — exactly enough to re-audit after compaction.
3. Extract the structured requirement tree from `original-plan.md` into `requirements.md` (see Requirements format). This is the audit's structured basis; do not rely on raw wording alone.
4. Create an ordered `step.json` for all expected steps using build order:
   1. discovery/constraints
   2. tooling/config/dependencies
   3. schemas/types/migrations/contracts
   4. adapters/infrastructure/clients
   5. core services/domain logic
   6. API/controllers/integration boundaries
   7. UI/user workflows
   8. tests/docs/cleanup
   9. final integration verification
5. Write `split-audit.md` by comparing `requirements.md` and `original-plan.md` to `step.json`.
6. If the audit finds missing, duplicated, ambiguous, or badly ordered work, fix `step.json` and the affected step names before execution.
7. Expand detailed mini-plan markdown only for the next 3 pending steps.

## Requirements format

`requirements.md` is the structured extraction of the user's intent. Keep it a
flat numbered list, not a nested essay:

```markdown
# Requirements

## R1 User login
- Intent: users can sign in with email + password
- Acceptance: wrong password is rejected with a clear error

## R2 JWT session
- Intent: sessions survive page reloads
- Acceptance: token validated on each protected request
```

One requirement may map to several steps (record the mapping in
`split-audit.md`). Update it when execution reveals a requirement change.

## Decisions log

Record "why" so a compacted model never has to re-derive it. Append-only; never
rewrite history.

```markdown
# Decisions

## 2026-08-04 14:30 — Use PostgreSQL over MongoDB
- Decision: PostgreSQL for the payment module
- Reason: transaction consistency across multi-step writes
- Impact: payment domain steps depend on this; migration step must use pg
```

Log: technology choices, contract changes, deviations from the original plan,
and rollback decisions. Reference a decision from a mini-plan `## Notes` when it
matters downstream.

## Split audit format

Use a compact audit; do not rewrite the whole original plan.

```markdown
# Split audit

## Coverage map
| Original requirement | Step(s) | Status |
| --- | --- | --- |
| ... | 02-contracts, 05-service | covered |

## Fixes made during audit
- Added/moved/split: ...

## Result
No known omissions. Step order follows build dependencies.
```

If mini-plan boundaries change later, append an `## Audit amendment yyyy-mm-dd hh:mm` section explaining what moved and why.

The audit maps `requirements.md` items to steps; if you adjust a requirement
during execution, update `requirements.md` and append an audit amendment.

## Mini-plan format

Use this slim format for each expanded step:

```markdown
# NN-step-name

## Goal
...

## Depends on
- previous completed steps or files

## Do
1. ...
2. ...

## Verify
Run immediately after this step:
1. command or observable check
2. command or observable check

## Notes
- append execution result, verification result, blockers, or audit amendments
- keep a standard artifact summary so resume does not rescan git:
  - Files changed: `src/auth/service.ts`, `src/auth/schema.ts`
  - Tests: `pytest tests/auth`
  - Commit: `a81f92d`
  - Failures: 0 (increment per failed verification; >= 3 means block the step)
```

Verification should include at least one check tied to the current step when possible. A broad build/typecheck can be included, but it should not be the only verification if a narrower check exists.

## Updating step.json

Do not manually edit state after initial creation. Run the bundled script from the skill directory or with its actual installed path:

```bash
python3 scripts/update_step_state.py docs/exec-plan-yyyy-mm-dd_hh-mm-ss/step.json NN-step-name runing
python3 scripts/update_step_state.py docs/exec-plan-yyyy-mm-dd_hh-mm-ss/step.json NN-step-name complate
```

The script validates JSON shape, legal states, legal transitions, previous-step order, and writes atomically.

If a real dependency reordering makes the legal transition impossible (e.g. a
UI mock must precede its API), use the script's override mode — never hand-edit:

```bash
python3 scripts/update_step_state.py docs/.../step.json 07-ui runing --force --reason "UI mock needed before API: dependency discovered during 05-service"
```

`--force` requires a non-empty `--reason`, which is recorded on the step entry as
`override_reason` so the deviation stays visible in durable state. Use it only
for genuine dependency/order changes, and mention it in `decisions.md` when it
changes the plan's shape.

Blocked steps keep their legal `state` (`runing`) and record failure via the
script — never hand-edit:

```bash
python3 scripts/update_step_state.py docs/.../step.json 05-payment block --reason "3 consecutive verification failures: <root cause>"
python3 scripts/update_step_state.py docs/.../step.json 05-payment unblock
```

`block` requires a non-empty `--reason` and sets `blocked: true` +
`block_reason` without touching `state`. `unblock` clears those fields — only
after the user decides how to proceed.

Legal transitions:
- `pending -> runing`: allowed only when all earlier steps are `complate`.
- `runing -> complate`: allowed after current-step verification passes.
- Other transitions are rejected unless the user explicitly asks for manual recovery; in that case inspect files first and edit with care.

## Execution loop

For each step:

1. Ensure its detailed mini-plan exists; if not, expand it from `original-plan.md`, `split-audit.md`, and `step.json`.
2. Run `update_step_state.py ... <step> runing`.
3. Implement only this step's scope.
4. Run this step's `## Verify` checks immediately.
5. If verification fails, fix the smallest cause in this step's scope and rerun verification. Count consecutive failures in the mini-plan `## Notes`.
6. Append concise notes to the mini-plan: changed files, verification command/result, blockers/deviations.
7. Run `update_step_state.py ... <step> complate` only after verification passes.
8. Report briefly: step, files changed, verification result, next step.

## Failure policy

- Track consecutive failures in the step's `## Notes` (`Failures: N`, increment
  on each failed verification).
- After 3 consecutive failures on the same step, stop patching and mark it
  structurally blocked via the script (never hand-edit):

  ```bash
  python3 scripts/update_step_state.py docs/.../step.json 05-payment block --reason "3 consecutive verification failures: <root cause>"
  ```

  `state` stays `runing`; `blocked: true` + `block_reason` make the failure
  machine-readable on resume.
- Write root cause and attempted fixes in the mini-plan `## Notes`.
- Update `README.md` to state that the plan is waiting on a human decision.
- Ask the user to decide: roll back, re-scope, or apply a manual fix; then
  `unblock` (or adjust the plan) before continuing.
- Downstream steps stay unstarted (the script's previous-step check enforces this).

## Three-step window and compact checkpoint

After steps 3, 6, 9, etc. are `complate`:

1. Ensure completed mini-plans have notes and verification results.
2. Update `README.md` with the next pending step and resume command.
3. Update `checkpoint.json` with the current git anchor and last verification, for example:

```json
{
  "last_compact_after_step": "03-create-user-domain",
  "next_step": "04-create-auth-service",
  "git_commit": "a81f92d",
  "branch": "feature/auth",
  "verification": {
    "command": "pytest tests/test_user_domain.py",
    "result": "pass"
  }
}
```

`git_commit`/`branch` are the recovery anchor: capture
`git rev-parse --short HEAD` at checkpoint time (omit both fields in a non-git
repo). `verification` records the last completed step's check so resume can
confirm the code is at that state.

4. If the next 3-step window has not been expanded yet, expand those mini-plan files before asking for compact, so resume has enough local context.
5. Tell the user:

```text
Compact checkpoint reached after 3 completed steps. Please run /compact, then ask me to continue execute-plan-plus from docs/exec-plan-yyyy-mm-dd_hh-mm-ss. Next step: NN-step-name.
```

Do not repeatedly ask for compact for the same checkpoint. Use `checkpoint.json` to see the last checkpoint already announced.

## Resume flow

When continuing an existing execution folder, read these files first:

1. `original-plan.md`
2. `requirements.md`
3. `decisions.md` if present
4. `README.md`
5. `split-audit.md`
6. `checkpoint.json` if present
7. `step.json`
8. the first non-`complate` mini-plan file

If the first non-`complate` step is `pending`, start it normally. If it is
`runing`, check its `step.json` entry for `blocked: true` (and the `## Notes`
marker): if blocked, resume only per the user's decision — read `block_reason`
and the notes first. Otherwise inspect the notes, verification output, and
repository diff before deciding whether to continue implementation, repair
verification, or ask the user.

## Keep it small

This is a mini superpower, not a full project-management system. Avoid verbose plans, duplicated repair policies, and large generated tables. The durable essentials are:

- original plan + extracted requirements
- ordered step index + decision log
- concise split audit
- current 3 detailed mini-plans
- per-step verification notes and failure state
- checkpoint metadata with git/verification anchor

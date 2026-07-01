---
name: execute-plan-plus
description: Use this skill when the user wants to execute a large/long implementation plan, split a plan into resumable chunks, avoid context loss, continue from docs/exec-plan-* state, or checkpoint with /compact. Keep it lightweight: persist the original plan, create an ordered step index, audit coverage, expand only the next small batch of steps, verify every step immediately, update step.json only via script, and pause after each 3-step checkpoint.
---

# Execute Plan Plus

A lightweight resumable execution workflow for large plans. The skill's job is not to create a huge planning document; it is to leave just enough durable state on disk that work can continue safely after `/compact`.

## Core rules

- Store execution state in `docs/exec-plan-yyyy-mm-dd_hh-mm-ss/`.
- Save the original user plan verbatim as `original-plan.md` before rewriting or summarizing it.
- Keep `step.json` as the progress source of truth: an array of `{ "step": "NN-name", "state": "pending|runing|complate" }`.
- Preserve the requested state spellings: `runing` and `complate`.
- After creating the step index, audit it against `original-plan.md` before implementation.
- Expand detailed mini-plan files only for the current 3-step window unless the user asks for a full expansion.
- Execute steps in dependency/build order.
- Verify the current step immediately after implementing it; do not defer verification to a final step.
- Update `step.json` only with `scripts/update_step_state.py`.
- After every 3 completed steps, persist notes and ask the user to run `/compact`.

## Minimal folder layout

```text
docs/exec-plan-yyyy-mm-dd_hh-mm-ss/
├── original-plan.md          # verbatim source of truth
├── README.md                 # short resume guide + next step
├── split-audit.md            # concise coverage map and audit fixes
├── checkpoint.json           # last compact checkpoint metadata
├── step.json                 # progress index
├── 01-foundation.md          # detailed only for current/near window
├── 02-contracts.md
└── 03-core.md
```

Keep artifacts concise. Prefer short tables and bullet lists over repeated boilerplate.

## Initial setup

1. Create the timestamped execution folder.
2. Write `original-plan.md` with the user's large plan exactly enough to re-audit after compaction.
3. Create an ordered `step.json` for all expected steps using build order:
   1. discovery/constraints
   2. tooling/config/dependencies
   3. schemas/types/migrations/contracts
   4. adapters/infrastructure/clients
   5. core services/domain logic
   6. API/controllers/integration boundaries
   7. UI/user workflows
   8. tests/docs/cleanup
   9. final integration verification
4. Write `split-audit.md` by comparing `original-plan.md` to `step.json`.
5. If the audit finds missing, duplicated, ambiguous, or badly ordered work, fix `step.json` and the affected step names before execution.
6. Expand detailed mini-plan markdown only for the next 3 pending steps.

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
```

Verification should include at least one check tied to the current step when possible. A broad build/typecheck can be included, but it should not be the only verification if a narrower check exists.

## Updating step.json

Do not manually edit state after initial creation. Run the bundled script from the skill directory or with its actual installed path:

```bash
python3 scripts/update_step_state.py docs/exec-plan-yyyy-mm-dd_hh-mm-ss/step.json NN-step-name runing
python3 scripts/update_step_state.py docs/exec-plan-yyyy-mm-dd_hh-mm-ss/step.json NN-step-name complate
```

The script validates JSON shape, legal states, legal transitions, previous-step order, and writes atomically.

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
5. If verification fails, fix the smallest cause in this step's scope and rerun verification.
6. Append concise notes to the mini-plan: changed files, verification command/result, blockers/deviations.
7. Run `update_step_state.py ... <step> complate` only after verification passes.
8. Report briefly: step, files changed, verification result, next step.

If a step is blocked or verification keeps failing, leave it `runing`, write the blocker/failure in that step's `## Notes`, and ask for guidance.

## Three-step window and compact checkpoint

After steps 3, 6, 9, etc. are `complate`:

1. Ensure completed mini-plans have notes and verification results.
2. Update `README.md` with the next pending step and resume command.
3. Update `checkpoint.json`, for example:

```json
{
  "last_compact_after_step": "03-core",
  "next_step": "04-api"
}
```

4. If the next 3-step window has not been expanded yet, expand those mini-plan files before asking for compact, so resume has enough local context.
5. Tell the user:

```text
Compact checkpoint reached after 3 completed steps. Please run /compact, then ask me to continue execute-plan-plus from docs/exec-plan-yyyy-mm-dd_hh-mm-ss. Next step: NN-step-name.
```

Do not repeatedly ask for compact for the same checkpoint. Use `checkpoint.json` to see the last checkpoint already announced.

## Resume flow

When continuing an existing execution folder, read these files first:

1. `original-plan.md`
2. `README.md`
3. `split-audit.md`
4. `checkpoint.json` if present
5. `step.json`
6. the first non-`complate` mini-plan file

If the first non-`complate` step is `pending`, start it normally. If it is `runing`, inspect its mini-plan `## Notes`, verification output if available, and repository diff before deciding whether to continue implementation, repair verification, or ask the user.

## Keep it small

This is a mini superpower, not a full project-management system. Avoid verbose plans, duplicated repair policies, and large generated tables. The durable essentials are:

- original plan
- ordered step index
- concise split audit
- current 3 detailed mini-plans
- per-step verification notes
- checkpoint metadata

# Checkpoint, /compact, resume, failure policy

Read this after every 3rd completed step, when resuming an existing plan folder, and when a
step has failed verification 3 times.

## Three-step window and /compact

After steps 3, 6, 9, ... are `complate`:

1. Ensure completed mini-plans have notes and verification results.
2. Update `README.md` with the next pending step and resume command.
3. Update `checkpoint.json`:

```json
{
  "last_compact_after_step": "03-create-user-domain",
  "next_step": "04-create-auth-service",
  "git_commit": "a81f92d",
  "branch": "feature/auth",
  "verification": { "command": "pytest tests/test_user_domain.py", "result": "pass" }
}
```

`git_commit`/`branch` are the recovery anchor: capture `git rev-parse --short HEAD` at
checkpoint time (omit both in a non-git repo). `verification` records the last completed step's
check.

4. Expand the next 3-step window's mini-plans before asking for compact.
5. Tell the user:

```text
Compact checkpoint reached after 3 completed steps. Please run /compact, then ask me to continue
execute-plan-plus-v2 from docs/exec-plan-<yyyy-mm-dd>-<slug>. Next step: NN-step-name.
```

Do not ask for compact repeatedly for the same checkpoint; `checkpoint.json` records the last.

## Resume

Read in order: `upstream.json` (+ the `handoff.json` it points to), `original-plan.md`,
`requirements.md`, `decisions.md`, `README.md`, `split-audit.md`, `checkpoint.json`,
`step.json`, the first non-`complate` mini-plan. Do not read `docs/.skill-metrics/runs.jsonl`.

**Anchor comparison**: compare the recorded `git_commit`/`branch` and current diff with
reality. If code or dependencies changed since the recorded verification, identify affected
steps and re-run their checks and review; a saved `complate` is not proof that today's code
still passes. Re-run `close-ac --run-cmd` for affected ACs (rev freshness).

First non-`complate` step: `pending` -> start normally. `runing` -> if `blocked: true`, resume
only per the user's decision after reading `block_reason` and the notes; otherwise inspect
notes, verification output and repository diff, then continue, repair verification, or ask.

## Failure policy and block

- Track consecutive failures in the step's `## Notes` (`Failures: N`).
- After 3 consecutive failures on the same step, stop patching and block it. `block` needs an
  explicit stance on the lesson:

```bash
# root cause belongs to an upstream boundary: record it there first
python3 <req-align-v2>/scripts/boundary_state.py pitfall-add --boundary BND-3 \
    --phenomenon "..." --root-cause "..." --guard "..."
python3 scripts/update_step_state.py docs/.../step.json 05-payment block \
    --reason "3 consecutive verification failures: <root cause>" --pitfall PIT-4
# or, if genuinely not worth recording
python3 scripts/update_step_state.py docs/.../step.json 05-payment block \
    --reason "..." --no-pitfall "one-off local env issue"
```

`block` is allowed on `pending` or `runing` steps and the state is unchanged; `blocked: true` + `block_reason` make it machine-readable. A blocked
step rejects `runing`/`complate` (even `--force`) until `unblock`. Write root cause and
attempted fixes in the notes, update `README.md` to say the plan waits on a human decision,
and ask the user to choose rollback / re-scope / manual fix before running:

```bash
python3 scripts/update_step_state.py docs/.../step.json 05-payment unblock
```

Downstream steps stay unstarted.

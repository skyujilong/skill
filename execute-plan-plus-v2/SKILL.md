---
name: execute-plan-plus-v2
description: Use this skill when the user wants to execute a large/long implementation plan, split a plan into resumable chunks, avoid context loss, continue from docs/exec-plan-* state, or checkpoint with /compact. It ingests an upstream req-align-v2 handoff.json when one exists (writing upstream.json so the link survives /compact), traces every step to stable acceptance ids via step.json `covers`, closes upstream ACs incrementally with executable evidence (close-ac --run-cmd) bound to the code version, records independent review in reviews.json, and ends with one final_gate.py command (steps, coverage, strict-closure incl. fresh evidence + final review, history-sync). Without an upstream it runs in generic mode. Keep it lightweight - persist the original plan, create an ordered step index, audit AC coverage, expand only the next small batch of steps, verify each step immediately, update step.json only via script, pause after each 3-step checkpoint.
---

# Execute Plan Plus v2

A lightweight resumable execution workflow for large plans: leave just enough durable state on
disk that work continues safely after `/compact`. Scripts live in `scripts/` of this skill;
`<req-align-v2>` means the sibling req-align-v2 skill directory.

## When to use

Only when at least one applies: work touches more than ~3 files or several layers; it spans
sessions or a `/compact`; it takes more than ~30 minutes of agent work; the user asks to plan,
split, resume or checkpoint; a significant architecture/technology decision is needed.
Small single-shot tasks: do not create `docs/exec-plan-*`, just do the work.

## Core rules

- State lives in `docs/exec-plan-<yyyy-mm-dd>-<slug>/`. The slug **must** be the upstream
  `handoff.json` slug (exact `exec-plan-<date>-<slug>`; `update_step_state.py` rejects any other
  name). No upstream: derive the slug from the task; name taken -> `-2`, `-3`.
- Save the original user plan verbatim as `original-plan.md` before rewriting anything.
- `step.json` is the progress source of truth: `{ "step": "NN-name", "state":
  "pending|runing|complate", "covers": ["AC-1"] }`. Keep the spellings `runing` / `complate`.
- A step is an execution unit that fits one context window and is independently verifiable
  (`03-create-user-domain`, not `03-core`). Expand mini-plans only for the current 3-step window.
- `covers` means this step **suffices to prove** the whole AC through its final functional
  path. Preparatory steps use `covers: []` and `--covers-none --reason "AC-N proven by NN-step"`.
  Never close a cross-layer AC from a single-layer unit test.
- Verify immediately after implementing; never defer. Before writing any `## Verify` block or
  closing an AC, read `references/verification.md`.
- Change `step.json` only through `scripts/update_step_state.py`.
- After every 3 completed steps, persist notes and ask the user to run `/compact`.

## Folder layout

`upstream.json` (absent = generic mode), `original-plan.md`, `requirements.md` (R-groups, each
with `Covers: AC-N`), `decisions.md` (append-only), `README.md` (resume guide), `split-audit.md`
(AC -> step map), `checkpoint.json`, `step.json`, `NN-name.md` mini-plans (current window only).

## Step 0 - upstream ingest

1. Look for `docs/req-align-*/handoff.json`. Several -> ask the user which; none -> **generic
   mode**: skip Step 0 and every upstream check below.
2. The handoff is the machine contract (slug, `next_stage`, `stages`, `acceptance[AC-N]`,
   `risks[RISK-N]`, `source_sha256`). Never re-derive from prose; **never renumber** ids.
   On linked transitions the script requires: `contract_version` `"1"`; handoff slug equal to
   `upstream.json` slug; `source_sha256` matching the raw bytes of `align.md`, `arch-risk.md`,
   `acceptance.md` (legacy handoff without it, or an unsynced edit, blocks - run `sync`; if a
   closed AC's text/priority changed, `fail-ac` first); the `next_stage` (sdd /
   arch-discovery) registered via `stage-add` with its required files still present; and no
   risk `待验证`. Registration proves files exist, **not** that conclusions are sound: read and
   challenge the acceptance matrix / architecture decisions before implementing against them.
3. Create the plan folder and write `upstream.json` (this is what survives `/compact`):

```json
{ "source": "req-align-v2", "contract_version": "1",
  "run_dir": "../req-align-2026-09-02-global-service-catalog", "slug": "global-service-catalog" }
```

## Initial setup

1. Write `original-plan.md` verbatim.
2. Write `requirements.md`; every R declares the upstream ids it serves:
   `## R1 Global service catalog` / `- Intent: ...` / `- Covers: AC-1, AC-3`.
3. Create ordered `step.json` (build/dependency order) with `covers` per entry, e.g.
   `{ "step": "05-service-and-api-check", "state": "pending", "covers": ["AC-1"] }`. Do not
   invent partial acceptance to fill `covers`; a `covers: []` step is an explicit non-closure.
4. Write `split-audit.md`: table `| AC | R | Final proving step | Preparatory steps | Status |`
   plus a "Fixes made during audit" list.
5. Run the coverage gate **before implementing anything** and fix until it passes:

```bash
python3 scripts/audit_coverage.py docs/exec-plan-<yyyy-mm-dd>-<slug>/
```

It fails on: upstream with no AC at all; an upstream AC covered by no step; a `covers` id
unknown upstream; `requirements.md` missing, lacking `Covers:`, referencing unknown ids, or
disagreeing with the union of `step.json` `covers`; handoff `contract_version`/slug mismatch.
Generic mode prints "skipped" - no upstream is not evidence of coverage; record a small
observable checklist in the mini-plans and use project gates.

6. Expand mini-plans for the next 3 pending steps only.

## Decisions log

Append-only (`decisions.md`): technology choices, contract changes, deviations, rollbacks. A
decision that resolves an upstream `RISK-N` **must also be written upstream**:

```bash
python3 <req-align-v2>/scripts/align_state.py resolve-risk <run_dir> RISK-3 \
    --decision "..." --reason "..." --impact "..." [--confirmed-by human|agent]
```

## Mini-plan format

```markdown
# NN-step-name
## Goal
## Depends on
## Do
## Verify
Run immediately after this step: 1. narrow automated test with expected result/exit status
2. if this step owns a user-visible AC: real path incl. failure/boundary case
- Covers: AC-1 -> <observable check proving the entire AC, not a layer>
## Notes
- Files changed / Tests / Commit / Failures: N   (>= 3 -> block the step)
```

## Execution loop

For each step:

1. Ensure its mini-plan exists (expand from `original-plan.md`, `split-audit.md`, `step.json`,
   `handoff.json`).
2. `python3 scripts/update_step_state.py <plan>/step.json <step> runing`
3. Implement only this step's scope.
4. Run its `## Verify` checks now. On failure fix the smallest cause and rerun; count
   consecutive failures in Notes (3 -> read `references/resume-and-checkpoint.md`, then `block`).
5. Append notes (changed files, command/result, blockers). If requirements, scope, external API
   behavior or an upstream AC changed, **stop and follow the invalidation procedure in
   `references/verification.md`** (re-audit, re-verify affected steps; closed AC needs `fail-ac`
   before `sync`).
6. Close the upstream ACs this step covers - prefer script-run evidence:

```bash
python3 <req-align-v2>/scripts/align_state.py close-ac <run_dir> AC-1 \
    --run-cmd "pytest tests/test_catalog.py -q" [--cwd DIR] [--timeout SEC] --step <step>
# human-observed path instead:  --manual --observer NAME --evidence "what was seen"
```

   Plain `--evidence` is legacy self-report, fine only for P1/P2. Re-running `--run-cmd` on a
   closed AC refreshes its evidence (latest wins). Details: `references/verification.md`.
7. At a review trigger (milestone, 45-minute backstop, final), read `references/review.md`
   first, get an independent reviewer, then `align_state.py record-review ...`.
8. `python3 scripts/update_step_state.py <plan>/step.json <step> complate`
9. Report briefly: step, files changed, verification result, next step.

## Updating step.json

Never hand-edit after creation. Commands (`<sj>` = `docs/exec-plan-<date>-<slug>/step.json`):

```bash
python3 scripts/update_step_state.py <sj> NN-step runing
python3 scripts/update_step_state.py <sj> NN-step complate
python3 scripts/update_step_state.py <sj> NN-step runing --force --reason "..."        # reorder
python3 scripts/update_step_state.py <sj> NN-step complate --covers-none --reason "..." # no AC
python3 scripts/update_step_state.py <sj> NN-step block --reason "..." (--pitfall PIT-N | --no-pitfall "...")
python3 scripts/update_step_state.py <sj> NN-step unblock
```

Legal transitions: `pending -> runing` (all earlier steps `complate`); `runing -> complate`
(covered ACs closed). Everything else is rejected. `--force` (needs `--reason`) is **only**
`pending -> runing` reordering; it cannot complete a step or skip upstream readiness checks.
`--covers-none` needs a non-empty `--reason` and is only for steps with empty `covers`. A
blocked step accepts nothing but `unblock`. A reason records why, not that anything passed.

## Hard gates (what blocks what)

| Gate | Script | Blocks | Fix |
| --- | --- | --- | --- |
| Folder name carries upstream slug | `update_step_state.py` | every transition | rename to `exec-plan-<date>-<slug>` |
| Contract fresh / version / slug / stage registered / no `待验证` risk | `update_step_state.py` | `runing`, `complate` (also `--force`) | `align_state.py sync`, `stage-add`, `resolve-risk` |
| Step order | `update_step_state.py` | `runing` with earlier step unfinished | finish earlier steps or `--force --reason` |
| Covered AC closed in handoff **and** `acceptance.md` shows ticked box + non-empty evidence | `update_step_state.py` | `complate` | `align_state.py close-ac` (not hand edits) |
| Step with empty `covers` | `update_step_state.py` | `complate` | list AC ids or `--covers-none --reason` |
| Blocked step | `update_step_state.py` | `runing`/`complate`/`--force` | user decision, then `unblock` |
| Closed-AC drift / unticked without 未通过记录 / missing handoff with ticks | `align_state.py` writes + `sync` | close-ac, fail-ac, resolve-risk, stage-add, sync | `fail-ac` first, then edit, then `sync`; restore handoff.json |
| AC coverage | `audit_coverage.py` | final gate (run it before coding) | fix `covers` / `requirements.md` `Covers:` |
| Evidence verified + fresh, final review | `check_alignment.py --strict-closure` | final gate | `close-ac --run-cmd`, `record-review --scope final` |
| Final gate | `final_gate.py` | plan completion | see below |

Write commands in `align_state.py` roll back their Markdown edit if rebuilding `handoff.json`
fails.

## Final gate

```bash
python3 scripts/final_gate.py docs/exec-plan-<yyyy-mm-dd>-<slug>/ --req-align-scripts <req-align-v2>/scripts
```

It checks, one PASS/FAIL line each: every step `complate`; `audit_coverage.py`;
`check_alignment.py --strict-closure` (all ACs ticked with evidence, no `待验证` risk, P0
evidence script-verified and fresh against the current code fingerprint, latest `reviews.json`
entry an approved `final` for the current fingerprint); `boundary_state.py history-sync`.
`--req-align-scripts` is required when `upstream.json` exists; without upstream it is generic
mode and only the steps gate runs. Fingerprint = HEAD + modified/untracked non-ignored files
excluding only the TOP-LEVEL `docs/` and the req-align run dir; without git the freshness
comparisons only WARN. Keep the req-align and exec-plan folders under the repo's top-level
`docs/` (the run dir must be a sibling of the plan dir), and install the skills outside the repo
or gitignore `__pycache__`, otherwise generated files change the fingerprint.

**Also run yourself** (the gate does not): the project's lint/typecheck, relevant
regression/integration/contract suites on the final code, and the real user path for
user-visible ACs; record command, exit status and revision. If any gate fails, a required check
cannot run, or independent review is pending (`待审核`), report **not complete** and name the
gap.

### What the scripts cannot prove

`--run-cmd true` passes; reviewer identity is a recorded name, not authenticated; `reviews.json`
and `acceptance.md` can be hand-edited; independence rests on a separate human or fresh
subagent; there is no mutation-testing engine; evals have no runner; generic mode only gets the
documented process plus the gate's step check.

## Resume and checkpoint

After steps 3, 6, 9...: update notes, `README.md`, `checkpoint.json`, expand the next window,
ask for `/compact`. When continuing an existing folder: read `upstream.json` + handoff, then
`original-plan.md`, `requirements.md`, `decisions.md`, `README.md`, `split-audit.md`,
`checkpoint.json`, `step.json`, the first non-`complate` mini-plan; never read
`docs/.skill-metrics/runs.jsonl`. Before either, read `references/resume-and-checkpoint.md`
(checkpoint format, anchor comparison, blocked-step handling).

## Keep it small

Durable essentials: original plan, `requirements.md` with `Covers:`, `step.json` with `covers`,
decision log, coverage audit, current 3 mini-plans, per-step verification notes and failure
state, checkpoint anchor, `upstream.json`.

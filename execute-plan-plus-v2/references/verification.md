# Verification, evidence and requirement-change invalidation

Read this before writing a step's `## Verify` block, before closing any AC, and whenever a
requirement or upstream AC changes mid-plan.

## What a step's Verify must contain

- At least one check tied to the current step. A broad build/typecheck may be included but must
  not be the only check when a narrower one exists.
- For each P0 AC: the positive example **and** the negative/boundary example from upstream
  `acceptance.md` (「P0 验证设计」).
- If the step owns a user-visible AC: the real API/browser/CLI path, including a failure or
  boundary case. A unit test alone does not close a user-visible AC.
- Record the actual command/output or a reproducible observation, never a planned test or an
  unverified claim.

## RED / GREEN

For a behavior change or bug fix, write the targeted regression assertion first and observe it
fail for the intended reason (RED); implement, observe it pass (GREEN). If a red baseline is
impractical (e.g. external-only dependency), record why and use an executable contract/fixture
instead. A test written after the fix alone does not show it could detect the original bug.

## High-risk changes

High-risk = auth, tenant isolation, external contracts, concurrency (also data migrations,
event ordering). For these, exercise a failure case at the relevant boundary and perturb at
least one input or environmental condition (wrong tenant, reordered event, upstream timeout,
duplicate delivery), then verify the expected failure behavior.

If the project already has a mutation-testing tool, run it on the changed critical logic after
the ordinary tests and investigate surviving mutants; do not enforce a universal score. Do not
confuse adversarial inputs with code mutation, and do not add a mutation framework just to
satisfy this skill (this skill ships no mutation engine).

## Evidence rules (what to pass to `close-ac`)

Prefer executable evidence; the script runs it and binds it to the code state:

```bash
python3 <req-align-v2>/scripts/align_state.py close-ac <run_dir> AC-1 \
    --run-cmd "pytest tests/test_catalog.py -q" [--cwd DIR] [--timeout SEC] \
    [--evidence "note"] --step 05-service-and-api-check
```

- `--run-cmd` executes the command (default cwd: git top level; outside a git repo `--cwd` is required; default timeout 600s). Non-zero
  exit or timeout refuses closure and changes no file. On success it records
  `[run exit=0 rev=<16hex|no-git> out=<8hex>] CMD`.
- Re-running `--run-cmd` on an already-closed AC refreshes the evidence (latest record wins).
  Do this after any later code change, because `--strict-closure` compares `rev` to the
  current code fingerprint.
- Human observation (e.g. a user-visible path): `--manual --observer NAME --evidence "what was
  seen"` records `[manual observer=NAME rev=...] TEXT`. `--manual` and `--run-cmd` are mutually
  exclusive; `--observer` is only valid with `--manual`.
- Plain `--evidence TEXT` is legacy self-reported text. It is accepted for P1/P2 only; P0 fails
  `--strict-closure`. (The concurrent req-align change also rejects plain evidence beginning
  with the reserved `[run ` / `[manual ` prefixes.)
- The code fingerprint is `HEAD` plus modified/untracked non-ignored files, **excluding only the
  TOP-LEVEL `docs/` and the req-align run dir**, so writing plan/evidence files does not
  invalidate it. Keep the req-align and exec-plan folders under the repo's top-level `docs/`, and
  install the skills outside the repo or gitignore `__pycache__`, otherwise generated files
  change the fingerprint. Without git the freshness comparisons only WARN.
- A passing `--run-cmd` proves the command exited 0 on that code, not that the command is
  meaningful. Choose commands that would fail if the AC were broken.

## Requirement-change invalidation procedure

When requirements, code scope, external API behavior, or an upstream AC changes:

1. Pause. Re-read the updated contract (`handoff.json`, `acceptance.md`).
2. If a **closed** AC's text or priority changed: `align_state.py fail-ac <run_dir> AC-N
   --observed "<why>"` first, then edit `align.md`/`acceptance.md`, then
   `align_state.py sync <run_dir>`. `sync` (and every write command) refuses drift of a still-closed
   AC; manually unticking an AC without a 未通过记录 entry is also refused.
3. Re-run `audit_coverage.py <plan_dir>`; fix `step.json` `covers` / `requirements.md`.
4. List previously `complate` steps affected by the change and re-run their checks; if you
   cannot trace the blast radius, re-verify every P0 AC.
5. Re-close the AC with fresh `--run-cmd`/`--manual` evidence. Neither old evidence nor an
   earlier code review approves the new behavior; request a new review (see `review.md`).

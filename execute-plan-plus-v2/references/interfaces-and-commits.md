# Interfaces, commits and resume anchors

Read this when writing `step.json`, before running the first step, and when resuming.
Purpose: stop "orphan code" (symbols built in one step that no later step ever calls) from
surviving a split plan and `/compact` windows.

## step.json interface fields (all optional, backward compatible)

| Field | Meaning |
| --- | --- |
| `depends_on` | step names that must be `complate` first; must exist and be EARLIER; no self reference |
| `produces` | symbols this step creates for later steps to call |
| `exposes` | symbols that are public entry points (CLI, route, exported API); need no later consumer |
| `consumes` | symbols this step calls; prefix `existing:` for code that predates the plan |

Each value is a list of non-empty strings. Name symbols as stable strings: `pkg.module:func`,
`pkg.module:Class.method`, or a file path. The scripts compare strings only; they never parse
code, so a wrong or invented name is not detected - keep names greppable in the real code.

```json
[
  { "step": "01-domain", "state": "pending", "covers": [], "depends_on": [],
    "produces": ["app.user:create_user"], "exposes": [], "consumes": ["existing:app.db:session"] },
  { "step": "02-api", "state": "pending", "covers": ["AC-1"], "depends_on": ["01-domain"],
    "produces": [], "exposes": ["POST /users"], "consumes": ["app.user:create_user"] }
]
```

Once ANY step declares any interface field, every step must carry `produces`, `exposes` and
`consumes` (empty lists are fine).

## Interface audit

`python3 scripts/audit_coverage.py <plan_dir>` prints it as its own PASS/FAIL/WARN lines in both
upstream-linked and generic mode; `final_gate.py` surfaces it. Rules: no declarations at all ->
WARN only (orphan risk unmanaged); missing keys -> FAIL; a non-`existing:` consumed symbol needs
an earlier producer/exposer; every `produces` symbol needs a later consumer (else declare it in
`exposes`); one symbol produced by two steps -> FAIL. Declaring nothing passes with a WARN, so
treat the WARN as a defect in plans that build more than one layer.

Fix declarations only through the tool (never hand-edit `step.json`), while the step is
`pending`:

```bash
python3 scripts/update_step_state.py <sj> NN-step declare [--depends-on a,b] [--produces a,b] \
    [--exposes a,b] [--consumes a,b] --reason "why"
```

Comma-separated; each given flag REPLACES that field (empty value clears it); at least one field
flag and a non-empty `--reason` are required; the same field validation as every other command
runs. A `runing`/`complate` step refuses: add a `decisions.md` entry and re-plan. Symbols are
compared after trimming whitespace; `existing:` is case-insensitive and valid only in `consumes`.
A `produces` symbol that any step lists in `exposes` is not an orphan.

## Dependency gate

`update_step_state.py ... runing` refuses while any `depends_on` step, or any EARLIER step that
produces/exposes a symbol this step consumes, is not `complate` (a consumer listed before its
producer is the audit's FAIL, not this gate's). `--force` only reorders positionally; it
does not bypass this gate.

## Commit per step

In a git repo, `runing` records `base_commit`. Commit the step's code BEFORE `complate`, using
the project's own commit message convention. `complate` then requires: no modified/untracked
files except under the repo's top-level `docs/`, and HEAD different from `base_commit`; it
records `commit`. A step that truly changes no code:

```bash
python3 scripts/update_step_state.py <sj> NN-step complate --no-code-change --reason "why"
```

(records `no_code_change: true`; the tree must still be clean). Outside git nothing is recorded
and a one-line note is printed. Legacy `complate` steps without `commit` only produce WARNs.
The gate cannot judge whether a commit really contains the step's work. Recording a commit is
not content verification: an amended or squashed commit that is still an ancestor of HEAD is not
detected, and a shallow clone can report a false STALE.

Once any step carries `base_commit`/`commit`, a `runing` step without `base_commit` makes
`complate` FAIL (in a git repo); re-issue `runing` on it to backfill `base_commit` from HEAD
(an existing `base_commit` is never overwritten), commit, then `complate`. A plan with no
commit fields at all is legacy: `complate` prints a note and skips binding. If `git status`
itself fails, `complate` stops with an error instead of treating the tree as clean.

## Resume check

```bash
python3 scripts/resume_check.py docs/exec-plan-<yyyy-mm-dd>-<slug>/
```

Read-only. Exit 0 ok, 1 when a `complate` step's `commit` is missing or not an ancestor of HEAD
(`STALE` - e.g. after reset/rebase; re-verify those steps), 2 usage. It lists files changed
since the last step commit (excluding top-level `docs/`), legacy steps without commits, and:

- EXPECTED ORPHANS: `produces` symbols whose consumer steps are not all `complate` yet. A
  code-graph orphan check (zero-caller symbols) will show exactly these mid-plan; they are not
  defects.
- UNEXPECTED: produced symbols with no consumer and no `exposes`; should not occur once the
  audit passes.

At the end of the plan, any zero-caller symbol the code-graph check reports that is not a
declared `exposes` entry point is a REAL orphan: wire it up or remove it.

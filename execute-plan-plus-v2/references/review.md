# Independent review protocol

Read this at each review trigger below, and before the final gate.

## Who reviews

A **different reviewer** from the code's author: a fresh read-only subagent, or a separate
human. The author does not write the reviewer's verdict. The reviewer must inspect the actual
diff, not the author's summary.

## What to send the reviewer

The original request, upstream AC/risk decisions, the actual code diff, and the verification
output. Do not supply a pre-approved conclusion. Require findings ordered by severity with
file/line, failure scenario, affected AC, and missing test. "No findings" must still list
residual risks and tests not run.

Focus on wrong behavior that can still pass the author's tests: authorization scope, error
propagation, concurrency, data migrations, compatibility, unintended edits.

## When

- **Milestone**: a meaningful behavior/boundary checkpoint (first vertical slice, external
  contract/security/tenant boundary, or a 3-step checkpoint with code changes).
- **Time backstop**: if coding continues 45 minutes without such a checkpoint, review the
  current diff. The timer is a backstop, never proof of quality; do not review merely because
  time passed with no code change.
- **Final**: after implementation stabilizes and before calling the plan complete. Resolve
  blocking correctness/security findings, re-run impacted tests, re-review changed hunks.
- **Re-review**: any code change after a `final` approval invalidates it (the record is bound
  to the code fingerprint). Avoid repeated full-diff reviews for a small repaired hunk, but the
  final review still considers the integrated result.

## Recording

```bash
python3 <req-align-v2>/scripts/align_state.py record-review <run_dir> \
    --reviewer "<name or subagent role>" --author "<author name>" \
    --scope milestone|time-backstop|final \
    --verdict approved|changes-requested --summary "<findings + disposition>"
```

- Writes `reviews.json` entry `REV-N` with `rev` = current code fingerprint (16 hex).
- `--reviewer` must differ from `--author` (case-insensitive).
- `check_alignment.py --strict-closure` (and so `final_gate.py`) requires the **latest** entry
  to be an approved `final` for the current fingerprint. Any later record, including a
  milestone review, supersedes it; any code change makes it stale (WARN only without git).
- Also write reviewer identity, reviewed diff/commit, findings, disposition and outstanding
  risks into the plan mini-plan notes.

## `待审核` rule

If the reviewer implemented the changes, or no independent reviewer is available, mark review
`待审核` in the notes and do not claim final approval. A separate human review is an acceptable
alternative. Do not run `record-review --scope final --verdict approved` in that case.

## Limits

The reviewer name is just recorded text; it is not authenticated. `reviews.json` can be
hand-edited. Independence rests on a genuinely separate human or fresh subagent, not on the
script.

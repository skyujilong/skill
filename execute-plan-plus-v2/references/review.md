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

## Creating the independent reviewer (per tool)

The scripts do not create a reviewer. The agent running this skill must start one with the
tool it runs in. Pick the first row that matches; every method gives a fresh context, but
**read-only is only enforced where noted**, so always run the read-only check below.

### Prefer the tool's native reviewer

Use the tool's own review command first; create a custom agent only where this table says so.
Never pass `--fix` or `--comment` (they edit code or post to a PR).

| Tool | Native reviewer | Takes our AC/risk packet? | Use it for |
| --- | --- | --- | --- |
| Claude Code | `/code-review <branch\|path\|range>` (alias `/review`), runs as a background subagent with its own context | Not documented; it looks for correctness bugs in the diff | Milestone and time-backstop reviews. For `final`, also use a custom AC-aware reviewer below |
| Codex | `/review` in the TUI (pick a preset or "custom review instructions"), or `codex review --uncommitted \| --base <branch> \| --commit <sha>`; per the command reference a run takes exactly one target **or** custom instructions (`codex review "<instructions>"`), so name the diff scope inside the instructions. Scripted read-only run: `codex exec --sandbox read-only --ask-for-approval never "<instructions>"` | Yes, via custom review instructions (paste the review packet below) | All reviews, including `final` |
| WorkBuddy | None. `/code-review` exists in CodeBuddy Code but is **not available in the WorkBuddy client** (confirmed by the user) | - | Always use the custom reviewer agent below |

A native reviewer that cannot take the packet does not know the ACs or risk decisions, so it
cannot approve a `final` review alone: record it as a milestone review and add an AC-aware
reviewer (rows below) for `final`. Paste the native reviewer's full output into the plan
notes as well.

### Custom reviewer agent (when the native one does not fit)

| Tool | How to create it | Read-only enforced? |
| --- | --- | --- |
| Claude Code | Built-in `Explore` subagent (Write/Edit denied), or a custom file `.claude/agents/<name>.md` / `~/.claude/agents/<name>.md` with YAML frontmatter `name`, `description`, and `tools: Read, Grep, Glob, Bash` plus `disallowedTools: Write, Edit`. Ask Claude to use that subagent for the review. | Yes for Write/Edit; `Bash` can still modify files, so leave it out unless the reviewer must run tests. |
| Codex | Ask Codex explicitly to spawn a subagent (it delegates on a direct request or when `AGENTS.md`/a skill asks). Custom agent: `.codex/agents/<name>.toml` or `~/.codex/agents/<name>.toml` with required `name`, `description`, `developer_instructions`. Inspect threads with `/subagents`. | **No.** Subagents inherit the parent's sandbox and approvals and a custom agent file cannot override them; "do not edit files" is an instruction only. Set the parent turn to a read-only permission mode before delegating if you need enforcement. |
| WorkBuddy | Create a custom agent whose tools exclude write/edit, or ask WorkBuddy to create one, then ask it to use that agent. Per Tencent's CodeBuddy Code docs (the same engine family), agents are Markdown files with YAML frontmatter (`name`, `description`, `tools`, `model`) in `.codebuddy/agents/` or `~/.codebuddy/agents/`, managed with `/agents`. A third-party analysis of the WorkBuddy desktop client reports `.workbuddy/agents/` and `~/.workbuddy/agents/`. | **Unverified for WorkBuddy.** The paths and fields above are from CodeBuddy Code docs and a third-party analysis, not WorkBuddy's own documentation. Check the agent's tool list in the UI. |
| None of the above works | Start a **new session** of the same tool with no shared history and give it only the review packet below, or ask a human. | No - use the read-only check. |

Official references: Claude Code <https://code.claude.com/docs/en/sub-agents>; Codex
<https://developers.openai.com/codex/subagents>; CodeBuddy Code
<https://cloud.tencent.com/document/product/1831/137015>.

### Read-only check (all tools)

Before the review run `git rev-parse HEAD` and `git status --porcelain`; after it, run both
again. If either changed, the reviewer edited the repository: discard that review, restore the
author's state, and re-run with a stricter setup. Do not record such a review.

### Reviewer prompt template

Give the reviewer exactly this, filled in. Do not add your own conclusion.

```text
You are an independent code reviewer. You did not write this code. Do NOT edit, create or delete
any file and do not run commands that modify the repository.
Original request: <paste the user's request / plan goal>
Upstream decisions: <AC ids with text, risk decisions>
Scope: <steps or commit range, e.g. BASE..HEAD>; inspect the real diff and the files, not my summary.
Verification output: <commands run and their real output>
Return findings ordered by severity (Critical/High/Medium/Low). For each: file:line, a concrete
failure scenario, the AC or decision it violates, and the missing test. If there are no findings,
say what you checked and list residual risks and tests not run. Be concrete; do not pad.
```

After the review, paste the reviewer's full reply into the plan notes; a one-line "reviewed"
is not evidence. The reviewer name you pass to `record-review` should name the reviewer
subagent/session (for example `claude-subagent:independent-reviewer`), never the author.

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

---
name: use-worktree
description: Manage git worktrees for parallel development. Create worktrees in sibling directories with automatic dependency installation, list existing worktrees with status, and safely delete worktrees with confirmation checks. Use this whenever the user mentions worktrees, parallel development, multiple branches, or needs to work on multiple branches simultaneously without switching.
---

# Git Worktree Manager

This skill helps manage git worktrees for parallel development across multiple branches.

## Core Principles

1. **Sibling Directory Convention**: Always create worktrees as siblings to the current project directory
2. **Naming Pattern**: `{project-name}-worktree-{branch-name}`
3. **Branch Naming Convention**:
   - Features: `feature/branch-name`
   - Fixes: `fix/branch-name`
4. **Fast Dependency Installation**:
   - Python: Use `uv sync` (fastest)
   - Node.js: Use `pnpm install` (detects `pnpm-lock.yaml`)
5. **Automatic Dependency Detection**: Detect project type (frontend, backend, monorepo) and install dependencies
6. **Safety First**: Check for uncommitted changes and confirm merge status before deletion

---

## Commands

### 1. Create a Worktree

**When the user asks to**: create a worktree, make a worktree, setup parallel branch, work on another branch simultaneously

**IMPORTANT**: Always use the `scripts/worktree_manager.py` script for creation and dependency installation.

**Steps**:

1. **Confirm current project info**:
   - Run `git status` to ensure current directory is clean (or inform user of pending changes)

2. **Get branch name**:
   - If user specified a branch: use that name
   - If not specified: ask the user for the target branch name
   - Optional: Suggest naming conventions (`feature/`, `fix/`, etc.)

3. **Create worktree (USE THE SCRIPT!)**:
   ```bash
   python3 scripts/worktree_manager.py create {branch-name}
   ```
   - Script automatically creates worktree as sibling: `../{project}-worktree-{branch}`
   - Script automatically creates the branch if it doesn't exist
   - Returns JSON with: `success`, `path`, `warnings`

4. **Install dependencies (USE THE SCRIPT!)**:
   ```bash
   python3 scripts/worktree_manager.py install-deps {worktree-path}
   ```
   - Script detects and installs automatically:
     - **Python (uv)**: `pyproject.toml` → `uv sync`
     - **Node.js (pnpm)**: `package.json` → `pnpm install`
     - **Rust (cargo)**: `Cargo.toml` → `cargo build`
     - **Go**: `go.mod` → `go mod download`
     - **Java (Maven)**: `pom.xml` → `mvn install -DskipTests`
   - Script handles monorepos: checks root, `frontend/`, `backend/` directories

5. **Report success**:
   - Show the full path to the new worktree
   - Show how to navigate there: `cd {full-path}`
   - List any warnings from the script

---

### 2. List Worktrees

**When the user asks to**: list worktrees, show worktrees, check worktree status, see active worktrees

**IMPORTANT**: Always use the `scripts/worktree_manager.py` script for listing worktrees. It automatically checks dirty status for each worktree and returns structured JSON.

**Steps**:

1. **Run list command (USE THE SCRIPT!)**:
   ```bash
   python3 scripts/worktree_manager.py list
   ```
   - Returns JSON array with: `path`, `branch`, `head`, `dirty` (bool), `dirty_count`, `locked` (bool)
   - No need to manually check dirty status - script does it automatically!

2. **Format output nicely**:
   - For each worktree, show:
     - Path (with project name highlighted)
     - Branch name
     - HEAD commit hash
     - Whether it's locked (if applicable)
     - Whether it's dirty (has uncommitted changes) - use `dirty` and `dirty_count` from JSON

3. **Summary stats**:
   - Total worktrees count
   - Count of dirty worktrees (with uncommitted changes) - `dirty = true`
   - Count of locked worktrees - `locked = true`

---

### 3. Delete a Worktree

**When the user asks to**: delete a worktree, remove worktree, clean up worktree, delete worktree by name/path

**IMPORTANT**: Always use the `scripts/worktree_manager.py` script for deletion, NOT manual git commands. The script handles edge cases like non-empty directories (node_modules, .venv, caches) and partial deletions.

**Steps**:

1. **Identify target worktree**:
   - Run `python3 scripts/worktree_manager.py list` to get all worktrees
   - If user provided a path/name: find the matching worktree from the list
   - If not specified: show the list of worktrees and ask which one to delete

2. **Safety checks (CRITICAL)**:
   ```bash
   python3 scripts/worktree_manager.py check {worktree-path}
   ```
   - Returns JSON with: `dirty` (has uncommitted changes), `dirty_files` (list), `is_merged` (bool), `main_branch` (str)

   a. **If dirty = true**: **WARN the user** and show `dirty_files`
      - Ask: "This worktree has uncommitted changes. Are you sure you want to delete? (yes/no)"

   b. **If is_merged = false**: **WARN the user**
      - Ask: "This branch does NOT appear to be merged into {main_branch}. Are you sure you want to delete? (yes/no)"

   c. **Double confirmation**: Always get explicit confirmation before deleting, especially if any safety check failed

3. **Perform deletion (USE THE SCRIPT!)**:
   ```bash
   python3 scripts/worktree_manager.py delete {worktree-path}
   ```
   - If user confirmed force delete (with uncommitted changes): add `--force` flag

4. **Cleanup confirmation**:
   - Script automatically runs `git worktree prune`
   - Verify deletion with: `python3 scripts/worktree_manager.py list`

---

## Path Safety Rules

- **Never** create worktrees inside the parent git repository (they should be siblings)
- **Always** use absolute paths when operating on worktrees
- **Always** verify the worktree exists before attempting deletion
- **Never** delete the main worktree (the one the user is currently in)

---

## Error Handling

- If worktree creation fails (branch already checked out elsewhere): inform user and suggest using that existing worktree
- If dependency installation fails: warn but don't fail the whole operation - worktree is still usable
- If deletion is cancelled: confirm cancellation and exit cleanly
- If git commands fail: show the exact error message to the user for debugging

---

## Quick Reference

**IMPORTANT**: Always use the script commands instead of raw git commands for consistency.

| Task | Script Command |
|------|----------------|
| List worktrees | `python3 scripts/worktree_manager.py list` |
| Create worktree | `python3 scripts/worktree_manager.py create <branch-name>` |
| Delete worktree | `python3 scripts/worktree_manager.py delete <worktree-path>` |
| Check worktree status | `python3 scripts/worktree_manager.py check <worktree-path>` |
| Install dependencies | `python3 scripts/worktree_manager.py install-deps <worktree-path>` |

**Fallback git commands** (only if script fails):
| Task | Git Command |
|------|-------------|
| List simple | `git worktree list` |
| Cleanup stale | `git worktree prune` |
| Check status | `git -C <worktree-path> status` |

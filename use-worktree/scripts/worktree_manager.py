#!/usr/bin/env python3
"""
Git Worktree Manager - Core utility functions

Usage:
  python3 worktree_manager.py list
  python3 worktree_manager.py create <branch-name>
  python3 worktree_manager.py delete <worktree-path>
  python3 worktree_manager.py check <worktree-path>
  python3 worktree_manager.py install-deps <worktree-path>
"""

import
  python worktree_manager.py list
  python worktree_manager.py create <branch-name>
  python worktree_manager.py delete <worktree-path>
  python worktree_manager.py check <worktree-path>
"""

import os
import sys
import json
import subprocess
from pathlib import Path


def run_cmd(cmd, cwd=None, capture_output=True, shell=True):
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
        capture_output=capture_output,
        text=True
    )
    return result


def run_git(args, cwd=None):
    """Run a git command safely with proper argument handling (no shell injection)."""
    result = subprocess.run(
        ['git'] + args,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    return result


def get_project_root():
    """Get the current git project root directory."""
    result = run_git(['rev-parse', '--show-toplevel'])
    if result.returncode != 0:
        print(f"Error: Not in a git repository: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_project_name():
    """Get the project name from the root directory."""
    root = get_project_root()
    return os.path.basename(root)


def get_worktree_name(branch_name):
    """Generate the worktree directory name.

    Replaces slashes with hyphens to avoid nested directories:
    feature/dynamic-prompt -> feature-dynamic-prompt
    """
    project = get_project_name()
    safe_branch = branch_name.replace('/', '-')
    return f"{project}-worktree-{safe_branch}"


def get_worktree_path(branch_name):
    """Generate the full path for a new worktree (sibling to project)."""
    root = get_project_root()
    parent = os.path.dirname(root)
    name = get_worktree_name(branch_name)
    return os.path.join(parent, name)


def list_worktrees():
    """List all worktrees with detailed status."""
    result = run_git(['worktree', 'list', '--porcelain'])
    if result.returncode != 0:
        print(f"Error listing worktrees: {result.stderr}", file=sys.stderr)
        return []

    worktrees = []
    current = {}

    for line in result.stdout.split('\n'):
        line = line.strip()
        if not line:
            if current:
                # Check if dirty
                if 'path' in current:
                    dirty_result = run_git(['-C', current['path'], 'status', '--porcelain'])
                    current['dirty'] = len(dirty_result.stdout.strip()) > 0
                    current['dirty_count'] = len([l for l in dirty_result.stdout.split('\n') if l.strip()])
                worktrees.append(current)
                current = {}
        elif line.startswith('worktree '):
            current['path'] = line[9:].strip()
        elif line.startswith('HEAD '):
            current['head'] = line[5:].strip()
        elif line.startswith('branch '):
            current['branch'] = line[7:].strip().replace('refs/heads/', '')
        elif line.startswith('detached'):
            current['detached'] = True
        elif line.startswith('locked'):
            current['locked'] = True
            current['lock_reason'] = line[6:].strip() if len(line) > 6 else ''

    return worktrees


def branch_exists(branch_name):
    """Check if a branch exists."""
    result = run_git(['show-ref', '--verify', '--quiet', f'refs/heads/{branch_name}'])
    return result.returncode == 0


def create_branch(branch_name):
    """Create a new branch from current HEAD."""
    result = run_git(['checkout', '-b', branch_name])
    if result.returncode != 0:
        return False, result.stderr
    # Return to original branch
    run_git(['checkout', '-'])
    return True, "Branch created"


def suggest_branch_name(branch_name):
    """Suggest proper branch naming if not following conventions."""
    suggestions = []
    if not branch_name.startswith(('feature/', 'fix/', 'chore/', 'docs/', 'refactor/')):
        suggestions.append(f"Consider prefix: feature/{branch_name} (new feature)")
        suggestions.append(f"Consider prefix: fix/{branch_name} (bug fix)")
    return suggestions


def create_worktree(branch_name):
    """Create a worktree for the given branch."""
    path = get_worktree_path(branch_name)
    warnings = []

    # Check branch naming convention
    suggestions = suggest_branch_name(branch_name)
    if suggestions:
        warnings.append(f"Branch naming tip: {suggestions[0]}")

    # Check if path already exists
    if os.path.exists(path):
        return False, f"Path already exists: {path}"

    # Check if branch exists
    if not branch_exists(branch_name):
        ok, msg = create_branch(branch_name)
        if not ok:
            return False, f"Failed to create branch: {msg}"
        warnings.append(f"Created new branch: {branch_name}")

    # Create worktree
    result = run_git(['worktree', 'add', path, branch_name])
    if result.returncode != 0:
        return False, result.stderr

    return True, {"path": path, "warnings": warnings}


def detect_node_package_manager(project_path):
    """Detect which Node.js package manager to use (prefer pnpm)."""
    if os.path.exists(os.path.join(project_path, 'pnpm-lock.yaml')):
        return 'pnpm install'
    elif os.path.exists(os.path.join(project_path, 'package.json')):
        # Always prefer pnpm even if only package-lock.json exists
        return 'pnpm install'
    elif os.path.exists(os.path.join(project_path, 'yarn.lock')):
        return 'yarn install'
    return None


def detect_python_package_manager(project_path):
    """Detect which Python package manager to use (prefer uv)."""
    if os.path.exists(os.path.join(project_path, 'pyproject.toml')):
        # Always use uv for Python projects with pyproject.toml
        return 'uv sync'
    elif os.path.exists(os.path.join(project_path, 'requirements.txt')):
        return 'pip install -r requirements.txt'
    return None


def install_dependencies(path):
    """Install dependencies for the project at the given path (fast mode)."""
    messages = []

    # Root level Python dependencies (uv)
    python_pm = detect_python_package_manager(path)
    if python_pm:
        messages.append(f"Installing Python dependencies with {python_pm}...")
        result = run_cmd(python_pm, cwd=path, capture_output=False)
        if result.returncode != 0:
            messages.append(f"Warning: Python dependency installation may have failed")

    # Root level Node.js dependencies (pnpm)
    node_pm = detect_node_package_manager(path)
    if node_pm:
        messages.append(f"Installing Node.js dependencies with {node_pm}...")
        result = run_cmd(node_pm, cwd=path, capture_output=False)
        if result.returncode != 0:
            messages.append(f"Warning: Node.js dependency installation may have failed")

    # Check for frontend directory (Node.js with pnpm)
    frontend_path = os.path.join(path, 'frontend')
    if os.path.exists(frontend_path):
        frontend_pm = detect_node_package_manager(frontend_path)
        if frontend_pm:
            messages.append(f"Installing frontend dependencies with {frontend_pm}...")
            result = run_cmd(frontend_pm, cwd=frontend_path, capture_output=False)
            if result.returncode != 0:
                messages.append(f"Warning: Frontend dependency installation may have failed")

    # Check for backend directory
    backend_path = os.path.join(path, 'backend')
    if os.path.exists(backend_path):
        # Python backend (uv)
        backend_python_pm = detect_python_package_manager(backend_path)
        if backend_python_pm:
            messages.append(f"Installing Python backend dependencies with {backend_python_pm}...")
            result = run_cmd(backend_python_pm, cwd=backend_path, capture_output=False)
            if result.returncode != 0:
                messages.append(f"Warning: Python backend dependency installation may have failed")

        # Node.js backend (pnpm)
        backend_node_pm = detect_node_package_manager(backend_path)
        if backend_node_pm:
            messages.append(f"Installing Node.js backend dependencies with {backend_node_pm}...")
            result = run_cmd(backend_node_pm, cwd=backend_path, capture_output=False)
            if result.returncode != 0:
                messages.append(f"Warning: Node.js backend dependency installation may have failed")

    # Rust project (cargo)
    if os.path.exists(os.path.join(path, 'Cargo.toml')):
        messages.append("Building Rust project...")
        result = run_cmd('cargo build', cwd=path, capture_output=False)

    # Go project
    if os.path.exists(os.path.join(path, 'go.mod')):
        messages.append("Downloading Go dependencies...")
        result = run_cmd('go mod download', cwd=path, capture_output=False)

    # Java Maven
    if os.path.exists(os.path.join(path, 'pom.xml')):
        messages.append("Installing Maven dependencies...")
        result = run_cmd('mvn install -DskipTests', cwd=path, capture_output=False)

    return messages


def check_worktree(path):
    """Check worktree status: dirty files and merge status."""
    if not os.path.exists(path):
        return {'exists': False}

    # Check for uncommitted changes
    dirty_result = run_git(['-C', path, 'status', '--porcelain'])
    dirty_files = [l.strip() for l in dirty_result.stdout.split('\n') if l.strip()]

    # Get current branch
    branch_result = run_git(['-C', path, 'rev-parse', '--abbrev-ref', 'HEAD'])
    branch = branch_result.stdout.strip()

    # Get main branch (use 'git remote show origin' via shell for grep)
    main_result = run_cmd("git remote show origin | grep 'HEAD branch' | cut -d: -f2 | tr -d ' '")
    main_branch = main_result.stdout.strip() if main_result.returncode == 0 else 'main'

    # Check if merged (run git branch -a to include remote tracking then filter)
    # Note: git branch only shows local branches; include main branch explicitly as it's always merged
    merged_result = run_git(['branch', '--merged', main_branch])
    branches_merged = [l.strip().replace('* ', '') for l in merged_result.stdout.split('\n') if l.strip()]
    is_merged = branch in branches_merged or branch == main_branch

    return {
        'exists': True,
        'branch': branch,
        'main_branch': main_branch,
        'dirty': len(dirty_files) > 0,
        'dirty_files': dirty_files,
        'is_merged': is_merged,
    }


def delete_worktree(path, force=False):
    """Delete a worktree with robust fallback for non-empty directories.

    Handles edge cases:
    1. Worktree has untracked files (node_modules, .venv, caches, etc.)
    2. Git partially deleted but directory remains
    3. Stale worktree references

    Args:
        path: Absolute path to worktree
        force: If True, skip safety checks and force delete

    Returns:
        (success: bool, message: str)
    """
    import shutil

    # First try: normal git worktree remove
    args = ['worktree', 'remove']
    if force:
        args.append('--force')
    args.append(path)
    result = run_git(args)

    if result.returncode == 0:
        run_git(['worktree', 'prune'])
        return True, "Deleted successfully (git worktree remove)"

    # Handle common error: Directory not empty
    stderr = result.stderr.strip()
    if 'Directory not empty' in stderr or 'not a working tree' in stderr:
        # Directory has untracked files - need manual cleanup
        try:
            # Check if this is actually a worktree path first
            if not os.path.exists(os.path.join(path, '.git')):
                # Already partially deleted, just remove dir and prune
                shutil.rmtree(path)
                run_git(['worktree', 'prune'])
                return True, "Deleted successfully (cleaned partial deletion)"

            # It's a valid worktree but has untracked files
            # Try with --force first
            force_result = run_git(['worktree', 'remove', '--force', path])
            if force_result.returncode == 0:
                run_git(['worktree', 'prune'])
                return True, "Deleted successfully (git worktree remove --force)"

            # If git still fails (e.g., .git was deleted mid-process), fallback to manual
            shutil.rmtree(path)
            run_git(['worktree', 'prune'])
            return True, "Deleted successfully (manual cleanup with rmtree)"

        except Exception as e:
            return False, f"Failed to delete directory: {str(e)}"

    # Other errors
    return False, stderr


def main():
    if len(sys.argv) < 2:
        print("Usage: worktree_manager.py <command> [args]")
        print("Commands:")
        print("  list                     - List all worktrees")
        print("  create <branch>          - Create worktree for branch")
        print("  delete <path> [--force] - Delete worktree")
        print("  check <path>            - Check worktree status")
        print("  install-deps <path>     - Install dependencies (uv + pnpm)")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'list':
        worktrees = list_worktrees()
        print(json.dumps(worktrees, indent=2))

    elif command == 'create':
        if len(sys.argv) < 3:
            print("Error: Branch name required", file=sys.stderr)
            sys.exit(1)
        branch = sys.argv[2]
        success, result = create_worktree(branch)
        if isinstance(result, dict):
            print(json.dumps({'success': success, **result}))
        else:
            print(json.dumps({'success': success, 'message': result}))

    elif command == 'delete':
        if len(sys.argv) < 3:
            print("Error: Worktree path required", file=sys.stderr)
            sys.exit(1)
        path = sys.argv[2]
        force = len(sys.argv) > 3 and sys.argv[3] == '--force'
        success, msg = delete_worktree(path, force)
        print(json.dumps({'success': success, 'message': msg}))

    elif command == 'check':
        if len(sys.argv) < 3:
            print("Error: Worktree path required", file=sys.stderr)
            sys.exit(1)
        path = sys.argv[2]
        status = check_worktree(path)
        print(json.dumps(status, indent=2))

    elif command == 'install-deps':
        if len(sys.argv) < 3:
            print("Error: Worktree path required", file=sys.stderr)
            sys.exit(1)
        path = sys.argv[2]
        messages = install_dependencies(path)
        print(json.dumps({'messages': messages}))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

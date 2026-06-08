"""DD-022 phase A: derive a session's code location (worktree / branch) MECHANICALLY
from its cwd via git — never from AI extraction (transcripts don't state the path, so
the AI could never reliably collect it; the cwd always can).

Standalone + dependency-free so it's unit-testable without importing serve.py.
"""
import os
import re
import subprocess
import time


def slugify(s: str) -> str:
    """A safe, semantic worktree/branch slug from a task name: lowercase, ascii
    [a-z0-9-], collapsed dashes, trimmed, ≤40 chars. '' if nothing usable
    (caller then lets `claude --worktree` auto-name)."""
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")[:40]


def _git(cwd, *args, timeout=3):
    """Run `git -C cwd <args>`; return stripped stdout, or None on any failure."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def compute_code_location(cwd: str):
    """Mechanically derive a card's code location from a cwd. Returns
        {"worktree": <toplevel dir>, "branch": <name>,
         "is_worktree": <bool>, "main_repo": <main checkout dir>}
    or None if cwd is not inside a git repo.

    is_worktree: a linked worktree's git-dir (…/.git/worktrees/<name>) differs from
    its git-common-dir (…/.git); the main checkout's are the same. main_repo is the
    parent of the common dir (…/.git → …)."""
    if not cwd or not os.path.isdir(cwd):
        return None
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or ""
    git_dir = _git(cwd, "rev-parse", "--absolute-git-dir") or ""
    common = _git(cwd, "rev-parse", "--git-common-dir") or ""
    if common and not os.path.isabs(common):
        common = os.path.abspath(os.path.join(cwd, common))
    is_wt = bool(git_dir and common
                 and os.path.abspath(git_dir) != os.path.abspath(common))
    main_repo = os.path.dirname(common) if common else top
    return {"worktree": top, "branch": branch,
            "is_worktree": is_wt, "main_repo": main_repo}


_CACHE: dict = {}      # cwd -> (epoch, code_location|None)
_TTL = 30.0            # branch/worktree change rarely; short TTL keeps git calls cheap


def code_location_for_cwd(cwd: str, _now=time.time):
    """Cached compute_code_location — git is shelled out at most once per cwd per TTL."""
    if not cwd:
        return None
    now = _now()
    ent = _CACHE.get(cwd)
    if ent and now - ent[0] < _TTL:
        return ent[1]
    info = compute_code_location(cwd)
    _CACHE[cwd] = (now, info)
    return info


def changed_files(repo_cwd: str, base_ref: str = ""):
    """DD-025: the set of repo-relative paths this checkout has touched — the coarse
    signal for the ⚠ same-file warning across parallel sub-cards. Union of:
      • committed since the fork point (`<base_ref>...HEAD`, if base_ref given & valid)
      • staged + unstaged working-tree changes
    Returns a sorted list (empty on any error). base_ref is the sibling's shared
    parent branch; an invalid/missing base just degrades to working-tree changes."""
    if not repo_cwd or not os.path.isdir(repo_cwd):
        return []
    seen: set = set()
    for args in (
        (["diff", "--name-only", f"{base_ref}...HEAD"] if base_ref else None),
        ["diff", "--name-only", "HEAD"],          # unstaged vs HEAD
        ["diff", "--name-only", "--cached"],      # staged
    ):
        if not args:
            continue
        out = _git(repo_cwd, *args)
        if out:
            seen.update(p for p in out.splitlines() if p.strip())
    return sorted(seen)


_FILES_CACHE: dict = {}    # (repo_cwd, base_ref) -> (epoch, [paths])
_FILES_TTL = 20.0          # working tree churns; keep fresh-ish but cheap


def changed_files_cached(repo_cwd: str, base_ref: str = "", _now=time.time):
    """Cached changed_files — at most one git diff trio per (cwd, base) per TTL."""
    key = (repo_cwd, base_ref)
    now = _now()
    ent = _FILES_CACHE.get(key)
    if ent and now - ent[0] < _FILES_TTL:
        return ent[1]
    files = changed_files(repo_cwd, base_ref)
    _FILES_CACHE[key] = (now, files)
    return files

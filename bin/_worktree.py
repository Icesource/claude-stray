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


def _git2(cwd, *args, timeout=3):
    """Like _git but returns (stdout|None, stderr) so callers can inspect WHY a
    command failed (e.g. tell a WIP-conflict FF refusal apart from a stale base)."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip(), r.stderr
        return None, (r.stderr or "") + (r.stdout or "")
    except Exception as e:
        return None, str(e)


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


_MERGE_CACHE: dict = {}   # worktree_path -> (tip, index_mtime, ts, result)
_MERGE_TTL = 8.0          # wall-clock ceiling so UNCOMMITTED edits surface too


def merge_status(main_repo: str, worktree: str, branch: str, _now=time.time):
    """Is this sub-card branch's work already absorbed elsewhere, and is its
    tree clean? Returns {merged, ahead, dirty} or None.
      - merged: the branch tip is contained in some OTHER branch (its commits
        survive a `branch -D`); also True when the branch has NO commits of its
        own ahead of the rest of history.
      - ahead:  commits on this branch not reachable from any other branch
        (what you'd LOSE on close) — the count shown as 'N 未合并'.
      - dirty:  uncommitted changes in the worktree (lost on `worktree remove`).
    Cache invalidates on tip move (a commit), on .git mtime change, OR after
    _MERGE_TTL seconds — the last is essential: UNCOMMITTED edits move neither
    the tip nor .git, so a pure (tip, mtime) key would let `dirty` go stale
    forever. With the 3s poll this still re-shells git at most ~once / 8s per
    actively-edited sub-card."""
    if not (main_repo and worktree and branch):
        return None
    tip = _git(main_repo, "rev-parse", "--verify", "--quiet", branch)
    if not tip:
        return None
    try:
        idx_mtime = os.path.getmtime(os.path.join(worktree, ".git"))
    except OSError:
        idx_mtime = 0.0
    now = _now()
    cached = _MERGE_CACHE.get(worktree)
    if cached and cached[0] == tip and cached[1] == idx_mtime and now - cached[2] < _MERGE_TTL:
        return cached[3]
    contains = _git(main_repo, "branch", "--format=%(refname:short)",
                    "--contains", tip) or ""
    others = [b.strip() for b in contains.splitlines()
              if b.strip() and b.strip() != branch]
    # commits unique to this branch (unreachable from every other branch).
    # NOTE: --exclude must precede the --branches it modifies (git pattern order).
    ahead_out = _git(main_repo, "rev-list", "--count", tip,
                     "--not", "--exclude=" + branch, "--branches")
    try:
        ahead = int((ahead_out or "0").strip() or "0")
    except ValueError:
        ahead = 0
    dirty = bool((_git(worktree, "status", "--porcelain", "-uno") or "").strip())
    result = {"merged": bool(others) or ahead == 0, "ahead": ahead, "dirty": dirty}
    _MERGE_CACHE[worktree] = (tip, idx_mtime, now, result)
    return result

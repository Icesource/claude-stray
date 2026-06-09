#!/usr/bin/env python3
"""Resolve the canonical claude-stray root: the MAIN git worktree.

Every stray hook script derives its ``cache/`` location from its own file
position (``Path(__file__).parent.parent``). That breaks the moment the code
runs from a *linked* git worktree under ``.claude/worktrees/<x>/bin``: the
naive derivation points ``cache/`` at the worktree, while the server only ever
reads the MAIN checkout's ``cache/``. Live-status writes then vanish into a
worktree dir and cards freeze on the last event the main checkout happened to
see — the recurring "active session, fresh jsonl, but live stuck on an
hours-old event" regression.

This helper always returns the main worktree's root so every writer and the
reader agree, regardless of which worktree the code physically runs from.

Resolution order (first hit wins):
  1. ``STRAY_REPO_ROOT`` env — set once by the shell entry hook, so the python
     children skip the git call entirely (hot path).
  2. ``git rev-parse --git-common-dir`` — the shared ``.git`` lives in the main
     checkout; its parent IS the main worktree, from any linked worktree.
  3. naive parent-of-bin — non-git installs (tarball) or git missing.

Never raises: hooks must not fail.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def repo_root(start: "Path | str | None" = None) -> Path:
    env = os.environ.get("STRAY_REPO_ROOT")
    if env:
        return Path(env)
    here = (Path(start).resolve() if start
            else Path(__file__).resolve().parent.parent)
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=2,
        )
        common = out.stdout.strip()
        if out.returncode == 0 and common:
            cp = Path(common)
            if not cp.is_absolute():
                cp = here / cp
            # The shared .git dir lives in the main checkout; its parent is the
            # main worktree root.
            return cp.resolve().parent
    except Exception:
        pass
    return here

"""P11.0: shared exclusive lock for cache/ write paths.

Exposes a single context manager:

    from _cache_lock import cache_lock

    with cache_lock("overrides"):
        # safe read-modify-write of user_overrides.json / deleted_ids.json
        ...

The lock file lives at  <cache>/.locks/<name>.lock.
The cache directory is derived the same way serve.py derives CACHE_DIR:
  1. STRAY_CACHE_DIR env override (test isolation)
  2. _repo_root.repo_root() / "cache"

Behaviour:
  - Blocks (LOCK_EX) until acquired — all protected operations are <100ms
    so indefinite spin is not a concern.
  - On non-POSIX platforms (or if fcntl is unavailable) the lock degrades
    to a no-op: the context manager is still usable, writes are just
    unprotected (same behaviour as today).

Style mirrors bin/_merge.py :: _locked.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover — non-POSIX
    _fcntl = None  # type: ignore[assignment]


def _cache_dir() -> Path:
    env = os.environ.get("STRAY_CACHE_DIR")
    if env:
        return Path(env)
    try:
        from _repo_root import repo_root
        return repo_root() / "cache"
    except Exception:
        # Fallback: navigate up from this file's location
        return Path(__file__).resolve().parent.parent / "cache"


@contextlib.contextmanager
def cache_lock(name: str = "overrides"):
    """Acquire an exclusive advisory lock on cache/.locks/<name>.lock.

    Blocks until acquired; releases on context exit.
    Degrades to no-op when fcntl is unavailable (non-POSIX).
    """
    if _fcntl is None:
        yield
        return

    lock_dir = _cache_dir() / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    fh = open(lock_path, "w")
    try:
        _fcntl.flock(fh, _fcntl.LOCK_EX)
        yield
    finally:
        try:
            _fcntl.flock(fh, _fcntl.LOCK_UN)
        finally:
            fh.close()

"""P11.0 cache lock tests.

Run: python3 tests/test_cache_lock.py   (or via bin/test / pytest)

Tests:
  1. Mutual exclusion — two threads competing on the same lock name; a
     shared counter is incremented inside the lock; no lost updates.
  2. No-op degradation — patch _cache_lock._fcntl to None; contextmanager
     still works and the body runs exactly once.
  3. Different lock names don't block each other.
"""
import os
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _cache_lock  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _lock_with_cache(cache_dir: str, name: str = "overrides"):
    """Return a cache_lock context manager backed by a specific temp dir."""
    # Temporarily redirect STRAY_CACHE_DIR so the lock module resolves there.
    old = os.environ.get("STRAY_CACHE_DIR")
    os.environ["STRAY_CACHE_DIR"] = cache_dir
    try:
        return _cache_lock.cache_lock(name)
    finally:
        if old is None:
            os.environ.pop("STRAY_CACHE_DIR", None)
        else:
            os.environ["STRAY_CACHE_DIR"] = old


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_mutual_exclusion():
    """Two threads increment a shared counter 500 times each inside the lock.
    Without mutual exclusion a read-modify-write race would lose increments."""
    with tempfile.TemporaryDirectory() as d:
        os.environ["STRAY_CACHE_DIR"] = d
        try:
            counter = [0]
            errors = []

            def worker():
                try:
                    for _ in range(500):
                        with _cache_lock.cache_lock("overrides"):
                            v = counter[0]
                            # Yield to encourage interleaving (best-effort).
                            counter[0] = v + 1
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start(); t2.start()
            t1.join(); t2.join()

            assert not errors, f"Thread errors: {errors}"
            assert counter[0] == 1000, (
                f"Expected 1000 increments, got {counter[0]} — mutual exclusion violated"
            )
        finally:
            os.environ.pop("STRAY_CACHE_DIR", None)


def test_noop_degradation():
    """When _fcntl is None the context manager still executes the body."""
    original = _cache_lock._fcntl
    _cache_lock._fcntl = None  # type: ignore[assignment]
    try:
        ran = []
        with tempfile.TemporaryDirectory() as d:
            os.environ["STRAY_CACHE_DIR"] = d
            try:
                with _cache_lock.cache_lock("overrides"):
                    ran.append(1)
            finally:
                os.environ.pop("STRAY_CACHE_DIR", None)
        assert ran == [1], f"Body did not run in no-op mode: {ran}"
    finally:
        _cache_lock._fcntl = original


def test_different_lock_names_independent():
    """Locks with different names must not block each other."""
    with tempfile.TemporaryDirectory() as d:
        os.environ["STRAY_CACHE_DIR"] = d
        try:
            results = []

            def hold_overrides():
                with _cache_lock.cache_lock("overrides"):
                    results.append("overrides-start")
                    # While holding 'overrides', acquire 'dashboard' — should
                    # NOT deadlock.
                    with _cache_lock.cache_lock("dashboard"):
                        results.append("dashboard-inside")
                    results.append("overrides-end")

            t = threading.Thread(target=hold_overrides)
            t.start()
            t.join(timeout=5)
            assert not t.is_alive(), "Deadlock: thread did not finish in 5 s"
            assert results == ["overrides-start", "dashboard-inside", "overrides-end"]
        finally:
            os.environ.pop("STRAY_CACHE_DIR", None)


def test_lock_file_created():
    """The lock file is created inside cache/.locks/."""
    with tempfile.TemporaryDirectory() as d:
        os.environ["STRAY_CACHE_DIR"] = d
        try:
            with _cache_lock.cache_lock("mylock"):
                pass
        finally:
            os.environ.pop("STRAY_CACHE_DIR", None)
        lock_path = os.path.join(d, ".locks", "mylock.lock")
        assert os.path.exists(lock_path), f"Lock file not created: {lock_path}"


# ---------------------------------------------------------------------------
# __main__ runner (same style as test_subcards.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except Exception as e:
            import traceback
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)

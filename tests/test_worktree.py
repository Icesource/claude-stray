"""DD-024 first test (and DD-022-A safety net): the mechanical worktree resolver.

Runs with zero deps:  python3 tests/test_worktree.py
Also discoverable by: python3 -m pytest tests/
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _worktree  # noqa: E402


def test_main_checkout():
    """cwd = this repo's main checkout → worktree==repo root, is_worktree False."""
    cl = _worktree.compute_code_location(REPO)
    assert cl is not None, "this repo should be a git repo"
    assert os.path.samefile(cl["worktree"], REPO), cl
    assert cl["is_worktree"] is False, cl
    assert os.path.samefile(cl["main_repo"], REPO), cl
    assert cl["branch"], "branch should be non-empty"


def test_non_git_dir():
    """A plain temp dir (no .git anywhere) → None."""
    with tempfile.TemporaryDirectory() as d:
        # ensure the temp dir isn't itself inside a repo (it isn't on macOS /tmp)
        assert _worktree.compute_code_location(d) is None


def test_linked_worktree():
    """A real linked worktree → is_worktree True, main_repo points back to this repo."""
    with tempfile.TemporaryDirectory() as base:
        wt = os.path.join(base, "wt-test")
        branch = "stray-test-wt-DD022"
        add = subprocess.run(["git", "-C", REPO, "worktree", "add", "-b", branch, wt],
                             capture_output=True, text=True)
        if add.returncode != 0:
            # don't fail the suite if a stale branch exists; clean and retry once
            subprocess.run(["git", "-C", REPO, "branch", "-D", branch], capture_output=True)
            add = subprocess.run(["git", "-C", REPO, "worktree", "add", "-b", branch, wt],
                                 capture_output=True, text=True)
        assert add.returncode == 0, "git worktree add failed: " + add.stderr
        try:
            cl = _worktree.compute_code_location(wt)
            assert cl is not None and cl["is_worktree"] is True, cl
            assert os.path.samefile(cl["worktree"], wt), cl
            assert os.path.samefile(cl["main_repo"], REPO), cl
            assert cl["branch"] == branch, cl
        finally:
            subprocess.run(["git", "-C", REPO, "worktree", "remove", "--force", wt],
                           capture_output=True)
            subprocess.run(["git", "-C", REPO, "branch", "-D", branch], capture_output=True)


def test_cache_reuses(monkeypatch=None):
    """code_location_for_cwd caches within the TTL (git not re-shelled)."""
    calls = {"n": 0}
    real = _worktree.compute_code_location

    def counting(cwd):
        calls["n"] += 1
        return real(cwd)
    _worktree.compute_code_location = counting
    _worktree._CACHE.clear()
    try:
        a = _worktree.code_location_for_cwd(REPO)
        b = _worktree.code_location_for_cwd(REPO)
        assert a == b
        assert calls["n"] == 1, "second call should hit cache"
    finally:
        _worktree.compute_code_location = real
        _worktree._CACHE.clear()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)

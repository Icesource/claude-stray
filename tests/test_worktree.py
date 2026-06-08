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


def test_slugify():
    s = _worktree.slugify
    assert s("Authz Fix!") == "authz-fix"
    assert s("  改鉴权超时 timeout  ") == "timeout"          # non-ascii dropped, trimmed
    assert s("feat/HSF--doc__v2") == "feat-hsf-doc-v2"        # collapse + lowercase
    assert s("") == "" and s("中文") == ""                    # nothing usable → ''
    assert len(s("a" * 80)) == 40                              # capped


def test_changed_files():
    """changed_files reports uncommitted + committed-since-fork; empty on non-repo."""
    with tempfile.TemporaryDirectory() as d:
        def g(*a):
            return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        open(os.path.join(d, "base.txt"), "w").write("x\n")
        g("add", "-A"); g("commit", "-qm", "base")
        fork = g("rev-parse", "HEAD").stdout.strip()
        # commit a new file on top of the fork point
        open(os.path.join(d, "feat.py"), "w").write("y\n")
        g("add", "-A"); g("commit", "-qm", "feat")
        # and an uncommitted working-tree change
        open(os.path.join(d, "wip.py"), "w").write("z\n")
        g("add", "wip.py")
        files = _worktree.changed_files(d, fork)
        assert "feat.py" in files and "wip.py" in files, files
        assert "base.txt" not in files, files
        # no base_ref → only working-tree changes (feat.py was committed, so excluded)
        wt_only = _worktree.changed_files(d, "")
        assert "wip.py" in wt_only and "feat.py" not in wt_only, wt_only
    assert _worktree.changed_files("/no/such/dir") == []


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

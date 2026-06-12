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


def _main_checkout(cwd):
    """The MAIN checkout of this repo, even when the suite is run from inside a
    linked worktree (e.g. .claude/worktrees/*). main_repo = parent of the shared
    git-common-dir. Without this, the tests below would falsely assume REPO is a
    main checkout and break whenever run from a worktree."""
    common = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    if not os.path.isabs(common):
        common = os.path.abspath(os.path.join(cwd, common))
    return os.path.dirname(common)


MAIN_REPO = _main_checkout(REPO)


def test_main_checkout():
    """cwd = this repo's main checkout → worktree==repo root, is_worktree False."""
    cl = _worktree.compute_code_location(MAIN_REPO)
    assert cl is not None, "this repo should be a git repo"
    assert os.path.samefile(cl["worktree"], MAIN_REPO), cl
    assert cl["is_worktree"] is False, cl
    assert os.path.samefile(cl["main_repo"], MAIN_REPO), cl
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
        add = subprocess.run(["git", "-C", MAIN_REPO, "worktree", "add", "-b", branch, wt],
                             capture_output=True, text=True)
        if add.returncode != 0:
            # don't fail the suite if a stale branch exists; clean and retry once
            subprocess.run(["git", "-C", MAIN_REPO, "branch", "-D", branch], capture_output=True)
            add = subprocess.run(["git", "-C", MAIN_REPO, "worktree", "add", "-b", branch, wt],
                                 capture_output=True, text=True)
        assert add.returncode == 0, "git worktree add failed: " + add.stderr
        try:
            cl = _worktree.compute_code_location(wt)
            assert cl is not None and cl["is_worktree"] is True, cl
            assert os.path.samefile(cl["worktree"], wt), cl
            assert os.path.samefile(cl["main_repo"], MAIN_REPO), cl
            assert cl["branch"] == branch, cl
        finally:
            subprocess.run(["git", "-C", MAIN_REPO, "worktree", "remove", "--force", wt],
                           capture_output=True)
            subprocess.run(["git", "-C", MAIN_REPO, "branch", "-D", branch], capture_output=True)


def test_slugify():
    s = _worktree.slugify
    assert s("Authz Fix!") == "authz-fix"
    assert s("  改鉴权超时 timeout  ") == "timeout"          # non-ascii dropped, trimmed
    assert s("feat/HSF--doc__v2") == "feat-hsf-doc-v2"        # collapse + lowercase
    assert s("") == "" and s("中文") == ""                    # nothing usable → ''
    assert len(s("a" * 80)) == 40                              # capped


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


def test_merge_status_counts_untracked_as_dirty():
    """徽章与关闭守卫必须同一把尺子:未跟踪文件也是未保存变更(worktree remove
    会丢)。回归:fftest 未跟踪目录曾骗过徽章(✓已合并)却被 × 拦下。"""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as d:
        def g(*a, cwd=d):
            subprocess.run(["git", "-C", cwd, *a], capture_output=True, check=True)
        g("init", "-q", "-b", "main")
        g("config", "user.email", "t@t"); g("config", "user.name", "t")
        open(os.path.join(d, "f"), "w").write("x")
        g("add", "-A"); g("commit", "-qm", "init")
        wt = os.path.join(d, ".claude", "worktrees", "sub")
        g("worktree", "add", "-q", "-b", "worktree-sub", wt)
        _worktree._MERGE_CACHE.clear()
        ms = _worktree.merge_status(d, wt, "worktree-sub")
        assert ms and ms["dirty"] is False                  # 干净
        open(os.path.join(wt, "untracked.txt"), "w").write("draft")   # 未跟踪文件
        _worktree._MERGE_CACHE.clear()
        ms2 = _worktree.merge_status(d, wt, "worktree-sub")
        assert ms2["dirty"] is True, "未跟踪文件必须算 dirty(和关闭守卫一致)"


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

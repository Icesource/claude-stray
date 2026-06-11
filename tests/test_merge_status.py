"""_worktree.merge_status: a sub-card branch's merge state relative to the
trunk (drives the live 已合并/未合并/未提交 badge + the close-guard).
Run: python3 tests/test_merge_status.py
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _worktree  # noqa: E402


def _git(cwd, *a):
    subprocess.run(["git", "-C", cwd, *a], capture_output=True, check=True)


def _setup():
    d = os.path.realpath(tempfile.mkdtemp(prefix="ms-"))
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    open(os.path.join(d, "f.txt"), "w").write("0\n")
    _git(d, "add", "-A"); _git(d, "commit", "-q", "-m", "seed")
    return d


def _worktree_add(main, slug):
    wt = os.path.join(main, ".claude", "worktrees", slug)
    _git(main, "worktree", "add", "-q", "-b", "worktree-" + slug, wt)
    return wt, "worktree-" + slug


def test_unmerged_commit_is_ahead():
    d = _setup()
    wt, br = _worktree_add(d, "a")
    open(os.path.join(wt, "a.txt"), "w").write("x\n")
    _git(wt, "add", "-A"); _git(wt, "commit", "-q", "-m", "work")
    ms = _worktree.merge_status(d, wt, br)
    assert ms["ahead"] == 1 and ms["merged"] is False and ms["dirty"] is False, ms


def test_merged_after_main_ffs():
    d = _setup()
    wt, br = _worktree_add(d, "b")
    open(os.path.join(wt, "b.txt"), "w").write("x\n")
    _git(wt, "add", "-A"); _git(wt, "commit", "-q", "-m", "work")
    _git(d, "merge", "--ff-only", br)          # land it onto main
    ms = _worktree.merge_status(d, wt, br)
    assert ms["merged"] is True and ms["ahead"] == 0, ms


def test_no_own_commits_is_merged():
    d = _setup()
    wt, br = _worktree_add(d, "c")             # branch at main, no commits of its own
    ms = _worktree.merge_status(d, wt, br)
    assert ms["merged"] is True and ms["ahead"] == 0, ms


def test_dirty_worktree():
    d = _setup()
    wt, br = _worktree_add(d, "e")
    open(os.path.join(wt, "f.txt"), "a").write("dirty\n")   # tracked, uncommitted
    ms = _worktree.merge_status(d, wt, br)
    assert ms["dirty"] is True, ms


def test_cache_keyed_on_tip_and_mtime():
    d = _setup()
    wt, br = _worktree_add(d, "f")
    a = _worktree.merge_status(d, wt, br)
    b = _worktree.merge_status(d, wt, br)      # cache hit → same object
    assert a is b
    open(os.path.join(wt, "n.txt"), "w").write("x\n")
    _git(wt, "add", "-A"); _git(wt, "commit", "-q", "-m", "more")  # tip moves
    c = _worktree.merge_status(d, wt, br)
    assert c is not a and c["ahead"] == 1, (a, c)


def test_ttl_refreshes_uncommitted_edit():
    """Uncommitted edits move neither tip nor .git — the wall-clock TTL is what
    lets `dirty` surface. A clock past the TTL must trigger a recompute."""
    d = _setup()
    wt, br = _worktree_add(d, "g")
    clock = [1000.0]
    a = _worktree.merge_status(d, wt, br, _now=lambda: clock[0])
    assert a["dirty"] is False
    open(os.path.join(wt, "f.txt"), "a").write("edit\n")   # uncommitted; tip/.git unchanged
    # within TTL → still the cached clean result
    clock[0] += 3
    assert _worktree.merge_status(d, wt, br, _now=lambda: clock[0])["dirty"] is False
    # past TTL → recompute picks up the dirty tree
    clock[0] += 10
    assert _worktree.merge_status(d, wt, br, _now=lambda: clock[0])["dirty"] is True


def test_missing_branch_is_none():
    d = _setup()
    assert _worktree.merge_status(d, d, "worktree-nope") is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except Exception as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)

"""DD-025 test: classify mechanically mints a card for every registered sub-card
(the AI drops trivial 1-turn `claude -p` sub-cards) + worktree→repo workspace mapping.
Run: python3 tests/test_subcard_mint.py   (or via bin/test / pytest)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import classify  # noqa: E402


def test_ws_name_strips_worktree():
    f = classify._ws_name_for_cwd
    assert f("/Users/x/Code/myrepo/.claude/worktrees/authz") == "myrepo"  # parent repo, not slug
    assert f("/Users/x/Code/myrepo") == "myrepo"
    assert f("") == "misc"


def test_mint_creates_subcard_in_parent_repo_ws():
    sid = "child-1"
    fm = {"cwd": "/Users/x/Code/myrepo/.claude/worktrees/authz",
          "last_activity_at": "2026-06-08T00:00:00Z",
          "status_guess": "active", "next_step": "跑测试", "awaiting_user": ""}
    all_summaries = [(sid, fm, "", "")]
    subs = {sid: {"parent": "P", "slug": "authz-fix"}}
    mm = {"workspaces": []}
    n = classify.mint_subcard_initiatives(mm, all_summaries, subs, [])
    assert n == 1
    ws = mm["workspaces"][0]
    assert ws["name"] == "myrepo", ws["name"]          # parent repo, NOT "authz"
    i = ws["initiatives"][0]
    assert i["id"] == "subcard::child-1"
    assert i["name"] == "authz-fix"                    # the slug
    assert i["sessions"] == [sid] and i["level"] == "card"
    assert i["status"] == "active" and i["next_step"] == "跑测试"
    assert "awaiting_user" not in i                    # empty string omitted


def test_mint_skips_already_represented():
    """AI already emitted a card containing the session → no mint (no duplicate)."""
    sid = "child-1"
    all_summaries = [(sid, {"cwd": "/r/.claude/worktrees/a"}, "", "")]
    subs = {sid: {"parent": "P", "slug": "x"}}
    mm = {"workspaces": [{"name": "r", "initiatives": [{"id": "ai-card", "sessions": [sid]}]}]}
    assert classify.mint_subcard_initiatives(mm, all_summaries, subs, []) == 0


def test_mint_respects_deleted_tombstone():
    sid = "child-1"
    all_summaries = [(sid, {"cwd": "/r/.claude/worktrees/a"}, "", "")]
    subs = {sid: {"parent": "P", "slug": "x"}}
    mm = {"workspaces": []}
    assert classify.mint_subcard_initiatives(mm, all_summaries, subs, ["subcard::child-1"]) == 0


def test_mint_skips_subcard_without_summary():
    subs = {"ghost": {"parent": "P", "slug": "x"}}
    mm = {"workspaces": []}
    assert classify.mint_subcard_initiatives(mm, [], subs, []) == 0


def test_mint_empty_registry_noop():
    mm = {"workspaces": []}
    assert classify.mint_subcard_initiatives(mm, [], {}, []) == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except Exception as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)

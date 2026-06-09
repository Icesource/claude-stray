"""DD-027 test: the instant-citizen pending-card registry.
Run: python3 tests/test_pending.py   (or via bin/test / pytest)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _pending  # noqa: E402


def test_register_and_load():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pending-cards.json")
        _pending.register(p, "tok-1", name="授权超时", cwd="/repo",
                          worktree_path="/repo/.claude/worktrees/authz",
                          worktree_name="authz", parent="parent-A", _now=100)
        got = _pending.load(p)
        ent = got["tok-1"]
        assert ent["name"] == "授权超时"
        assert ent["parent"] == "parent-A"
        assert ent["worktree_name"] == "authz"
        assert ent["session_id"] is None
        assert ent["created_at"] == 100


def test_load_missing_is_empty():
    assert _pending.load("/no/such/file.json") == {}


def test_capture_sid_backfills():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pending-cards.json")
        _pending.register(p, "tok-1", name="x", _now=100)
        _pending.capture_sid(p, "tok-1", "sid-XYZ")
        assert _pending.load(p)["tok-1"]["session_id"] == "sid-XYZ"


def test_capture_sid_noop_when_pruned():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pending-cards.json")
        _pending.capture_sid(p, "gone", "sid-1")  # must not raise / create
        assert _pending.load(p) == {}


def test_remove():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pending-cards.json")
        _pending.register(p, "tok-1", name="x", _now=100)
        _pending.remove(p, "tok-1")
        assert _pending.load(p) == {}


def test_merge_adds_placeholder_when_no_real_card():
    mm = {"workspaces": [{"name": "repo", "cwd": "/repo", "initiatives": []}]}
    doc = {"tok-1": {"name": "授权超时", "cwd": "/repo",
                     "worktree_path": "/repo/.claude/worktrees/authz",
                     "worktree_name": "authz", "parent": "parent-A",
                     "session_id": None, "created_at": 1000}}
    added, stale = _pending.merge_into_mindmap(mm, doc, _now=1001)
    assert added == 1 and stale == []
    cards = mm["workspaces"][0]["initiatives"]
    assert len(cards) == 1
    c = cards[0]
    assert c["_pending"] is True
    assert c["id"] == "pending-tok-1"
    assert c["name"] == "授权超时"
    assert c["parent_session_id"] == "parent-A"
    assert c["code_location"]["worktree"] == "/repo/.claude/worktrees/authz"


def test_merge_drops_when_real_card_aligns_by_worktree():
    # a REAL card already exists with the same worktree path → placeholder dropped
    mm = {"workspaces": [{"name": "repo", "cwd": "/repo", "initiatives": [
        {"id": "real-1", "sessions": ["sid-real"],
         "code_location": {"worktree": "/repo/.claude/worktrees/authz"}},
    ]}]}
    doc = {"tok-1": {"name": "授权超时", "cwd": "/repo",
                     "worktree_path": "/repo/.claude/worktrees/authz",
                     "worktree_name": "authz", "parent": None,
                     "session_id": None, "created_at": 1000}}
    added, stale = _pending.merge_into_mindmap(mm, doc, _now=1001)
    assert added == 0
    assert stale == ["tok-1"]
    assert len(mm["workspaces"][0]["initiatives"]) == 1  # only the real card


def test_merge_drops_when_real_card_aligns_by_sid():
    mm = {"workspaces": [{"name": "repo", "cwd": "/repo", "initiatives": [
        {"id": "real-1", "sessions": ["sid-captured"]},
    ]}]}
    doc = {"tok-1": {"name": "x", "cwd": "/repo", "worktree_path": None,
                     "worktree_name": None, "parent": None,
                     "session_id": "sid-captured", "created_at": 1000}}
    added, stale = _pending.merge_into_mindmap(mm, doc, _now=1001)
    assert added == 0 and stale == ["tok-1"]


def test_merge_expires_stale_placeholder():
    mm = {"workspaces": []}
    doc = {"tok-1": {"name": "x", "cwd": "/repo", "worktree_path": None,
                     "worktree_name": None, "parent": None,
                     "session_id": None, "created_at": 0}}
    added, stale = _pending.merge_into_mindmap(mm, doc, _now=_pending.TTL + 1)
    assert added == 0 and stale == ["tok-1"]


def test_merge_creates_synthetic_workspace_for_new_repo():
    # no workspace matches the repo → a synthetic one is created so the card shows
    mm = {"workspaces": [{"name": "other", "cwd": "/other", "initiatives": []}]}
    doc = {"tok-1": {"name": "新活", "cwd": "/fresh-repo", "worktree_path": None,
                     "worktree_name": None, "parent": None,
                     "session_id": None, "created_at": 1000}}
    added, stale = _pending.merge_into_mindmap(mm, doc, _now=1001)
    assert added == 1 and stale == []
    assert len(mm["workspaces"]) == 2
    new_ws = mm["workspaces"][1]
    assert new_ws["initiatives"][0]["name"] == "新活"


def test_merge_no_placeholder_no_crash():
    assert _pending.merge_into_mindmap({"workspaces": []}, {}, _now=1) == (0, [])
    assert _pending.merge_into_mindmap(None, {"a": {}}, _now=1) == (0, [])


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

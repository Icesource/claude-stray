"""DD-030: the unified created-cards registry.
Run: python3 tests/test_created.py   (or via bin/test / pytest)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _created  # noqa: E402


def test_register_capture_remove():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "created-cards.json")
        _created.register(p, "tok-1", name="改鉴权", cwd="/r", parent="P", _now=100)
        got = _created.load(p)
        assert got["tok-1"]["sid"] is None and got["tok-1"]["parent"] == "P"
        _created.capture_sid(p, "tok-1", "sid-A")
        assert _created.load(p)["tok-1"]["sid"] == "sid-A"
        assert _created.remove_by_sid(p, "sid-A") is True
        assert _created.load(p) == {}


def test_by_sid_and_registered_sids():
    doc = {"t1": {"sid": "s1", "parent": "P"}, "t2": {"sid": None}, "t3": {"sid": "s3"}}
    assert set(_created.registered_sids(doc)) == {"s1", "s3"}   # t2 (no sid) excluded
    assert _created.by_sid(doc)["s1"]["parent"] == "P"


def test_link_sets_parent_on_card():
    doc = {"t1": {"sid": "child", "parent": "parent-A"}}
    mm = {"workspaces": [{"initiatives": [
        {"id": "card::child", "sessions": ["child"]},
        {"id": "other", "sessions": ["x"]},
    ]}]}
    assert _created.link(mm, doc) == 1
    inits = {i["id"]: i for i in mm["workspaces"][0]["initiatives"]}
    assert inits["card::child"]["parent_session_id"] == "parent-A"
    assert "parent_session_id" not in inits["other"]


def test_merge_shows_placeholder_until_real_card():
    doc = {"t1": {"sid": "s1", "name": "改鉴权", "cwd": "/r", "created_at": 100}}
    mm = {"workspaces": []}
    added, stale = _created.merge_into_mindmap(mm, doc, _now=200)
    assert added == 1 and stale == []
    card = mm["workspaces"][0]["initiatives"][0]
    assert card["_pending"] is True and card["id"] == "card::s1"
    assert card["name"] == "改鉴权" and card["sessions"] == ["s1"]
    # 'band' is NOT forced — _pending is an orthogonal badge
    assert "band" not in card


def test_merge_hides_placeholder_when_real_card_exists_but_keeps_entry():
    doc = {"t1": {"sid": "s1", "name": "x", "created_at": 100}}
    mm = {"workspaces": [{"name": "r", "cwd": "/r",
                          "initiatives": [{"id": "card::s1", "sessions": ["s1"]}]}]}
    added, stale = _created.merge_into_mindmap(mm, doc, _now=200)
    assert added == 0                       # real card present → no placeholder
    assert stale == []                      # but entry KEPT (durable, classify still uses it)


def test_merge_prunes_failed_launch_only():
    doc = {"nosid": {"sid": None, "created_at": 0},          # no sid, old → failed launch
           "working": {"sid": "s9", "created_at": 0}}        # has sid, old → KEEP
    mm = {"workspaces": []}
    _added, stale = _created.merge_into_mindmap(mm, doc, _now=10_000)
    assert stale == ["nosid"]               # only the failed launch is pruned


def test_provisional_name_falls_back():
    doc = {"t1": {"sid": "s1", "initial_task": "排查超时", "created_at": 1}}
    mm = {"workspaces": []}
    _created.merge_into_mindmap(mm, doc, _now=2)
    assert mm["workspaces"][0]["initiatives"][0]["name"] == "排查超时"
    doc2 = {"t2": {"sid": "s2", "created_at": 1}}            # no name/task
    mm2 = {"workspaces": []}
    _created.merge_into_mindmap(mm2, doc2, _now=2)
    assert mm2["workspaces"][0]["initiatives"][0]["name"] == "准备中…"


def test_subtask_metadata():
    doc = {"t1": {"sid": "c1", "parent": "P"}, "t2": {"sid": "c2", "parent": "OTHER"}}
    mm = {"workspaces": [{"initiatives": [
        {"name": "改鉴权", "sessions": ["c1"], "status": "active",
         "progress": "写了 handler\n还差测试", "blockers": ["等评审"], "next_step": "加测试",
         "code_location": {"worktree": "/w/a", "branch": "worktree-a"}},
        {"name": "别人的", "sessions": ["c2"]},
    ]}]}
    md = _created.subtask_metadata("P", mm, doc, jsonl_lookup=lambda s: f"/j/{s}.jsonl")
    assert {m["name"] for m in md} == {"改鉴权"}        # only P's child
    m = md[0]
    assert m["session_id"] == "c1" and m["progress"] == "写了 handler"
    assert m["worktree"] == "/w/a" and m["jsonl"] == "/j/c1.jsonl"


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

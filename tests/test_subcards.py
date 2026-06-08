"""DD-025 slice 1 test: the sub-card parent/child registry.
Run: python3 tests/test_subcards.py   (or via bin/test / pytest)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _subcards  # noqa: E402


def test_record_and_load():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "subcards.json")
        _subcards.record(p, "child-1", "parent-A", slug="authz-fix", _now=123)
        _subcards.record(p, "child-2", "parent-A", slug="authz-doc", _now=124)
        got = _subcards.load(p)
        assert got["child-1"] == {"parent": "parent-A", "slug": "authz-fix", "created_at": 123}
        assert got["child-2"]["parent"] == "parent-A"


def test_load_missing_is_empty():
    assert _subcards.load("/no/such/file.json") == {}


def test_link_sets_parent():
    subcards = {"child-1": {"parent": "parent-A"}, "child-2": {"parent": "parent-A"}}
    mm = {"workspaces": [{"initiatives": [
        {"id": "i1", "sessions": ["child-1"]},          # a sub-card
        {"id": "i2", "sessions": ["parent-A"]},          # the parent itself
        {"id": "i3", "sessions": ["unrelated"]},         # unrelated
        {"id": "i4", "sessions": []},                    # no session
    ]}]}
    n = _subcards.link(mm, subcards)
    inits = {i["id"]: i for i in mm["workspaces"][0]["initiatives"]}
    assert n == 1
    assert inits["i1"].get("parent_session_id") == "parent-A"
    assert "parent_session_id" not in inits["i2"]
    assert "parent_session_id" not in inits["i3"]
    assert "parent_session_id" not in inits["i4"]


def test_find_session_by_cwd():
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "projects")
        enc = os.path.join(proj, "-Users-x-repo--claude-worktrees-authz")
        sub = os.path.join(proj, "subagents")
        os.makedirs(enc); os.makedirs(sub)
        # a real child session in the worktree cwd
        with open(os.path.join(enc, "child-sid.jsonl"), "w") as f:
            f.write('{"cwd": "/Users/x/repo/.claude/worktrees/authz"}\n')
        # a teammate in subagents with the SAME cwd → must be ignored
        with open(os.path.join(sub, "agent-z.jsonl"), "w") as f:
            f.write('{"cwd": "/Users/x/repo/.claude/worktrees/authz"}\n')
        got = _subcards.find_session_by_cwd(proj, "/Users/x/repo/.claude/worktrees/authz")
        assert got == "child-sid", got
        # non-matching prefix → None
        assert _subcards.find_session_by_cwd(proj, "/other/path") is None


def test_subtask_metadata():
    subcards = {"c1": {"parent": "P"}, "c2": {"parent": "P"}, "c3": {"parent": "OTHER"}}
    mm = {"workspaces": [{"initiatives": [
        {"name": "改鉴权", "sessions": ["c1"], "status": "active",
         "progress": "写了 handler\n还差测试", "blockers": ["等评审"], "next_step": "加测试",
         "code_location": {"worktree": "/w/authz", "branch": "worktree-authz"}},
        {"name": "写文档", "sessions": ["c2"], "status": "done", "progress": "完成"},
        {"name": "别人的", "sessions": ["c3"]},
        {"name": "父卡", "sessions": ["P"]},
    ]}]}
    md = _subcards.subtask_metadata("P", mm, subcards, jsonl_lookup=lambda s: f"/j/{s}.jsonl")
    assert {m["name"] for m in md} == {"改鉴权", "写文档"}
    a = next(m for m in md if m["session_id"] == "c1")
    assert a["progress"] == "写了 handler 还差测试" and a["blockers"] == ["等评审"]
    assert a["worktree"] == "/w/authz" and a["jsonl"] == "/j/c1.jsonl"


def test_find_conflicts():
    fb = {"a": ["x.py", "y.py"], "b": ["y.py", "z.py"], "c": ["q.py"]}
    out = _subcards.find_conflicts(fb)
    assert out == {"a": ["b"], "b": ["a"]}        # a&b share y.py; c alone
    assert _subcards.find_conflicts({}) == {}


def test_link_empty_registry_noop():
    mm = {"workspaces": [{"initiatives": [{"id": "i1", "sessions": ["x"]}]}]}
    assert _subcards.link(mm, {}) == 0
    assert "parent_session_id" not in mm["workspaces"][0]["initiatives"][0]


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

"""DD-029 test: stabilize_card_ids_against_prior kills AI id-churn.
Run: python3 tests/test_id_stability.py   (or via bin/test / pytest)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import classify  # noqa: E402

f = classify.stabilize_card_ids_against_prior


def test_single_session_id_pinned_to_prior():
    """AI renamed the same session's card → reuse the prior id."""
    prior = {"workspaces": [{"initiatives": [
        {"id": "dd-024-dead-code-cleanup", "sessions": ["s1"]}]}]}
    new = {"workspaces": [{"initiatives": [
        {"id": "render-html-cleanup", "sessions": ["s1"], "name": "新名字也无妨"}]}]}
    assert f(new, prior) == 1
    i = new["workspaces"][0]["initiatives"][0]
    assert i["id"] == "dd-024-dead-code-cleanup"   # id pinned
    assert i["name"] == "新名字也无妨"               # name left to AI


def test_exact_multi_session_tuple_matches():
    prior = {"workspaces": [{"initiatives": [
        {"id": "thread-A", "sessions": ["a", "b"]}]}]}
    new = {"workspaces": [{"initiatives": [
        {"id": "ai-renamed", "sessions": ["b", "a"]}]}]}   # order-insensitive
    assert f(new, prior) == 1
    assert new["workspaces"][0]["initiatives"][0]["id"] == "thread-A"


def test_no_match_keeps_ai_id():
    """Brand-new session the prior never saw → AI id becomes the anchor."""
    prior = {"workspaces": [{"initiatives": [{"id": "old", "sessions": ["x"]}]}]}
    new = {"workspaces": [{"initiatives": [{"id": "fresh", "sessions": ["y"]}]}]}
    assert f(new, prior) == 0
    assert new["workspaces"][0]["initiatives"][0]["id"] == "fresh"


def test_session_split_out_of_thread_not_misanchored():
    """A session leaving a prior MULTI-session thread must NOT inherit the
    thread's id (single-sid fallback only consults prior single-session cards)."""
    prior = {"workspaces": [{"initiatives": [
        {"id": "thread-AB", "sessions": ["a", "b"]}]}]}
    new = {"workspaces": [{"initiatives": [
        {"id": "ai-a", "sessions": ["a"]}]}]}              # 'a' split out, now solo
    assert f(new, prior) == 0
    assert new["workspaces"][0]["initiatives"][0]["id"] == "ai-a"


def test_sealed_card_skipped():
    """Empty sessions[] (sealed) carry their own anchor — never rewritten."""
    prior = {"workspaces": [{"initiatives": [{"id": "p", "sessions": []}]}]}
    new = {"workspaces": [{"initiatives": [{"id": "sealed::mr::1", "sessions": []}]}]}
    assert f(new, prior) == 0
    assert new["workspaces"][0]["initiatives"][0]["id"] == "sealed::mr::1"


def test_deleted_card_cannot_resurrect_under_new_slug():
    """The point of pinning: a user-deleted card the AI re-emits with a fresh
    slug gets pinned back to the tombstoned id, so the downstream deleted_ids
    re-strip can suppress it again (no zombie resurrection)."""
    prior = {"workspaces": [{"initiatives": [
        {"id": "claude-stray-webterminal-copy-fix", "sessions": ["s9"]}]}]}
    new = {"workspaces": [{"initiatives": [
        {"id": "webterminal-native-selection", "sessions": ["s9"]}]}]}
    f(new, prior)
    assert new["workspaces"][0]["initiatives"][0]["id"] == "claude-stray-webterminal-copy-fix"


def test_no_prior_is_noop():
    new = {"workspaces": [{"initiatives": [{"id": "x", "sessions": ["s"]}]}]}
    assert f(new, None) == 0 and f(new, {}) == 0


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

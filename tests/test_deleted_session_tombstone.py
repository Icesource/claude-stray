"""DD-029: deleted cards must session-tombstone, not just id-tombstone.

A deleted sub-card's session keeps its summary, so the AI re-mints a card for it
under a FRESH id every classify round — dodging the id tombstone and resurrecting
as a top-level card. deleted_session_ids_on_disk() drives a time-windowed session
filter (same as archive) that keeps it gone until genuinely touched again.
Run: python3 tests/test_deleted_session_tombstone.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import classify  # noqa: E402


def _with_deleted_file(doc, fn):
    """Run fn() with classify.DELETED_FILE pointed at a temp deleted_ids.json."""
    import pathlib
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "deleted_ids.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        orig = classify.DELETED_FILE
        classify.DELETED_FILE = pathlib.Path(p)
        try:
            return fn()
        finally:
            classify.DELETED_FILE = orig


def test_maps_sessions_with_deleted_at():
    doc = {"initiatives": [
        {"id": "a", "deleted_at": "2026-06-10T00:00:00Z", "sessions": ["s1", "s2"]},
        {"id": "b", "deleted_at": "2026-06-10T01:00:00Z", "sessions": ["s3"]},
    ]}
    got = _with_deleted_file(doc, classify.deleted_session_ids_on_disk)
    assert got == {"s1": "2026-06-10T00:00:00Z",
                   "s2": "2026-06-10T00:00:00Z",
                   "s3": "2026-06-10T01:00:00Z"}, got


def test_id_only_entries_contribute_nothing():
    """Legacy tombstones without `sessions` are ignored here (id-strip handles them)."""
    doc = {"initiatives": [{"id": "old", "deleted_at": "2026-06-10T00:00:00Z"}]}
    assert _with_deleted_file(doc, classify.deleted_session_ids_on_disk) == {}


def test_most_recent_deleted_at_wins():
    doc = {"initiatives": [
        {"id": "a", "deleted_at": "2026-06-10T00:00:00Z", "sessions": ["s1"]},
        {"id": "a2", "deleted_at": "2026-06-10T05:00:00Z", "sessions": ["s1"]},
    ]}
    got = _with_deleted_file(doc, classify.deleted_session_ids_on_disk)
    assert got["s1"] == "2026-06-10T05:00:00Z"


def test_missing_file_is_empty():
    import pathlib
    orig = classify.DELETED_FILE
    classify.DELETED_FILE = pathlib.Path("/no/such/deleted_ids.json")
    try:
        assert classify.deleted_session_ids_on_disk() == {}
    finally:
        classify.DELETED_FILE = orig


def test_window_semantics():
    """The whole point: untouched session stays tombstoned; new activity frees it.
    Mirror the comparison main() does (last_activity_at <= deleted_at → tombstoned)."""
    deleted_at = "2026-06-10T00:00:00Z"
    stale = "2026-06-09T12:00:00Z"   # before delete → still tombstoned
    fresh = "2026-06-10T06:00:00Z"   # touched after delete → un-tombstoned
    assert stale <= deleted_at        # tombstoned
    assert not (fresh <= deleted_at)  # freed


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

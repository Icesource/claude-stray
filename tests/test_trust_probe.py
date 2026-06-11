"""Folder-trust advisory heuristic (DD-032 follow-up, 2026-06-11 边界):
the dialog fires only for cwds with NO ~/.claude.json projects entry on the
path itself, an ancestor, or a prior child path. Advisory only — never blocks.
Run: python3 tests/test_trust_probe.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _created      # noqa: E402
import _subcard_api  # noqa: E402

trusted = _subcard_api.repo_probably_trusted


def test_exact_entry():
    assert trusted("/a/repo", {"/a/repo": {}})


def test_ancestor_entry():
    # an entry on an ancestor suppresses the dialog (observed: /Users/bby
    # covers everything beneath it)
    assert trusted("/a/repo", {"/a": {}})


def test_child_entry_counts():
    # a previously-opened worktree beneath the repo is evidence too
    assert trusted("/a/repo", {"/a/repo/.claude/worktrees/x": {}})


def test_unknown_path_untrusted():
    assert not trusted("/var/folders/tmp123/repo", {"/a/repo": {}})


def test_flag_value_is_irrelevant():
    # hasTrustDialogAccepted: False does NOT prompt — entry existence is the signal
    assert trusted("/a/repo", {"/a/repo": {"hasTrustDialogAccepted": False}})


def test_unreadable_config_stays_quiet():
    assert trusted("/a/repo", None) in (True, False)  # never raises


def test_annotate_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "created.json")
        _created.register(p, "tok", name="x", cwd="/r")
        _created.annotate(p, "tok", stuck_trust=True)
        assert _created.load(p)["tok"]["stuck_trust"] is True
        _created.annotate(p, "gone-token", stuck_trust=True)  # no-op, no raise
        card = _created._placeholder_card("tok", _created.load(p)["tok"], 0)
        assert card["_stuck"] == "trust"


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

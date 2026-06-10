"""Regression: live status must not infer 'running' from non-turn jsonl writes.
A card flipped to 运行中 with no message sent — because ai-title / file-history-snapshot
/ attachment / sub-agent(isSidechain) writes bump the file mtime, and the old code
used mtime as the "AI is working" signal. _last_turn_epoch ignores those.
Run: python3 tests/test_live_status.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("serve", os.path.join(REPO, "bin", "serve.py"))
serve = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(serve)            # safe: server only starts under __main__
except SystemExit:
    pass


def _iso(ep):
    return datetime.fromtimestamp(ep, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_ignores_non_turn_writes():
    now = time.time()
    old_turn = now - 30000        # last real turn: ~8h ago
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.jsonl")
        _write(p, [
            {"type": "user", "timestamp": _iso(old_turn), "message": {"role": "user"}},
            {"type": "assistant", "timestamp": _iso(old_turn + 5), "message": {"role": "assistant"}},
            # recent NON-turn writes that bump file mtime but are not the AI working:
            {"type": "ai-title", "timestamp": _iso(now - 10)},
            {"type": "file-history-snapshot", "timestamp": _iso(now - 8)},
            {"type": "user", "timestamp": _iso(now - 6), "isSidechain": True, "message": {"role": "user"}},
        ])
        os.utime(p, (now, now))   # file mtime = now (fresh)
        lt = serve._last_turn_epoch(p)
        assert abs(lt - (old_turn + 5)) < 2, f"should be the real turn ~8h ago, got {now - lt:.0f}s ago"
        assert (now - lt) > 3000, "must read as stale (no recent real turn) → won't fake running"


def test_counts_a_real_recent_turn():
    now = time.time()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.jsonl")
        _write(p, [
            {"type": "user", "timestamp": _iso(now - 4000), "message": {"role": "user"}},
            {"type": "assistant", "timestamp": _iso(now - 20), "message": {"role": "assistant"}},
        ])
        lt = serve._last_turn_epoch(p)
        assert (now - lt) < 60, "a real recent assistant turn must count → running still detected"


def test_empty_or_missing():
    assert serve._last_turn_epoch("") == 0.0
    assert serve._last_turn_epoch("/no/such/file.jsonl") == 0.0


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

"""DD-029: _subcards.record/remove must be lost-update safe under concurrency.

The atomic os.replace only prevents a TORN file; without a lock, two processes
that both load() the old map and write back will clobber each other (last writer
wins). This drove the user-visible "sub-card 条目莫名其妙少了 → 子卡浮到顶层" bug
when a `stray spawn` raced a re-register. Run: python3 tests/test_subcards_concurrency.py
"""
import multiprocessing as mp
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _subcards  # noqa: E402


def _record_worker(path, n):
    _subcards.record(path, f"child-{n}", "parent-P", slug=f"s{n}")


def test_parallel_records_no_lost_update():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "subcards.json")
        N = 24
        # fork: children inherit the imported module; spawn can't re-exec a test
        # run cleanly on macOS. fork is fine for this short CPU-light section.
        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_record_worker, args=(p, n)) for n in range(N)]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join()
        got = _subcards.load(p)
        assert len(got) == N, f"lost updates: only {len(got)}/{N} survived"
        assert all(f"child-{n}" in got for n in range(N))


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

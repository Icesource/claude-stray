"""DD-031: sub-card merge-closure orchestration (pure logic).
Run: python3 tests/test_merge.py   (or via bin/test / pytest)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _merge  # noqa: E402


def test_merge_branch():
    assert _merge.merge_branch("authz-fix") == "merge-authz-fix"
    assert _merge.merge_branch("") == "merge-subcard"


def test_precheck():
    f = _merge.evaluate_precheck
    assert f(0, False, True)["ok"] is False          # no commits ahead
    assert "无可合并" in f(0, False, True)["reason"]
    assert f(3, False, False)["ok"] is False          # target missing
    ok = f(3, False, True)
    assert ok["ok"] is True and ok["warn"] == ""
    warn = f(3, True, True)                            # dirty sub-card → warn, still ok
    assert warn["ok"] is True and "未提交" in warn["warn"]


def test_landing_plan():
    f = _merge.landing_plan
    assert f(True, False) == "ff_here"                # checked out here, clean
    assert f(True, True) == "blocked_wip"             # checked out here, WIP → refuse
    assert f(False, False) == "ff_ref"                # not checked out → advance ref
    assert f(False, True) == "ff_ref"                 # main dirty irrelevant when not on target


def test_serial_queue():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "merge-jobs.json")
        j1, started1 = _merge.add_job(p, sub_sid="A", sub_slug="a",
                                      target_branch="main", main_repo="/r", _now=1)
        assert started1 is True                       # first → may start
        # mark it active (resolving)
        _merge.update_job(p, "A", state="resolving", merge_sid="mA")
        j2, started2 = _merge.add_job(p, sub_sid="B", sub_slug="b",
                                      target_branch="main", main_repo="/r", _now=2)
        assert started2 is False                      # serial: B queues behind active A
        assert _merge.has_active(p) is True
        assert _merge.next_queued(p) is None          # A still active → nothing to start
        # A lands → removed
        assert _merge.remove_job(p, "A") is True
        nq = _merge.next_queued(p)
        assert nq and nq["sub_sid"] == "B"            # now B is next


def test_add_job_idempotent():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "merge-jobs.json")
        _merge.add_job(p, sub_sid="A", sub_slug="a", target_branch="main", main_repo="/r", _now=1)
        _merge.update_job(p, "A", state="resolving")
        j, started = _merge.add_job(p, sub_sid="A", sub_slug="a",
                                    target_branch="main", main_repo="/r", _now=2)
        assert started is True and j["state"] == "resolving"  # focus existing, no dup
        assert len(_merge.load(p)["jobs"]) == 1


def test_job_by_merge_sid():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "merge-jobs.json")
        _merge.add_job(p, sub_sid="A", sub_slug="a", target_branch="main", main_repo="/r", _now=1)
        _merge.update_job(p, "A", merge_sid="m-123")
        assert _merge.job_by_merge_sid(p, "m-123")["sub_sid"] == "A"
        assert _merge.job_by_merge_sid(p, "nope") is None


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

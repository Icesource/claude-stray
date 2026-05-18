#!/usr/bin/env python3
"""
Regression test for DD-011 task-persistence invariants.

DD-011 contract:
  - Tasks live ONLY in mindmap.json (no task_archive/).
  - Each task has {id, title, status: pending|done|cancelled,
    evidence?, terminal_at?}.
  - AI is additive: PRIOR tasks must survive every classify round.
  - Terminal statuses (done, cancelled) are monotone from AI's
    perspective; only user-toggles can revive them.
  - AI may flip pending→done or pending→cancelled with evidence.

Scenarios — all must pass:

  1. Empty session frontmatter vs PRIOR carrying 5 tasks. The
     2026-05-18 incident. All 5 PRIOR tasks survive in init.tasks.

  2. PRIOR has 1 pending + 1 done + 1 cancelled. AI continuation
     emits all three with their PRIOR statuses. All three survive
     with status intact.

  3. Hot summary adds 2 new tasks not in PRIOR. init.tasks has all
     7 (PRIOR 5 + 2 new), each with status field set.

  4. AI tries to flip a PRIOR `cancelled` task back to `pending` —
     terminal-monotone forces it back to `cancelled`.

  5. AI flips a PRIOR pending task to `cancelled` with evidence —
     it's accepted (post-process keeps the status + evidence +
     stamps terminal_at).

Exit 0 = all pass. Exit 1 = at least one regression.

Run:
  python3 bin/_test_task_persistence.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


TMP_ROOT = Path(tempfile.mkdtemp(prefix="ccw-test-dd011-"))
TMP_CACHE = TMP_ROOT / "cache"
TMP_SUMMARIES = TMP_CACHE / "summaries"
TMP_CACHE.mkdir(parents=True)
TMP_SUMMARIES.mkdir()


def _patch_classify_paths():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import classify
    classify.CACHE_DIR = TMP_CACHE
    classify.SESSIONS_DIR = TMP_CACHE / "sessions"
    classify.SUMMARIES_DIR = TMP_SUMMARIES
    classify.MINDMAP_FILE = TMP_CACHE / "mindmap.json"
    return classify


def _make_summary(sid: str, *, last_activity_at: str,
                  tasks: list[dict] | None) -> None:
    fm = [
        "---",
        f"session_id: {sid}",
        "cwd: /tmp/test",
        f"last_activity_at: {last_activity_at}",
        "user_turns: 4",
        f"updated_at: {last_activity_at}",
        "status_guess: active",
    ]
    if tasks:
        fm.append("tasks:")
        for t in tasks:
            fm.append(f"  - title: {t['title']}")
            fm.append(f"    status: {t['status']}")
            if t.get("evidence"):
                fm.append(f"    evidence: {t['evidence']}")
    fm.append("---")
    fm.append("")
    fm.append("# 目标")
    fm.append("synthetic test fixture")
    (TMP_SUMMARIES / f"{sid}.md").write_text("\n".join(fm) + "\n")


failures: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        failures.append(msg)


def _tasks_by_id(tasks):
    return {t["id"]: t for t in tasks}


def main() -> int:
    cf = _patch_classify_paths()

    # === Scenario 1: empty session vs PRIOR with 5 pending tasks =========
    print("\n[scenario 1] empty session summary vs PRIOR with 5 tasks")
    SID = "ffffffff-1111-2222-3333-444444444444"
    _make_summary(SID, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i1", "name": "i1", "status": "active",
                "sessions": [SID],
                "tasks": [
                    {"id": f"t{i}", "title": f"Task {i}", "status": "pending"}
                    for i in range(5)
                ],
            }],
        }],
    }
    new_mm = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i1", "name": "i1", "status": "active",
                "sessions": [SID], "tasks": [],
            }],
        }],
    }
    hot = list(cf.collect_summaries())
    cf.aggregate_tasks(new_mm, prior, hot)
    init = new_mm["workspaces"][0]["initiatives"][0]
    check(len(init["tasks"]) == 5,
          f"all 5 PRIOR tasks survive (got {len(init['tasks'])})")
    check(all(t["status"] == "pending" for t in init["tasks"]),
          "all 5 stay pending")
    check(not any("tasks_archived_count" in init for init in [init]),
          "no tasks_archived_count field appears")

    # === Scenario 2: PRIOR mix of pending+done+cancelled ================
    print("\n[scenario 2] PRIOR has pending + done + cancelled mix")
    SID2 = "ffffffff-1111-2222-3333-555555555555"
    _make_summary(SID2, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior2 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i2", "name": "i2", "status": "active",
                "sessions": [SID2],
                "tasks": [
                    {"id": "open-1", "title": "Open one", "status": "pending"},
                    {"id": "done-1", "title": "Done one", "status": "done",
                     "evidence": "merged 27411369",
                     "terminal_at": "2026-05-15T10:00:00Z"},
                    {"id": "canc-1", "title": "Cancelled one",
                     "status": "cancelled",
                     "evidence": "merged into Open one",
                     "terminal_at": "2026-05-16T10:00:00Z"},
                ],
            }],
        }],
    }
    new_mm2 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i2", "name": "i2", "status": "active",
                "sessions": [SID2], "tasks": [],
            }],
        }],
    }
    hot2 = list(cf.collect_summaries())
    cf.aggregate_tasks(new_mm2, prior2, hot2)
    init2 = new_mm2["workspaces"][0]["initiatives"][0]
    by_id = _tasks_by_id(init2["tasks"])
    check(by_id.get("open-1", {}).get("status") == "pending",
          "pending PRIOR stays pending")
    check(by_id.get("done-1", {}).get("status") == "done",
          "done PRIOR stays done")
    check(by_id.get("canc-1", {}).get("status") == "cancelled",
          "cancelled PRIOR stays cancelled")
    check(by_id.get("done-1", {}).get("evidence") == "merged 27411369",
          "done evidence preserved verbatim")
    check(by_id.get("canc-1", {}).get("evidence") == "merged into Open one",
          "cancelled evidence preserved verbatim")

    # === Scenario 3: session adds 2 new tasks ============================
    print("\n[scenario 3] session adds 2 new tasks; PRIOR still survives")
    SID3 = "ffffffff-1111-2222-3333-666666666666"
    _make_summary(SID3, last_activity_at="2026-05-18T07:00:00Z", tasks=[
        {"title": "Brand new A", "status": "pending"},
        {"title": "Brand new B", "status": "done", "evidence": "shipped"},
    ])
    prior3 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i3", "name": "i3", "status": "active",
                "sessions": [SID3],
                "tasks": [
                    {"id": f"keep{i}", "title": f"Keep {i}", "status": "pending"}
                    for i in range(5)
                ],
            }],
        }],
    }
    new_mm3 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i3", "name": "i3", "status": "active",
                "sessions": [SID3], "tasks": [],
            }],
        }],
    }
    hot3 = list(cf.collect_summaries())
    cf.aggregate_tasks(new_mm3, prior3, hot3)
    init3 = new_mm3["workspaces"][0]["initiatives"][0]
    titles = {t["title"] for t in init3["tasks"]}
    check(len(init3["tasks"]) == 7,
          f"PRIOR 5 + session 2 = 7 (got {len(init3['tasks'])})")
    check("Brand new A" in titles and "Brand new B" in titles,
          "session tasks added")
    by_id3 = {t["title"]: t for t in init3["tasks"]}
    check(by_id3["Brand new B"]["status"] == "done"
          and by_id3["Brand new B"].get("terminal_at"),
          "session done task gets terminal_at stamped")

    # === Scenario 4: AI tries to revert cancelled→pending ===============
    print("\n[scenario 4] terminal-monotone: AI cannot revive cancelled")
    SID4 = "ffffffff-1111-2222-3333-777777777777"
    _make_summary(SID4, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior4 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i4", "name": "i4", "status": "active",
                "sessions": [SID4],
                "tasks": [
                    {"id": "task-x", "title": "Task X", "status": "cancelled",
                     "evidence": "merged into Y",
                     "terminal_at": "2026-05-16T10:00:00Z"},
                ],
            }],
        }],
    }
    new_mm4 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i4", "name": "i4", "status": "active",
                "sessions": [SID4],
                # AI maliciously says it's pending again
                "tasks": [{"id": "task-x", "title": "Task X",
                           "status": "pending"}],
            }],
        }],
    }
    hot4 = list(cf.collect_summaries())
    cf.aggregate_tasks(new_mm4, prior4, hot4)
    # Then run the belt-and-suspenders monotone repair
    cf.enforce_cold_and_terminal_monotone(new_mm4, prior4, [SID4])
    init4 = new_mm4["workspaces"][0]["initiatives"][0]
    t = init4["tasks"][0] if init4["tasks"] else {}
    check(t.get("status") == "cancelled",
          f"cancelled PRIOR survives AI revert attempt (got {t.get('status')})")
    check(t.get("evidence") == "merged into Y",
          "evidence carried over from PRIOR after monotone repair")

    # === Scenario 5: AI flips pending→cancelled with evidence ===========
    print("\n[scenario 5] AI cancels a pending task with evidence")
    SID5 = "ffffffff-1111-2222-3333-888888888888"
    _make_summary(SID5, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior5 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i5", "name": "i5", "status": "active",
                "sessions": [SID5],
                "tasks": [
                    {"id": "drop-me", "title": "Drop me", "status": "pending"},
                ],
            }],
        }],
    }
    new_mm5 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "i5", "name": "i5", "status": "active",
                "sessions": [SID5],
                "tasks": [{"id": "drop-me", "title": "Drop me",
                           "status": "cancelled",
                           "evidence": "user redirected scope"}],
            }],
        }],
    }
    hot5 = list(cf.collect_summaries())
    cf.aggregate_tasks(new_mm5, prior5, hot5)
    init5 = new_mm5["workspaces"][0]["initiatives"][0]
    t5 = init5["tasks"][0] if init5["tasks"] else {}
    check(t5.get("status") == "cancelled",
          f"AI cancellation accepted (got {t5.get('status')})")
    check(t5.get("evidence") == "user redirected scope",
          f"evidence stored (got {t5.get('evidence')!r})")
    check(bool(t5.get("terminal_at")),
          "terminal_at stamped on cancellation")

    print()
    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: all DD-011 invariants hold")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    raise SystemExit(rc)

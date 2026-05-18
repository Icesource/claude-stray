#!/usr/bin/env python3
"""
Regression test for DD-010 task-persistence invariants.

Three scenarios — all must pass:

  scenario 1: a hot session with empty `tasks:` frontmatter against a
              PRIOR carrying 5 tasks. The 2026-05-18 incident.
              Expected: all 5 PRIOR tasks survive in init.tasks AND
              the archive file is not wiped.

  scenario 2: same setup but the archive file already has 3 evicted
              tasks from a previous round. Expected: archive after
              the call still contains those 3 PLUS the 5 PRIOR (no
              loss).

  scenario 3: hot summary adds 2 new tasks not in PRIOR. Expected:
              init.tasks contains all 7 (PRIOR 5 + 2 new). PRIOR
              tasks are still there.

Exit 0 = all pass. Exit 1 = at least one regression.

Run:
  python3 bin/_test_task_persistence.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


# Set up an isolated cache root so the real cache/ isn't touched.
TMP_ROOT = Path(tempfile.mkdtemp(prefix="ccw-test-dd010-"))
TMP_CACHE = TMP_ROOT / "cache"
TMP_SUMMARIES = TMP_CACHE / "summaries"
TMP_ARCHIVE = TMP_CACHE / "task_archive"
TMP_CACHE.mkdir(parents=True)
TMP_SUMMARIES.mkdir()
TMP_ARCHIVE.mkdir()


def _patch_classify_paths():
    """Point classify.py at our temp directories so we don't clobber
    real cache files."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import classify
    classify.CACHE_DIR = TMP_CACHE
    classify.SESSIONS_DIR = TMP_CACHE / "sessions"
    classify.SUMMARIES_DIR = TMP_SUMMARIES
    classify.TASK_ARCHIVE_DIR = TMP_ARCHIVE
    classify.MINDMAP_FILE = TMP_CACHE / "mindmap.json"
    return classify


def _make_summary(sid: str, *, last_activity_at: str, tasks: list[dict] | None) -> None:
    """Write a synthetic Layer 1 summary to TMP_SUMMARIES."""
    fm_lines = [
        "---",
        f"session_id: {sid}",
        "cwd: /tmp/test",
        f"last_activity_at: {last_activity_at}",
        "user_turns: 4",
        f"updated_at: {last_activity_at}",
        "status_guess: active",
    ]
    if tasks:
        fm_lines.append("tasks:")
        for t in tasks:
            fm_lines.append(f"  - title: {t['title']}")
            fm_lines.append(f"    done: {'true' if t['done'] else 'false'}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append("# 目标")
    fm_lines.append("synthetic test fixture")
    (TMP_SUMMARIES / f"{sid}.md").write_text("\n".join(fm_lines) + "\n")


def _archive(init_id: str) -> list[dict]:
    p = TMP_ARCHIVE / f"{init_id}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("tasks", [])


# ---------- assertions --------------------------------------------------

failures: list[str] = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        failures.append(msg)


# ---------- run scenarios ----------------------------------------------

def main() -> int:
    cf = _patch_classify_paths()
    SID = "ffffffff-1111-2222-3333-444444444444"

    # === Scenario 1: empty session summary, PRIOR has 5 tasks ===
    print("\n[scenario 1] empty session summary vs PRIOR with 5 tasks")
    _make_summary(SID, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init",
                "name": "test",
                "status": "active",
                "sessions": [SID],
                "tasks": [
                    {"id": f"t{i}", "title": f"Task {i}", "done": i % 2 == 0}
                    for i in range(5)
                ],
            }],
        }],
    }
    # AI's new mindmap simulates: same initiative, AI emitted no tasks
    # (the failure mode that caused the original wipe).
    new_mm = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init",
                "name": "test",
                "status": "active",
                "sessions": [SID],
                "tasks": [],
            }],
        }],
    }

    # Need to load hot_summaries the same way main() does
    hot = list(cf.collect_summaries())
    cf.aggregate_and_archive_tasks(new_mm, prior, hot)

    init = new_mm["workspaces"][0]["initiatives"][0]
    check(len(init["tasks"]) == 5, f"all 5 PRIOR tasks survive in init.tasks (got {len(init['tasks'])})")
    arc = _archive("test-init")
    check(len(arc) >= 5, f"archive contains all 5 PRIOR records (got {len(arc)})")

    # === Scenario 2: archive already has 3 evicted entries ===
    print("\n[scenario 2] archive pre-loaded with 3 historical entries")
    # Reset state — wipe archive + summary
    (TMP_ARCHIVE / "test-init-2.json").write_text(json.dumps({
        "initiative_id": "test-init-2",
        "updated_at": "2026-05-10T00:00:00Z",
        "tasks": [
            {"id": "old-1", "title": "Historical 1", "done": True,
             "evicted_at": "2026-05-10T00:00:00Z",
             "eviction_reason": "overflow_capped"},
            {"id": "old-2", "title": "Historical 2", "done": True,
             "evicted_at": "2026-05-10T00:00:00Z",
             "eviction_reason": "overflow_capped"},
            {"id": "old-3", "title": "Historical 3", "done": False,
             "evicted_at": "2026-05-10T00:00:00Z",
             "eviction_reason": "overflow_capped"},
        ],
    }, indent=2, ensure_ascii=False))
    SID2 = "ffffffff-1111-2222-3333-555555555555"
    _make_summary(SID2, last_activity_at="2026-05-18T07:00:00Z", tasks=None)
    prior2 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init-2", "name": "t2", "status": "active",
                "sessions": [SID2],
                "tasks": [
                    {"id": f"new{i}", "title": f"Active {i}", "done": False}
                    for i in range(2)
                ],
            }],
        }],
    }
    new_mm2 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init-2", "name": "t2", "status": "active",
                "sessions": [SID2], "tasks": [],
            }],
        }],
    }
    hot2 = list(cf.collect_summaries())
    cf.aggregate_and_archive_tasks(new_mm2, prior2, hot2)

    arc2 = _archive("test-init-2")
    arc2_ids = {t["id"] for t in arc2}
    check("old-1" in arc2_ids and "old-2" in arc2_ids and "old-3" in arc2_ids,
          f"3 historical archive entries preserved (got ids: {sorted(arc2_ids)})")
    init2 = new_mm2["workspaces"][0]["initiatives"][0]
    check(len(init2["tasks"]) == 2, f"both PRIOR tasks still visible (got {len(init2['tasks'])})")

    # === Scenario 3: session adds 2 new tasks not in PRIOR ===
    print("\n[scenario 3] session summary adds 2 new tasks")
    SID3 = "ffffffff-1111-2222-3333-666666666666"
    _make_summary(SID3, last_activity_at="2026-05-18T07:00:00Z", tasks=[
        {"title": "Brand new A", "done": False},
        {"title": "Brand new B", "done": True},
    ])
    prior3 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init-3", "name": "t3", "status": "active",
                "sessions": [SID3],
                "tasks": [
                    {"id": f"keep{i}", "title": f"Keep {i}", "done": False}
                    for i in range(5)
                ],
            }],
        }],
    }
    new_mm3 = {
        "workspaces": [{
            "name": "test", "cwd": "/tmp",
            "initiatives": [{
                "id": "test-init-3", "name": "t3", "status": "active",
                "sessions": [SID3], "tasks": [],
            }],
        }],
    }
    hot3 = list(cf.collect_summaries())
    cf.aggregate_and_archive_tasks(new_mm3, prior3, hot3)

    init3 = new_mm3["workspaces"][0]["initiatives"][0]
    titles = {t["title"] for t in init3["tasks"]}
    check(len(init3["tasks"]) == 7,
          f"PRIOR 5 + session 2 = 7 visible (got {len(init3['tasks'])})")
    check("Brand new A" in titles and "Brand new B" in titles,
          f"new session tasks included (titles: {sorted(titles)})")

    # === Done ===
    print()
    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: all DD-010 invariants hold")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    raise SystemExit(rc)

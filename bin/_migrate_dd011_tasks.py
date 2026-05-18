#!/usr/bin/env python3
"""
DD-011 one-shot migration: collapse cache/task_archive/ into mindmap.json.

Reads every cache/task_archive/<id>.json, finds the matching initiative
in cache/mindmap.json, and merges archive entries into init["tasks"]
under the DD-011 schema:

    {id, title, status: pending|done|cancelled, evidence?, terminal_at?}

Field rewrites:
    done: true       → status: done
    done: false      → status: pending  (anything else stays pending)
    done_evidence    → evidence
    done_at          → terminal_at
    first_seen_at, last_seen_at, sessions, evicted_at,
    eviction_reason  → DROPPED

After a successful write to mindmap.json, the task_archive/ directory
is renamed to task_archive.bak/ (rollback). Run the script a second
time and it exits cleanly — no archive directory found.

Modes:
  --dry-run    Print per-initiative diff; touch nothing.
  (default)    Apply.

Idempotent. Safe to re-run.

Usage:
  python3 bin/_migrate_dd011_tasks.py --dry-run
  python3 bin/_migrate_dd011_tasks.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "bin"))

from classify import (
    MINDMAP_FILE, CACHE_DIR, slugify_task_title, atomic_write_json,
    TASK_STATUSES, TASK_TERMINAL,
)

TASK_ARCHIVE_DIR = CACHE_DIR / "task_archive"
ARCHIVE_BAK_DIR = CACHE_DIR / "task_archive.bak"


def _coerce_status(t: dict) -> str:
    s = t.get("status")
    if s in TASK_STATUSES:
        return s
    if t.get("done") is True:
        return "done"
    return "pending"


def _coerce_to_dd011(t: dict, *, fallback_terminal_at: str | None = None) -> dict:
    """Map any pre-DD-011 task shape to the 5-field DD-011 record."""
    title = t.get("title") or ""
    tid = t.get("id") or slugify_task_title(title)
    status = _coerce_status(t)
    rec: dict = {"id": tid, "title": title, "status": status}
    evidence = t.get("evidence") or t.get("done_evidence")
    if evidence:
        rec["evidence"] = str(evidence)[:80]
    if status in TASK_TERMINAL:
        rec["terminal_at"] = (t.get("terminal_at")
                              or t.get("done_at")
                              or t.get("evicted_at")
                              or fallback_terminal_at)
        if rec["terminal_at"] is None:
            rec.pop("terminal_at")
    return rec


def _safe_filename(s: str) -> str:
    import re as _re
    return _re.sub(r"[^\w\-]", "_", s or "unknown")[:120]


def _load_archive_entries() -> dict[str, list[dict]]:
    """{init_id: [tasks…]} read from cache/task_archive/."""
    if not TASK_ARCHIVE_DIR.is_dir():
        return {}
    out: dict[str, list[dict]] = {}
    for p in TASK_ARCHIVE_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ! skip {p.name}: {e}", file=sys.stderr)
            continue
        iid = rec.get("initiative_id") or p.stem
        out[iid] = rec.get("tasks") or []
    return out


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not MINDMAP_FILE.exists():
        print(f"no mindmap.json at {MINDMAP_FILE}", file=sys.stderr)
        return 1

    mm = json.loads(MINDMAP_FILE.read_text())

    if not TASK_ARCHIVE_DIR.is_dir():
        # Idempotent: archive already gone. Still normalize mindmap so any
        # legacy `done: bool` records get rewritten to the new schema.
        print(f"=== DD-011 migration {'(DRY RUN)' if dry_run else ''} ===")
        print("  cache/task_archive/ not present — normalizing mindmap only.")
    else:
        print(f"=== DD-011 migration {'(DRY RUN)' if dry_run else ''} ===")

    archive_by_init = _load_archive_entries()
    n_inits = 0
    n_tasks_normalized = 0
    n_tasks_merged_in = 0
    n_fields_dropped = 0

    LEGACY_FIELDS = {"first_seen_at", "last_seen_at", "sessions",
                     "evicted_at", "eviction_reason", "done",
                     "done_at", "done_evidence"}

    for ws in (mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            iid = init.get("id")
            if not iid:
                continue
            n_inits += 1
            existing = init.get("tasks") or []
            ordered_ids: list[str] = []
            merged: dict[str, dict] = {}
            for t in existing:
                if not t.get("title"):
                    continue
                rec = _coerce_to_dd011(t)
                merged[rec["id"]] = rec
                ordered_ids.append(rec["id"])
                n_tasks_normalized += 1
                n_fields_dropped += sum(1 for k in LEGACY_FIELDS if k in t)
            for t in archive_by_init.pop(iid, []):
                if not t.get("title"):
                    continue
                rec = _coerce_to_dd011(t)
                if rec["id"] in merged:
                    # Keep mindmap entry as source of truth; only adopt
                    # archive's terminal_at/evidence if mindmap lacks them.
                    cur = merged[rec["id"]]
                    if rec.get("evidence") and not cur.get("evidence"):
                        cur["evidence"] = rec["evidence"]
                    if rec.get("terminal_at") and not cur.get("terminal_at"):
                        cur["terminal_at"] = rec["terminal_at"]
                else:
                    merged[rec["id"]] = rec
                    ordered_ids.append(rec["id"])
                    n_tasks_merged_in += 1
            init["tasks"] = [merged[i] for i in ordered_ids if i in merged]
            init.pop("tasks_archived_count", None)

    if archive_by_init:
        print(f"  ! {len(archive_by_init)} archive file(s) had no matching "
              f"initiative; skipping:")
        for iid in list(archive_by_init.keys())[:10]:
            print(f"      - {iid}")

    print(f"  initiatives processed:        {n_inits}")
    print(f"  tasks normalized in mindmap:  {n_tasks_normalized}")
    print(f"  tasks merged in from archive: {n_tasks_merged_in}")
    print(f"  legacy fields dropped:        {n_fields_dropped}")

    if dry_run:
        print("\n  (dry-run; re-run without --dry-run to apply)")
        return 0

    atomic_write_json(MINDMAP_FILE, mm)
    print(f"\n  wrote {MINDMAP_FILE}")

    if TASK_ARCHIVE_DIR.is_dir():
        if ARCHIVE_BAK_DIR.exists():
            print(f"  (existing {ARCHIVE_BAK_DIR.name} found; leaving alone)")
        else:
            shutil.move(str(TASK_ARCHIVE_DIR), str(ARCHIVE_BAK_DIR))
            print(f"  renamed cache/task_archive/ → cache/task_archive.bak/")
            print(f"  (delete cache/task_archive.bak/ once you're sure)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

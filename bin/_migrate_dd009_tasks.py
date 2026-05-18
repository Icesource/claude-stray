#!/usr/bin/env python3
"""
DD-009 / DD-010 task migration helper.

Originally a cross-initiative-pollution cleanup tool (DD-009). The
DD-010 amendment — "AI may never delete a task; only the user can" —
makes eviction logic incorrect, so this script is now an idempotent
backfill / merge:

  - Ensure every task has a stable `id` slug
  - Union PRIOR + session-summary tasks (no PRIOR drop)
  - Done-monotone is preserved
  - Cap visible at MAX_VISIBLE_TASKS; overflow → archive
  - Archive file load-then-merge-then-save (no overwrite)

Cold initiatives are left alone (§5).

Modes:
  --dry-run    Print per-initiative diff; touch nothing.
  (default)    Apply the changes.

Usage:
  python3 bin/_migrate_dd009_tasks.py --dry-run
  python3 bin/_migrate_dd009_tasks.py

Always safe to re-run — idempotent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "bin"))

from classify import (
    MINDMAP_FILE, SUMMARIES_DIR, MAX_VISIBLE_TASKS, HOT_HOURS,
    parse_frontmatter, parse_tasks_from_fm,
    slugify_task_title,
    load_task_archive, save_task_archive, atomic_write_json,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_hot_session(sid: str) -> tuple[bool, str | None]:
    """Return (is_hot, summary_text or None). A session is hot if its
    summary file's last_activity_at is within HOT_HOURS."""
    p = SUMMARIES_DIR / f"{sid}.md"
    if not p.exists():
        return False, None
    text = p.read_text()
    fm, _body, _raw = parse_frontmatter(text)
    la = fm.get("last_activity_at")
    if not la:
        return False, None
    try:
        la_dt = datetime.fromisoformat(la.replace("Z", "+00:00"))
    except ValueError:
        return False, None
    is_hot = la_dt >= datetime.now(timezone.utc) - timedelta(hours=HOT_HOURS)
    return is_hot, text


def _session_tasks(sid: str) -> list[dict]:
    """Return [{title, done}] from the session's summary frontmatter,
    or [] if the summary doesn't exist."""
    p = SUMMARIES_DIR / f"{sid}.md"
    if not p.exists():
        return []
    _fm, _body, raw_fm = parse_frontmatter(p.read_text())
    return parse_tasks_from_fm(raw_fm)


def _migrate_initiative(init: dict, *, dry_run: bool) -> dict:
    """Returns a dict of stats for this init."""
    init_id = init.get("id")
    sessions = init.get("sessions") or []
    prior_tasks = init.get("tasks") or []

    # Hot sessions for this initiative + their canonical tasks
    canonical_titles_by_slug: dict[str, str] = {}  # slug → latest title wording
    canonical_done: dict[str, bool] = {}
    hot_session_count = 0
    for sid in sessions:
        is_hot, _ = _is_hot_session(sid)
        if not is_hot:
            continue
        hot_session_count += 1
        for t in _session_tasks(sid):
            slug = slugify_task_title(t["title"])
            canonical_titles_by_slug[slug] = t["title"]
            if t["done"]:
                canonical_done[slug] = True

    if hot_session_count == 0:
        # Cold — DD-009 still respects §5 (no changes). Skip.
        return {"init_id": init_id, "cold": True, "kept": len(prior_tasks),
                "evicted": 0, "carried_done": 0}

    # Index PRIOR by slug (carries forward; DD-010 forbids eviction).
    prior_by_slug: dict[str, dict] = {}
    for pt in prior_tasks:
        if not pt.get("title"):
            continue
        slug = pt.get("id") or slugify_task_title(pt["title"])
        pt["id"] = slug
        prior_by_slug[slug] = pt

    # Build new task set: union of PRIOR + canonical (session-summary)
    # tasks. Under DD-010, PRIOR is preserved in full; sessions only
    # add new items.
    kept_tasks: list[dict] = []
    seen_slugs: set[str] = set()
    # PRIOR first (preserved verbatim except for id/timestamps backfill)
    for slug, pt in prior_by_slug.items():
        rec = dict(pt)
        rec["id"] = slug
        if rec.get("done") and not rec.get("done_at"):
            rec["done_at"] = _now_iso()
        kept_tasks.append(rec)
        seen_slugs.add(slug)
    # Then canonical (only slugs not already in PRIOR)
    for slug, title in canonical_titles_by_slug.items():
        if slug in seen_slugs:
            # Refresh title wording on the existing PRIOR entry; carry
            # done-monotone if the session marks it done.
            for r in kept_tasks:
                if r["id"] == slug:
                    r["title"] = title
                    if canonical_done.get(slug) and not r.get("done"):
                        r["done"] = True
                        r["done_at"] = _now_iso()
                    break
            continue
        kept_tasks.append({
            "id": slug,
            "title": title,
            "done": canonical_done.get(slug, False),
            **({"done_at": _now_iso()} if canonical_done.get(slug) else {}),
        })

    # Sort: not-done first, then done; cap visible at MAX_VISIBLE_TASKS.
    not_done = [t for t in kept_tasks if not t["done"]]
    done_tasks = [t for t in kept_tasks if t["done"]]
    visible = not_done + done_tasks[:max(0, MAX_VISIBLE_TASKS - len(not_done))]

    # NO eviction under DD-010. Only overflow.
    overflow = kept_tasks[len(visible):]

    # Persist
    now = _now_iso()
    if not dry_run:
        init["tasks"] = visible
        init["tasks_archived_count"] = len(overflow)
        archive_existing = {a.get("id"): a for a in load_task_archive(init_id)
                            if a.get("id")}
        for ov in overflow:
            ov["evicted_at"] = now
            ov["eviction_reason"] = "overflow_capped"
            archive_existing[ov["id"]] = ov
        # Visible go to archive too with no eviction marker
        for v in visible:
            archive_existing.setdefault(v["id"], dict(v))
        save_task_archive(init_id, list(archive_existing.values()))

    return {
        "init_id": init_id,
        "cold": False,
        "hot_sessions": hot_session_count,
        "kept": len(visible),
        "evicted": len(overflow),
        "carried_done": sum(1 for t in visible if t["done"]),
        "evicted_titles": [],
        "overflow_titles": [t["title"] for t in overflow],
    }


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not MINDMAP_FILE.exists():
        print(f"no mindmap.json at {MINDMAP_FILE}", file=sys.stderr)
        return 1

    mm = json.loads(MINDMAP_FILE.read_text())
    total_kept = total_evicted = 0
    cold_n = hot_n = 0

    print(f"=== DD-009 task migration {'(DRY RUN)' if dry_run else ''} ===\n")
    for ws in (mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            stats = _migrate_initiative(init, dry_run=dry_run)
            if stats["cold"]:
                cold_n += 1
                continue
            hot_n += 1
            total_kept += stats["kept"]
            total_evicted += stats["evicted"]
            arrow = "→"
            print(f"  {stats['init_id']:50} "
                  f"prior={stats['kept'] + stats['evicted']:>3} {arrow} "
                  f"kept={stats['kept']:>2} evicted={stats['evicted']:>2} "
                  f"(done: {stats['carried_done']})")
            if stats["evicted_titles"]:
                for t in stats["evicted_titles"][:5]:
                    print(f"      − {t[:60]}")
                if len(stats["evicted_titles"]) > 5:
                    print(f"      − ... and {len(stats['evicted_titles']) - 5} more")

    print()
    print(f"  hot initiatives processed: {hot_n}")
    print(f"  cold initiatives untouched: {cold_n}")
    print(f"  total kept:    {total_kept}")
    print(f"  total evicted: {total_evicted}")

    if not dry_run:
        atomic_write_json(MINDMAP_FILE, mm)
        print(f"\n  wrote {MINDMAP_FILE}")
    else:
        print(f"\n  (dry-run; re-run without --dry-run to apply)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

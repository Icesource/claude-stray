#!/usr/bin/env python3
"""DD-033 one-shot migration: unify legacy card ids to card::<session_id>.

Pre-DD-030 cards carry AI-minted slug ids (e.g. `hsf-ops-triple-protocol-…`)
or `subcard::<sid>`. The mechanical assembler mints `card::<sid>` for every
session, so this script renames every live single-session card in
dashboard.json and rewrites the id references that point at it:

  - cache/dashboard.json            initiative ids
  - cache/user_overrides.json       task_toggles / deleted_tasks /
                                    hidden_artifacts [].init_id

NOT rewritten (and why it's safe):
  - cache/deleted_ids.json / cache/archive/ — those reference cards that are
    no longer in the dashboard, so there is no session to map them to. They
    stay as-is; resurrection is prevented by session-level tombstones plus
    the assembler's cold-session gate (a cold session that never had a card
    never becomes one).
  - sealed::* ids — already stable, identity anchored on artifact_key.

AI corpses: a live card with EMPTY sessions[] is a card whose session link
the AI lost (the bug family DD-033 kills). If exactly one hot, not-yet-carded
session lives in the same workspace, the corpse is re-linked to it (id →
card::<sid>, sessions restored — its good name survives). Otherwise it is a
duplicate with no recoverable identity and is dropped.

The whole cache dir is backed up to cache.bak-<UTC timestamp> first.
Idempotent: already-canonical ids are left untouched.

Usage:
  python3 bin/_migrate_card_ids.py [--cache DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_mapping(mindmap: dict) -> dict[str, str]:
    """{old_id: card::<sid>} for every live, single-session, non-canonical card."""
    mapping: dict[str, str] = {}
    for ws in (mindmap.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            if init.get("sealed"):
                continue
            iid = init.get("id") or ""
            sids = init.get("sessions") or []
            if iid.startswith("card::"):
                continue
            if len(sids) != 1:
                if sids:
                    print(f"  !! skip multi-session card {iid} ({len(sids)} sessions)",
                          file=sys.stderr)
                continue
            mapping[iid] = "card::" + sids[0]
    return mapping


def adopt_or_drop_corpses(mindmap: dict, cache_dir: Path) -> tuple[int, int]:
    """Repair live cards with empty sessions[] (AI lost the link).
    Re-link to the unique uncarded hot session in the same workspace when
    one exists; otherwise drop the card. Returns (adopted, dropped)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import classify as c
    from datetime import datetime, timezone
    # point classify's tombstone readers at THIS cache dir (a snapshot may
    # differ from classify's baked-in REPO_ROOT/cache)
    c.ARCHIVE_DIR = cache_dir / "archive"
    c.DELETED_FILE = cache_dir / "deleted_ids.json"

    carded = {s for ws in (mindmap.get("workspaces") or [])
              for i in (ws.get("initiatives") or [])
              for s in (i.get("sessions") or [])}
    # session-tombstoned sids are dead to the assembler — never adopt onto one
    tomb = dict(c.archived_session_ids_on_disk())
    for s, ts in c.deleted_session_ids_on_disk().items():
        if s not in tomb or ts > tomb[s]:
            tomb[s] = ts
    # uncarded hot sessions per workspace name, from the summaries dir
    now = datetime.now(timezone.utc)
    candidates: dict[str, list[str]] = {}
    summaries_dir = cache_dir / "summaries"
    if summaries_dir.is_dir():
        for md in summaries_dir.glob("*.md"):
            try:
                fm, _b, _r = c.parse_frontmatter(md.read_text(encoding="utf-8"))
            except OSError:
                continue
            sid = md.stem
            if sid in carded or not c.is_hot(fm, now):
                continue
            ts = tomb.get(sid)
            if ts and (fm.get("last_activity_at") or "") <= ts:
                continue
            try:   # thin sessions won't be carded by the assembler either
                if int(fm.get("user_turns", "0") or "0") < c.MIN_TURNS:
                    continue
            except (TypeError, ValueError):
                pass
            candidates.setdefault(
                c._ws_name_for_cwd(fm.get("cwd") or ""), []).append(sid)

    adopted = dropped = 0
    for ws in (mindmap.get("workspaces") or []):
        kept = []
        for init in (ws.get("initiatives") or []):
            if init.get("sealed") or (init.get("sessions") or []) \
                    or not init.get("id"):
                kept.append(init)
                continue
            cands = candidates.get(ws.get("name") or "", [])
            if len(cands) == 1:
                sid = cands[0]
                print(f"  corpse {init['id']} → adopted session {sid[:8]} "
                      f"(name kept: {init.get('name')})")
                init["id"] = "card::" + sid
                init["sessions"] = [sid]
                carded.add(sid)
                candidates[ws.get("name") or ""] = []
                adopted += 1
                kept.append(init)
            else:
                print(f"  corpse {init['id']} dropped (no unique uncarded "
                      f"hot session in ws {ws.get('name')})")
                dropped += 1
        ws["initiatives"] = kept
    return adopted, dropped


def migrate(cache_dir: Path, dry_run: bool = False) -> int:
    dash_path = cache_dir / "dashboard.json"
    if not dash_path.exists():
        print(f"[migrate] no dashboard at {dash_path}; nothing to do")
        return 0
    mindmap = json.loads(dash_path.read_text(encoding="utf-8"))
    mapping = build_mapping(mindmap)
    adopted, dropped = adopt_or_drop_corpses(mindmap, cache_dir)
    if not (mapping or adopted or dropped):
        print("[migrate] all card ids already canonical; nothing to do")
        return 0

    print(f"[migrate] {len(mapping)} card id(s) to rename, "
          f"{adopted} corpse(s) adopted, {dropped} dropped:")
    for old, new in sorted(mapping.items()):
        print(f"  {old}  →  {new}")
    if dry_run:
        print("[migrate] dry-run: no files written")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = cache_dir.parent / f"{cache_dir.name}.bak-{stamp}"
    shutil.copytree(cache_dir, backup,
                    ignore=shutil.ignore_patterns("sessions", "*.lock*"))
    print(f"[migrate] cache backed up to {backup}")

    # 1. dashboard.json
    for ws in (mindmap.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            iid = init.get("id") or ""
            if iid in mapping:
                init["id"] = mapping[iid]
    tmp = dash_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mindmap, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(dash_path)
    print(f"[migrate] rewrote {dash_path}")

    # 2. user_overrides.json — every list entry that carries init_id
    ov_path = cache_dir / "user_overrides.json"
    if ov_path.exists():
        try:
            ov = json.loads(ov_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ov = None
        if isinstance(ov, dict):
            n = 0
            for key in ("task_toggles", "deleted_tasks", "hidden_artifacts"):
                for ent in (ov.get(key) or []):
                    if isinstance(ent, dict) and ent.get("init_id") in mapping:
                        ent["init_id"] = mapping[ent["init_id"]]
                        n += 1
            if n:
                tmp = ov_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(ov, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                tmp.replace(ov_path)
                print(f"[migrate] rewrote {n} init_id reference(s) in {ov_path}")

    print("[migrate] done")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=REPO_ROOT / "cache")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return migrate(args.cache, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

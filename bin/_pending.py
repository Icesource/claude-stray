"""DD-027: the instant-citizen pending-card registry.

A card is a system citizen the MOMENT it is created. But the AI pipeline
(extract→summarize→classify, ~10-40s) hasn't produced the real card yet, so
the dashboard would show a void right after "new task" / "fan out sub-card".

We register a PLACEHOLDER card to cache/pending-cards.json the instant the
creation action fires, and merge it into /api/data so the dashboard shows it
at once (marked _pending → cockpit renders "准备中"). When the real card
surfaces — matched by the captured session_id OR by worktree path — the
placeholder is dropped seamlessly. Entries self-expire after a TTL so a failed
launch never leaves a ghost.

Pure + path-injectable so it unit-tests without serve.py — mirrors _subcards.py
and _worktree.py.
"""
import json
import os
import time

TTL = 900.0  # 15 min: a placeholder whose launch never produced a card self-expires


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def register(path, key, *, name="", cwd="", worktree_path=None,
             worktree_name=None, parent=None, _now=None):
    """Register a placeholder card under `key` (the caller's stable handle —
    a terminal token or a uuid). Atomic write. Re-registering the same key
    overwrites (idempotent). worktree_path is stored realpath'd so it aligns
    with a real card's code_location.worktree later."""
    d = load(path)
    d[key] = {
        "name": (name or "").strip(),
        "cwd": cwd or "",
        "worktree_path": os.path.realpath(worktree_path) if worktree_path else None,
        "worktree_name": worktree_name or None,
        "parent": parent or None,
        "session_id": None,
        "created_at": _now if _now is not None else time.time(),
    }
    _write(path, d)
    return d


def capture_sid(path, key, sid):
    """Backfill the captured child session_id onto a placeholder (the second
    alignment key, and what lets a no-worktree placeholder align at all).
    No-op if the key is gone (already pruned). Atomic write."""
    d = load(path)
    ent = d.get(key)
    if not ent:
        return d
    ent["session_id"] = sid
    _write(path, d)
    return d


def remove(path, key):
    d = load(path)
    if key in d:
        del d[key]
        _write(path, d)
    return d


def _real_keys(mindmap):
    """(set of real session_ids, set of real worktree paths) across all cards —
    the things a placeholder aligns against."""
    sids, wts = set(), set()
    for w in (mindmap or {}).get("workspaces", []) or []:
        for init in w.get("initiatives", []) or []:
            for s in (init.get("sessions") or []):
                if s:
                    sids.add(s)
            wt = (init.get("code_location") or {}).get("worktree")
            if wt:
                wts.add(os.path.realpath(wt))
    return sids, wts


def _represented(ent, real_sids, real_wts):
    """Is this placeholder already covered by a REAL card?"""
    sid = ent.get("session_id")
    if sid and sid in real_sids:
        return True
    wt = ent.get("worktree_path")
    if wt and os.path.realpath(wt) in real_wts:
        return True
    return False


def _placeholder_card(key, ent, now):
    """Synthesize a _pending initiative from a placeholder entry."""
    wt = ent.get("worktree_path")
    cl = None
    if wt:
        cl = {"worktree": wt, "branch": ("worktree-" + ent["worktree_name"])
              if ent.get("worktree_name") else "", "is_worktree": True,
              "main_repo": os.path.dirname(os.path.dirname(os.path.dirname(wt))) or ent.get("cwd") or ""}
    sid = ent.get("session_id")
    return {
        "id": "pending-" + key,
        "name": ent.get("name") or "准备中…",
        "status": "active",
        "level": "thread",
        "summary": "",
        "progress": "卡片已创建,正在准备(AI 总结稍后补充)…",
        "tasks": [],
        "sessions": [sid] if sid else [],
        "linked_cwds": [ent.get("cwd")] if ent.get("cwd") else [],
        "last_activity_at": _iso(ent.get("created_at") or now),
        "code_location": cl,
        "parent_session_id": ent.get("parent"),
        "_pending": True,
    }


def merge_into_mindmap(mindmap, doc, _now=None):
    """Append a synthetic _pending card for each LIVE placeholder not yet
    represented by a real card. Returns (added, stale_keys):
      - added: how many placeholder cards were merged in
      - stale_keys: keys safe to prune (expired OR now represented by a real card)
    Pure render-time enrichment — does NOT mutate `doc` or persist anything.
    The caller prunes stale_keys from the file separately."""
    if not mindmap or not isinstance(doc, dict) or not doc:
        return 0, []
    now = _now if _now is not None else time.time()
    real_sids, real_wts = _real_keys(mindmap)
    workspaces = mindmap.setdefault("workspaces", [])
    added, stale = 0, []
    for key, ent in doc.items():
        if not isinstance(ent, dict):
            stale.append(key)
            continue
        if now - (ent.get("created_at") or 0) > TTL:
            stale.append(key)
            continue
        if _represented(ent, real_sids, real_wts):
            stale.append(key)          # real card arrived — drop the placeholder
            continue
        card = _placeholder_card(key, ent, now)
        _place(workspaces, card, ent)
        added += 1
    return added, stale


def _place(workspaces, card, ent):
    """Drop the placeholder card into the workspace matching its repo, creating
    a synthetic workspace if none matches (brand-new repo with no cards yet)."""
    cl = card.get("code_location") or {}
    repo = cl.get("main_repo") or ent.get("cwd") or ""
    target = None
    if repo:
        rp = os.path.realpath(repo)
        for w in workspaces:
            wc = w.get("cwd")
            if wc and os.path.realpath(os.path.expanduser(wc)) == rp:
                target = w
                break
    if target is None:
        name = os.path.basename(repo.rstrip("/")) or "新任务"
        target = {"name": name, "cwd": repo or None, "initiatives": []}
        workspaces.append(target)
    target.setdefault("initiatives", []).append(card)

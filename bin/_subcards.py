"""DD-025 slice 1: the parent↔child sub-card registry.

A sub-card is a normal independent Claude Code session that a PARENT session fanned
out (each in its own worktree). Claude Code records no parent/child link, so we keep
our own: a tiny json mapping child_session_id → {parent, slug, created_at}.

Linking by the CHILD's session_id (captured at spawn) — not by guessing
`claude --worktree`'s dir/branch naming — keeps it robust to Claude Code internals.
Pure + path-injectable so it unit-tests without serve.py.
"""
import json
import os
import time


def load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def record(path, child_sid, parent_sid, slug="", _now=None):
    """Register child_sid as a sub-card of parent_sid. Atomic write."""
    d = load(path)
    d[child_sid] = {"parent": parent_sid, "slug": slug,
                    "created_at": _now if _now is not None else time.time()}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return d


def link(mindmap, subcards):
    """Set init['parent_session_id'] on every card that IS a registered sub-card
    (its session is a child). Returns how many cards were linked. Pure render-time
    enrichment — no persistence, mirrors DD-022-A's code_location attach."""
    if not mindmap or not subcards:
        return 0
    n = 0
    for w in mindmap.get("workspaces", []) or []:
        for init in w.get("initiatives", []) or []:
            for sid in (init.get("sessions") or []):
                ent = subcards.get(sid)
                if ent and ent.get("parent"):
                    init["parent_session_id"] = ent["parent"]
                    n += 1
                    break
    return n

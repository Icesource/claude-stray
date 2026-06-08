"""DD-025 slice 1: the parent↔child sub-card registry.

A sub-card is a normal independent Claude Code session that a PARENT session fanned
out (each in its own worktree). Claude Code records no parent/child link, so we keep
our own: a tiny json mapping child_session_id → {parent, slug, created_at}.

Linking by the CHILD's session_id (captured at spawn) — not by guessing
`claude --worktree`'s dir/branch naming — keeps it robust to Claude Code internals.
Pure + path-injectable so it unit-tests without serve.py.
"""
import glob
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


def _first_cwd(jsonl_path):
    try:
        with open(jsonl_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    c = json.loads(line).get("cwd")
                except Exception:
                    continue
                if c:
                    return c
    except Exception:
        pass
    return None


def find_session_by_cwd(projects_dir, cwd_prefix, after_ts=0.0):
    """session_id of the most-recent `projects_dir/*/*.jsonl` whose first cwd starts
    with cwd_prefix and mtime >= after_ts (excludes the 'subagents' namespace).
    None if no match. Used to capture a freshly-spawned child's id — we know the
    worktree cwd it was started in, so we match on that."""
    best, best_mt = None, -1.0
    for f in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        if os.path.basename(os.path.dirname(f)) == "subagents":
            continue
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        if mt < after_ts or mt <= best_mt:
            continue
        cwd = _first_cwd(f)
        if cwd and cwd.startswith(cwd_prefix):
            best, best_mt = os.path.basename(f)[:-6], mt
    return best


def _firstline(s):
    s = (s or "").replace("\n", " ").strip()
    return (s[:120] + "…") if len(s) > 120 else s


def subtask_metadata(parent_sid, mindmap, subcards, jsonl_lookup=None):
    """The low-token progress digest a PARENT pulls (`stray subtasks`): one entry
    per child card of parent_sid, from the cards' existing summaries — no AI."""
    children = {c for c, e in (subcards or {}).items() if e.get("parent") == parent_sid}
    out = []
    for w in (mindmap or {}).get("workspaces", []) or []:
        for i in w.get("initiatives", []) or []:
            sid = next((s for s in (i.get("sessions") or []) if s in children), None)
            if not sid:
                continue
            cl = i.get("code_location") or {}
            out.append({
                "name": i.get("name"), "session_id": sid,
                "status": i.get("status") or "", "progress": _firstline(i.get("progress")),
                "blockers": i.get("blockers") or [], "next_step": i.get("next_step"),
                "worktree": cl.get("worktree"), "branch": cl.get("branch"),
                "jsonl": jsonl_lookup(sid) if jsonl_lookup else None,
            })
    return out


def find_conflicts(files_by_sid):
    """files_by_sid: {sid: iterable of changed file paths}. Returns {sid: [sibling
    sids that touch >=1 of the same files]} — the ⚠ same-files warning across
    parallel sub-cards (filename overlap; coarse but no product does even this)."""
    items = [(s, set(fs or [])) for s, fs in (files_by_sid or {}).items()]
    out = {}
    for s, fs in items:
        peers = sorted(s2 for s2, fs2 in items if s2 != s and fs and (fs & fs2))
        if peers:
            out[s] = peers
    return out


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

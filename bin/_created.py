"""DD-030: the unified created-cards registry.

ONE durable registry for every card the user creates through the cockpit
("+新建主卡" / "+子卡") — replacing BOTH the old ephemeral pending-cards.json
(instant 准备中 placeholder) AND subcards.json (parent links). A created card is
a system citizen the instant it's made; the AI pipeline enriches it in place
under the SAME id `card::<sid>` — no second card, no handoff (the bug engine of
DD-027's placeholder→real-card swap).

Shape — keyed by the creation `token`, indexable by captured `sid`:
    {token: {sid, name, cwd, worktree_path, worktree_name, parent,
             initial_task, created_at}}

Lifetime:
  - register() at creation (no sid yet).
  - capture_sid() ~10s later when the child jsonl appears.
  - DURABLE once a sid is captured: the entry persists until the user deletes the
    card. This is what lets classify always know "this session is a user-created
    card" → exempt it from the thin/noise filter, claim it into card::<sid>, and
    keep the parent link. An entry with NO sid after TTL is a failed launch → pruned.

Pure + path-injectable so it unit-tests without serve.py — mirrors _subcards.py /
_pending.py, whose proven logic it absorbs.
"""
import contextlib
import json
import os
import time

TTL = 900.0  # 15 min: a placeholder that never captured a sid (failed launch) self-expires

try:
    import fcntl  # POSIX (macOS/Linux)
except ImportError:  # pragma: no cover
    fcntl = None


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def _locked(path):
    """Serialize read-modify-write across processes (DD-029 lost-update guard).
    One fixed sibling lockfile, reused forever (no per-entry leak)."""
    if fcntl is None:
        yield
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fh = open(path + ".lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _atomic_dump(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def register(path, token, *, name="", cwd="", worktree_path=None,
             worktree_name=None, parent=None, initial_task="", _now=None):
    """Register a created card under `token`. Atomic + lost-update safe.
    Re-registering the same token overwrites (idempotent)."""
    with _locked(path):
        d = load(path)
        d[token] = {
            "sid": None,
            "name": (name or "").strip(),
            "cwd": cwd or "",
            "worktree_path": os.path.realpath(worktree_path) if worktree_path else None,
            "worktree_name": worktree_name or None,
            "parent": parent or None,
            "initial_task": (initial_task or "").strip(),
            "created_at": _now if _now is not None else time.time(),
        }
        _atomic_dump(path, d)
    return d


def capture_sid(path, token, sid):
    """Backfill the captured child session_id. No-op if the token is gone."""
    with _locked(path):
        d = load(path)
        ent = d.get(token)
        if ent is not None:
            ent["sid"] = sid
            _atomic_dump(path, d)
    return d


def annotate(path, token, **fields):
    """Merge extra fields into an entry (e.g. stuck_trust=True when the spawned
    claude is sitting at the folder-trust dialog). No-op if the token is gone."""
    with _locked(path):
        d = load(path)
        ent = d.get(token)
        if ent is not None:
            ent.update(fields)
            _atomic_dump(path, d)
    return d


def remove(path, token):
    """Unregister by token. Returns True if it existed."""
    with _locked(path):
        d = load(path)
        if token not in d:
            return False
        del d[token]
        _atomic_dump(path, d)
    return True


def remove_by_sid(path, sid):
    """Unregister whichever entry owns this sid (delete by card). Returns True if removed."""
    with _locked(path):
        d = load(path)
        hit = [t for t, e in d.items() if isinstance(e, dict) and e.get("sid") == sid]
        if not hit:
            return False
        for t in hit:
            del d[t]
        _atomic_dump(path, d)
    return True


# ---------- read-side helpers (pure, for classify + render) ----------------

def by_sid(doc):
    """{sid: entry} for entries that have captured a sid — classify's lookup
    for claim / parent-link / thin-filter exemption."""
    out = {}
    for ent in (doc or {}).values():
        if isinstance(ent, dict) and ent.get("sid"):
            out[ent["sid"]] = ent
    return out


def registered_sids(doc):
    """Set of captured sids — sessions the user explicitly created (exempt from
    the noise/thin filter, must always surface as a card)."""
    return set(by_sid(doc).keys())


def _firstline(s):
    return (s or "").splitlines()[0].strip() if s else ""


def subtask_metadata(parent_sid, mindmap, doc, jsonl_lookup=None):
    """The low-token progress digest a PARENT pulls (`stray subtasks`): one entry
    per child card of parent_sid, from the cards' existing summaries — no AI.
    Ported from _subcards.subtask_metadata; reads the unified registry's parent links."""
    children = {sid for sid, ent in by_sid(doc).items() if ent.get("parent") == parent_sid}
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


def link(mindmap, doc):
    """Set init['parent_session_id'] on every card whose session is a registered
    created card with a parent. Pure render-time enrichment (mirrors the old
    _subcards.link). Returns count linked."""
    if not mindmap or not doc:
        return 0
    parent_of = {sid: ent.get("parent") for sid, ent in by_sid(doc).items() if ent.get("parent")}
    if not parent_of:
        return 0
    n = 0
    for ws in mindmap.get("workspaces", []) or []:
        for init in ws.get("initiatives", []) or []:
            for s in (init.get("sessions") or []):
                if s in parent_of:
                    init["parent_session_id"] = parent_of[s]
                    n += 1
                    break
    return n


# ---------- render-side: instant 准备中 placeholders ------------------------

def _real_sids_wts(mindmap):
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


def _has_real_card(ent, real_sids, real_wts):
    sid = ent.get("sid")
    if sid and sid in real_sids:
        return True
    wt = ent.get("worktree_path")
    if wt and os.path.realpath(wt) in real_wts:
        return True
    return False


def _placeholder_card(token, ent, now):
    """Synthesize a 准备中 card from a registry entry (shown until its real card
    exists). DD-030: NOT a band — `_pending` is an orthogonal badge; band is left
    to the normal live→classify logic. Name = initial task (provisional) else 准备中."""
    wt = ent.get("worktree_path")
    cl = None
    if wt:
        cl = {"worktree": wt,
              "branch": ("worktree-" + ent["worktree_name"]) if ent.get("worktree_name") else "",
              "is_worktree": True,
              "main_repo": os.path.dirname(os.path.dirname(os.path.dirname(wt))) or ent.get("cwd") or ""}
    sid = ent.get("sid")
    prov = ent.get("name") or ent.get("initial_task") or ""
    return {
        "id": "card::" + sid if sid else "pending::" + token,
        "name": prov[:60] if prov else "准备中…",
        "status": "active",
        "level": "card",
        "summary": "",
        "progress": "卡片已创建,正在准备(AI 总结稍后补充)…",
        "tasks": [],
        "sessions": [sid] if sid else [],
        "linked_cwds": [ent.get("cwd")] if ent.get("cwd") else [],
        "last_activity_at": _iso(ent.get("created_at") or now),
        "code_location": cl,
        "parent_session_id": ent.get("parent"),
        "_pending": True,
        # the spawned claude is sitting at Claude Code's folder-trust dialog —
        # the cockpit renders an actionable hint instead of an eternal 准备中
        "_stuck": "trust" if ent.get("stuck_trust") else None,
    }


def placeholder_id(token, ent):
    """The id a placeholder renders with — card::<sid> once captured, else
    pending::<token>. The handle a delete/tombstone must target."""
    sid = ent.get("sid")
    return ("card::" + sid) if sid else ("pending::" + token)


def merge_into_mindmap(mindmap, doc, _now=None, tombstoned_ids=None):
    """Append a 准备中 placeholder for each registry entry not yet backed by a real
    card. Returns (added, stale_tokens). DURABLE: an entry is stale ONLY if it's a
    failed launch (no sid past TTL) OR the user tombstoned its placeholder; a
    captured entry is otherwise kept even after its real card appears (the registry
    stays the durable record). Pure: does not mutate `doc`.

    DD-030 (ported from the task-ee1695 sub-card's finding): a 准备中 card lives ONLY
    here, overlaid at render — tombstoning it in dashboard.json can't kill it, it
    re-merges every /api/data until TTL. So honor `tombstoned_ids`: a placeholder
    whose id is tombstoned is NOT re-merged AND is marked stale (caller prunes the
    source entry) so the delete actually sticks."""
    if not mindmap or not isinstance(doc, dict) or not doc:
        return 0, []
    now = _now if _now is not None else time.time()
    tomb = tombstoned_ids or set()
    real_sids, real_wts = _real_sids_wts(mindmap)
    workspaces = mindmap.setdefault("workspaces", [])
    added, stale = 0, []
    for token, ent in doc.items():
        if not isinstance(ent, dict):
            stale.append(token)
            continue
        if placeholder_id(token, ent) in tomb:
            stale.append(token)          # user deleted it → drop source so it sticks
            continue
        if not ent.get("sid") and now - (ent.get("created_at") or 0) > TTL:
            stale.append(token)          # failed launch — never captured a sid
            continue
        if _has_real_card(ent, real_sids, real_wts):
            continue                     # real card exists → don't show placeholder (but KEEP entry)
        _place(workspaces, _placeholder_card(token, ent, now), ent)
        added += 1
    return added, stale


def _place(workspaces, card, ent):
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

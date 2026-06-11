#!/usr/bin/env python3
"""DD-033: the mechanical Layer-2 assembler — classify without the AI.

North star (2026-06-04): a work unit IS one session, so the global
dashboard needs no cross-session intelligence. This module deterministically
assembles cache/dashboard.json from per-session Layer-1 summaries:

    one eligible session  →  one card (id = card::<sid>)
    cards grouped by cwd  →  workspaces
    prior dashboard       →  name stability + tasks/artifacts monotone floor

Eligibility gate (replicates the implicit rule of the AI flow, where cold
summaries were never fed to the model and cards survived only via PRIOR
carry-forward):

    a session becomes a card iff it has a Layer-1 summary AND
      (it is hot  OR  it already has a card in PRIOR)
    AND it is not session-tombstoned (user deleted/archived, untouched since)
    AND (user_turns >= MIN_TURNS  OR  user-created  OR  already in PRIOR)

Without this gate the ~160 summaries on disk would flood the ~25-card
dashboard, and the 53 legacy id-only delete tombstones (whose sessions we
can't recover) would resurrect.

Everything here is a pure function of its arguments — disk I/O lives in
assemble_main() (and in classify.py, which remains the CLI entry point).
Parsing helpers are imported from classify (the surviving, non-AI half).
"""

from __future__ import annotations

import os

import classify as c


# ---------- small pure helpers ----------------------------------------------


def parse_blockers_from_fm(raw_fm: str) -> list[str]:
    """Extract the `blockers:` list (plain strings) from raw frontmatter.
    Same hand-rolled, zero-dep style as classify.parse_artifacts_from_fm."""
    if not raw_fm or "blockers:" not in raw_fm:
        return []
    out: list[str] = []
    in_block = False
    for line in raw_fm.splitlines():
        stripped = line.rstrip()
        if stripped and not line[0].isspace():
            if in_block:
                break
            if stripped.startswith("blockers:"):
                in_block = True
            continue
        if not in_block:
            continue
        s = stripped.lstrip()
        if s.startswith("- "):
            val = c._yaml_scalar(s[2:].strip())
            if val:
                out.append(val)
    return out


def first_sentence(text: str, max_len: int = 40) -> str:
    """First sentence of a body section, for the name-fallback ladder."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    for i, ch in enumerate(t):
        if ch in "。!?！？.;；":
            t = t[:i]
            break
    return t[:max_len].strip()


def derive_status(fm: dict) -> str:
    """DD-013 rule, degenerate single-session form."""
    sg = (fm.get("status_guess") or "active").strip().lower()
    if sg == "done":
        return "done"
    if sg in ("paused", "abandoned"):
        return "paused"
    return "active"


def assign_level(init: dict) -> str:
    """DD-014 minus `thread` (removed per DD-033 / north star)."""
    if init.get("sealed"):
        return "card"
    if (len(init.get("tasks") or []) <= 1 and not init.get("artifacts")
            and not init.get("blockers")):
        return "chip"
    return "card"


def card_name(prior_init: dict | None, fm: dict, body: str,
              created_ent: dict | None, ws_name: str) -> str:
    """Name precedence: prior card name (stability; covers legacy Layer-2
    names) → Layer-1 `title:` → first sentence of `# 目标` → workspace name.
    Exception: a prior name that is just the created-card placeholder (the
    worktree slug / ws name) upgrades to the Layer-1 title when one exists
    (DD-030's「AI 的好名字同步拷贝」, mechanically)."""
    title = (fm.get("title") or "").strip()
    prior_name = (prior_init or {}).get("name", "").strip()
    placeholder = {(created_ent or {}).get("slug") or "", ws_name, "sub-task"}
    if prior_name and not (prior_name in placeholder and title):
        return prior_name
    if title:
        return title
    goal = first_sentence(c._body_section(body, "目标", "Goal"))
    if goal:
        return goal
    return (created_ent or {}).get("slug") or ws_name


# ---------- tasks / artifacts: monotone merge vs PRIOR -----------------------
# Single-session ports of classify.aggregate_tasks / aggregate_artifacts
# (steps 1-2 of each; there is no "AI continuation" step 3 any more).


def merge_tasks(prior_init: dict | None, fm_tasks: list[dict],
                now_iso: str) -> list[dict]:
    """PRIOR tasks are the floor (never deleted, terminal never reverted);
    summary tasks insert new ids and may push pending → terminal.
    Shrink guard: if the merge would somehow lose entries, keep PRIOR."""
    prior_init = prior_init or {}
    merged: dict[str, dict] = {}
    for pt in (prior_init.get("tasks") or []):
        if not pt.get("title"):
            continue
        pid = pt.get("id") or c.slugify_task_title(pt["title"])
        merged[pid] = c._normalize_task(pt, pid, default_terminal_at=now_iso)
    for t in fm_tasks:
        if not t.get("title"):
            continue
        tid = c.slugify_task_title(t["title"])
        sess_status = t.get("status", "pending")
        cur = merged.get(tid)
        if cur is None:
            rec = {"id": tid, "title": t["title"], "status": sess_status}
            if sess_status in c.TASK_TERMINAL:
                rec["terminal_at"] = now_iso
                if t.get("evidence"):
                    rec["evidence"] = t["evidence"][:80]
            merged[tid] = rec
        else:
            cur["title"] = t["title"]
            if cur.get("status") == "pending" and sess_status in c.TASK_TERMINAL:
                cur["status"] = sess_status
                cur["terminal_at"] = now_iso
                if t.get("evidence"):
                    cur["evidence"] = t["evidence"][:80]
    prior_count = len([t for t in (prior_init.get("tasks") or [])
                       if t.get("title")])
    if len(merged) < prior_count:
        return list(prior_init.get("tasks") or [])
    return c._ordered_records(merged, prior_init)


def merge_artifacts(prior_init: dict | None, fm_arts: list[dict],
                    sess_la: str, hidden: set[str]) -> list[dict]:
    """PRIOR artifacts are the floor; summary artifacts add/advance status
    (terminal-monotone). DD-021 source filters: `commit` and url-less `doc`
    entries evaporate. User-hidden keys stay hidden. Cap 20, open-first."""
    prior_init = prior_init or {}
    merged: dict[str, dict] = {}

    def absorb(art: dict, source_recency: str) -> None:
        atype = (art.get("type") or "").strip().lower()
        if atype == "commit":
            return
        if atype == "doc":
            u = (art.get("url") or "").strip().lower()
            if not (u.startswith("http://") or u.startswith("https://")):
                return
        k = c.artifact_key(art)
        if not k:
            return
        cur = merged.get(k)
        if cur is None:
            merged[k] = dict(art)
            if source_recency and not merged[k].get("last_mentioned_at"):
                merged[k]["last_mentioned_at"] = source_recency
            return
        for f in ("type", "title", "ref_id", "url"):
            if not cur.get(f) and art.get(f):
                cur[f] = art[f]
        a_lm = art.get("last_mentioned_at") or source_recency or ""
        if a_lm and a_lm > (cur.get("last_mentioned_at") or ""):
            cur["last_mentioned_at"] = a_lm
        cur_status = (cur.get("status") or "").lower()
        new_status = (art.get("status") or "").lower()
        if cur_status in c.ARTIFACT_TERMINAL or not new_status:
            return
        if new_status in c.ARTIFACT_TERMINAL:
            cur["status"] = new_status
            return
        if (c._ARTIFACT_STATUS_PRIORITY.get(new_status, 0)
                >= c._ARTIFACT_STATUS_PRIORITY.get(cur_status, 0)):
            cur["status"] = new_status

    for art in (prior_init.get("artifacts") or []):
        absorb(art, prior_init.get("last_activity_at") or "")
    for art in fm_arts:
        absorb(art, sess_la)
    if hidden:
        merged = {k: v for k, v in merged.items() if k not in hidden}
    if len(merged) > 20:
        merged = dict(sorted(
            merged.items(),
            key=lambda kv: kv[1].get("last_mentioned_at") or "",
            reverse=True)[:20])

    def sort_key(a: dict) -> tuple:
        terminal = 1 if (a.get("status") or "").lower() in c.ARTIFACT_TERMINAL else 0
        return (terminal, c._neg_iso(a.get("last_mentioned_at")))

    return sorted(merged.values(), key=sort_key)


# ---------- the assembler ----------------------------------------------------


def build_card(sid: str, fm: dict, body: str, raw_fm: str,
               prior_init: dict | None, created_ent: dict | None,
               hidden_by_init: dict[str, set[str]], now_iso: str) -> dict:
    """One session → one card. Field sources per DD-033's table."""
    cwd = fm.get("cwd") or ""
    ws_name = c._ws_name_for_cwd(cwd)
    cid = "card::" + sid
    # hidden_artifacts overrides may be keyed by the prior (pre-migration)
    # id or by the canonical card::<sid> — honor both.
    hidden = set(hidden_by_init.get(cid) or set())
    if prior_init and prior_init.get("id"):
        hidden |= hidden_by_init.get(prior_init["id"]) or set()

    init: dict = {
        "id": cid,
        "name": card_name(prior_init, fm, body, created_ent, ws_name),
        "status": derive_status(fm),
        "summary": c._body_section(body, "目标", "Goal") or
                   (prior_init or {}).get("summary", ""),
        "progress": c._body_section(body, "当前状态", "Current state",
                                    "Current Status") or
                    (prior_init or {}).get("progress", ""),
        "tasks": merge_tasks(prior_init, c.parse_tasks_from_fm(raw_fm), now_iso),
        "sessions": [sid],
        "linked_cwds": [cwd] if cwd else [],
        "last_activity_at": fm.get("last_activity_at") or now_iso,
    }
    arts = merge_artifacts(prior_init, c.parse_artifacts_from_fm(raw_fm),
                           fm.get("last_activity_at") or "", hidden)
    if arts:
        init["artifacts"] = arts
    blockers = parse_blockers_from_fm(raw_fm)
    if blockers:
        init["blockers"] = blockers
    if (fm.get("next_step") or "").strip():
        init["next_step"] = fm["next_step"].strip()
    if (fm.get("awaiting_user") or "").strip():
        init["awaiting_user"] = fm["awaiting_user"].strip()
    init["level"] = assign_level(init)
    prior_level = (prior_init or {}).get("level")
    if init["level"] == prior_level and (prior_init or {}).get("level_set_at"):
        init["level_set_at"] = prior_init["level_set_at"]
    else:
        init["level_set_at"] = now_iso
    return init


def assemble(all_summaries: list, prior: dict | None, created_map: dict,
             deleted_ids: list[str], archived_ids: set[str],
             tomb_sids: dict[str, str], hidden_by_init: dict[str, set[str]],
             now_iso: str, *, hot_hours: int | None = None,
             min_turns: int | None = None) -> dict:
    """Assemble the full mindmap. Pure: every input is an argument.

    all_summaries: [(sid, fm, body, raw_fm)] — classify.collect_summaries()
    prior:         previous dashboard.json dict (or None)
    created_map:   {sid: {parent, slug}} — classify.load_created_cards_map()
    deleted_ids / archived_ids: id-level tombstones
    tomb_sids:     {sid: tombstoned_at} — session-level tombstones (archive ∪
                   delete, latest wins); a session is dead while
                   last_activity_at <= tombstoned_at
    """
    from datetime import datetime, timezone
    hot_hours = hot_hours if hot_hours is not None else c.HOT_HOURS
    min_turns = min_turns if min_turns is not None else c.MIN_TURNS
    dead_ids = set(deleted_ids or []) | set(archived_ids or set())
    now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) \
        if now_iso else datetime.now(timezone.utc)

    # PRIOR indexes: live cards by contributing session; sealed cards verbatim.
    prior_by_sid: dict[str, dict] = {}
    prior_sealed: list[tuple[str, str, dict]] = []   # (ws_name, ws_cwd, init)
    for w in ((prior or {}).get("workspaces") or []):
        for i in (w.get("initiatives") or []):
            if i.get("sealed"):
                prior_sealed.append((w.get("name") or "misc",
                                     w.get("cwd") or "", i))
                continue
            for s in (i.get("sessions") or []):
                prior_by_sid.setdefault(s, i)

    def session_tombstoned(sid: str, fm: dict) -> bool:
        ts = tomb_sids.get(sid)
        return bool(ts) and (fm.get("last_activity_at") or "") <= ts

    # ---- 1. eligibility + one card per session ----
    cards: list[dict] = []
    cwd_of: dict[str, str] = {}
    for sid, fm, body, raw_fm in all_summaries:
        prior_init = prior_by_sid.get(sid)
        created_ent = created_map.get(sid)
        if session_tombstoned(sid, fm):
            continue
        if prior_init is None and not c.is_hot(fm, now_dt):
            continue   # the gate: cold + never carded → never a card
        if prior_init is None and created_ent is None:
            try:
                if int(fm.get("user_turns", "0") or "0") < min_turns:
                    continue
            except (TypeError, ValueError):
                pass
        card = build_card(sid, fm, body, raw_fm, prior_init, created_ent,
                          hidden_by_init, now_iso)
        if card["id"] in dead_ids or (prior_init or {}).get("id") in dead_ids:
            continue
        cards.append(card)
        cwd_of[sid] = fm.get("cwd") or ""

    # ---- 2. group into workspaces by cwd (worktree → main repo) ----
    new_mm: dict = {"schema_version": 3, "generated_at": now_iso,
                    "workspaces": []}
    ws_by_name: dict[str, dict] = {}

    def ws_for(name: str, cwd: str) -> dict:
        ws = ws_by_name.get(name)
        if ws is None:
            main_cwd = (cwd.split("/.claude/worktrees/")[0]
                        if "/.claude/worktrees/" in cwd else cwd)
            ws = {"name": name, "cwd": main_cwd, "last_activity_at": "",
                  "initiatives": []}
            ws_by_name[name] = ws
            new_mm["workspaces"].append(ws)
        return ws

    for card in cards:
        sid = card["sessions"][0]
        cwd = cwd_of.get(sid, "")
        ws = ws_for(c._ws_name_for_cwd(cwd), cwd)
        ws["initiatives"].append(card)

    # ---- 3. sealed cards: carry PRIOR's verbatim, then mint new ones ----
    for ws_name, ws_cwd, init in prior_sealed:
        if init.get("id") in dead_ids:
            continue
        ws_for(ws_name, ws_cwd)["initiatives"].append(init)
    c.mint_sealed_initiatives(new_mm, all_summaries, list(dead_ids))

    # ---- 4. workspace stamps + deterministic order ----
    for ws in new_mm["workspaces"]:
        ws["last_activity_at"] = max(
            (i.get("last_activity_at") or "" for i in ws["initiatives"]),
            default="")
        ws["initiatives"].sort(
            key=lambda i: i.get("last_activity_at") or "", reverse=True)
    new_mm["workspaces"] = [w for w in new_mm["workspaces"]
                            if w["initiatives"]]
    new_mm["workspaces"].sort(
        key=lambda w: w.get("last_activity_at") or "", reverse=True)
    return new_mm


# ---------- I/O wrapper (the only impure part) -------------------------------


def assemble_main(output_path=None, *, consume_overrides: bool | None = None):
    """Assemble from the real cache and write dashboard.json (or
    output_path). Mirrors classify.main()'s I/O contract so the CLI shell
    and layer2-trigger.sh stay unchanged.

    consume_overrides: bake + clear user task toggles. Defaults to True
    only when writing the canonical dashboard (a shadow/diff run must
    never consume user intent)."""
    output_path = output_path or c.DASHBOARD_FILE
    is_canonical = (output_path == c.DASHBOARD_FILE)
    if consume_overrides is None:
        consume_overrides = is_canonical

    prior = c.load_prior() or {"schema_version": 3, "workspaces": []}
    c.apply_user_overrides_inplace(prior, consume=consume_overrides)
    all_summaries = c.collect_summaries()
    deleted_ids = c.load_deleted_ids()
    archived_ids = c.archived_ids_on_disk()
    tomb_sids = dict(c.archived_session_ids_on_disk())
    for sid, ts in c.deleted_session_ids_on_disk().items():
        if sid not in tomb_sids or ts > tomb_sids[sid]:
            tomb_sids[sid] = ts

    new_mm = assemble(all_summaries, prior, c.load_created_cards_map(),
                      deleted_ids, archived_ids, tomb_sids,
                      c.load_hidden_artifacts(), c.now_utc_iso())

    n_cards = sum(len(w["initiatives"]) for w in new_mm["workspaces"])
    print(f"[assemble] {len(all_summaries)} summaries → {n_cards} cards in "
          f"{len(new_mm['workspaces'])} workspaces (mechanical, no AI)")
    c.atomic_write_json(output_path, new_mm)
    print(f"[assemble] wrote {output_path}")
    c.emit_diff(prior, new_mm)
    if is_canonical:
        c.regen_html()
    return 0

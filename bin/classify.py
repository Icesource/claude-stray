#!/usr/bin/env python3
"""
Layer 2: mechanical dashboard assembly (DD-033 — no AI).

This module is the CLI shell + shared parsing/persistence library; the
assembly itself lives in bin/_assemble.py. The AI classifier and its nine
defensive repair passes were removed by DD-033 (the north star made
card = session, leaving the AI nothing to decide).

Reads:
  - cache/summaries/*.md             (Layer 1 outputs — the only AI in the pipeline)
  - cache/dashboard.json             (PRIOR — name stability + monotone floors)
  - cache/deleted_ids.json / cache/archive/   (tombstones, id + session level)
  - cache/user_overrides.json        (task toggles, hidden artifacts)
  - cache/created-cards.json / subcards.json  (user-created card registry)

Writes:
  - cache/dashboard.json             (replaces; atomic tmp+rename)
  - cache/mindmap-tree.html (regen)    (best-effort, non-fatal)

Concurrency:
  - One process at a time. Use bin/layer2-trigger.sh to launch
    (coalesce pattern: if another instance is running, the trigger
    just touches a pending marker and exits; the running instance
    loops if pending exists after its current run finishes).

Usage:
  python3 bin/classify.py                 # assemble cache/dashboard.json
  python3 bin/classify.py --output FILE   # write to FILE (shadow run; does
                                          #   not consume user overrides)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# STRAY_CACHE_DIR: test-isolation override (same contract as serve.py) —
# e2e tests point classify at a throwaway cache; production leaves it unset.
CACHE_DIR = Path(os.environ.get("STRAY_CACHE_DIR") or (REPO_ROOT / "cache"))
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
ARCHIVE_DIR = CACHE_DIR / "archive"
DASHBOARD_FILE = CACHE_DIR / "dashboard.json"
DELETED_FILE = CACHE_DIR / "deleted_ids.json"
OVERRIDES_FILE = CACHE_DIR / "user_overrides.json"
CONFIG_FILE = CACHE_DIR / "config.json"

# Valid task status values (DD-011).
TASK_STATUSES = ("pending", "done", "cancelled")
TASK_TERMINAL = ("done", "cancelled")

# Hot/cold threshold (configurable via env). A cold session that never had a
# card never becomes one (the DD-033 eligibility gate).
HOT_HOURS = int(os.environ.get("CLAUDE_WORKTREE_HOT_HOURS", "48"))
# Minimum user_turns for a session to mint a NEW card. Single-turn sessions
# are usually automation noise. User-created cards and sessions already
# carded in PRIOR are exempt. Set to 1 to disable filtering.
MIN_TURNS = int(os.environ.get("CLAUDE_WORKTREE_MIN_TURNS", "2"))


# ---------- helpers ---------------------------------------------------------


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Parse leading YAML frontmatter. Returns (flat_dict, body, raw_fm).

    flat_dict has only top-level scalar `key: value` entries (last_activity_at,
    status_guess, etc) — enough for hot/cold sorting. Nested fields like
    artifacts:/blockers: are NOT parsed into the dict but ARE preserved in
    raw_fm so we can re-emit them verbatim for the AI prompt.

    Tolerates AI drift in three flavors:
      1. Closing fence `---` (the canonical form).
      2. Closing fence ```` ``` ```` (Haiku occasionally swaps it).
      3. NO closing fence at all (Haiku sometimes drops it entirely;
         observed on summaries that still have valid YAML + a
         well-formed body). In that case we use the first markdown
         heading line `^# ...` as the boundary. Without this
         fallback, the whole summary is silently treated as
         frontmatter-less and any downstream code that reads
         last_activity_at, status_guess, etc. gets the wrong answer
         — including is_hot() returning False and skipping the
         session entirely (DD-013 §debug).
    """
    if not text.startswith("---"):
        return {}, text, ""
    m = re.search(r"^(?:---|```)\s*$", text[3:], flags=re.MULTILINE)
    if m:
        fm_end_pos = m.start()
        body_start_pos = m.end()
    else:
        # Tolerate Layer 1 dropping the closing fence. The first
        # markdown heading line (e.g. `# 目标`) is a reliable
        # boundary because Layer 1's body always starts with one.
        m_h = re.search(r"^#\s", text[3:], flags=re.MULTILINE)
        if not m_h:
            return {}, text, ""
        fm_end_pos = m_h.start()
        body_start_pos = m_h.start()  # keep the heading in the body
    fm_text = text[3:3 + fm_end_pos].strip()
    body = text[3 + body_start_pos:].lstrip("\n")
    fm: dict[str, str] = {}
    # Flat scalar fields only. Stop matching once a nested key starts
    # (e.g. `artifacts:` with list items beneath).
    for line in fm_text.splitlines():
        if line and not line[0].isspace() and ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            # If value is empty, this is a nested key (list/dict follows).
            # Skip; raw_fm has the full structure for prompt purposes.
            if not v:
                continue
            # Strip simple quotes for YAML scalars
            if (v.startswith('"') and v.endswith('"')) or \
               (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            fm[k.strip()] = v
    return fm, body, fm_text


_SLUG_NONWORD = re.compile(r"[^\w]+", flags=re.UNICODE)
_SLUG_DASHES = re.compile(r"-+")


def slugify_task_title(title: str, max_len: int = 64) -> str:
    """Stable slug derived from a task title (DD-008 §3.1).

    Deterministic: equal titles → equal slugs. Slight rewordings produce
    different slugs (v1 limitation; classify prompt instructs AI to
    reuse exact titles).
    """
    s = (title or "").strip().lower()
    s = _SLUG_NONWORD.sub("-", s)
    s = _SLUG_DASHES.sub("-", s).strip("-")
    s = (s or "task")[:max_len].rstrip("-")
    return s or "task"


def parse_tasks_from_fm(raw_fm: str) -> list[dict]:
    """Extract the `tasks:` block from raw frontmatter text.

    Expected shape (per prompts/summarize-session.md Rule 12, DD-011):

        tasks:
          - title: <text>
            status: pending | done | cancelled
            evidence: <text>     # optional, when status != pending
          - title: <text>
            status: pending

    Returns [{"title": str, "status": str, "evidence": str|None}, ...].
    Empty list if no `tasks:` key or it's malformed.

    Backward compatibility: a legacy `done: true|false` is mapped to
    `status: done|pending` so an old Layer 1 summary still in
    cache/summaries/ doesn't get dropped on the way to DD-011 storage.
    """
    if not raw_fm or "tasks:" not in raw_fm:
        return []
    lines = raw_fm.splitlines()
    out: list[dict] = []
    in_block = False
    cur: dict | None = None
    for line in lines:
        stripped = line.rstrip()
        # Top-level key starts at column 0
        if stripped and not line[0].isspace():
            if in_block:
                # Hit the next top-level key — stop
                if cur and cur.get("title"):
                    out.append(cur)
                break
            if stripped.startswith("tasks:"):
                in_block = True
            continue
        if not in_block:
            continue
        # Inside the tasks: block
        s = stripped.lstrip()
        if s.startswith("- "):
            if cur and cur.get("title"):
                out.append(cur)
            cur = {}
            rest = s[2:].strip()
            _absorb_task_field(cur, rest)
        elif cur is not None and ":" in s:
            _absorb_task_field(cur, s)
    if in_block and cur and cur.get("title"):
        out.append(cur)
    # Normalize: every task has a title and a status (default pending).
    norm: list[dict] = []
    for t in out:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        status = t.get("status")
        if status not in TASK_STATUSES:
            # Legacy fallback: `done: true|false`
            status = "done" if t.get("_legacy_done") else "pending"
        entry = {"title": title, "status": status}
        evidence = (t.get("evidence") or "").strip()
        if evidence:
            entry["evidence"] = evidence[:80]
        norm.append(entry)
    return norm


def _absorb_task_field(cur: dict, s: str) -> None:
    """Helper for parse_tasks_from_fm: parse one `key: value` line into cur."""
    if s.startswith("title:"):
        cur["title"] = _yaml_scalar(s[len("title:"):].strip())
    elif s.startswith("status:"):
        v = _yaml_scalar(s[len("status:"):].strip()).lower()
        if v in TASK_STATUSES:
            cur["status"] = v
    elif s.startswith("evidence:"):
        cur["evidence"] = _yaml_scalar(s[len("evidence:"):].strip())
    elif s.startswith("done:"):
        # Legacy bridge — kept so a pre-DD-011 summary in cache/
        # still parses. New Layer 1 outputs use `status:`.
        cur["_legacy_done"] = _yaml_bool(s[len("done:"):].strip())


def _yaml_scalar(s: str) -> str:
    if not s:
        return s
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _yaml_bool(s: str) -> bool:
    return s.strip().lower() in ("true", "yes", "on", "1")


# Artifact status values that, once reached, must not be reverted to an
# open state. (Mirrors prompts/summarize-session.md Rule 10 status enums.)
ARTIFACT_TERMINAL = frozenset({
    "merged", "closed", "wontfix", "stale", "released",
    "rolled-back", "pushed",
})

# Sort order priority for artifact status when rendering / picking
# canonical "most recent wins" outcome. Lower = more open, higher = more
# settled.
_ARTIFACT_STATUS_PRIORITY = {
    "pending": 0, "open": 0, "active": 0, "unknown": 0,
    "approved": 1, "live": 1, "local": 1,
    "merged": 2, "closed": 2, "wontfix": 2, "released": 2,
    "stale": 2, "rolled-back": 2, "pushed": 2,
}


def artifact_key(a: dict) -> str | None:
    """Stable identity key for an artifact across PRIOR / hot summaries /
    AI output.

    Precedence (matches the dedup rules in §7a of the classify prompt
    and Rule 10 of summarize-session):
      1. `url` if present and http(s)://
      2. `(type, ref_id)` if both present
      3. `(type, title)` if both present
    Otherwise: no stable identity → return None and the caller skips it
    (we won't promote untrackable noise into a permanent record).
    """
    if not isinstance(a, dict):
        return None
    typ = (a.get("type") or "").strip().lower()
    ref = str(a.get("ref_id") or "").strip()
    title = (a.get("title") or "").strip()
    # DD-021: prefer (type, ref_id) as identity. The SAME artifact often arrives
    # once WITH a url and once WITHOUT (different runs), and once with its name in
    # ref_id vs title — keying on url first would split those into duplicates.
    # ref_id is the stable id; fall back to url, then title.
    if typ and ref:
        return f"tid::{typ}::{ref}"
    url = (a.get("url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return "url::" + url
    if typ and title:
        return f"tid::{typ}::{title}"
    return None


def parse_artifacts_from_fm(raw_fm: str) -> list[dict]:
    """Extract the `artifacts:` block from raw frontmatter text.

    Expected shape (per prompts/summarize-session.md Rule 10):

        artifacts:
          - type: mr
            title: Kryo ClassLoader-aware
            ref_id: "27471050"
            url: https://code.alibaba-inc.com/.../27471050
            status: pending
            last_mentioned_at: 2026-05-19T09:21:42Z

    Returns a list of dicts, identity-preserving. Empty list if no
    `artifacts:` key or malformed. Zero external deps — hand-rolled to
    match parse_tasks_from_fm.
    """
    if not raw_fm or "artifacts:" not in raw_fm:
        return []
    lines = raw_fm.splitlines()
    out: list[dict] = []
    in_block = False
    cur: dict | None = None
    for line in lines:
        stripped = line.rstrip()
        if stripped and not line[0].isspace():
            # Top-level key — entering or leaving the block.
            if in_block:
                if cur and artifact_key(cur):
                    out.append(cur)
                cur = None
                in_block = False
                # Don't `break` — caller might have other top-level keys
                # after `artifacts:` (e.g. `blockers:`), and we want to
                # stop only at the artifacts boundary, not the whole FM.
            if stripped.startswith("artifacts:"):
                in_block = True
            continue
        if not in_block:
            continue
        s = stripped.lstrip()
        if s.startswith("- "):
            if cur and artifact_key(cur):
                out.append(cur)
            cur = {}
            rest = s[2:].strip()
            _absorb_artifact_field(cur, rest)
        elif cur is not None and ":" in s:
            _absorb_artifact_field(cur, s)
    if in_block and cur and artifact_key(cur):
        out.append(cur)
    return out


def _absorb_artifact_field(cur: dict, s: str) -> None:
    """Helper for parse_artifacts_from_fm: parse one `key: value` line."""
    field, _, val = s.partition(":")
    field = field.strip()
    val = _yaml_scalar(val.strip())
    if field in ("type", "title", "ref_id", "url", "status",
                 "last_mentioned_at") and val:
        cur[field] = val


def parse_sealed_segments_from_fm(raw_fm: str) -> list[dict]:
    """DD-019 — extract the `sealed_segments:` block from raw frontmatter.

    Shape (per prompts/summarize-session.md Rule 13):

        sealed_segments:
          - seg_id: linkify-error-message-url
            title: 错误消息 URL linkify
            status: done
            summary: ...
            sealed_at: 2026-06-03T02:50:08Z
            artifacts:
              - type: mr
                ref_id: "27752189"
                status: merged
            tasks:
              - title: ...
                status: done
                evidence: ...

    Returns [{seg_id,title,status,summary,sealed_at,artifacts[],tasks[]}].
    Each segment is dedented to column 0 and its nested artifacts/tasks are
    parsed by the existing parse_artifacts_from_fm / parse_tasks_from_fm
    (which key on a column-0 `artifacts:` / `tasks:`). Empty list if the key
    is absent or malformed.
    """
    if not raw_fm or "sealed_segments:" not in raw_fm:
        return []
    lines = raw_fm.splitlines()
    block: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() and not line[0].isspace():
            if in_block:
                break  # next top-level key ends the block
            if line.strip().startswith("sealed_segments:"):
                in_block = True
            continue
        if in_block:
            block.append(line)
    if not block:
        return []
    # Segment items start with a dash at the block's minimal indent.
    seg_indent = None
    for ln in block:
        st = ln.lstrip()
        if st.startswith("- "):
            seg_indent = len(ln) - len(st)
            break
    if seg_indent is None:
        return []
    groups: list[list[str]] = []
    cur: list[str] | None = None
    for ln in block:
        st = ln.lstrip()
        indent = len(ln) - len(st)
        if st.startswith("- ") and indent == seg_indent:
            if cur is not None:
                groups.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur is not None:
        groups.append(cur)
    base = seg_indent + 2  # "- " is two chars
    out: list[dict] = []
    for g in groups:
        dedented = [g[0].lstrip()[2:]]  # drop "<indent>- "
        for ln in g[1:]:
            dedented.append(ln[base:] if len(ln) >= base else ln.lstrip())
        seg = _parse_sealed_one("\n".join(dedented))
        if seg:
            out.append(seg)
    return out


def _parse_sealed_one(text: str) -> dict | None:
    """Parse one dedented sealed-segment block. Scalars at column 0;
    nested artifacts/tasks handled by the shared parsers. Requires a
    title to be a valid segment."""
    seg: dict = {
        "artifacts": parse_artifacts_from_fm(text),
        "tasks": parse_tasks_from_fm(text),
    }
    for line in text.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        if k in ("seg_id", "title", "status", "summary", "sealed_at"):
            val = _yaml_scalar(v.strip())
            if val:
                seg[k] = val
    if not seg.get("title"):
        return None
    seg.setdefault("status", "done")
    return seg


def collect_summaries() -> list[tuple[str, dict, str, str]]:
    """Return [(sid, flat_fm, body, raw_fm_text)] for all summary files."""
    if not SUMMARIES_DIR.is_dir():
        return []
    out = []
    for md in sorted(SUMMARIES_DIR.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body, raw_fm = parse_frontmatter(text)
        out.append((md.stem, fm, body, raw_fm))
    return out


def is_hot(fm: dict, now: datetime) -> bool:
    la = fm.get("last_activity_at", "")
    if not la:
        return False
    try:
        t = datetime.fromisoformat(la.replace("Z", "+00:00"))
    except ValueError:
        return False
    return t >= now - timedelta(hours=HOT_HOURS)


def load_prior() -> dict | None:
    if not DASHBOARD_FILE.exists():
        return None
    try:
        return json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_deleted_ids() -> list[str]:
    if not DELETED_FILE.exists():
        return []
    try:
        d = json.loads(DELETED_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [x.get("id") for x in (d.get("initiatives") or []) if x.get("id")]


# ---------- DD-019: intra-session segmentation (seal the past) ---------------
# A long session can finish one sub-effort then pivot to another. Layer 1 marks
# the terminal earlier sub-effort via `sealed_segments` (Rule 13). We mint each
# as a FROZEN historical card with `sessions: []` — which makes it automatically
# invisible to every session-keyed pass (the cockpit live OR-loop, focus/send,
# status derivation) — plus an `origin_session` soft-pointer for resume/
# transcript. Identity anchors on the segment's strongest artifact_key so the
# id is stable across reruns.

def _strip_sealed_from_live(new_mm: dict, sid: str, sealed_id: str,
                            seg: dict) -> None:
    """Remove the sealed segment's artifacts/tasks from the LIVE card(s)
    still bound to `sid`, so the achievement isn't double-listed on both the
    sealed card and the current-focus card."""
    art_keys = {artifact_key(a) for a in (seg.get("artifacts") or [])}
    art_keys.discard(None)
    task_ids = {slugify_task_title(t.get("title", ""))
                for t in (seg.get("tasks") or [])}
    task_ids.discard("")
    for ws in (new_mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            if init.get("sealed") or init.get("id") == sealed_id:
                continue
            if sid not in (init.get("sessions") or []):
                continue
            if art_keys and init.get("artifacts"):
                init["artifacts"] = [a for a in init["artifacts"]
                                     if artifact_key(a) not in art_keys]
            if task_ids and init.get("tasks"):
                init["tasks"] = [
                    t for t in init["tasks"]
                    if (t.get("id") or slugify_task_title(t.get("title", "")))
                    not in task_ids]


def mint_sealed_initiatives(new_mm: dict, all_summaries: list,
                            deleted_ids: list[str], prior: dict | None = None) -> int:
    """Mint/refresh sealed historical cards from Layer 1 sealed_segments.
    The empty sessions[] keeps these cards out of every session-keyed pass.
    Idempotent: a sealed card already carried forward (by id) is left frozen.

    Name freeze: a sealed card is FROZEN history — its name/summary must never
    drift. Layer-1 re-summarizes hot sessions, and the regenerated segment title
    can differ wildly from the original (conversation-internal jargon like
    "step 0 strip-group 探索及退出" replacing a good app-doc name). So when the
    same sealed_id exists in PRIOR_MINDMAP (i.e. it was minted before but got
    dropped from new_mm this round), re-mint it as a byte-copy of the PRIOR card
    — never from the fresh segment fields."""
    import copy as _copy
    prior_sealed = {}
    for w in ((prior or {}).get("workspaces") or []):
        for i in (w.get("initiatives") or []):
            if i.get("sealed") and i.get("id"):
                prior_sealed[i["id"]] = i
    deleted_set = set(deleted_ids or [])
    archived = archived_ids_on_disk()
    existing_ids: set[str] = set()
    ws_by_name = {w.get("name"): w for w in (new_mm.get("workspaces") or [])}
    ws_of_sid: dict[str, dict] = {}
    for ws in (new_mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            if init.get("id"):
                existing_ids.add(init["id"])
            for s in (init.get("sessions") or []):
                ws_of_sid.setdefault(s, ws)
    cwd_by_sid = {sid: (fm.get("cwd") or "")
                  for sid, fm, _b, _r in all_summaries}

    minted = 0
    for sid, fm, _body, raw_fm in all_summaries:
        for seg in parse_sealed_segments_from_fm(raw_fm):
            anchor_key = None
            for a in (seg.get("artifacts") or []):
                k = artifact_key(a)
                if k:
                    anchor_key = k
                    break
            if anchor_key:
                sealed_id = "sealed::" + anchor_key
            elif seg.get("seg_id"):
                sealed_id = "sealed::seg::" + seg["seg_id"]
            else:
                continue  # nothing stable to anchor on
            if (sealed_id in deleted_set or sealed_id in archived
                    or sealed_id in existing_ids):
                continue
            if sealed_id in prior_sealed:
                # was minted before, dropped this round → resurrect FROZEN
                # (prior byte-copy; never the re-generated segment title).
                init = _copy.deepcopy(prior_sealed[sealed_id])
                ws = ws_of_sid.get(sid)
                if ws is None:
                    cwd = cwd_by_sid.get(sid, "")
                    name = os.path.basename(cwd.rstrip("/")) or "misc"
                    ws = ws_by_name.get(name)
                    if ws is None:
                        ws = {"name": name, "cwd": cwd,
                              "last_activity_at": init.get("last_activity_at") or now_utc_iso(),
                              "initiatives": []}
                        (new_mm.setdefault("workspaces", [])).append(ws)
                        ws_by_name[name] = ws
                ws.setdefault("initiatives", []).append(init)
                existing_ids.add(sealed_id)
                minted += 1
                continue
            seg_status = (seg.get("status") or "done").lower()
            status = "archived" if seg_status == "abandoned" else "done"
            la = (seg.get("sealed_at") or fm.get("last_activity_at")
                  or now_utc_iso())
            tasks: list[dict] = []
            for t in (seg.get("tasks") or []):
                tid = slugify_task_title(t.get("title", ""))
                if not tid:
                    continue
                tst = t.get("status") if t.get("status") in TASK_STATUSES else "done"
                rec = {"id": tid, "title": t["title"], "status": tst}
                if t.get("evidence"):
                    rec["evidence"] = str(t["evidence"])[:80]
                if tst in TASK_TERMINAL:
                    rec["terminal_at"] = la
                tasks.append(rec)
            init = {
                "id": sealed_id,
                "name": seg.get("title") or "(sealed)",
                "status": status,
                "level": "card",
                "parent_thread_id": None,
                "summary": seg.get("summary") or "",
                "progress": seg.get("summary") or "",
                "tasks": tasks,
                "sessions": [],
                "linked_cwds": [],
                "last_activity_at": la,
                "artifacts": seg.get("artifacts") or [],
                "sealed": True,
                "origin_session": sid,
                "seg_id": seg.get("seg_id") or "",
                "sealed_at": seg.get("sealed_at") or la,
            }
            ws = ws_of_sid.get(sid)
            if ws is None:
                cwd = cwd_by_sid.get(sid, "")
                name = os.path.basename(cwd.rstrip("/")) or "misc"
                ws = ws_by_name.get(name)
                if ws is None:
                    ws = {"name": name, "cwd": cwd,
                          "last_activity_at": la, "initiatives": []}
                    (new_mm.setdefault("workspaces", [])).append(ws)
                    ws_by_name[name] = ws
            ws.setdefault("initiatives", []).append(init)
            existing_ids.add(sealed_id)
            _strip_sealed_from_live(new_mm, sid, sealed_id, seg)
            minted += 1
    return minted


def load_overrides() -> dict | None:
    if not OVERRIDES_FILE.exists():
        return None
    try:
        return json.loads(OVERRIDES_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def archived_ids_on_disk() -> set[str]:
    """Scan cache/archive/<ws>/<id>.json — those ids are user-archived
    and must NOT appear in PRIOR fed to AI (per DD-002 §6.2)."""
    out: set[str] = set()
    if not ARCHIVE_DIR.is_dir():
        return out
    for f in ARCHIVE_DIR.glob("*/*.json"):
        out.add(f.stem)
    return out


def load_subcards_map() -> dict:
    """cache/subcards.json — {child_sid: {parent, slug, created_at}} (DD-025)."""
    try:
        d = json.loads((CACHE_DIR / "subcards.json").read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_created_cards_map() -> dict:
    """DD-030: every user-created card (main OR sub) as {sid: {parent, slug}} —
    so mint_subcard_initiatives claims ALL of them into a stable card, not just
    sub-cards. Unioned with the legacy subcards.json. A main card has parent=None
    (link() then leaves it top-level); slug falls back to the workspace name."""
    out = dict(load_subcards_map())
    try:
        import _created
        doc = json.loads((CACHE_DIR / "created-cards.json").read_text())
        for sid, ent in _created.by_sid(doc).items():
            out.setdefault(sid, {"parent": ent.get("parent"),
                                 "slug": ent.get("worktree_name") or ent.get("name") or ""})
    except Exception:
        pass
    return out


def _ws_name_for_cwd(cwd: str) -> str:
    """Workspace label for a cwd. A worktree (…/.claude/worktrees/<slug>) belongs to
    its MAIN repo, so strip the worktree suffix → the repo's basename. The home
    dir itself reads as "home", not the user's login name."""
    c = (cwd or "").rstrip("/")
    if "/.claude/worktrees/" in c:
        c = c.split("/.claude/worktrees/")[0]
    if c and c == os.path.expanduser("~").rstrip("/"):
        return "home"
    return os.path.basename(c) or "misc"


def archived_session_ids_on_disk() -> dict[str, str]:
    """Map of {session_id: most-recent archived_at} for sessions that
    lived inside a user-archived initiative.

    Caller compares each session's `last_activity_at` against this
    timestamp: if the session hasn't been touched since being
    archived, it stays tombstoned (AI won't see it, can't recreate
    the initiative under a new id). If the user reopens the session
    and works on it again, last_activity > archived_at → the session
    is automatically un-tombstoned for the next classify round.

    Background: simply id-blacklisting an archived initiative isn't
    enough — AI can mint a NEW id for the same hot session and the
    card reappears (observed on 2026-05-15: same conceptual work
    archived 3 times under 3 slightly-different ids). And simply
    permanent-blacklisting the session_id over-archives long-lived
    sessions (e.g. session 940413c0 was once in
    claude-code-worktree-localization-hierarchy but has months of
    later work on a different topic; tombstoning it would erase that).
    Time-windowed tombstoning splits the difference.
    """
    out: dict[str, str] = {}
    if not ARCHIVE_DIR.is_dir():
        return out
    for f in ARCHIVE_DIR.glob("*/*.json"):
        try:
            rec = json.loads(f.read_text())
            archived_at = rec.get("archived_at") or ""
            init = rec.get("initiative") or {}
            for sid in (init.get("sessions") or []):
                if not sid:
                    continue
                # Keep the most-recent archive of this session
                if sid not in out or archived_at > out[sid]:
                    out[sid] = archived_at
        except (json.JSONDecodeError, OSError):
            continue
    return out


def deleted_session_ids_on_disk() -> dict[str, str]:
    """Map {session_id: most-recent deleted_at} for sessions that lived inside a
    user-DELETED card — the delete-side mirror of archived_session_ids_on_disk().

    DD-029: a deleted card was ONLY id-blacklisted (deleted_ids.json stored just
    the id). But the contributing session keeps its summary, so the AI re-mints a
    card for it with a FRESH id every round, dodging the id tombstone → the card
    the user deleted resurrects as a top-level card (observed: a merged sub-card
    deleted 4-5 times kept coming back). Same cure as archive: time-windowed
    SESSION tombstoning — filter the session from `hot` until
    last_activity_at > deleted_at, so genuine new work auto-un-tombstones while an
    untouched done session stays gone.

    Only tombstone entries carrying a `sessions` list participate; older id-only
    entries keep their id-based strip (strip_deleted_from_prior / the re-strip).
    """
    out: dict[str, str] = {}
    if not DELETED_FILE.exists():
        return out
    try:
        d = json.loads(DELETED_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return out
    for x in (d.get("initiatives") or []):
        deleted_at = x.get("deleted_at") or ""
        for sid in (x.get("sessions") or []):
            if not sid:
                continue
            if sid not in out or deleted_at > out[sid]:
                out[sid] = deleted_at
    return out


# ---------- apply user overrides ------------------------------------------


def apply_user_overrides_inplace(mindmap: dict, *, consume: bool = True) -> int:
    """Bake task_toggles + deleted_tasks from user_overrides.json into
    the in-memory mindmap. Returns count of changes.

    consume=False (DD-033 shadow/diff runs) applies the toggles but does
    NOT clear the overrides file — a non-canonical run must never eat
    user intent meant for the real dashboard.

    DD-011: toggles carry a `status` enum (`pending|done|cancelled`).
    A pre-DD-011 toggle with `done: bool` is accepted for backward
    compatibility — `done: true` → status `done`, `done: false` →
    status `pending`. The user-toggle path is the only way to revive
    a terminal task; AI never sees it (overrides are applied to PRIOR
    before slim_prior runs).

    P11.0: the read + clear of user_overrides.json is wrapped in
    cache_lock("overrides") so concurrent /api/save writes don't lose
    toggles between this function's read and its clear."""
    try:
        from _cache_lock import cache_lock as _cache_lock
    except Exception:
        import contextlib
        _cache_lock = contextlib.nullcontext  # type: ignore[assignment]

    with _cache_lock("overrides"):
        overrides = load_overrides()
        if not overrides:
            return 0
        task_toggles = overrides.get("task_toggles") or []
        deleted_tasks = overrides.get("deleted_tasks") or []
        if not (task_toggles or deleted_tasks):
            return 0

        def coerce_status(tt: dict) -> str:
            v = tt.get("status")
            if v in TASK_STATUSES:
                return v
            if "done" in tt:
                return "done" if tt["done"] else "pending"
            return "pending"

        toggle_idx = {(tt["init_id"], tt["task_title"]): coerce_status(tt)
                      for tt in task_toggles}
        del_set = {(dt["init_id"], dt["task_title"]) for dt in deleted_tasks}
        applied_tog = 0
        removed_tasks = 0
        now = now_utc_iso()
        for ws in mindmap.get("workspaces") or []:
            for init in ws.get("initiatives") or []:
                iid = init.get("id")
                new_tasks = []
                for t in init.get("tasks") or []:
                    title = t.get("title")
                    if (iid, title) in del_set:
                        removed_tasks += 1
                        continue
                    if (iid, title) in toggle_idx:
                        desired = toggle_idx[(iid, title)]
                        if t.get("status") != desired:
                            t["status"] = desired
                            if desired in TASK_TERMINAL:
                                t["terminal_at"] = now
                            else:
                                t.pop("terminal_at", None)
                                t.pop("evidence", None)
                            applied_tog += 1
                    new_tasks.append(t)
                init["tasks"] = new_tasks
        if (applied_tog or removed_tasks) and consume:
            print(f"[classify] applied {applied_tog} task toggles, "
                  f"removed {removed_tasks} deleted tasks")
            # Clear the consumed task overrides. Persistent suppression
            # lists (hidden_artifacts) carry forward — they must keep
            # filtering on every classify run.
            try:
                persistent = overrides.get("hidden_artifacts") or []
                OVERRIDES_FILE.write_text(
                    json.dumps({"version": 1, "task_toggles": [],
                                "deleted_tasks": [],
                                "hidden_artifacts": persistent,
                                "consumed_at": now_utc_iso()},
                               indent=2, ensure_ascii=False),
                    encoding="utf-8")
            except OSError as e:
                print(f"[classify] warning: failed to clear overrides: {e}",
                      file=sys.stderr)
        return applied_tog + removed_tasks


# ---------- shared task/artifact record helpers -----------------------------


def _body_section(body: str, *titles: str) -> str:
    """Extract one H1 section body (e.g. '当前状态') from a Layer-1 summary."""
    want = {t.strip() for t in titles}
    out, grab = [], False
    for ln in (body or "").splitlines():
        if ln.startswith("# "):
            if grab:
                break
            grab = ln[2:].strip() in want
            continue
        if grab:
            out.append(ln)
    return "\n".join(out).strip()


def _neg_iso(s: str | None) -> str:
    """Helper: reverse ISO-timestamp sort by inverting the string.
    Sorts None / empty last, newer timestamps first."""
    if not s:
        return "\x00"
    # Invert each char so lexicographic sort gives descending order.
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def load_hidden_artifacts() -> dict[str, set[str]]:
    """Return {init_id: set(artifact_key, ...)} from user_overrides.json.

    Stable suppression list (unlike task_toggles, NOT cleared after
    consumption) — an artifact the user deleted must stay deleted on
    every subsequent classify run, even if Layer 1 keeps re-emitting it
    from session frontmatter."""
    overrides = load_overrides()
    out: dict[str, set[str]] = {}
    if not overrides:
        return out
    for entry in (overrides.get("hidden_artifacts") or []):
        init_id = entry.get("init_id")
        key = entry.get("key")
        if init_id and key:
            out.setdefault(init_id, set()).add(key)
    return out


def _normalize_task(pt: dict, pid: str, *, default_terminal_at: str) -> dict:
    """Coerce a PRIOR task into the DD-011 schema. Legacy fields
    (done bool, done_evidence, done_at) are mapped to status/evidence/
    terminal_at; everything else (first_seen_at, sessions[], …) is
    dropped per DD-011's "5 fields max" goal."""
    title = pt["title"]
    status = pt.get("status")
    if status not in TASK_STATUSES:
        status = "done" if pt.get("done") else "pending"
    rec = {"id": pid, "title": title, "status": status}
    evidence = pt.get("evidence") or pt.get("done_evidence")
    if evidence:
        rec["evidence"] = str(evidence)[:80]
    terminal_at = pt.get("terminal_at") or pt.get("done_at")
    if status in TASK_TERMINAL:
        rec["terminal_at"] = terminal_at or default_terminal_at
    return rec


def _ordered_records(merged: dict[str, dict], prior_init: dict) -> list[dict]:
    """Return tasks sorted: pending in PRIOR order (new tasks last,
    by id order in dict), then terminal tasks by terminal_at desc."""
    prior_order = {t.get("id") or slugify_task_title(t.get("title", "")): i
                   for i, t in enumerate(prior_init.get("tasks") or [])
                   if t.get("title")}
    pending = [t for t in merged.values() if t.get("status") == "pending"]
    terminal = [t for t in merged.values() if t.get("status") in TASK_TERMINAL]
    pending.sort(key=lambda t: prior_order.get(t["id"], 10**6))
    terminal.sort(key=lambda t: t.get("terminal_at") or "", reverse=True)
    return pending + terminal


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def regen_html() -> None:
    """Best-effort regeneration of the markmap export view (render-tree.py).
    The classic card dashboard (render-html.py) was retired — the cockpit is
    the only live UI now. Failures here don't fail the run."""
    if os.environ.get("STRAY_NO_BG") == "1":
        return   # test isolation: render-tree writes to the REAL repo cache
    for script in ("render-tree.py",):
        try:
            subprocess.run(
                ["python3", str(REPO_ROOT / "bin" / script)],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass


# ---------- DIFF logging ---------------------------------------------------


def emit_diff(prior: dict | None, new: dict) -> None:
    """Print a structured DIFF for the log."""
    def index(d):
        out = {}
        for ws in (d.get("workspaces") or []):
            for i in (ws.get("initiatives") or []):
                tasks = i.get("tasks") or []
                out[i.get("id")] = {
                    "name": i.get("name"),
                    "status": i.get("status"),
                    "tasks_n": len(tasks),
                    "tasks_done": sum(1 for t in tasks
                                      if (t.get("status") == "done")
                                      or t.get("done") is True),
                }
        return out

    p = index(prior or {})
    n = index(new)
    added = sorted(set(n) - set(p))
    removed = sorted(set(p) - set(n))
    common = set(n) & set(p)
    status_changed = [i for i in common if p[i]["status"] != n[i]["status"]]
    name_changed = [i for i in common if p[i]["name"] != n[i]["name"]]
    task_progress = [
        i for i in common
        if p[i]["tasks_n"] != n[i]["tasks_n"]
        or p[i]["tasks_done"] != n[i]["tasks_done"]
    ]

    if not (added or removed or status_changed or name_changed or task_progress):
        print("[classify] DIFF vs prior: no structural change")
        return
    print("[classify] DIFF vs prior:")
    for i in added:
        print(f"  + NEW: {i} — {n[i]['name']}")
    for i in removed:
        print(f"  - REMOVED: {i} — {p[i]['name']}")
    for i in status_changed:
        print(f"  ~ status: {i} {p[i]['status']} → {n[i]['status']}  ({n[i]['name']})")
    for i in name_changed:
        print(f"  ~ name: {i}  {p[i]['name']!r} → {n[i]['name']!r}")
    for i in task_progress:
        print(f"  ~ tasks: {i} {p[i]['tasks_n']}→{n[i]['tasks_n']}, "
              f"done {p[i]['tasks_done']}→{n[i]['tasks_done']}  ({n[i]['name']})")


# ---------- main ------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Layer 2: mechanical dashboard assembly (DD-033)")
    ap.add_argument("--output", type=Path, default=None,
                    help=f"write result to FILE instead of {DASHBOARD_FILE} "
                         "(shadow run: user overrides are not consumed)")
    ap.add_argument("--mech", action="store_true",
                    help="deprecated no-op (mechanical assembly is the default)")
    args = ap.parse_args()
    import _assemble
    return _assemble.assemble_main(args.output or DASHBOARD_FILE)


if __name__ == "__main__":
    sys.exit(main())

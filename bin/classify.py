#!/usr/bin/env python3
"""
Layer 2 of the AI pipeline (per DD-002).

Reads:
  - cache/summaries/*.md             (Layer 1 outputs)
  - cache/mindmap.json               (PRIOR_MINDMAP — sole task store, DD-011)
  - cache/deleted_ids.json           (DELETED_IDS)
  - cache/user_overrides.json        (applied to PRIOR before AI call)
  - cache/archive/<ws>/<id>.json     (used to strip archived ids from PRIOR)

Calls Haiku with prompts/classify-cross-session.md.

Writes:
  - cache/mindmap.json               (replaces; atomic tmp+rename)
  - cache/cost_log.jsonl             (via _cost_log helper)
  - cache/mindmap.html (regen)       (best-effort, non-fatal)
  - cache/mindmap-tree.html (regen)

Concurrency:
  - One process at a time. Use bin/layer2-trigger.sh to launch
    (coalesce pattern: if another instance is running, the trigger
    just touches a pending marker and exits; the running instance
    loops if pending exists after its current run finishes).

Usage:
  python3 bin/classify.py                 # do the thing
  python3 bin/classify.py --dry-run       # build prompt, don't call AI
  python3 bin/classify.py --output FILE   # write to FILE instead of mindmap.json
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
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
ARCHIVE_DIR = CACHE_DIR / "archive"
MINDMAP_FILE = CACHE_DIR / "mindmap.json"
DELETED_FILE = CACHE_DIR / "deleted_ids.json"
OVERRIDES_FILE = CACHE_DIR / "user_overrides.json"
CONFIG_FILE = CACHE_DIR / "config.json"
PROMPT_FILE = REPO_ROOT / "prompts" / "classify-cross-session.md"

# Valid task status values (DD-011).
TASK_STATUSES = ("pending", "done", "cancelled")
TASK_TERMINAL = ("done", "cancelled")

# Hot/cold threshold (configurable via env)
HOT_HOURS = int(os.environ.get("CLAUDE_WORKTREE_HOT_HOURS", "48"))
# Hard cap on how many hot summaries we feed Haiku in one call. Haiku-4.5
# has 200K context; ~1KB per summary + 30KB of instructions + slim PRIOR
# means ~150 summaries is the safe ceiling. If you have more, take the
# most-recently-active ones; older "still hot" sessions are continued
# via PRIOR_MINDMAP on the next run.
MAX_HOT = int(os.environ.get("CLAUDE_WORKTREE_MAX_HOT", "120"))
# Minimum user_turns for a summary to be a hot input. Single-turn sessions
# are usually automation noise (despite is_automation filtering some out)
# and rarely add real signal. Set to 1 to disable filtering.
MIN_TURNS = int(os.environ.get("CLAUDE_WORKTREE_MIN_TURNS", "2"))

# claude -p settings
CLAUDE_TIMEOUT_SECS = int(os.environ.get("CLAUDE_WORKTREE_TIMEOUT", "600"))
CLAUDE_MODEL = os.environ.get("CLAUDE_WORKTREE_MODEL", "claude-haiku-4-5-20251001")


# ---------- helpers ---------------------------------------------------------


def get_lang() -> str:
    env = os.environ.get("CLAUDE_WORKTREE_LANG")
    if env:
        return env
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text()).get("lang", "zh-CN")
        except Exception:
            pass
    return "zh-CN"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Parse leading YAML frontmatter. Returns (flat_dict, body, raw_fm).

    flat_dict has only top-level scalar `key: value` entries (last_activity_at,
    status_guess, etc) — enough for hot/cold sorting. Nested fields like
    artifacts:/blockers: are NOT parsed into the dict but ARE preserved in
    raw_fm so we can re-emit them verbatim for the AI prompt.

    Tolerates AI drift: accepts either `---` or ```` ``` ```` as the
    closing fence, because Haiku occasionally emits the latter when the
    prompt happens to wrap the example template in a code fence.
    """
    if not text.startswith("---"):
        return {}, text, ""
    m = re.search(r"^(?:---|```)\s*$", text[3:], flags=re.MULTILINE)
    if not m:
        return {}, text, ""
    fm_text = text[3:3 + m.start()].strip()
    body = text[3 + m.end():].lstrip("\n")
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
    if not MINDMAP_FILE.exists():
        return None
    try:
        return json.loads(MINDMAP_FILE.read_text(encoding="utf-8"))
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


# ---------- apply user overrides ------------------------------------------


def apply_user_overrides_inplace(mindmap: dict) -> int:
    """Bake task_toggles + deleted_tasks from user_overrides.json into
    the in-memory mindmap. Returns count of changes.

    DD-011: toggles carry a `status` enum (`pending|done|cancelled`).
    A pre-DD-011 toggle with `done: bool` is accepted for backward
    compatibility — `done: true` → status `done`, `done: false` →
    status `pending`. The user-toggle path is the only way to revive
    a terminal task; AI never sees it (overrides are applied to PRIOR
    before slim_prior runs)."""
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
    if applied_tog or removed_tasks:
        print(f"[classify] applied {applied_tog} task toggles, "
              f"removed {removed_tasks} deleted tasks")
        # Clear the consumed overrides
        try:
            OVERRIDES_FILE.write_text(
                json.dumps({"version": 1, "task_toggles": [], "deleted_tasks": [],
                            "consumed_at": now_utc_iso()},
                           indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            print(f"[classify] warning: failed to clear overrides: {e}",
                  file=sys.stderr)
    return applied_tog + removed_tasks


def strip_archived_from_prior(mindmap: dict) -> int:
    """Remove initiatives whose id is in cache/archive/. They're user-
    archived; AI must never see them in PRIOR."""
    arc_ids = archived_ids_on_disk()
    if not arc_ids:
        return 0
    removed = 0
    for ws in mindmap.get("workspaces") or []:
        before = len(ws.get("initiatives") or [])
        ws["initiatives"] = [
            i for i in (ws.get("initiatives") or [])
            if i.get("id") not in arc_ids
        ]
        removed += before - len(ws.get("initiatives") or [])
    # Drop workspaces left empty
    mindmap["workspaces"] = [
        w for w in (mindmap.get("workspaces") or [])
        if (w.get("initiatives") or [])
    ]
    if removed:
        print(f"[classify] excluded {removed} archived initiatives from PRIOR")
    return removed


def strip_deleted_from_prior(mindmap: dict, deleted_ids: list[str]) -> int:
    """Remove initiatives whose id is in deleted_ids.json tombstones."""
    if not deleted_ids:
        return 0
    del_set = set(deleted_ids)
    removed = 0
    for ws in mindmap.get("workspaces") or []:
        before = len(ws.get("initiatives") or [])
        ws["initiatives"] = [
            i for i in (ws.get("initiatives") or [])
            if i.get("id") not in del_set
        ]
        removed += before - len(ws.get("initiatives") or [])
    mindmap["workspaces"] = [
        w for w in (mindmap.get("workspaces") or [])
        if (w.get("initiatives") or [])
    ]
    if removed:
        print(f"[classify] excluded {removed} deleted-id initiatives from PRIOR")
    return removed


# ---------- prompt build ----------------------------------------------------


def slim_prior(prior: dict | None) -> dict | None:
    """Keep everything AI needs for continuity (id, name, status,
    summary, progress, tasks, sessions, linked_cwds, last_activity_at)
    and drop noise (generated_at, schema_version stays)."""
    if not prior:
        return None
    return {
        "schema_version": prior.get("schema_version", 2),
        "workspaces": [
            {
                "name": w.get("name"),
                "cwd": w.get("cwd"),
                "last_activity_at": w.get("last_activity_at"),
                "initiatives": [
                    {
                        "id": i.get("id"),
                        "name": i.get("name"),
                        "status": i.get("status"),
                        "summary": i.get("summary"),
                        "progress": i.get("progress"),
                        "tasks": i.get("tasks", []),
                        "sessions": i.get("sessions", []),
                        "linked_cwds": i.get("linked_cwds", []),
                        "last_activity_at": i.get("last_activity_at"),
                        **({"artifacts": i["artifacts"]}
                            if i.get("artifacts") else {}),
                        **({"blockers": i["blockers"]}
                            if i.get("blockers") else {}),
                    }
                    for i in (w.get("initiatives") or [])
                ],
            }
            for w in (prior.get("workspaces") or [])
        ],
    }


def build_prompt(hot: list[tuple[str, dict, str, str]],
                 prior_slim: dict | None,
                 deleted_ids: list[str],
                 lang: str) -> str:
    instructions = PROMPT_FILE.read_text(encoding="utf-8")
    parts = [instructions, ""]
    parts.append("<context>")
    parts.append(f"  <output_lang>{lang}</output_lang>")
    parts.append(f"  <now>{now_utc_iso()}</now>")
    parts.append("</context>")
    parts.append("")

    if prior_slim and prior_slim.get("workspaces"):
        parts.append("<prior_mindmap>")
        parts.append(json.dumps(prior_slim, ensure_ascii=False, indent=2))
        parts.append("</prior_mindmap>")
    else:
        parts.append("<prior_mindmap>(none — first run)</prior_mindmap>")
    parts.append("")

    if deleted_ids:
        parts.append("<deleted_ids>")
        parts.append(json.dumps({"deleted_initiative_ids": deleted_ids},
                                ensure_ascii=False))
        parts.append("</deleted_ids>")
    else:
        parts.append("<deleted_ids>(none)</deleted_ids>")
    parts.append("")

    parts.append(f'<hot_summaries count="{len(hot)}">')
    for sid, _fm, body, raw_fm in hot:
        # Re-emit the whole summary file (frontmatter + body) so AI sees the
        # exact structure Layer 1 wrote — including nested `artifacts:` /
        # `blockers:` YAML that our flat parser dropped.
        parts.append(f'<summary sid="{sid}">')
        parts.append("---")
        parts.append(raw_fm.rstrip())
        parts.append("---")
        parts.append(body.rstrip())
        parts.append("</summary>")
    parts.append("</hot_summaries>")

    return "\n".join(parts)


# ---------- AI call ---------------------------------------------------------


def call_claude(prompt: str) -> tuple[dict | None, str, int, float]:
    t_start = time.time()
    try:
        # --no-session-persistence: see summarize.py for the full
        # reasoning. Required to prevent self-recursion via Stop hook.
        # --max-budget-usd is per-call: a normal classify is ~$0.17 with
        # ~120 hot summaries, $2.50 covers worst-case w/ retries.
        argv = [
            "perl", "-e", "alarm shift @ARGV; exec @ARGV",
            str(CLAUDE_TIMEOUT_SECS),
            "claude", "--no-session-persistence", "-p",
            "--model", CLAUDE_MODEL,
            "--output-format", "json",
            "--max-budget-usd", "2.50",
            "--disallowedTools", "Bash Edit Write Read Glob Grep",
        ]
        result = subprocess.run(
            argv, input=prompt, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT_SECS + 10,
        )
        duration = time.time() - t_start
        if result.returncode != 0:
            return None, result.stderr or "", result.returncode, duration
        try:
            env = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, result.stdout, 1, duration
        return env, env.get("result", "") or "", 0, duration
    except subprocess.TimeoutExpired:
        return None, "timeout", 124, time.time() - t_start
    except Exception as e:
        return None, str(e), 1, time.time() - t_start


def log_cost(envelope: dict | None, duration_s: float, ok: bool) -> None:
    try:
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from _cost_log import log_cost as _log
        _log(layer="classify", envelope=envelope, duration_s=duration_s,
             session_id=None, ok=ok)
    except Exception as e:
        print(f"[classify] cost-log failed: {e}", file=sys.stderr)


# ---------- output parse + repair ------------------------------------------


def parse_ai_output(raw: str) -> dict:
    raw = raw.strip()
    # Strip surrounding code fence if present
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    if not raw.startswith("{"):
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j != -1:
            raw = raw[i:j + 1]
    return json.loads(raw)


def enforce_cold_and_terminal_monotone(new_mm: dict, prior: dict,
                                        hot_sids: list[str]) -> int:
    """
    Belt-and-suspenders enforcement of two hard rules from
    prompts/classify-cross-session.md:

      §5 (Cold rule)            An initiative whose sessions[] in PRIOR
                                has NO overlap with the hot sids is
                                "cold". For cold initiatives, ONLY status
                                and last_activity_at may change.

      §4 (Terminal monotone)    Any task that was status=done OR
                                status=cancelled in PRIOR must remain
                                that exact terminal status in output.
                                (DD-011 extension of DD-010's done-monotone.)

    AI follows the prompt most of the time but sometimes drifts. This
    pass deterministically repairs drift so downstream readers can
    trust the invariants.

    Returns the number of repairs made (for logging).
    """
    hot_sids_set = set(hot_sids)
    prior_by_id: dict[str, dict] = {}
    for w in (prior.get("workspaces") or []):
        for i in (w.get("initiatives") or []):
            prior_by_id[i.get("id")] = i

    repairs = 0
    for ws in new_mm.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            iid = init.get("id")
            prior_init = prior_by_id.get(iid)
            if prior_init is None:
                continue  # genuinely new initiative — AI is free

            prior_sessions = set(prior_init.get("sessions") or [])
            is_cold = not (prior_sessions & hot_sids_set)

            if is_cold:
                # §5: restore every field except status + last_activity_at.
                # artifacts/blockers are also restricted (they only update
                # when a hot session contributes).
                for field in ("name", "summary", "progress", "tasks",
                              "sessions", "linked_cwds",
                              "artifacts", "blockers"):
                    if field not in prior_init:
                        # PRIOR doesn't have this field → strip from output
                        if field in init:
                            init.pop(field)
                            repairs += 1
                        continue
                    if init.get(field) != prior_init.get(field):
                        init[field] = prior_init.get(field)
                        repairs += 1
            else:
                # §4: terminal monotone. Walk PRIOR tasks; for any task
                # in a terminal status in PRIOR, force that exact status
                # in output if the same id still exists. Add back tasks
                # AI dropped (DD-011 invariant — no AI deletion).
                prior_tasks = prior_init.get("tasks") or []
                new_tasks = init.get("tasks") or []
                new_by_id = {t.get("id") or slugify_task_title(t.get("title", "")):
                             t for t in new_tasks if t.get("title")}
                for pt in prior_tasks:
                    title = pt.get("title")
                    if not title:
                        continue
                    pt_status = pt.get("status") or "pending"
                    if pt_status not in TASK_TERMINAL:
                        continue
                    pid = pt.get("id") or slugify_task_title(title)
                    nt = new_by_id.get(pid)
                    if nt is None:
                        # AI dropped a terminal task — add it back
                        restored = {"id": pid, "title": title, "status": pt_status}
                        if pt.get("evidence"):
                            restored["evidence"] = pt["evidence"]
                        if pt.get("terminal_at"):
                            restored["terminal_at"] = pt["terminal_at"]
                        new_tasks.append(restored)
                        repairs += 1
                    elif nt.get("status") != pt_status:
                        nt["status"] = pt_status
                        # Keep PRIOR's evidence/terminal_at if AI clobbered them.
                        if pt.get("evidence") and not nt.get("evidence"):
                            nt["evidence"] = pt["evidence"]
                        if pt.get("terminal_at") and not nt.get("terminal_at"):
                            nt["terminal_at"] = pt["terminal_at"]
                        repairs += 1
                init["tasks"] = new_tasks
    return repairs


def aggregate_tasks(new_mm: dict, prior: dict,
                    hot_summaries: list) -> int:
    """DD-011 — tri-state, single-store task aggregation.

    Tasks live solely in mindmap.json. AI is additive-only: it may add
    new tasks and may flip PRIOR `pending` to `done` or `cancelled`
    with evidence, but never deletes and never reverts terminal status.
    Only the user can delete or revive (via user_overrides.json).

    For each hot initiative:
      1. Carry forward every PRIOR task (DD-010/DD-011 invariant).
      2. Merge in tasks from this initiative's hot session summaries
         (Layer 1 frontmatter). New ids are inserted; existing ids
         get title refresh + terminal-monotone update.
      3. Apply AI continuations from new_mm: id-matched PRIOR entries
         get title rewording / status flips with evidence.
      4. Defensive shrink check: if the post-merge count is somehow
         lower than PRIOR, refuse to write (leaves stale tasks rather
         than silently destroying data).
      5. Replace init["tasks"] with the 5-field DD-011 record.

    Cold initiatives are untouched (§5) beyond a one-shot id backfill.

    Returns n_initiatives_processed (for log).
    """
    now_iso = now_utc_iso()

    hot_tasks_by_sid: dict[str, list[dict]] = {}
    for sid, _fm, _body, raw_fm in hot_summaries:
        hot_tasks_by_sid[sid] = parse_tasks_from_fm(raw_fm)

    prior_by_id: dict[str, dict] = {}
    for w in (prior.get("workspaces") or []):
        for i in (w.get("initiatives") or []):
            prior_by_id[i.get("id")] = i

    n_inits = 0

    for ws in new_mm.get("workspaces") or []:
        for init in (ws.get("initiatives") or []):
            init_id = init.get("id")
            if not init_id:
                continue
            sessions = init.get("sessions") or []
            hot_in_init = [s for s in sessions if s in hot_tasks_by_sid]
            if not hot_in_init:
                # Cold — only backfill missing id slugs on legacy entries.
                for t in (init.get("tasks") or []):
                    if t.get("title") and not t.get("id"):
                        t["id"] = slugify_task_title(t["title"])
                continue
            n_inits += 1

            prior_init = prior_by_id.get(init_id, {})

            # Step 1: carry forward PRIOR. Normalize to DD-011 schema
            # in case legacy entries with `done: bool` slipped through.
            merged: dict[str, dict] = {}
            for pt in (prior_init.get("tasks") or []):
                if not pt.get("title"):
                    continue
                pid = pt.get("id") or slugify_task_title(pt["title"])
                merged[pid] = _normalize_task(pt, pid, default_terminal_at=now_iso)

            # Step 2: hot-summary tasks. Existing ids get monotonic upgrade
            # to terminal status; new ids are inserted as fresh tasks.
            for sid in hot_in_init:
                for t in hot_tasks_by_sid.get(sid, []):
                    tid = slugify_task_title(t["title"])
                    sess_status = t.get("status", "pending")
                    cur = merged.get(tid)
                    if cur is None:
                        rec = {"id": tid, "title": t["title"],
                               "status": sess_status}
                        if sess_status in TASK_TERMINAL:
                            rec["terminal_at"] = now_iso
                            if t.get("evidence"):
                                rec["evidence"] = t["evidence"][:80]
                        merged[tid] = rec
                    else:
                        cur["title"] = t["title"]  # latest wording
                        if (cur.get("status") == "pending"
                                and sess_status in TASK_TERMINAL):
                            cur["status"] = sess_status
                            cur["terminal_at"] = now_iso
                            if t.get("evidence"):
                                cur["evidence"] = t["evidence"][:80]

            # Step 3: AI continuations. Match by id only — DD-011 forbids
            # AI from inventing new ids here (those come via hot summaries).
            for t in (init.get("tasks") or []):
                ai_id = t.get("id")
                title = t.get("title")
                if not ai_id or ai_id not in merged or not title:
                    continue
                cur = merged[ai_id]
                cur["title"] = title
                ai_status = (t.get("status") or "").lower()
                evidence = (t.get("evidence")
                            or t.get("done_evidence")  # legacy field name
                            or "").strip()[:80] or None
                if (cur.get("status") == "pending"
                        and ai_status in TASK_TERMINAL):
                    cur["status"] = ai_status
                    cur["terminal_at"] = now_iso
                    if evidence:
                        cur["evidence"] = evidence
                elif evidence and cur.get("status") in TASK_TERMINAL \
                        and not cur.get("evidence"):
                    cur["evidence"] = evidence

            # Step 4: shrink guard. The post-merge set must not be smaller
            # than PRIOR — that's the DD-010/DD-011 canary for "AI dropped
            # tasks." If tripped, skip the write for this initiative.
            prior_count = len([t for t in (prior_init.get("tasks") or [])
                               if t.get("title")])
            if len(merged) < prior_count:
                print(f"[classify] !! REFUSING to shrink tasks on {init_id}: "
                      f"prior={prior_count} new={len(merged)} — leaving "
                      f"PRIOR tasks unchanged", file=sys.stderr)
                continue

            # Step 5: emit DD-011 records (id, title, status, evidence?,
            # terminal_at?). Order: pending first (PRIOR order preserved),
            # then terminal (most-recent terminal_at first).
            init["tasks"] = _ordered_records(merged, prior_init)
            # DD-011 cleanup: archive-related counters no longer apply.
            init.pop("tasks_archived_count", None)

    return n_inits


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


def repair_short_session_ids(mindmap: dict, hot_sids: list[str]) -> int:
    """If AI emitted 8-char prefixes instead of full UUIDs, restore via
    exact-prefix match against the hot sids we know."""
    prefix_to_full: dict[str, list[str]] = {}
    for fid in hot_sids:
        for L in (4, 6, 8, 10, 12):
            prefix_to_full.setdefault(fid[:L], []).append(fid)

    def repair(sid: str) -> str:
        if not sid or len(sid) >= 30:
            return sid
        cands = prefix_to_full.get(sid, [])
        return cands[0] if len(cands) == 1 else sid

    repaired = 0
    for ws in mindmap.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            new = []
            for s in init.get("sessions") or []:
                fixed = repair(s)
                if fixed != s:
                    repaired += 1
                new.append(fixed)
            init["sessions"] = new
    return repaired


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def regen_html() -> None:
    """Best-effort HTML regeneration. Failures here don't fail the run."""
    for script in ("render-html.py", "render-tree.py"):
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
    ap = argparse.ArgumentParser(description="Layer 2: cross-session classifier")
    ap.add_argument("--dry-run", action="store_true",
                    help="build prompt, print summary, do not call AI")
    ap.add_argument("--output", type=Path, default=None,
                    help=f"write result to FILE instead of {MINDMAP_FILE}")
    args = ap.parse_args()

    output_path = args.output or MINDMAP_FILE

    # ---- 1. Load + clean PRIOR ----
    prior = load_prior() or {"schema_version": 2, "workspaces": []}
    apply_user_overrides_inplace(prior)
    strip_archived_from_prior(prior)
    deleted_ids = load_deleted_ids()
    # Note: don't strip deleted from PRIOR if you want AI to see the
    # tombstones explicitly; instead we pass deleted_ids separately.
    # But we DO need to remove them from the AI's PRIOR view because
    # the prompt §3 says "never include deleted ids in output" — if AI
    # sees them in PRIOR it might preserve them out of continuity.
    strip_deleted_from_prior(prior, deleted_ids)
    prior_slim = slim_prior(prior)

    # ---- 2. Hot summaries ----
    all_summaries = collect_summaries()
    now = datetime.now(timezone.utc)
    hot = [(sid, fm, body, raw_fm)
           for sid, fm, body, raw_fm in all_summaries if is_hot(fm, now)]
    cold_count = len(all_summaries) - len(hot)
    hot_total = len(hot)

    # Filter user-archived session_ids: when the user archived an
    # initiative, its sessions are tombstoned UNTIL they're touched
    # again (last_activity_at > archived_at). New activity
    # automatically un-tombstones — the session reappears in a fresh
    # initiative. Prevents the "archive recreates with a new id" loop.
    archived_sids_map = archived_session_ids_on_disk()
    if archived_sids_map:
        def is_still_archived(sid: str, fm: dict) -> bool:
            arch_at = archived_sids_map.get(sid)
            if not arch_at:
                return False
            last_act = fm.get("last_activity_at") or ""
            return last_act <= arch_at
        before = len(hot)
        hot = [tup for tup in hot if not is_still_archived(tup[0], tup[1])]
        filtered_archived = before - len(hot)
    else:
        filtered_archived = 0

    # Filter low-signal sessions: 1-turn (likely automation noise).
    if MIN_TURNS > 1:
        def has_enough_turns(fm):
            try:
                return int(fm.get("user_turns", "0") or "0") >= MIN_TURNS
            except (TypeError, ValueError):
                return True
        hot = [tup for tup in hot if has_enough_turns(tup[1])]
        filtered_thin = hot_total - len(hot) - filtered_archived
    else:
        filtered_thin = 0

    # Cap: keep most-recently-active MAX_HOT. Older "still hot" sessions are
    # carried by PRIOR_MINDMAP. Sort by last_activity_at desc.
    def sort_key(tup):
        return tup[1].get("last_activity_at") or ""
    hot.sort(key=sort_key, reverse=True)
    capped = len(hot) > MAX_HOT
    if capped:
        hot = hot[:MAX_HOT]

    print(f"[classify] summaries: {len(all_summaries)} total, "
          f"{hot_total} hot (last {HOT_HOURS}h), {cold_count} cold")
    if filtered_archived:
        print(f"[classify] filtered {filtered_archived} archived-session(s) "
              f"(user-archived; will NOT regenerate as new initiative)")
    if filtered_thin:
        print(f"[classify] filtered {filtered_thin} thin sessions "
              f"(user_turns<{MIN_TURNS})")
    if capped:
        print(f"[classify] capped to {MAX_HOT} most-recent hot summaries "
              f"(env CLAUDE_WORKTREE_MAX_HOT to override)")
    if not hot and (prior_slim is None or not prior_slim.get("workspaces")):
        print("[classify] nothing to classify (no hot summaries, no prior)",
              file=sys.stderr)
        return 0

    # ---- 3. Build prompt ----
    lang = get_lang()
    prompt = build_prompt(hot, prior_slim, deleted_ids, lang)
    prompt_kb = len(prompt.encode("utf-8")) / 1024

    if args.dry_run:
        print(f"[classify] dry-run: prompt={prompt_kb:.1f}KB, "
              f"{len(hot)} hot summaries")
        print(f"[classify] would write to {output_path}")
        # Optional: also dump prompt preview
        preview_path = CACHE_DIR / "_classify_prompt_preview.txt"
        preview_path.write_text(prompt, encoding="utf-8")
        print(f"[classify] prompt dumped to {preview_path}")
        return 0

    print(f"[classify] feeding {len(hot)} hot summaries to AI "
          f"(prompt={prompt_kb:.1f}KB)")

    # ---- 4. Call AI ----
    envelope, raw, rc, duration = call_claude(prompt)
    if rc != 0 or not raw.strip():
        print(f"[classify] AI call failed (rc={rc}, duration={duration:.1f}s)",
              file=sys.stderr)
        if raw:
            print(f"  output: {raw[:500]}", file=sys.stderr)
        log_cost(envelope, duration, ok=False)
        return 1

    # ---- 5. Parse + repair ----
    try:
        new_mm = parse_ai_output(raw)
    except json.JSONDecodeError as e:
        print(f"[classify] AI output is not parseable JSON: {e}", file=sys.stderr)
        print(f"  raw start: {raw[:500]}", file=sys.stderr)
        log_cost(envelope, duration, ok=False)
        return 1

    new_mm["generated_at"] = now_utc_iso()
    hot_sids = [s for s, _, _, _ in hot]
    repaired = repair_short_session_ids(new_mm, hot_sids)
    if repaired:
        print(f"[classify] repaired {repaired} truncated session_ids")
    rule_repairs = enforce_cold_and_terminal_monotone(new_mm, prior, hot_sids)
    if rule_repairs:
        print(f"[classify] enforced cold/terminal-monotone rules: {rule_repairs} repairs")

    # DD-011: rebuild hot initiatives' tasks[] from PRIOR + hot summary
    # frontmatter + AI output. Single store, tri-state, no archive.
    task_inits = aggregate_tasks(new_mm, prior, hot)
    if task_inits:
        print(f"[classify] tasks: rebuilt for {task_inits} hot initiative(s)")

    # ---- 6. Write + diff + log ----
    atomic_write_json(output_path, new_mm)
    ws_n = len(new_mm.get("workspaces") or [])
    init_n = sum(len(w.get("initiatives") or []) for w in new_mm.get("workspaces") or [])
    print(f"[classify] wrote {output_path}: {ws_n} workspaces, {init_n} initiatives")
    emit_diff(prior, new_mm)
    log_cost(envelope, duration, ok=True)

    # ---- 7. Regen HTML (only when writing to canonical mindmap.json) ----
    if output_path == MINDMAP_FILE:
        regen_html()

    return 0


if __name__ == "__main__":
    sys.exit(main())

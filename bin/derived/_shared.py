"""
Shared helpers for DD-006 derived features.

The four derived features (weekly report, next-steps, tips, wellness)
all consume the same upstream data (cache/dashboard.json + summaries +
cost_log) and produce different artifacts under cache/derived/. This
module centralizes:

  - file paths and cache directory bootstrap
  - date / week-range computations
  - signal extraction: WeeklySignal aggregates what got touched, shipped,
    archived, and produced within a calendar week
  - last-run gating (skip if too recent)
  - the Haiku call (mirrors classify.py / summarize.py invocation:
    --no-session-persistence + --max-budget-usd)
  - cost-log append

Per DD-006 §3.3 — every AI call here is logged with `layer:
derived.<feature>` so DD-004's budget cap can include or exclude them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
ARCHIVE_DIR = CACHE_DIR / "archive"
DASHBOARD_FILE = CACHE_DIR / "dashboard.json"
COST_LOG = CACHE_DIR / "cost_log.jsonl"
DERIVED_DIR = CACHE_DIR / "derived"
PROMPTS_DIR = REPO_ROOT / "prompts"

# claude -p invocation defaults — same as summarize.py / classify.py.
CLAUDE_TIMEOUT_SECS = int(os.environ.get("CLAUDE_WORKTREE_TIMEOUT", "600"))
CLAUDE_MODEL = os.environ.get(
    "CLAUDE_WORKTREE_MODEL", "claude-haiku-4-5-20251001"
)


# ---------- file ops ------------------------------------------------------

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def atomic_write_json(path: Path, data) -> None:
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- locale --------------------------------------------------------

_CONFIG = CACHE_DIR / "config.json"

def get_lang() -> str:
    if _CONFIG.exists():
        try:
            d = json.loads(_CONFIG.read_text())
            v = d.get("lang")
            if v in ("zh-CN", "en"):
                return v
        except (json.JSONDecodeError, OSError):
            pass
    return "zh-CN"


# ---------- date / week math ---------------------------------------------

def monday_of_week(d: date) -> date:
    """Return Monday of d's ISO week."""
    return d - timedelta(days=d.weekday())


@dataclass(frozen=True)
class WeekRange:
    """Local calendar week [Mon 00:00, next Mon 00:00) — half-open."""
    monday: date            # local date of Monday
    label: str              # ISO label e.g. "2026-W20"

    @classmethod
    def for_date(cls, d: date | None = None) -> "WeekRange":
        d = d or date.today()
        m = monday_of_week(d)
        iso = m.isocalendar()  # (year, week, weekday)
        return cls(monday=m, label=f"{iso[0]}-W{iso[1]:02d}")

    @classmethod
    def previous(cls, n: int = 1) -> "WeekRange":
        """The week starting n Mondays before this week's Monday."""
        return cls.for_date(date.today() - timedelta(days=7 * n))

    def contains(self, ts_iso: str | None) -> bool:
        if not ts_iso:
            return False
        try:
            dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        except ValueError:
            return False
        local = dt.astimezone().date()
        return self.monday <= local < self.monday + timedelta(days=7)

    def as_text(self, lang: str) -> str:
        end = self.monday + timedelta(days=6)
        if lang.startswith("zh"):
            return f"{self.label}（{self.monday:%Y-%m-%d} 至 {end:%Y-%m-%d}）"
        return f"{self.label} ({self.monday:%Y-%m-%d} to {end:%Y-%m-%d})"


# ---------- signal extraction --------------------------------------------

@dataclass
class WeeklySignal:
    """All evidence of "what got done this week", structured.

    weekly_report.py serializes this into JSON for Haiku and into a
    prebuilt section the user can verify (each summary item is
    traceable back to a session/initiative).
    """
    week: WeekRange
    hot_sessions: list[dict] = field(default_factory=list)
    # Each hot session: {sid, cwd, last_activity_at, user_turns,
    #                    summary_md_path, summary_excerpt}
    active_initiatives: list[dict] = field(default_factory=list)
    # Each: {id, name, status, last_activity_at, progress, ws_name}
    archived_this_week: list[dict] = field(default_factory=list)
    # Each: {id, name, archived_at, ws_name}
    tasks_done_this_week: list[dict] = field(default_factory=list)
    # Each: {init_id, init_name, task_id, task_title, terminal_at,
    #        evidence?}
    tasks_cancelled_this_week: list[dict] = field(default_factory=list)
    # Each: {init_id, init_name, task_id, task_title, terminal_at,
    #        evidence?}  (DD-011)
    new_artifacts_this_week: list[dict] = field(default_factory=list)
    # Each: {init_id, init_name, type, title, url, status,
    #        last_mentioned_at}

    def is_empty(self) -> bool:
        return not (self.hot_sessions or self.active_initiatives
                    or self.archived_this_week
                    or self.tasks_done_this_week
                    or self.tasks_cancelled_this_week
                    or self.new_artifacts_this_week)

    def to_dict(self) -> dict:
        return {
            "week_label": self.week.label,
            "week_start": self.week.monday.isoformat(),
            "hot_sessions": self.hot_sessions,
            "active_initiatives": self.active_initiatives,
            "archived_this_week": self.archived_this_week,
            "tasks_done_this_week": self.tasks_done_this_week,
            "tasks_cancelled_this_week": self.tasks_cancelled_this_week,
            "new_artifacts_this_week": self.new_artifacts_this_week,
        }


_FRONTMATTER_END = re.compile(r"^(?:---|```)\s*$", re.MULTILINE)


def _read_summary(sid: str) -> dict | None:
    """Return {fm_dict, body, raw_fm, full_text} or None."""
    p = SUMMARIES_DIR / f"{sid}.md"
    if not p.exists():
        return None
    text = p.read_text()
    if not text.startswith("---"):
        return None
    m = _FRONTMATTER_END.search(text[3:])
    if not m:
        return None
    fm_text = text[3:3 + m.start()]
    body = text[3 + m.end():].lstrip("\n")
    fm: dict = {}
    for line in fm_text.splitlines():
        if line and not line[0].isspace() and ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            if v:
                fm[k.strip()] = v
    return {"fm": fm, "body": body, "raw_fm": fm_text, "full": text}


def compute_weekly_signal(week: WeekRange | None = None) -> WeeklySignal:
    """Walk cache/summaries, cache/dashboard.json, and cache/archive to
    assemble all evidence of work in `week`. Per DD-011, tasks live
    only in dashboard.json — no task_archive directory is consulted."""
    week = week or WeekRange.for_date()
    sig = WeeklySignal(week=week)

    # ---- Hot sessions: summaries with last_activity_at in this week ----
    if SUMMARIES_DIR.is_dir():
        for p in SUMMARIES_DIR.glob("*.md"):
            s = _read_summary(p.stem)
            if not s:
                continue
            fm = s["fm"]
            la = fm.get("last_activity_at")
            if not week.contains(la):
                continue
            # Excerpt: pull the # 当前状态 / # Current state section.
            excerpt = ""
            body = s["body"]
            for header in ("# 当前状态", "# Current state", "# 目标", "# Goal"):
                idx = body.find(header)
                if idx >= 0:
                    rest = body[idx + len(header):].strip()
                    excerpt = rest.split("\n#", 1)[0].strip()
                    excerpt = excerpt[:280]
                    break
            sig.hot_sessions.append({
                "sid": p.stem,
                "cwd": fm.get("cwd"),
                "last_activity_at": la,
                "user_turns": fm.get("user_turns"),
                "status_guess": fm.get("status_guess"),
                "summary_path": str(p.relative_to(REPO_ROOT)),
                "summary_excerpt": excerpt,
            })

    # ---- Mindmap-derived signals (active initiatives, artifacts, tasks) ----
    if DASHBOARD_FILE.exists():
        try:
            mm = json.loads(DASHBOARD_FILE.read_text())
        except json.JSONDecodeError:
            mm = {}
        hot_sids = {s["sid"] for s in sig.hot_sessions}
        for ws in (mm.get("workspaces") or []):
            for init in (ws.get("initiatives") or []):
                # Active initiative = any of its sessions is hot, OR its
                # own last_activity_at falls in this week.
                la = init.get("last_activity_at") or ""
                sids = init.get("sessions") or []
                hits_this_week = (
                    week.contains(la)
                    or any(sid in hot_sids for sid in sids)
                )
                if hits_this_week:
                    sig.active_initiatives.append({
                        "id": init.get("id"),
                        "name": init.get("name"),
                        "status": init.get("status"),
                        "last_activity_at": la,
                        "progress": init.get("progress"),
                        "ws_name": ws.get("name"),
                    })
                # Artifacts mentioned this week
                for art in (init.get("artifacts") or []):
                    lm = art.get("last_mentioned_at")
                    if week.contains(lm):
                        sig.new_artifacts_this_week.append({
                            "init_id": init.get("id"),
                            "init_name": init.get("name"),
                            "type": art.get("type"),
                            "title": art.get("title"),
                            "url": art.get("url"),
                            "status": art.get("status"),
                            "last_mentioned_at": lm,
                        })
                # DD-011: tasks that became terminal this week, read straight
                # from the canonical store.
                iid = init.get("id")
                iname = init.get("name") or iid
                for t in (init.get("tasks") or []):
                    ts = t.get("status")
                    # Tolerate legacy `done: bool` records that may slip
                    # through during the DD-011 rollout window.
                    if ts not in ("done", "cancelled"):
                        if t.get("done") is True:
                            ts = "done"
                        else:
                            continue
                    term_at = t.get("terminal_at") or t.get("done_at")
                    if not week.contains(term_at):
                        continue
                    rec = {
                        "init_id": iid,
                        "init_name": iname,
                        "task_id": t.get("id"),
                        "task_title": t.get("title"),
                        "terminal_at": term_at,
                        "evidence": t.get("evidence") or t.get("done_evidence"),
                    }
                    if ts == "done":
                        sig.tasks_done_this_week.append(rec)
                    else:
                        sig.tasks_cancelled_this_week.append(rec)

    # ---- Archived this week (cache/archive) ----
    if ARCHIVE_DIR.is_dir():
        for f in ARCHIVE_DIR.glob("*/*.json"):
            try:
                rec = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            at = rec.get("archived_at")
            if not week.contains(at):
                continue
            init = rec.get("initiative") or {}
            sig.archived_this_week.append({
                "id": init.get("id"),
                "name": init.get("name"),
                "archived_at": at,
                "ws_name": rec.get("from_workspace") or f.parent.name,
            })

    # Stable ordering: most recent first within each group
    sig.hot_sessions.sort(key=lambda x: x.get("last_activity_at") or "", reverse=True)
    sig.active_initiatives.sort(key=lambda x: x.get("last_activity_at") or "", reverse=True)
    sig.archived_this_week.sort(key=lambda x: x.get("archived_at") or "", reverse=True)
    sig.tasks_done_this_week.sort(key=lambda x: x.get("terminal_at") or "", reverse=True)
    sig.tasks_cancelled_this_week.sort(key=lambda x: x.get("terminal_at") or "", reverse=True)
    sig.new_artifacts_this_week.sort(key=lambda x: x.get("last_mentioned_at") or "", reverse=True)

    return sig


# ---------- last-run gating ----------------------------------------------

def last_run_path(feature: str) -> Path:
    return DERIVED_DIR / feature / ".last_run.json"


def read_last_run(feature: str) -> dict:
    p = last_run_path(feature)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_last_run(feature: str, payload: dict) -> None:
    payload = {**payload, "at": now_utc_iso()}
    p = last_run_path(feature)
    ensure_dir(p.parent)
    atomic_write_json(p, payload)


def hours_since(iso_ts: str | None) -> float:
    if not iso_ts:
        return 1e9
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return max(0.0, delta)
    except ValueError:
        return 1e9


# ---------- AI call -------------------------------------------------------

def call_claude(
    prompt: str,
    *,
    max_budget_usd: float = 0.50,
    timeout_secs: int | None = None,
) -> tuple[dict | None, str, int, float]:
    """Same convention as summarize.py / classify.py — invoke claude -p
    with no-session-persistence so the call doesn't recurse via Stop
    hook. Returns (envelope, raw_text, rc, duration_s)."""
    t_start = time.time()
    timeout = timeout_secs or CLAUDE_TIMEOUT_SECS
    try:
        argv = [
            "perl", "-e", "alarm shift @ARGV; exec @ARGV",
            str(timeout),
            "claude", "--no-session-persistence", "-p",
            "--model", CLAUDE_MODEL,
            "--output-format", "json",
            "--max-budget-usd", f"{max_budget_usd:.2f}",
            "--disallowedTools", "Bash Edit Write Read Glob Grep",
        ]
        result = subprocess.run(
            argv, input=prompt, capture_output=True, text=True,
            timeout=timeout + 10,
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


def log_cost(layer: str, envelope: dict | None, duration_s: float,
             *, ok: bool, extra: dict | None = None) -> None:
    """Append a cost_log.jsonl entry. Mirrors bin/_cost_log.py shape.
    `layer` should be the feature name (e.g. derived.weekly_report)."""
    rec = {
        "at": now_utc_iso(),
        "layer": layer,
        "session_id": None,
        "model": (envelope or {}).get("model") if envelope else CLAUDE_MODEL,
        "input_tokens": ((envelope or {}).get("usage") or {}).get("input_tokens", 0),
        "cache_creation_tokens": ((envelope or {}).get("usage") or {}).get(
            "cache_creation_input_tokens", 0),
        "cache_read_tokens": ((envelope or {}).get("usage") or {}).get(
            "cache_read_input_tokens", 0),
        "output_tokens": ((envelope or {}).get("usage") or {}).get("output_tokens", 0),
        "cost_usd": (envelope or {}).get("total_cost_usd") or 0,
        "duration_s": round(duration_s, 2),
        "ok": ok,
    }
    if extra:
        rec.update(extra)
    ensure_dir(COST_LOG.parent)
    with COST_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

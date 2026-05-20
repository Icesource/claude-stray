#!/usr/bin/env python3
"""
Diagnose why a Claude Code session may not appear in the mindmap.

Walks the pipeline stage by stage for one session id, telling you which
stage it fell off at and what to do next.

Usage:
  mindmap --diagnose                 # auto-detect most recent session
  mindmap --diagnose <session_id>    # check a specific session
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
DASHBOARD_FILE = CACHE_DIR / "dashboard.json"
COST_LOG = CACHE_DIR / "cost_log.jsonl"
KILL_SWITCH = CACHE_DIR / ".refresh-disabled"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


GREEN = "32"; RED = "31"; YELLOW = "33"; DIM = "2"; BOLD = "1"; CYAN = "36"


def ok(msg: str) -> str:  return f"{c(GREEN, '✓')} {msg}"
def bad(msg: str) -> str: return f"{c(RED, '✗')} {msg}"
def warn(msg: str) -> str: return f"{c(YELLOW, '!')} {msg}"
def info(msg: str) -> str: return f"  {msg}"
def head(msg: str) -> str: return c(BOLD, msg)


def log_path() -> Path:
    if sys.platform == "darwin":
        return HOME / "Library" / "Logs" / "claude-code-worktree.log"
    state_home = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
    return state_home / "claude-code-worktree" / "refresh.log"


def find_most_recent_session() -> tuple[str, Path] | None:
    """Latest-mtime jsonl under ~/.claude/projects."""
    if not PROJECTS_DIR.exists():
        return None
    latest = None
    latest_mtime = 0
    for f in PROJECTS_DIR.glob("*/*.jsonl"):
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt > latest_mtime:
            latest_mtime = mt
            latest = f
    if latest is None:
        return None
    return latest.stem, latest


def find_session(session_id: str) -> Path | None:
    """Find the jsonl for a given session_id under ~/.claude/projects."""
    for f in PROJECTS_DIR.glob(f"*/{session_id}.jsonl"):
        return f
    return None


def humanize_age(mtime: float) -> str:
    s = int(datetime.now().timestamp() - mtime)
    if s < 0: return "just now"
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h {(s % 3600) // 60}m ago"
    return f"{s // 86400}d ago"


def grep_log_tail(n: int = 30) -> list[str]:
    path = log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except OSError:
        return []


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--diagnose",)]
    target_sid = args[0] if args else None

    print(head("Claude Code Worktree — Diagnostic"))
    print(c(DIM, "─" * 60))

    # ---- 0. Hook installation -------------------------------------------
    print("\n" + head("[0] Hook installation"))
    settings = HOME / ".claude" / "settings.json"
    if not settings.exists():
        print(bad(f"{settings} not found — hook never installed"))
        print(info(f"Run: bash {REPO_ROOT}/bin/install.sh"))
        return 1
    try:
        sdata = json.loads(settings.read_text())
    except json.JSONDecodeError:
        print(bad(f"{settings} is not valid JSON"))
        return 1
    hooks = sdata.get("hooks", {})
    stop_hooks = hooks.get("Stop") or []
    ss_hooks = hooks.get("SessionStart") or []
    bg_str = "refresh-bg.sh"
    stop_has = any(bg_str in h.get("command", "") for entry in stop_hooks for h in entry.get("hooks", []))
    ss_has   = any(bg_str in h.get("command", "") for entry in ss_hooks  for h in entry.get("hooks", []))
    print(ok("Stop hook installed") if stop_has else bad("Stop hook missing"))
    print(ok("SessionStart hook installed") if ss_has else bad("SessionStart hook missing"))
    if not (stop_has and ss_has):
        print(info(f"Re-install: bash {REPO_ROOT}/bin/install.sh"))

    # ---- 1. Target session ----------------------------------------------
    print("\n" + head("[1] Target session"))
    if target_sid:
        jsonl = find_session(target_sid)
        if not jsonl:
            print(bad(f"session_id {target_sid} not found under {PROJECTS_DIR}"))
            return 1
        print(ok(f"using user-provided id: {target_sid}"))
    else:
        latest = find_most_recent_session()
        if not latest:
            print(bad(f"no jsonl files under {PROJECTS_DIR}"))
            return 1
        target_sid, jsonl = latest
        print(ok(f"auto-detected most recent: {target_sid}"))
    mt = jsonl.stat().st_mtime
    print(info(f"jsonl: {jsonl}"))
    print(info(f"size: {jsonl.stat().st_size} bytes · modified {humanize_age(mt)}"))

    # ---- 2. extract.py output -------------------------------------------
    print("\n" + head("[2] Stage 1: extract.py (cache/sessions/)"))
    summary_file = SESSIONS_DIR / f"{target_sid}.json"
    if summary_file.exists():
        try:
            summary = json.loads(summary_file.read_text())
        except json.JSONDecodeError:
            summary = {}
        print(ok(f"summary present: {summary_file.name}"))
        msg_n = summary.get("message_count", 0)
        umsg_n = summary.get("user_message_count", 0)
        last_act = summary.get("last_activity_at") or "?"
        print(info(f"messages: {msg_n} total, {umsg_n} user · last activity {last_act}"))
        prompt = summary.get("first_user_prompt") or ""
        if prompt:
            print(info(f"first prompt: {prompt[:140]}"))
        recent = summary.get("recent_user_prompts") or []
        if recent:
            print(info(f"recent prompts: {len(recent)}"))
        is_auto = summary.get("is_automation")
        if is_auto:
            print(warn("flagged as automation (classifier run, will be excluded)"))
    else:
        print(bad(f"summary missing: {summary_file}"))
        print(info("Stage 1 hasn't seen this session yet — hook may not have run after the new session."))
        print(info(f"Try: bash {REPO_ROOT}/bin/extract.py"))

    # ---- 3. Layer 1 summary ---------------------------------------------
    print("\n" + head("[3] Stage 2: Layer 1 summarize (cache/summaries/)"))
    summary_md = SUMMARIES_DIR / f"{target_sid}.md"
    summary_md_ok = False
    if summary_md.exists():
        size = summary_md.stat().st_size
        age = humanize_age(summary_md.stat().st_mtime)
        print(ok(f"summary written: {summary_md.name} · {size}B · {age}"))
        summary_md_ok = True
    else:
        # Determine why: filtered, or not yet processed
        if summary_file.exists():
            sj = json.loads(summary_file.read_text())
            if sj.get("is_automation"):
                print(warn("skipped: session flagged is_automation (self-recursive AI call)"))
            elif (sj.get("user_message_count", 0) or 0) < 1:
                print(warn("skipped: user_message_count < 1 (no real prompts yet)"))
            else:
                print(bad("Layer 1 hasn't summarized this session yet"))
                print(info(f"Try: python3 {REPO_ROOT}/bin/summarize.py {target_sid}"))
        else:
            print(bad("waiting on Stage 1 (extract); Layer 1 will run after"))

    # ---- 4. dashboard.json ------------------------------------------------
    print("\n" + head("[4] Stage 3: AI classification (cache/dashboard.json)"))
    if DASHBOARD_FILE.exists():
        try:
            mm = json.loads(DASHBOARD_FILE.read_text())
        except json.JSONDecodeError:
            mm = {}
        gen = mm.get("generated_at", "?")
        print(info(f"dashboard.json generated_at: {gen} (file mtime {humanize_age(DASHBOARD_FILE.stat().st_mtime)})"))
        found_init = None
        found_ws = None
        for ws in (mm.get("workspaces") or []):
            for init in (ws.get("initiatives") or []):
                if target_sid in (init.get("sessions") or []):
                    found_init = init
                    found_ws = ws
                    break
            if found_init: break
        if found_init:
            print(ok(f"session is in initiative {c(CYAN, found_init['name'])}"))
            print(info(f"  workspace: {found_ws.get('name')}"))
            print(info(f"  initiative id: {found_init.get('id')}"))
            print(info(f"  status: {found_init.get('status')}"))
        else:
            print(bad("session_id is NOT in any initiative in dashboard.json"))
            print(info("Causes: AI hasn't run since this session existed, OR AI ignored it (rare)."))
    else:
        print(bad("dashboard.json missing — never ran a refresh"))

    # ---- 5. Kill switch + recent AI activity (from cost_log.jsonl) -------
    print("\n" + head("[5] Pipeline health"))
    if KILL_SWITCH.exists():
        print(bad(f"kill switch ENGAGED: {KILL_SWITCH}"))
        print(info(f"To re-enable: rm {KILL_SWITCH}"))
    else:
        print(ok("kill switch not set; pipeline allowed to run"))

    last_classify = last_summarize = None
    today_iso = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    today_n = today_cost = 0.0
    if COST_LOG.exists():
        try:
            for line in COST_LOG.read_text().splitlines():
                if not line.strip(): continue
                d = json.loads(line)
                at = d.get('at') or ''
                if at.startswith(today_iso):
                    today_n += 1
                    today_cost += d.get('cost_usd') or 0
                layer = d.get('layer')
                if layer == 'classify':
                    last_classify = at
                elif layer == 'summarize':
                    last_summarize = at
        except Exception as e:
            print(warn(f"cost_log read failed: {e}"))
        print(info(f"today: {today_n} calls / ${today_cost:.2f}"))
        if last_summarize:
            print(info(f"last summarize: {last_summarize}"))
        if last_classify:
            print(info(f"last classify:  {last_classify}"))
    else:
        print(warn(f"cost_log missing ({COST_LOG}) — pipeline has never recorded an AI call"))

    # ---- 6. Recent hook outcomes ----------------------------------------
    print("\n" + head("[6] Recent hook outcomes"))
    lp = log_path()
    print(info(f"log: {lp}"))
    tail = grep_log_tail(80)
    if not tail:
        print(warn("log empty or unreadable"))
    else:
        # Each invocation starts with a [hook] line.
        groups: list[list[str]] = []
        cur: list[str] = []
        for line in tail:
            if "[hook]" in line:
                if cur:
                    groups.append(cur)
                cur = [line]
            elif cur is not None:
                cur.append(line)
        if cur:
            groups.append(cur)
        groups = [g for g in groups if g and "[hook]" in g[0]]
        # Summarize the last 8 invocations
        for grp in groups[-8:]:
            hook_line = grp[0]
            text = "\n".join(grp)
            if "Layer 1: 0 session(s) dirty" in text and "Layer 2: nothing new, skip" in text:
                outcome = c(DIM, "noop (nothing dirty)")
            elif "wrote" in text and ".md" in text and "Layer 2" in text:
                outcome = c(GREEN, "OK summarized + classified")
            elif "wrote" in text and "initiatives" in text:
                outcome = c(GREEN, "OK ran classify")
            elif "AI call failed" in text or "claude -p failed" in text:
                outcome = c(RED, "FAIL")
            elif "busy → pending" in text:
                outcome = c(DIM, "skip locked")
            else:
                outcome = c(DIM, "?")
            ts = ""
            parts = hook_line.split()
            if len(parts) >= 2 and parts[0] == "[hook]":
                ts = parts[1]
            print(f"  · {ts:<28}  {outcome}")
            # If AI ran, show the DIFF lines
            for ln in grp:
                if any(s in ln for s in ("DIFF vs prior", "+ NEW initiative", "- removed initiative", "~ status change", "~ task progress", "usage:")):
                    print("      " + ln.strip())

    # ---- 7. Verdict + actions -------------------------------------------
    print("\n" + head("[7] Verdict"))
    if KILL_SWITCH.exists():
        print(bad("Pipeline kill switch is engaged — Stop hooks exit immediately."))
        print(info(f"→ Re-enable: rm {KILL_SWITCH}"))
    elif not (stop_has and ss_has):
        print(bad("Hooks not installed — pipeline won't fire on Claude Code events."))
        print(info(f"→ Re-install: bash {REPO_ROOT}/bin/install.sh"))
    elif not summary_file.exists():
        print(warn("Stage 1 (extract) hasn't recorded this session yet."))
        print(info(f"→ Manually run: python3 {REPO_ROOT}/bin/extract.py"))
        print(info(f"→ Then:        mindmap --refresh"))
    elif not summary_md_ok:
        print(warn("Stage 2 (Layer 1 summarize) hasn't summarized this session."))
        print(info("Causes: is_automation, user_message_count<1, or not yet processed."))
    elif not (DASHBOARD_FILE.exists() and any(target_sid in (i.get('sessions') or []) for ws in (json.loads(DASHBOARD_FILE.read_text()).get('workspaces') or []) for i in (ws.get('initiatives') or []))):
        print(warn("Session is summarized but isn't in dashboard.json yet."))
        print(info("Cause: Layer 2 (classify) hasn't run with this summary yet."))
        print(info(f"→ Force classify: mindmap --refresh"))
    else:
        print(ok("All stages green — this session is classified."))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

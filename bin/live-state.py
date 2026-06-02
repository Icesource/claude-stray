#!/usr/bin/env python3
"""
DD-015 Stage 1 — live session telemetry.

Maps a Claude Code hook event to a per-session live *status* and writes it
to cache/live/<session_id>.json. The dashboard reads these (via the
server's /api/live snapshot + /api/events SSE stream) to show, per
session, whether the AI is running / idle / waiting on you — and how long
it has been in that state.

State machine (verified against the hooks docs, 2026-06-01):
  UserPromptSubmit                       -> running   (you sent a prompt, AI working)
  Stop                                   -> idle      (turn ended)
  Notification permission_prompt/elicit  -> needs_you (AI blocked on your approval/input)
  Notification idle_prompt               -> (no change; never downgrades done_unread)
  SessionStart (startup/resume)          -> idle      (opened, nothing running yet)
  SessionEnd                             -> ended
  (other notifications)                  -> ignored   (don't clobber current status)

There is no "thinking" hook, so `running` simply persists from
UserPromptSubmit until the next Stop. `status_since` lets the UI render
"running 5m" / "idle 2h".

Identity note (DD-016): session_id is the stable atom. This file is keyed
by it directly; initiative/stream rollup happens downstream by mapping
session_id -> initiative, never the reverse.

Non-fatal by design: any error is swallowed so it never blocks the hook
chain. Pure disk write — NO AI pipeline is triggered here.
"""

from __future__ import annotations

import json
import os
import select
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = REPO_ROOT / "cache" / "live"

NEEDS_YOU_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_stdin_with_timeout(timeout_sec: float = 0.5) -> str:
    if sys.stdin.isatty():
        return ""
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not ready:
            return ""
        return sys.stdin.read()
    except Exception:
        return ""


def status_for(payload: dict) -> tuple[str | None, str | None]:
    """Return (status, reason). status None => leave current state untouched."""
    event = payload.get("hook_event_name") or payload.get("source") or ""
    if event == "UserPromptSubmit":
        return "running", None
    if event == "Stop":
        # AI finished a turn but the human hasn't necessarily returned to it.
        # "done_unread" = finished, awaiting your attention. Clears on the next
        # UserPromptSubmit (you went back) or decays to idle after a while.
        return "done_unread", None
    if event == "SessionStart":
        return "idle", None
    if event == "SessionEnd":
        return "ended", None
    if event == "Notification":
        nt = payload.get("notification_type") or ""
        if nt in NEEDS_YOU_NOTIFICATIONS:
            return "needs_you", "等待你授权 / 输入"
        # idle_prompt fires right after EVERY Stop ("Claude is idle, waiting
        # for you"). Mapping it to idle used to clobber the done_unread that
        # Stop had just set, so a finished turn instantly looked "idle" and the
        # card never showed 在跑/待查看. Leave the status untouched instead —
        # done_unread persists until you re-engage (UserPromptSubmit) or decay.
        return None, None  # idle_prompt / auth_success etc. — never downgrade
    return None, None


def main() -> int:
    payload_str = read_stdin_with_timeout()
    payload: dict = {}
    if payload_str:
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = {}

    session_id = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not session_id:
        return 0

    status, reason = status_for(payload)
    if status is None:
        # Event we don't act on (e.g. an auth_success notification) — leave
        # the existing record alone rather than clobbering it.
        return 0

    now = _now()
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    rec_path = LIVE_DIR / f"{session_id}.json"

    prev: dict = {}
    try:
        prev = json.loads(rec_path.read_text())
        if not isinstance(prev, dict):
            prev = {}
    except (OSError, json.JSONDecodeError):
        prev = {}

    record = {
        "session_id": session_id,
        "cwd": payload.get("cwd") or prev.get("cwd") or os.environ.get("PWD") or "",
        "status": status,
        "event": payload.get("hook_event_name") or payload.get("source") or "",
        "updated_at": now,
        # status_since only advances when the status actually changes, so the
        # UI can show a stable "running for 5m" / "idle for 2h" timer.
        "status_since": now if prev.get("status") != status else (prev.get("status_since") or now),
        "started_at": prev.get("started_at") or now,
    }
    if reason:
        record["reason"] = reason

    # Atomic write so a concurrent reader never sees a half-written file.
    try:
        fd, tmp = tempfile.mkstemp(dir=str(LIVE_DIR), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(record, ensure_ascii=False, indent=2))
        os.replace(tmp, rec_path)
    except Exception:
        # Fall back to a plain write; still must not raise.
        try:
            rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Hooks must never fail. Swallow.
        raise SystemExit(0)

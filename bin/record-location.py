#!/usr/bin/env python3
"""
Record the current Claude Code session's location (cwd) into
cache/session_locations.json.

Called from refresh-bg.sh which is wired up as a Claude Code hook
(SessionStart, Stop). Reads the hook JSON payload from stdin to get the
authoritative session_id.

The cwd is the durable value: serve.py uses it as the resume-cwd fallback
(`claude --resume` must run in the session's project dir) and the cockpit
uses it for spawn/new-session directory suggestions. (The zellij pane
fields this hook used to record were retired 2026-06-11 with the
/focus + /newpane endpoints — the cockpit is fully web + webterminal.)

Non-fatal: any error here is silently swallowed so it never blocks the
hook chain.
"""

from __future__ import annotations

import json
import os
import select
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from _repo_root import repo_root
    REPO_ROOT = repo_root()
except Exception:
    # Hooks must never fail; fall back to the naive (pre-fix) derivation.
    REPO_ROOT = Path(__file__).resolve().parent.parent
LOC_FILE = REPO_ROOT / "cache" / "session_locations.json"


def read_stdin_with_timeout(timeout_sec: float = 0.5) -> str:
    """Read all stdin within timeout. Hooks deliver a quick JSON blob."""
    if sys.stdin.isatty():
        return ""
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not ready:
            return ""
        return sys.stdin.read()
    except Exception:
        return ""


def main() -> int:
    payload_str = read_stdin_with_timeout()
    payload = {}
    if payload_str:
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = {}

    session_id = (
        payload.get("session_id")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )
    if not session_id:
        # Without a session_id we can't key the record. Bail silently.
        return 0

    cwd = payload.get("cwd") or os.environ.get("PWD") or os.getcwd()

    record = {
        "session_id": session_id,
        "cwd": cwd,
        "term_program": os.environ.get("TERM_PROGRAM") or None,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(LOC_FILE.read_text())
        if not isinstance(existing, dict):
            existing = {}
    except (OSError, json.JSONDecodeError):
        existing = {}

    by_id = existing.get("by_session_id") or {}
    # Preserve started_at on first record; only updated_at moves forward.
    if session_id in by_id and "started_at" in by_id[session_id]:
        record["started_at"] = by_id[session_id]["started_at"]
    else:
        record["started_at"] = record["updated_at"]
    by_id[session_id] = record

    out = {
        "version": 1,
        "by_session_id": by_id,
    }
    LOC_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Hooks must never fail. Swallow.
        raise SystemExit(0)

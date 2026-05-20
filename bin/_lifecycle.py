#!/usr/bin/env python3
"""
Pipeline lifecycle helper — pause / resume / status.

Wraps the kill-switch file `cache/.refresh-disabled` with a sidecar
`cache/.refresh-disabled.reason` (JSON: paused_at, reason, by) so the
UI and CLI can display *why* the pipeline was paused.

`bin/refresh-bg.sh` already exits early when the kill-switch file
exists; this module is purely about adding context + a programmatic
way to flip the switch (used by `stray --pause/--resume` and
`POST /api/lifecycle`).

Per DD-005 §3 — Option B (explicit pause/resume).

CLI:
  python3 bin/_lifecycle.py status               # print JSON status
  python3 bin/_lifecycle.py pause [reason text]  # engage kill switch
  python3 bin/_lifecycle.py resume               # release kill switch

Exit codes:
  0  success
  1  unexpected error
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
SWITCH_FILE = CACHE_DIR / ".refresh-disabled"
REASON_FILE = CACHE_DIR / ".refresh-disabled.reason"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status() -> dict:
    """Return the current lifecycle state as a dict."""
    paused = SWITCH_FILE.exists()
    detail: dict = {"paused": paused}
    if paused and REASON_FILE.exists():
        try:
            detail.update(json.loads(REASON_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return detail


def pause(reason: str | None = None, by: str = "cli") -> dict:
    """Engage the kill switch with an optional reason. Idempotent — calling
    pause on an already-paused pipeline refreshes the reason/timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SWITCH_FILE.touch()
    payload = {
        "paused": True,
        "paused_at": _now_utc_iso(),
        "reason": (reason or "manual pause").strip(),
        "by": by,
    }
    REASON_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def resume() -> dict:
    """Release the kill switch. Idempotent."""
    for p in (SWITCH_FILE, REASON_FILE):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    return {"paused": False, "resumed_at": _now_utc_iso()}


def _main(argv: list[str]) -> int:
    if not argv:
        argv = ["status"]
    cmd = argv[0]
    if cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
        return 0
    if cmd == "pause":
        reason = " ".join(argv[1:]) or None
        res = pause(reason=reason)
        print(f"[lifecycle] pipeline PAUSED at {res['paused_at']}")
        print(f"[lifecycle] reason: {res['reason']}")
        print(f"[lifecycle] kill switch: {SWITCH_FILE}")
        print(f"[lifecycle] resume with: stray --resume")
        return 0
    if cmd == "resume":
        was_paused = SWITCH_FILE.exists()
        resume()
        if was_paused:
            print(f"[lifecycle] pipeline RESUMED at {_now_utc_iso()}")
        else:
            print("[lifecycle] pipeline was not paused; nothing to do")
        return 0
    print(f"[lifecycle] unknown command: {cmd}", file=sys.stderr)
    print("[lifecycle] usage: pause [reason] | resume | status", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

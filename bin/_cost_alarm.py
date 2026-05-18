#!/usr/bin/env python3
"""
Cost / rate-alarm helper — minimal version for serve.py console output.

Reads cache/cost_log.jsonl and computes:
  - today_calls, today_cost          (sum of cost_usd where at startswith today_iso)
  - window_calls, window_cost        (last RATE_WINDOW_S, default 300s = 5min)

Classifies overall state into a level:
  ok    — within all warn thresholds
  warn  — over a warn threshold
  halt  — over a halt threshold (reported but NOT auto-engaged here;
          full circuit-breaker engagement is DD-004's job)

The full DD-004 (daily cap auto-engage + dashboard banner) builds on
top of this — its `/api/health` endpoint will reuse `snapshot()` and
its banner will read the same fields.

CLI:
  python3 bin/_cost_alarm.py             # print JSON snapshot
  python3 bin/_cost_alarm.py --watch     # tail-like, print on change

Thresholds (env-overridable):
  CLAUDE_WORKTREE_DAILY_WARN_USD   default 2.00
  CLAUDE_WORKTREE_DAILY_HALT_USD   default 10.00
  CLAUDE_WORKTREE_RATE_WINDOW_S    default 300
  CLAUDE_WORKTREE_RATE_WARN        default 15  (calls in window)
  CLAUDE_WORKTREE_RATE_HALT        default 40  (calls in window)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_LOG = REPO_ROOT / "cache" / "cost_log.jsonl"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _thresholds() -> dict:
    return {
        "daily_warn_usd": _env_float("CLAUDE_WORKTREE_DAILY_WARN_USD", 2.00),
        "daily_halt_usd": _env_float("CLAUDE_WORKTREE_DAILY_HALT_USD", 10.00),
        "rate_window_s": _env_int("CLAUDE_WORKTREE_RATE_WINDOW_S", 300),
        "rate_warn": _env_int("CLAUDE_WORKTREE_RATE_WARN", 15),
        "rate_halt": _env_int("CLAUDE_WORKTREE_RATE_HALT", 40),
    }


def snapshot() -> dict:
    """Compute the current alarm state. Returns:
        {
          level: 'ok'|'warn'|'halt',
          reasons: [str, ...],   # human-readable why
          today: {calls, cost, by_layer: {layer: (n, cost)}},
          window: {seconds, calls, cost},
          thresholds: {...},
        }
    """
    th = _thresholds()
    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    window_cutoff = now - timedelta(seconds=th["rate_window_s"])

    today_calls = 0
    today_cost = 0.0
    by_layer: dict[str, list] = {}     # layer → [calls, cost]
    window_calls = 0
    window_cost = 0.0

    if COST_LOG.exists():
        with COST_LOG.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                at = d.get("at") or ""
                if not at.startswith(today_iso):
                    continue
                cost = d.get("cost_usd") or 0.0
                layer = d.get("layer") or "unknown"
                today_calls += 1
                today_cost += cost
                bl = by_layer.setdefault(layer, [0, 0.0])
                bl[0] += 1
                bl[1] += cost
                # window check
                try:
                    at_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                    if at_dt >= window_cutoff:
                        window_calls += 1
                        window_cost += cost
                except ValueError:
                    pass

    reasons: list[str] = []
    level = "ok"
    if today_cost >= th["daily_halt_usd"]:
        level = "halt"
        reasons.append(
            f"daily cost ${today_cost:.2f} ≥ halt ${th['daily_halt_usd']:.2f}"
        )
    elif today_cost >= th["daily_warn_usd"]:
        level = "warn"
        reasons.append(
            f"daily cost ${today_cost:.2f} ≥ warn ${th['daily_warn_usd']:.2f}"
        )
    if window_calls >= th["rate_halt"]:
        level = "halt"
        reasons.append(
            f"{window_calls} calls in last {th['rate_window_s']}s ≥ halt {th['rate_halt']}"
        )
    elif window_calls >= th["rate_warn"]:
        if level != "halt":
            level = "warn"
        reasons.append(
            f"{window_calls} calls in last {th['rate_window_s']}s ≥ warn {th['rate_warn']}"
        )

    return {
        "level": level,
        "reasons": reasons,
        "today": {
            "calls": today_calls,
            "cost": round(today_cost, 4),
            "by_layer": {k: {"calls": v[0], "cost": round(v[1], 4)}
                         for k, v in by_layer.items()},
        },
        "window": {
            "seconds": th["rate_window_s"],
            "calls": window_calls,
            "cost": round(window_cost, 4),
        },
        "thresholds": th,
        "computed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------- console formatting --------------------------------------------

# ANSI when stderr is a TTY; plain otherwise (so logs pipe cleanly).
def _ansi(code: str, text: str, *, force_color: bool = False) -> str:
    if force_color or sys.stderr.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


_LEVEL_PREFIX = {
    "ok": ("ok",   "32"),    # green
    "warn": ("WARN", "33"),  # yellow
    "halt": ("HALT", "31;1"),  # bold red
}


def format_console_line(snap: dict, *, force_color: bool = False) -> str:
    """One-line formatted state for stderr — only emit when level ≠ ok
    (caller decides; this just formats)."""
    tag_text, color = _LEVEL_PREFIX.get(snap["level"], ("?", "0"))
    tag = _ansi(color, f"[{tag_text}]", force_color=force_color)
    today = snap["today"]
    win = snap["window"]
    pieces = [
        f"today: {today['calls']} calls / ${today['cost']:.2f}",
        f"last {win['seconds']}s: {win['calls']} calls / ${win['cost']:.4f}",
    ]
    if snap["reasons"]:
        pieces.append(" · ".join(snap["reasons"]))
    return f"[cost-alarm] {tag} " + " · ".join(pieces)


# ---------- CLI ------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if "--watch" in argv:
        import time
        last_print = ""
        while True:
            snap = snapshot()
            line = format_console_line(snap, force_color=True)
            if line != last_print:
                print(line, file=sys.stderr)
                last_print = line
            time.sleep(5)
    snap = snapshot()
    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

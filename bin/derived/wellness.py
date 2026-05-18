#!/usr/bin/env python3
"""
DD-006 derived feature: wellness nudge.

Signal-gated — runs AI only when one of three concrete patterns
appears in the user's recent sessions:

  late_nights:        ≥ 3 sessions ending after 22:00 in last 7 days
  consecutive_days:   ≥ 7 distinct days of session activity in a row
  long_hours:         avg daily span ≥ 10h across last 7 days

If none fire, the script exits with no AI call (no spend, no noise).
The wellness message itself comes from Haiku — warm, brief, cites the
specific pattern, never preachy.

Output: cache/derived/wellness/latest.json
  {generated_at, pattern, message, history}

CLI:
  python3 bin/derived/wellness.py [--dry-run] [--force]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from derived._shared import (  # noqa: E402
    DERIVED_DIR, SESSIONS_DIR, get_lang, call_claude, log_cost,
    atomic_write_json, ensure_dir, read_last_run, write_last_run,
    hours_since, now_utc_iso,
)

OUT_DIR = DERIVED_DIR / "wellness"
OUT_FILE = OUT_DIR / "latest.json"
FEATURE = "derived.wellness"
HISTORY_LIMIT = 10
MIN_HOURS_BETWEEN_RUNS = 18      # roughly daily, won't double-fire same day
WINDOW_DAYS = 7

# Thresholds — env-overridable (DD-006 §4.4 calls these "intentionally high")
LATE_NIGHT_HOUR = 22             # 22:00 local
LATE_NIGHT_MIN_COUNT = 3
CONSECUTIVE_DAYS_MIN = 7
LONG_HOURS_MIN = 10              # avg daily span


def _read_recent_sessions(window_days: int = WINDOW_DAYS) -> list[dict]:
    """Sessions with last_activity in the last N days, with started_at +
    last_activity_at parsed."""
    if not SESSIONS_DIR.is_dir():
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    out = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("is_automation"):
            continue
        if (d.get("user_message_count", 0) or 0) < 1:
            continue
        la = d.get("last_activity_at")
        if not la:
            continue
        try:
            la_dt = datetime.fromisoformat(la.replace("Z", "+00:00"))
        except ValueError:
            continue
        if la_dt < cutoff:
            continue
        st = d.get("started_at")
        try:
            st_dt = datetime.fromisoformat((st or la).replace("Z", "+00:00"))
        except ValueError:
            st_dt = la_dt
        out.append({
            "sid": p.stem,
            "started_at": st_dt,
            "last_activity_at": la_dt,
        })
    return out


def _detect_signals() -> list[dict]:
    """Return a list of pattern dicts that fired."""
    sessions = _read_recent_sessions()
    if not sessions:
        return []

    fired: list[dict] = []

    # late_nights: sessions whose last_activity local hour ≥ 22
    late_n = sum(
        1 for s in sessions
        if s["last_activity_at"].astimezone().hour >= LATE_NIGHT_HOUR
    )
    if late_n >= LATE_NIGHT_MIN_COUNT:
        fired.append({
            "pattern": "late_nights",
            "summary": f"{late_n} sessions ending after "
                       f"{LATE_NIGHT_HOUR}:00 in the last {WINDOW_DAYS} days",
            "count": late_n,
        })

    # consecutive_days: 7+ distinct days in a row of activity
    activity_days = sorted({
        s["last_activity_at"].astimezone().date() for s in sessions
    }, reverse=True)
    streak = 1
    longest = 1
    for i in range(1, len(activity_days)):
        delta = (activity_days[i - 1] - activity_days[i]).days
        if delta == 1:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 1
    if longest >= CONSECUTIVE_DAYS_MIN:
        fired.append({
            "pattern": "consecutive_days",
            "summary": f"{longest} consecutive days of session activity",
            "streak": longest,
        })

    # long_hours: for each calendar day with session activity, measure
    # the daily working span as (last_activity_on_that_day -
    # first_activity_on_that_day). Use last_activity_at as the per-day
    # "end" marker and the SAME field across sessions as the "first"
    # marker — session.started_at often pre-dates the day (multi-day
    # sessions), so we'd over-count by treating it as today's start.
    # The session.last_activity_at IS today's end (we grouped by that),
    # and any other sessions' last_activity also on this day give us
    # the within-day span. Cap each session contribution at 24h.
    by_day: dict = defaultdict(list)
    for s in sessions:
        d_local = s["last_activity_at"].astimezone().date()
        by_day[d_local].append(s["last_activity_at"].astimezone())
    spans_h = []
    for d_local, ends_today in by_day.items():
        # Span = max(end) - min(end) for sessions that ended this day.
        span = (max(ends_today) - min(ends_today)).total_seconds() / 3600.0
        # If only one session ended on this day, no informative span;
        # treat as 0h contribution.
        spans_h.append(min(24.0, span))
    if spans_h:
        avg = sum(spans_h) / len(spans_h)
        if avg >= LONG_HOURS_MIN:
            fired.append({
                "pattern": "long_hours",
                "summary": f"average daily span {avg:.1f}h over the last "
                           f"{len(spans_h)} active days",
                "avg_hours": round(avg, 1),
            })

    return fired


def _build_prompt(patterns: list[dict], lang: str) -> str:
    lang_block = (
        "用简体中文,1-2 句,温和不说教,要具体引用数字(例如"
        "'你这周已经有 5 次晚于 22 点结束的会话');允许小幽默。"
        if lang.startswith("zh") else
        "Reply in English, 1–2 sentences, warm but not preachy. "
        "Cite specific numbers ('5 sessions ended past 22:00'). "
        "A touch of humor is OK."
    )
    return f"""The user works heavily and the following patterns have
appeared in their recent activity. Write ONE short, warm message
reminding them that sustainable pace matters. The message must
reference the specific number(s) from the patterns — never generic
"take care of yourself" advice.

Return STRICT JSON:
  {{"pattern": "<chosen pattern id>", "message": "<your text>"}}

If multiple patterns fired, pick the one with the strongest signal.

{lang_block}

Patterns:
{json.dumps(patterns, indent=2, ensure_ascii=False)}
"""


def generate(*, dry_run: bool = False, force: bool = False) -> int:
    patterns = _detect_signals()
    if not patterns:
        print("[wellness] no signals fired — skipping (no AI call)",
              file=sys.stderr)
        return 2

    last = read_last_run(FEATURE)
    if (not force and last.get("at")
            and hours_since(last["at"]) < MIN_HOURS_BETWEEN_RUNS):
        print(f"[wellness] last run {hours_since(last['at']):.1f}h ago — "
              f"debounced", file=sys.stderr)
        return 2

    print(f"[wellness] signals: {[p['pattern'] for p in patterns]}",
          file=sys.stderr)
    if dry_run:
        print(json.dumps(patterns, indent=2, ensure_ascii=False))
        return 0

    prompt = _build_prompt(patterns, get_lang())
    envelope, raw, rc, duration = call_claude(prompt, max_budget_usd=0.10)
    if rc != 0 or not raw.strip():
        print(f"[wellness] AI call failed (rc={rc}): {raw[:200]}",
              file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    body = raw.strip()
    if body.startswith("```"):
        body = "\n".join(body.splitlines()[1:-1])
    i, j = body.find("{"), body.rfind("}")
    if i != -1 and j != -1:
        body = body[i:j + 1]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    msg = (parsed.get("message") or "").strip()
    if not msg:
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    existing = {}
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            pass
    history = list(existing.get("history") or [])
    if existing.get("message"):
        history.append({
            "message": existing["message"],
            "pattern": existing.get("pattern"),
            "generated_at": existing.get("generated_at"),
        })
    history = history[-(HISTORY_LIMIT - 1):]

    payload = {
        "generated_at": now_utc_iso(),
        "pattern": parsed.get("pattern") or patterns[0]["pattern"],
        "message": msg,
        "history": history,
    }
    ensure_dir(OUT_DIR)
    atomic_write_json(OUT_FILE, payload)
    log_cost(FEATURE, envelope, duration, ok=True)
    write_last_run(FEATURE, {"pattern": payload["pattern"]})

    cost = (envelope or {}).get("total_cost_usd", 0)
    print(f"[wellness] wrote {OUT_FILE.name}  cost=${cost:.4f}  "
          f"duration={duration:.1f}s", file=sys.stderr)
    print(f"[wellness] msg: {msg}", file=sys.stderr)
    return 0


def _main(argv: list[str]) -> int:
    return generate(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

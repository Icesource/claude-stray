#!/usr/bin/env python3
"""
Read cache/cost_log.jsonl and present spend/usage summaries.

Usage:
  mindmap --cost              # default: today + last 7d table
  mindmap --cost today
  mindmap --cost week         # last 7 days breakdown
  mindmap --cost month        # last 30 days
  mindmap --cost all          # lifetime
  mindmap --cost log          # tail of raw entries
  mindmap --cost json         # JSON output for scripting

Dates are shown in local time; the log stores UTC.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_LOG = REPO_ROOT / "cache" / "cost_log.jsonl"
CONFIG_FILE = REPO_ROOT / "cache" / "config.json"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


BOLD, DIM, CYAN, GREEN, YELLOW, RED = "1", "2", "36", "32", "33", "31"


def load_log() -> list[dict]:
    if not COST_LOG.exists():
        return []
    out = []
    with open(COST_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def to_local_date(iso_z: str) -> datetime:
    try:
        t = datetime.fromisoformat(iso_z.replace("Z", "+00:00"))
        return t.astimezone()
    except (ValueError, AttributeError):
        return datetime.now()


def group_by_day(records: list[dict]) -> dict:
    """Returns {date_str: [records], ...} keyed by local YYYY-MM-DD."""
    out: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        date_str = to_local_date(r["at"]).strftime("%Y-%m-%d")
        out[date_str].append(r)
    return out


def aggregate(records: list[dict]) -> dict:
    """Aggregate stats over a record list."""
    by_layer: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "cost": 0.0, "duration": 0.0, "ok": 0, "fail": 0,
        "input": 0, "cache_create": 0, "cache_read": 0, "output": 0,
    })
    total = {"count": 0, "cost": 0.0, "duration": 0.0, "ok": 0, "fail": 0,
             "input": 0, "cache_create": 0, "cache_read": 0, "output": 0}
    for r in records:
        layer = r.get("layer") or "unknown"
        b = by_layer[layer]
        for bucket in (b, total):
            bucket["count"] += 1
            bucket["cost"] += r.get("cost_usd", 0)
            bucket["duration"] += r.get("duration_s", 0)
            bucket["ok"] += 1 if r.get("ok", True) else 0
            bucket["fail"] += 0 if r.get("ok", True) else 1
            bucket["input"] += r.get("input_tokens", 0)
            bucket["cache_create"] += r.get("cache_creation_tokens", 0)
            bucket["cache_read"] += r.get("cache_read_tokens", 0)
            bucket["output"] += r.get("output_tokens", 0)
    return {"total": total, "by_layer": dict(by_layer)}


def fmt_n(n: int | float) -> str:
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def print_period(title: str, records: list[dict]) -> None:
    print(c(BOLD, title))
    if not records:
        print(c(DIM, "  (no calls)"))
        return
    agg = aggregate(records)
    t = agg["total"]
    fail_tag = c(RED, f" ({t['fail']} failed)") if t["fail"] else ""
    print(f"  {fmt_n(t['count'])} calls   {c(GREEN, '$' + fmt_n(t['cost']))}"
          f"   avg ${t['cost'] / max(t['count'], 1):.3f}{fail_tag}")
    if len(agg["by_layer"]) > 1:
        for layer in sorted(agg["by_layer"]):
            b = agg["by_layer"][layer]
            avg = b["cost"] / max(b["count"], 1)
            print(f"    {c(CYAN, layer):<22}  {b['count']:>3} × ~${avg:.3f}"
                  f" = ${b['cost']:.2f}   avg {b['duration']/max(b['count'],1):.1f}s")
    elif agg["by_layer"]:
        # single layer — show duration only
        layer = next(iter(agg["by_layer"]))
        b = agg["by_layer"][layer]
        print(f"    {c(CYAN, layer)}   avg {b['duration']/max(b['count'],1):.1f}s")


def print_bar(value: float, max_value: float, width: int = 20) -> str:
    if max_value <= 0:
        return ""
    filled = int(round(value / max_value * width))
    return "█" * filled


def print_weekday_table(records: list[dict], n_days: int) -> None:
    by_day = group_by_day(records)
    today = datetime.now().date()
    rows: list[tuple[str, int, float]] = []
    for i in range(n_days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        weekday = d.strftime("%a")
        recs = by_day.get(ds, [])
        agg = aggregate(recs)["total"]
        rows.append((f"{weekday} {ds}", agg["count"], agg["cost"]))

    max_cost = max((r[2] for r in rows), default=0.0)
    total_cost = sum(r[2] for r in rows)
    total_count = sum(r[1] for r in rows)

    print(c(BOLD, f"Last {n_days} days"))
    for label, count, cost in rows:
        bar = print_bar(cost, max_cost)
        cost_str = f"${cost:.2f}" if cost > 0 else c(DIM, "$0.00")
        print(f"  {label:<18}  {count:>3}  {cost_str:>8}  {c(DIM, bar)}")
    print(c(DIM, f"  {'─' * 18}"))
    print(f"  {'total':<18}  {total_count:>3}  ${total_cost:.2f}")


def filter_today(records: list[dict]) -> list[dict]:
    today = datetime.now().date()
    return [r for r in records if to_local_date(r["at"]).date() == today]


def filter_days(records: list[dict], n: int) -> list[dict]:
    cutoff = datetime.now().date() - timedelta(days=n - 1)
    return [r for r in records if to_local_date(r["at"]).date() >= cutoff]


def print_tokens_summary(records: list[dict]) -> None:
    if not records:
        return
    agg = aggregate(records)["total"]
    if agg["count"] == 0:
        return
    print(c(BOLD, "Tokens this period"))
    print(f"  input:           {fmt_n(agg['input']):>14}")
    print(f"  cache create:    {fmt_n(agg['cache_create']):>14}")
    print(f"  cache read:      {fmt_n(agg['cache_read']):>14}")
    print(f"  output:          {fmt_n(agg['output']):>14}")
    cache_ratio = agg["cache_read"] / max(agg["input"] + agg["cache_read"] + agg["cache_create"], 1)
    if cache_ratio > 0:
        print(f"  cache hit ratio: {c(GREEN, f'{cache_ratio*100:.1f}%'):>14}")


def cmd_default(records: list[dict]) -> None:
    """Today + last 7 days table."""
    print(c(BOLD, c(CYAN, "Claude Code Worktree — Cost & Calls")))
    print(c(DIM, "─" * 56))
    print()
    print_period("Today", filter_today(records))
    print()
    print_weekday_table(records, 7)
    print()
    if records:
        first = min(records, key=lambda r: r["at"])
        first_date = to_local_date(first["at"]).strftime("%Y-%m-%d")
        agg = aggregate(records)["total"]
        print(c(BOLD, "Lifetime"))
        print(f"  {fmt_n(agg['count'])} calls   {c(GREEN, '$' + fmt_n(agg['cost']))}"
              f"   since {first_date}")


def cmd_today(records: list[dict]) -> None:
    today = filter_today(records)
    print_period("Today", today)
    print()
    print_tokens_summary(today)


def cmd_week(records: list[dict]) -> None:
    print_weekday_table(records, 7)
    print()
    print_tokens_summary(filter_days(records, 7))


def cmd_month(records: list[dict]) -> None:
    print_weekday_table(records, 30)
    print()
    print_tokens_summary(filter_days(records, 30))


def cmd_all(records: list[dict]) -> None:
    if not records:
        print("(no records)")
        return
    first = min(records, key=lambda r: r["at"])
    first_date = to_local_date(first["at"]).strftime("%Y-%m-%d")
    print_period(f"Lifetime (since {first_date})", records)
    print()
    print_tokens_summary(records)


def cmd_log(records: list[dict]) -> None:
    """Tail raw entries (last 20)."""
    if not records:
        print("(no records)")
        return
    for r in records[-20:]:
        t = to_local_date(r["at"]).strftime("%m-%d %H:%M:%S")
        layer = r.get("layer", "?")
        cost = r.get("cost_usd", 0)
        dur = r.get("duration_s", 0)
        sid = (r.get("session_id") or "")[:8]
        ok = "" if r.get("ok", True) else c(RED, " FAIL")
        sid_str = f"  sid={sid}" if sid else ""
        print(f"  {t}  {c(CYAN, layer):<18}  ${cost:.4f}  {dur:.1f}s{sid_str}{ok}")


def cmd_json(records: list[dict]) -> None:
    today = filter_today(records)
    out = {
        "lifetime": aggregate(records),
        "today": aggregate(today),
        "last_7_days": aggregate(filter_days(records, 7)),
        "last_30_days": aggregate(filter_days(records, 30)),
        "first_entry_at": (min(records, key=lambda r: r["at"]).get("at") if records else None),
        "total_entries": len(records),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


COMMANDS = {
    "today": cmd_today,
    "week": cmd_week,
    "month": cmd_month,
    "all": cmd_all,
    "log": cmd_log,
    "json": cmd_json,
}


def main() -> int:
    args = sys.argv[1:]
    records = load_log()

    if not records and not args:
        print(c(YELLOW, "No AI calls logged yet."))
        print(c(DIM, f"  Log file: {COST_LOG}"))
        print(c(DIM, "  Run `mindmap --refresh` to trigger one."))
        return 0

    if not args or args[0] == "--help" or args[0] == "-h":
        if args == ["--help"] or args == ["-h"]:
            print(__doc__.strip())
            return 0
        cmd_default(records)
        return 0

    fn = COMMANDS.get(args[0])
    if not fn:
        print(f"unknown subcommand: {args[0]}", file=sys.stderr)
        print(f"available: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    fn(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())

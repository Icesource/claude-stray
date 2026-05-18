#!/usr/bin/env python3
"""
DD-006 derived feature: daily AI tip.

Examines patterns across cache/mindmap.json (paused-with-stale-blockers,
many-initiatives-same-reviewer, low-throughput-vs-volume, etc.) and
asks Haiku to produce ONE concrete, data-anchored tip — never generic
advice.

Output: cache/derived/tips/latest.json
  {
    "generated_at": "<ISO>",
    "tip": "...",
    "pattern": "<which pattern the tip reacts to>",
    "history": [last 10 tips, oldest dropped]
  }

CLI:
  python3 bin/derived/tips.py [--dry-run] [--force]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from derived._shared import (  # noqa: E402
    DERIVED_DIR, MINDMAP_FILE, get_lang, call_claude, log_cost,
    atomic_write_json, ensure_dir, read_last_run, write_last_run,
    hours_since, now_utc_iso,
)

OUT_DIR = DERIVED_DIR / "tips"
OUT_FILE = OUT_DIR / "latest.json"
FEATURE = "derived.tips"
HISTORY_LIMIT = 10
MIN_HOURS_BETWEEN_RUNS = 12   # once a day-ish


def _detect_patterns() -> list[dict]:
    """Return a list of (pattern_id, evidence) tuples worth a tip.

    Each entry: {pattern, evidence, examples} so the AI prompt can
    quote specific cards.
    """
    if not MINDMAP_FILE.exists():
        return []
    try:
        mm = json.loads(MINDMAP_FILE.read_text())
    except json.JSONDecodeError:
        return []

    patterns: list[dict] = []
    now = datetime.now(timezone.utc)

    paused_with_blockers: list[dict] = []
    paused_long: list[dict] = []
    active_too_many_pending: list[dict] = []
    reviewers_clustered: dict[str, list[str]] = {}

    for ws in (mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            status = init.get("status")
            blockers = init.get("blockers") or []
            la = init.get("last_activity_at")
            try:
                la_dt = datetime.fromisoformat((la or "").replace("Z", "+00:00"))
                days_idle = (now - la_dt).days if la else 9999
            except (ValueError, TypeError):
                days_idle = 9999

            if status == "paused" and blockers:
                paused_with_blockers.append({
                    "id": init.get("id"), "name": init.get("name"),
                    "blockers": blockers[:3], "days_idle": days_idle,
                })
            if status == "paused" and days_idle >= 14:
                paused_long.append({
                    "id": init.get("id"), "name": init.get("name"),
                    "days_idle": days_idle,
                })
            if status == "active":
                pending = [t for t in (init.get("tasks") or [])
                           if not t.get("done")]
                if len(pending) >= 6:
                    active_too_many_pending.append({
                        "id": init.get("id"), "name": init.get("name"),
                        "pending_count": len(pending),
                    })
            # Reviewer clustering (very rough — extract a name from blockers
            # like "等 CodeOwner @某某 评审")
            for b in blockers:
                if "@" in b:
                    # Pull the @handle
                    after = b.split("@", 1)[1]
                    handle = after.split()[0] if after else None
                    if handle:
                        reviewers_clustered.setdefault(handle, []).append(
                            init.get("name") or init.get("id"))

    if paused_with_blockers:
        patterns.append({
            "pattern": "paused_with_blockers",
            "summary": f"{len(paused_with_blockers)} paused initiatives "
                       f"have active blockers",
            "examples": paused_with_blockers[:3],
        })
    if paused_long:
        patterns.append({
            "pattern": "paused_long",
            "summary": f"{len(paused_long)} initiatives paused for "
                       f">14 days — candidates for archive",
            "examples": paused_long[:3],
        })
    if active_too_many_pending:
        patterns.append({
            "pattern": "active_too_many_pending",
            "summary": f"{len(active_too_many_pending)} active initiatives "
                       f"have 6+ pending tasks — possibly over-scoped",
            "examples": active_too_many_pending[:3],
        })
    clustered = {k: v for k, v in reviewers_clustered.items() if len(v) >= 2}
    if clustered:
        patterns.append({
            "pattern": "reviewer_clustered",
            "summary": f"{len(clustered)} reviewer(s) blocking 2+ "
                       f"initiatives each",
            "examples": [{"reviewer": k, "blocking": v}
                         for k, v in list(clustered.items())[:3]],
        })

    return patterns


def _build_prompt(patterns: list[dict], lang: str) -> str:
    lang_block = (
        "用简体中文,2 句之内,具体引用 1 个 example,避免泛泛而谈。"
        if lang.startswith("zh") else
        "Reply in English, ≤ 2 sentences, must cite ≥ 1 specific "
        "example, no generic platitudes."
    )
    return f"""Given these patterns observed in the user's current
work, produce ONE concrete, actionable tip. The tip MUST reference
specific data (an initiative name, a blocker, a count) — never
generic life advice.

Return STRICT JSON:
  {{"pattern": "<id from input>", "tip": "<the tip text>"}}

{lang_block}

Patterns:
{json.dumps(patterns, indent=2, ensure_ascii=False)}
"""


def generate(*, dry_run: bool = False, force: bool = False) -> int:
    patterns = _detect_patterns()
    if not patterns:
        print("[tips] no patterns surfaced — skipping", file=sys.stderr)
        return 2

    last = read_last_run(FEATURE)
    if (not force and last.get("at")
            and hours_since(last["at"]) < MIN_HOURS_BETWEEN_RUNS):
        print(f"[tips] last run {hours_since(last['at']):.1f}h ago — debounced",
              file=sys.stderr)
        return 2

    print(f"[tips] patterns: {[p['pattern'] for p in patterns]}",
          file=sys.stderr)
    if dry_run:
        print(json.dumps(patterns, indent=2, ensure_ascii=False))
        return 0

    prompt = _build_prompt(patterns, get_lang())
    envelope, raw, rc, duration = call_claude(prompt, max_budget_usd=0.10)
    if rc != 0 or not raw.strip():
        print(f"[tips] AI call failed (rc={rc}): {raw[:200]}", file=sys.stderr)
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
        print(f"[tips] AI output not parseable: {raw[:200]}", file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    tip = (parsed.get("tip") or "").strip()
    pat = (parsed.get("pattern") or "").strip()
    if not tip:
        print("[tips] AI returned empty tip — skipping", file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    existing = {}
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            pass
    history = list(existing.get("history") or [])
    if existing.get("tip"):
        history.append({"tip": existing["tip"], "pattern": existing.get("pattern"),
                        "generated_at": existing.get("generated_at")})
    history = history[-(HISTORY_LIMIT - 1):]

    payload = {
        "generated_at": now_utc_iso(),
        "pattern": pat,
        "tip": tip,
        "history": history,
    }
    ensure_dir(OUT_DIR)
    atomic_write_json(OUT_FILE, payload)
    log_cost(FEATURE, envelope, duration, ok=True)
    write_last_run(FEATURE, {"pattern": pat})

    cost = (envelope or {}).get("total_cost_usd", 0)
    print(f"[tips] wrote {OUT_FILE.name}  cost=${cost:.4f}  "
          f"duration={duration:.1f}s", file=sys.stderr)
    print(f"[tips] tip: {tip}", file=sys.stderr)
    return 0


def _main(argv: list[str]) -> int:
    return generate(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

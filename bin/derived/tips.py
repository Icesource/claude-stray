#!/usr/bin/env python3
"""
DD-006 derived feature: rotating tips ticker.

Each invocation produces FOUR tips in different categories so the UI
can cycle through them — keeps a single "today's tip" from getting
stale and gives the user content that isn't just about work:

  work       — data-anchored, references a current pattern in the user's
               work (paused-with-blockers, reviewer-clustered, etc.).
               Only emitted when a corresponding pattern fires.
  wisdom     — short quote, poem fragment, or piece of life wisdom.
  rest       — gentle reminder to take a break, hydrate, etc.
  curiosity  — a small fact about the world / language / programming /
               history / nature — meant to delight, not instruct.

One AI call returns all four. The UI rotates through them every
20-30 seconds.

Output: cache/derived/tips/latest.json
  {
    "generated_at": "<ISO>",
    "tips": [
      {"kind": "work" | "wisdom" | "rest" | "curiosity",
       "text": "<≤120 chars>",
       "pattern": "<id>"  // present only for kind=work
      },
      ...
    ],
    "history": [
      // last N previous rotations (each = {generated_at, tips: [...]})
    ]
  }

CLI:
  python3 bin/derived/tips.py [--dry-run] [--force]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
HISTORY_LIMIT = 6        # keep last 6 rotations
MIN_HOURS_BETWEEN_RUNS = 6


# ---------- work-pattern detection (unchanged from v1) -------------------

def _detect_work_patterns() -> list[dict]:
    """Returns a list of work-pattern dicts (may be empty)."""
    if not MINDMAP_FILE.exists():
        return []
    try:
        mm = json.loads(MINDMAP_FILE.read_text())
    except json.JSONDecodeError:
        return []

    patterns: list[dict] = []
    paused_with_blockers: list[dict] = []
    paused_long: list[dict] = []
    active_too_many_pending: list[dict] = []
    reviewers_clustered: dict[str, list[str]] = {}

    now = datetime.now(timezone.utc)
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
            for b in blockers:
                if "@" in b:
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


# ---------- prompt -------------------------------------------------------

def _build_prompt(work_patterns: list[dict], recent_history: list[dict],
                  lang: str) -> str:
    """Ask for 4 tips, one per category. recent_history is the flat list
    of recent tip texts so we can ask AI to avoid repetition."""
    work_block = (
        f"Work patterns observed in user's current data:\n"
        f"{json.dumps(work_patterns, indent=2, ensure_ascii=False)}"
        if work_patterns
        else "No work patterns surfaced this round — skip the `work` tip "
             "and pick a fresh general suggestion in its place "
             '(kind: "wisdom", "rest", or "curiosity") — total still 4 tips, '
             "no duplicates."
    )
    recent_block = (
        f"\nRECENTLY SHOWN (avoid repeating these texts):\n"
        f"{json.dumps([h['text'] for h in recent_history[:10]], ensure_ascii=False)}"
        if recent_history else ""
    )

    if lang.startswith("zh"):
        lang_block = (
            "全部 4 条用简体中文。tone:温和、口语化、不说教。每条 ≤ 50 字。"
        )
        kind_examples = """
- work: 数据驱动的工作建议 (引用具体 initiative 名/数字)
  e.g. "hsf-hanging-mrs 已卡 3 天,瓶颈是 aone 发布。建议今天约一下排期。"
- wisdom: 一句诗、名言、人生感悟。可以是古今中外的经典。
  e.g. "结庐在人境,而无车马喧。问君何能尔?心远地自偏。— 陶渊明"
- rest: 温和的休息提醒,不要假大空。
  e.g. "屏幕看久了眼睛会涩,起身倒杯水,看 20 秒远处再回来。"
- curiosity: 生活/语言/编程/科学/历史的小知识,带点惊喜感。
  e.g. "鸭子的嘎嘎声其实有回声,只是它的频率让人耳听不清。"
"""
    else:
        lang_block = (
            "All 4 in English. Tone: warm, conversational, never preachy. "
            "Each ≤ 90 chars."
        )
        kind_examples = """
- work: data-anchored advice citing a specific initiative or number.
- wisdom: a short quote or piece of life wisdom (any era/culture).
- rest: gentle break reminder, no platitudes.
- curiosity: a small surprising fact about life/language/programming.
"""

    return f"""Generate FOUR short tips for a developer's dashboard.
Each in a different category. The UI rotates through them.

Categories:
{kind_examples}

Return STRICT JSON of the form:
  {{
    "tips": [
      {{"kind": "work",      "text": "...", "pattern": "<id-from-input>"}},
      {{"kind": "wisdom",    "text": "..."}},
      {{"kind": "rest",      "text": "..."}},
      {{"kind": "curiosity", "text": "..."}}
    ]
  }}

Hard rules:
- Exactly 4 tips total, one per category.
- {lang_block}
- `work` tip MUST cite specific data from the patterns block. If no
  patterns are listed below, omit `work` and emit a second non-work
  tip in its place (still 4 total, no kind duplicates).
- No generic platitudes ("take care of yourself", "stay focused").
- No identical or near-identical text to RECENTLY SHOWN entries.

{work_block}{recent_block}
"""


def _collect_recent_history(existing: dict) -> list[dict]:
    """Flatten last few rotations into [{kind, text}, ...] for dedup."""
    out: list[dict] = []
    for batch in (existing.get("history") or [])[-3:]:
        for t in (batch.get("tips") or []):
            if t.get("text"):
                out.append({"kind": t.get("kind"), "text": t["text"]})
    # Plus the current round's tips
    for t in (existing.get("tips") or []):
        if t.get("text"):
            out.append({"kind": t.get("kind"), "text": t["text"]})
    return out


def generate(*, dry_run: bool = False, force: bool = False) -> int:
    last = read_last_run(FEATURE)
    if (not force and last.get("at")
            and hours_since(last["at"]) < MIN_HOURS_BETWEEN_RUNS):
        print(f"[tips] last run {hours_since(last['at']):.1f}h ago — debounced",
              file=sys.stderr)
        return 2

    work_patterns = _detect_work_patterns()
    existing: dict = {}
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            pass
    recent = _collect_recent_history(existing)

    print(f"[tips] work patterns: {[p['pattern'] for p in work_patterns] or '(none)'}",
          file=sys.stderr)
    if dry_run:
        print(json.dumps({
            "work_patterns": work_patterns,
            "recent_history_size": len(recent),
        }, indent=2, ensure_ascii=False))
        return 0

    prompt = _build_prompt(work_patterns, recent, get_lang())
    envelope, raw, rc, duration = call_claude(prompt, max_budget_usd=0.15)
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

    new_tips = []
    for t in (parsed.get("tips") or []):
        text = (t.get("text") or "").strip()
        kind = (t.get("kind") or "").strip()
        if not text or kind not in ("work", "wisdom", "rest", "curiosity"):
            continue
        entry = {"kind": kind, "text": text[:200]}
        if kind == "work" and t.get("pattern"):
            entry["pattern"] = str(t["pattern"])[:60]
        new_tips.append(entry)

    if not new_tips:
        print("[tips] AI returned no usable tips", file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    # Roll history: previous "tips" becomes the newest history entry
    history = list(existing.get("history") or [])
    if existing.get("tips"):
        history.append({
            "generated_at": existing.get("generated_at"),
            "tips": existing["tips"],
        })
    history = history[-HISTORY_LIMIT:]

    payload = {
        "generated_at": now_utc_iso(),
        "tips": new_tips,
        "history": history,
    }
    ensure_dir(OUT_DIR)
    atomic_write_json(OUT_FILE, payload)
    log_cost(FEATURE, envelope, duration, ok=True,
             extra={"n_tips": len(new_tips)})
    write_last_run(FEATURE, {"n_tips": len(new_tips)})

    cost = (envelope or {}).get("total_cost_usd", 0)
    print(f"[tips] wrote {OUT_FILE.name} ({len(new_tips)} tips)  "
          f"cost=${cost:.4f}  duration={duration:.1f}s", file=sys.stderr)
    for t in new_tips:
        print(f"[tips]   [{t['kind']}] {t['text']}", file=sys.stderr)
    return 0


def _main(argv: list[str]) -> int:
    return generate(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

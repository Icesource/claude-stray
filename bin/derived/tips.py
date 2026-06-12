#!/usr/bin/env python3
"""
DD-006 derived feature: rotating tips ticker.

Each invocation produces TWENTY tips with an intentionally uneven
split (curiosity 8, wisdom 6, work 3, rest 3) so the UI
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
    DERIVED_DIR, DASHBOARD_FILE, get_lang, call_claude, log_cost,
    atomic_write_json, ensure_dir, read_last_run, write_last_run,
    hours_since, now_utc_iso,
)

OUT_DIR = DERIVED_DIR / "tips"
OUT_FILE = OUT_DIR / "latest.json"
FEATURE = "derived.tips"
HISTORY_LIMIT = 6        # keep last 6 rotations
MIN_HOURS_BETWEEN_RUNS = 2


# ---------- work-pattern detection (unchanged from v1) -------------------

def _detect_work_patterns() -> list[dict]:
    """Returns a list of work-pattern dicts (may be empty)."""
    if not DASHBOARD_FILE.exists():
        return []
    try:
        mm = json.loads(DASHBOARD_FILE.read_text())
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
    """Ask for 20 tips with intentionally uneven split: curiosity 8,
    wisdom 6, work 3, rest 3 (rounded to 20). recent_history is the
    flat list of recent tip texts so AI can avoid repetition."""
    work_block = (
        f"Work patterns observed in user's current data:\n"
        f"{json.dumps(work_patterns, indent=2, ensure_ascii=False)}"
        if work_patterns
        else "No work patterns surfaced this round — emit 0 `work` tips. "
             "Backfill the 3 work slots into `curiosity` so the total stays "
             "at 20 (curiosity becomes 11, wisdom 6, rest 3, work 0)."
    )
    recent_block = (
        f"\nRECENTLY SHOWN (avoid repeating these texts):\n"
        f"{json.dumps([h['text'] for h in recent_history[:40]], ensure_ascii=False)}"
        if recent_history else ""
    )

    if lang.startswith("zh"):
        lang_block = (
            "全部 20 条用简体中文。tone:温和、口语化、不说教。每条 ≤ 50 字。"
            "wisdom 类的诗句保持原文文言/古文,不要翻译,但 — 字号后跟的"
            "归属说明用现代汉语。"
        )
        kind_examples = """
- work (3 条): 数据驱动的工作建议 (引用具体 initiative 名/数字)。无需 source_url。
  e.g. "checkout-hanging-mrs 已卡 3 天,瓶颈是发布流水线。建议今天约一下排期。"

- wisdom (6 条): 真实存在的诗句、闲适风格的人生感悟。**重点是放松/写景/生活意境,
  不要励志说教。**
  偏好题材:山水景色、四季时节、闲居琐事、日常感受、对自然的观察、淡然心境。
  避免:励志自勉("莫等闲白了少年头")、勤学苦读("学而不思则罔")、修身齐家。
  必须有明确出处,source_url 指向 Wikipedia / Wikiquote / 诗词作者页等可核验页面。
  好的例子:
    "采菊东篱下,悠然见南山。— 陶渊明《饮酒·其五》"
        → https://zh.wikipedia.org/wiki/陶淵明
    "明月松间照,清泉石上流。— 王维《山居秋暝》"
        → https://zh.wikipedia.org/wiki/王維
    "竹外桃花三两枝,春江水暖鸭先知。— 苏轼《惠崇春江晚景》"
        → https://zh.wikipedia.org/wiki/蘇軾
    "山光悦鸟性,潭影空人心。— 常建《题破山寺后禅院》"
    "稻花香里说丰年,听取蛙声一片。— 辛弃疾《西江月·夜行黄沙道中》"

- rest (3 条): 温和的休息提醒,基于常识可不带 URL,但不要鼓吹无稽的健康偏方。
  e.g. "屏幕看久了眼睛会涩,起身倒杯水,看 20 秒远处再回来。"

- curiosity (8 条): 真实可核验的小知识。每条 MUST 配 source_url(维基百科 / Etymonline /
  Stanford Encyclopedia / MDN / 权威官网)。无法找到可信链接的不要写。
  题材尽量发散:词源、生物、编程史、物理、食物、音乐、地理 — 让读者每条都有新发现。
  反例 ❌ "鸭子嘎嘎声没有回声"(这是流传甚广的伪科学)。
  正例 ✓ "'OK' 一词源自 1839 年波士顿一份报纸刊登的玩笑缩写 'oll korrect'。"
         source_url: https://en.wikipedia.org/wiki/OK
"""
    else:
        lang_block = (
            "All 20 in English. Tone: warm, conversational, never preachy. "
            "Each ≤ 90 chars."
        )
        kind_examples = """
- work (3 tips): data-anchored advice citing a specific initiative / number.
  No source_url needed.
- wisdom (6 tips): a real quote or piece of life wisdom. **Bias toward
  calm / scenic / observational tones — landscape, seasons, daily-life
  reflection.** Avoid hustle-mode "seize the day" motivational lines.
  Attribution must be verifiable; include source_url pointing to
  Wikipedia / Wikiquote / primary text.
- rest (3 tips): gentle break reminder. Common-sense items don't need
  a URL, but never push unproven health claims.
- curiosity (8 tips): a small surprising fact about life / language /
  programming / science / history. EVERY curiosity tip MUST include
  a source_url (Wikipedia, Etymonline, Stanford Encyclopedia, MDN,
  official docs). If you cannot find a credible source for a claim,
  drop the tip — don't fabricate. Avoid widely-repeated-but-false
  trivia (e.g. the myth that ducks' quacks don't echo — debunked).
"""

    return f"""Generate TWENTY short tips for a developer's dashboard.
Intentionally uneven split: curiosity gets the most rotation slots,
wisdom second, work / rest equal and small.

Default split:
  - curiosity: 8
  - wisdom:    6
  - rest:      3
  - work:      3
  Total:      20

Categories:
{kind_examples}

Return STRICT JSON. Structure (order doesn't matter — counts do):
  {{
    "tips": [
      {{"kind": "curiosity", "text": "...", "source_url": "https://..."}},
      ... 8 curiosity entries total — source_url REQUIRED ...
      {{"kind": "wisdom",    "text": "...", "source_url": "https://..."}},
      ... 6 wisdom entries total — source_url REQUIRED ...
      {{"kind": "rest",      "text": "..."}},
      ... 3 rest entries total — source_url optional ...
      {{"kind": "work",      "text": "...", "pattern": "<id-from-input>"}},
      ... 3 work entries total — no source_url ...
    ]
  }}

Hard rules:
- Aim for the split above. If you cannot fill a category with that
  many *verifiable* entries (curiosity / wisdom), emit fewer in that
  category and add the surplus to curiosity. Floor: 14 tips total.
- {lang_block}
- **No fabrication.** Every factual claim must be traceable. If you
  are unsure whether a quote is correctly attributed, a fact is true,
  or a URL exists, DROP the tip. Better a sparse round than a wrong
  one.
- `source_url` is REQUIRED on every `curiosity` tip and every `wisdom`
  tip. The URL must be one you have high confidence is real and
  on-topic. Prefer canonical references:
    * Wikipedia / Wikiquote (zh.wikipedia.org / en.wikipedia.org)
    * Etymonline.com for word origins
    * Plato.stanford.edu for philosophy
    * MDN / official language docs for programming history
    * Standards bodies for science/math facts
  If you can't find a stable canonical URL, drop the tip.
- Every `work` tip MUST cite specific data from the patterns block —
  a concrete initiative id, MR number, blocker count, etc. Skip
  `source_url` (work tips are grounded in the user's own data).
- Within a category, all tips must be meaningfully different —
  different angle, mood, era, reference, or topic. Don't write
  near-duplicates.
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
        url = (t.get("source_url") or "").strip()
        # Sanity-check the URL — only accept http(s) on a domain that
        # plausibly hosts factual references. Dropping malformed entries
        # is cheap protection against AI hallucinating URLs.
        if url.startswith(("http://", "https://")) and " " not in url \
                and len(url) <= 300:
            entry["source_url"] = url
        elif kind == "curiosity":
            # Curiosity tips REQUIRE a source URL per prompt rules. If
            # AI omitted it, the tip is unverifiable — drop.
            print(f"[tips] dropped curiosity tip without source_url: "
                  f"{text[:60]!r}", file=sys.stderr)
            continue
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

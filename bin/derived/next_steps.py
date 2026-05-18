#!/usr/bin/env python3
"""
DD-006 derived feature: next-step suggestions.

Reads cache/mindmap.json's active + paused initiatives plus their
blockers/last_activity, and asks Haiku to pick 3 the user should
focus on next. Cheap (~$0.05/run) and runs after every classify
finish, debounced to once per 30 minutes.

Output: cache/derived/suggestions/latest.json
  {
    "generated_at": "<ISO>",
    "items": [
      {"init_id", "init_name", "ws_name", "reason"}, ...     (max 3)
    ]
  }

CLI:
  python3 bin/derived/next_steps.py           # generate now
  python3 bin/derived/next_steps.py --dry-run # show candidate set
  python3 bin/derived/next_steps.py --force   # ignore debounce
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from derived._shared import (  # noqa: E402
    DERIVED_DIR, MINDMAP_FILE, get_lang, call_claude, log_cost,
    atomic_write_json, ensure_dir, read_last_run, write_last_run,
    hours_since, now_utc_iso,
)

OUT_DIR = DERIVED_DIR / "suggestions"
OUT_FILE = OUT_DIR / "latest.json"
FEATURE = "derived.next_steps"

DEBOUNCE_MINUTES = 30


def _gather_candidates() -> list[dict]:
    """Pull active + paused initiatives. AI picks 3."""
    if not MINDMAP_FILE.exists():
        return []
    try:
        mm = json.loads(MINDMAP_FILE.read_text())
    except json.JSONDecodeError:
        return []
    items = []
    for ws in (mm.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            status = init.get("status")
            if status not in ("active", "paused"):
                continue
            items.append({
                "id": init.get("id"),
                "name": init.get("name"),
                "ws_name": ws.get("name"),
                "status": status,
                "progress": init.get("progress"),
                "last_activity_at": init.get("last_activity_at"),
                "blockers": init.get("blockers") or [],
                "pending_tasks": [
                    t.get("title") for t in (init.get("tasks") or [])
                    if not t.get("done")
                ][:5],
                "artifacts_open": [
                    a for a in (init.get("artifacts") or [])
                    if a.get("status") in ("open", "pending", "in_review")
                ][:3],
            })
    # Sort: active first, then by recency desc — bias toward fresh work
    items.sort(key=lambda i: (
        0 if i["status"] == "active" else 1,
        i.get("last_activity_at") or "",
    ), reverse=False)
    items[1:] = sorted(
        [i for i in items if i["status"] != "active"],
        key=lambda i: i.get("last_activity_at") or "",
        reverse=True,
    )
    return items


def _build_prompt(candidates: list[dict], lang: str) -> str:
    lang_block = (
        "用简体中文回复。reason 字段保持 ≤ 60 字。"
        if lang.startswith("zh") else
        "Reply in English. Each `reason` ≤ 60 chars."
    )
    return f"""Given these in-flight initiatives, pick the 3 the user
should focus on NEXT.

Selection heuristics (in priority order):
  1. Fresh momentum: recent active status with pending tasks the
     user can act on alone.
  2. Blocked-but-unblockable: blockers that look user-actionable
     (e.g. "等用户确认"), not external (e.g. "等 CodeOwner 评审").
  3. Low-effort cleanup: small initiatives with 1–2 pending tasks
     and an open MR/PR.

Avoid initiatives whose blockers are clearly external (waiting on
reviewer, CI, ops). Avoid done/archived.

Return STRICT JSON of the form:
  {{"items": [
    {{
      "init_id": "<id from input>",
      "reason": "<short, concrete justification ≤60 chars>"
    }},
    ...
  ]}}

Exactly 3 items if there are 3+ candidates; fewer if not. {lang_block}

Candidates:
{json.dumps(candidates, indent=2, ensure_ascii=False)}
"""


def generate(*, dry_run: bool = False, force: bool = False) -> int:
    candidates = _gather_candidates()
    if len(candidates) == 0:
        print("[next_steps] no active/paused initiatives — skipping",
              file=sys.stderr)
        return 2

    # Debounce
    last = read_last_run(FEATURE)
    if not force and last.get("at"):
        gap_min = hours_since(last["at"]) * 60
        if gap_min < DEBOUNCE_MINUTES:
            print(f"[next_steps] last run {gap_min:.0f}m ago — debounced "
                  f"(use --force to override)", file=sys.stderr)
            return 2

    print(f"[next_steps] {len(candidates)} candidates", file=sys.stderr)
    if dry_run:
        print(json.dumps(candidates, indent=2, ensure_ascii=False))
        return 0

    prompt = _build_prompt(candidates, get_lang())
    envelope, raw, rc, duration = call_claude(prompt, max_budget_usd=0.20)
    if rc != 0 or not raw.strip():
        print(f"[next_steps] AI call failed (rc={rc}): {raw[:200]}",
              file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    # Parse: tolerate JSON wrapped in code fence
    body = raw.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines)
    # Extract {...}
    i, j = body.find("{"), body.rfind("}")
    if i != -1 and j != -1:
        body = body[i:j + 1]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        print(f"[next_steps] AI output not parseable JSON: {e}",
              file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    # Enrich + validate: each item must reference a real candidate
    cand_by_id = {c["id"]: c for c in candidates}
    items_out = []
    for it in (parsed.get("items") or [])[:3]:
        iid = it.get("init_id")
        c = cand_by_id.get(iid)
        if not c:
            continue
        items_out.append({
            "init_id": iid,
            "init_name": c["name"],
            "ws_name": c["ws_name"],
            "reason": (it.get("reason") or "").strip()[:120],
        })

    payload = {"generated_at": now_utc_iso(), "items": items_out}
    ensure_dir(OUT_DIR)
    atomic_write_json(OUT_FILE, payload)
    log_cost(FEATURE, envelope, duration, ok=True)
    write_last_run(FEATURE, {"items": len(items_out)})

    cost = (envelope or {}).get("total_cost_usd", 0)
    print(f"[next_steps] wrote {OUT_FILE.name} ({len(items_out)} items)  "
          f"cost=${cost:.4f}  duration={duration:.1f}s", file=sys.stderr)
    return 0


def _main(argv: list[str]) -> int:
    return generate(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

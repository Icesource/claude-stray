#!/usr/bin/env python3
"""
DD-006 derived feature: weekly report.

Approach (per user discussion 2026-05-18):
  1. Locally compute a structured WeeklySignal — five buckets of
     verifiable evidence ('what got touched / shipped / archived /
     done / produced this week'). No AI involvement.
  2. Pass that JSON + a short instruction to Haiku, which writes a
     human-readable markdown narrative. AI's job is to organize
     wording, not to invent facts.
  3. Save both: the prebuilt JSON (so each report sentence is
     traceable back to a source signal) and the narrative markdown.

Output:
  cache/derived/reports/<YYYY-Www>.md      ← narrative (UI shows this)
  cache/derived/reports/<YYYY-Www>.json    ← prebuilt signal payload
  cache/derived/reports/.last_run.json     ← gating

CLI:
  python3 bin/derived/weekly_report.py [--week N]   # 0=this, 1=last, ...
  python3 bin/derived/weekly_report.py --dry-run    # show signal, skip AI
  python3 bin/derived/weekly_report.py --force      # ignore last-run gate

Trigger:
  - Manual:   mindmap --weekly-report
  - Scheduled: launchd Sunday 18:00 local (DD-006 §3.2)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from derived._shared import (  # noqa: E402
    DERIVED_DIR, WeekRange, compute_weekly_signal, get_lang, call_claude,
    log_cost, atomic_write, atomic_write_json, ensure_dir, read_last_run,
    write_last_run, hours_since, now_utc_iso,
)

REPORTS_DIR = DERIVED_DIR / "reports"
FEATURE = "derived.weekly_report"

# Skip if regenerated within this many hours (avoid spamming on manual
# re-runs; weekly scheduler runs once a week anyway).
MIN_HOURS_BETWEEN_RUNS = 6


def _build_prompt(signal_json: dict, lang: str) -> str:
    """The instruction wrap around the structured signal.

    Critical principle: AI writes prose FROM the JSON, doesn't invent
    facts beyond it. Every claim in the report must trace to a signal.
    """
    if lang.startswith("zh"):
        lang_block = (
            "用简体中文写,语气客观、专业但不机械。每一句都必须来自"
            "下面 JSON 里某条信号。不引入未列出的内容。"
        )
    else:
        lang_block = (
            "Write in English, objective and professional but not robotic. "
            "Every claim must trace to a signal in the JSON below. "
            "Don't invent anything not listed."
        )

    return f"""You are writing a weekly work summary for one developer.
The week is {signal_json['week_label']} ({signal_json['week_start']} —).

Structure your output as markdown with these sections (translate
section names if writing in zh-CN):

  ## Highlights
    3–6 bullets covering the most impactful events of the week.
    Anchor on archived_this_week + tasks_done_this_week +
    new_artifacts_this_week (esp. MR/PR with status:merged).

  ## Active initiatives
    For each item in active_initiatives, one line: name + status +
    a short paraphrase of progress. Group by workspace if it helps.

  ## Shipped / Closed
    Recap archived_this_week + tasks_done_this_week as a bulleted
    list. If empty, write "(no items this week)" once for the
    section.

  ## Scope changes
    From tasks_cancelled_this_week, list tasks that were cancelled
    or merged into other tasks. Cite the evidence field briefly
    (e.g. "Merged into X" or "Scoped out per turn"). Skip the
    section if the list is empty.

  ## Notable artifacts
    From new_artifacts_this_week, list MR/PR/issue/doc links worth
    referencing. Skip if the list is empty.

  ## Sessions touched
    A single line: "N sessions across M workspaces" — pull these
    counts from hot_sessions. Brief.

Style rules:
  - No preamble, no postscript ("Hope this helps", etc.).
  - Tech identifiers (HSF, MR numbers, branch names, file paths)
    stay in English even in zh-CN.
  - Quote artifact URLs as inline markdown links.
  - {lang_block}
  - Keep total length to ~30 lines or less.

JSON signal:
{json.dumps(signal_json, indent=2, ensure_ascii=False)}
"""


def generate(week_offset: int = 1, *, dry_run: bool = False,
             force: bool = False) -> int:
    """week_offset=0 → this week, 1 → last week (default), 2 → two ago, …

    Returns exit code (0 success, 2 skip, 1 failure)."""
    week = (WeekRange.for_date() if week_offset == 0
            else WeekRange.previous(week_offset))
    lang = get_lang()
    signal = compute_weekly_signal(week)
    sig_dict = signal.to_dict()

    if signal.is_empty():
        print(f"[weekly_report] {week.label}: no evidence this week — skipping",
              file=sys.stderr)
        return 2

    out_md = REPORTS_DIR / f"{week.label}.md"
    out_json = REPORTS_DIR / f"{week.label}.json"

    # Gating: skip if this same week was generated <MIN_HOURS_BETWEEN_RUNS h ago.
    last = read_last_run(FEATURE)
    if (not force and out_md.exists() and last.get("week") == week.label
            and hours_since(last.get("at")) < MIN_HOURS_BETWEEN_RUNS):
        print(f"[weekly_report] {week.label}: already generated "
              f"{hours_since(last.get('at')):.1f}h ago — skip "
              f"(use --force to regenerate)", file=sys.stderr)
        return 2

    # Always write the prebuilt JSON (zero cost; useful for audit + UI).
    ensure_dir(REPORTS_DIR)
    atomic_write_json(out_json, sig_dict)

    print(f"[weekly_report] {week.label}: signal=[hot={len(signal.hot_sessions)} "
          f"active={len(signal.active_initiatives)} "
          f"archived={len(signal.archived_this_week)} "
          f"tasks_done={len(signal.tasks_done_this_week)} "
          f"tasks_cancelled={len(signal.tasks_cancelled_this_week)} "
          f"artifacts={len(signal.new_artifacts_this_week)}]",
          file=sys.stderr)

    if dry_run:
        print(json.dumps(sig_dict, indent=2, ensure_ascii=False))
        return 0

    prompt = _build_prompt(sig_dict, lang)
    print(f"[weekly_report] calling Haiku (prompt={len(prompt)/1024:.1f}KB)",
          file=sys.stderr)
    envelope, raw, rc, duration = call_claude(prompt, max_budget_usd=0.50)
    if rc != 0 or not raw.strip():
        print(f"[weekly_report] AI call failed (rc={rc}, {duration:.1f}s): "
              f"{raw[:200]}", file=sys.stderr)
        log_cost(FEATURE, envelope, duration, ok=False)
        return 1

    # Strip any code-fence wrapper Haiku might emit.
    md = raw.strip()
    if md.startswith("```"):
        lines = md.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        md = "\n".join(lines)

    # Front-matter header so the file is self-describing
    header = (
        f"<!-- DD-006 weekly report\n"
        f"     week: {week.label} ({week.monday} — {week.monday.toordinal()})\n"
        f"     generated_at: {now_utc_iso()}\n"
        f"     model: {envelope.get('model') if envelope else '?'}\n"
        f"     cost_usd: {(envelope or {}).get('total_cost_usd', 0):.4f}\n"
        f"     signal: {out_json.name}\n"
        f"-->\n\n"
    )
    atomic_write(out_md, header + md + "\n")
    log_cost(FEATURE, envelope, duration, ok=True,
             extra={"week": week.label})
    write_last_run(FEATURE, {"week": week.label, "path": str(out_md)})

    cost = (envelope or {}).get("total_cost_usd", 0)
    print(f"[weekly_report] wrote {out_md.name}  cost=${cost:.4f} "
          f"duration={duration:.1f}s", file=sys.stderr)
    return 0


def _main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    force = "--force" in argv
    week_offset = 1
    for i, a in enumerate(argv):
        if a == "--week" and i + 1 < len(argv):
            try:
                week_offset = int(argv[i + 1])
            except ValueError:
                print(f"--week needs an integer, got {argv[i + 1]!r}",
                      file=sys.stderr)
                return 1
    return generate(week_offset, dry_run=dry, force=force)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

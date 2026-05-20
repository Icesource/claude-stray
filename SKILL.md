---
name: stray
description: |
  A local Claude Code companion that turns the user's ~200+ session
  history into a card-style dashboard of "initiatives" (work themes /
  projects-in-flight). Activate when the user asks "what am I working
  on", "where did I leave off", "what's blocked", "how much have I
  spent on Claude Code", or needs to navigate / resume a past Claude
  Code session. Also relevant for weekly summaries, paused/stalled
  work review, and lifecycle pause/resume of the AI pipeline.
---

# stray — Claude Code dashboard

`stray` reads every `~/.claude/projects/*/*.jsonl` (the Claude Code
session transcripts), runs a three-layer AI pipeline (extract →
per-session summarize → cross-session classify) on Haiku-4.5, and
emits a card dashboard at `http://127.0.0.1:9876/` with:

- **Initiatives** — semantic groupings of sessions ("HSF MR cleanup",
  "claude-stray dashboard", "documentation refactor", etc.)
- **Tasks** with tri-state status (`pending` / `done` / `cancelled`)
- **Artifacts** (CR / MR / PR / issue / branch URLs extracted from
  each session)
- **Blockers** ("等 reviewer 评审", "等 CI 通过", etc.)
- **Weekly report** auto-generated each Friday at noon
- **Tips bubble** — a playful walking pixel cat that surfaces curated
  knowledge (poems, etymology, programming history) every 25s, all
  with source URLs

The pipeline only runs when Claude Code's Stop / SessionStart hooks
fire, or when the dashboard's in-process scheduler ticks — never as a
background daemon when no one is looking.

## When to activate this skill

Listen for prompts like:

| User says | What to do |
|---|---|
| "What am I working on", "What's on my plate" | `stray` (terminal tree) or open `http://127.0.0.1:9876/` |
| "Where did I leave off" | `stray --serve` then point at the most-recently-active card |
| "What's blocked", "What's waiting on me" | open the dashboard and filter status=paused, or look at blocker chips |
| "How much have I spent on Claude / Haiku" | `stray --cost` (no arg = today + last 7d) |
| "Refresh / re-run the AI pipeline" | `stray --refresh` (forces a classify even if cache is hot) |
| "Pause / stop the AI", "Stop running in background" | `stray --pause` with optional reason |
| "Resume" / "Turn AI back on" | `stray --resume` |
| "Show me last week's recap" | `stray --weekly-report` (or open dashboard, click the weekly widget) |
| "What should I focus on next" | `stray --next-steps` (3 data-anchored suggestions) |
| "Diagnose / why isn't session X showing up" | `stray --diagnose [SID]` (SID optional) |
| "Resume claude session", "Reopen session Y" | open the dashboard, click 🆕 next to the session id; or `cd <cwd> && claude --resume <full-uuid>` |

## Command reference

All commands are sub-flags of the single `stray` binary. They print to
stdout / open browser / write to `cache/` as documented. None mutates
anything outside the repo unless explicitly noted.

| Command | What it does | Cost |
|---|---|---|
| `stray` | Render the cached dashboard as an ANSI tree in the terminal | $0 |
| `stray --serve` | **Recommended.** Start http://127.0.0.1:9876/, auto-open browser. Runs the in-process derived scheduler (tips / weekly). | $0 to start |
| `stray --refresh` | Force re-run of Layer 2 (cross-session classify). Use when the dashboard feels stale. | ~$0.17 per run with Haiku-4.5 |
| `stray --open` | Regenerate HTML and open via `file://` (no server) | $0 |
| `stray --tree` | Open the markmap tree view (alternate visualization) | $0 |
| `stray --html` | Regenerate HTML only, don't open anything | $0 |
| `stray --diagnose [SID]` | Decision tree: why might a session not appear in the dashboard? Without SID picks most-recent. | $0 |
| `stray --cost [PERIOD]` | AI call cost breakdown. PERIOD ∈ `today` (default+7d table) / `week` / `month` / `all` / `log` / `json`. | $0 |
| `stray --backfill` | One-shot: re-summarize EVERY session in `~/.claude/projects/`. | ~$8 (one-time) |
| `stray --pause [REASON]` | Engage kill switch — all subsequent hook fires become no-ops until `--resume`. Banner shows on dashboard. | $0 |
| `stray --resume` | Release kill switch | $0 |
| `stray --status` | Print lifecycle JSON | $0 |
| `stray --weekly-report [N]` | Generate weekly report for `N` weeks ago (default 1 = last week). Auto-runs Fri 12:00 local. | $0.10–$0.50 |
| `stray --next-steps` | Suggest 3 initiatives to focus on next, with rationale | ~$0.05 |
| `stray --tips` | Generate one fresh batch of 20 tips (curiosity-heavy). Auto-runs every 2h while `--serve` is up. | ~$0.08 |
| `stray --wellness` | Check for late-night / consecutive-day patterns; emit a kind nudge only if a signal fires. Silent (and free) otherwise. | ~$0.02 max |

Backward-compat: `mindmap` is a symlink to `stray`. Same flags, same
behavior. (Will be dropped in v0.7.)

## How it works (1-paragraph summary)

Claude Code's `Stop` hook triggers `bin/refresh-bg.sh`, which forks
`bin/pipeline-run.sh` into the background. Layer 1 (`summarize.py`)
turns each dirty session's raw jsonl into a structured markdown
summary under `cache/summaries/<sid>.md`. Layer 2 (`classify.py`) is
coalesced (only one runs at a time) and feeds all "hot" summaries
(touched in the last 48h) plus the PRIOR `cache/dashboard.json` to
Haiku, which returns the new `dashboard.json`. The dashboard HTML
(`cache/dashboard.html`) is regenerated by `render-html.py` whenever
data changes. `serve.py` is the local HTTP front and also runs an
in-process scheduler that fires the "derived" features
(tips/weekly/next-steps/wellness) on a clock.

Data sovereignty: nothing leaves the user's machine except outbound
Anthropic API calls. All cache lives at `cache/` inside the repo.

## Troubleshooting decision tree

When the user reports a problem, walk through this in order:

1. **"Dashboard is empty" / first-run**
   - Did `stray --refresh` ever complete? Check `cache/cost_log.jsonl`
     for at least one `layer: classify` entry.
   - If never: `stray --refresh` (takes 30–120s on first run)

2. **"Card didn't update after my session"**
   - Is the Stop hook installed? Look in `~/.claude/settings.json`
     for an entry with `bin/refresh-bg.sh` under `hooks.Stop`.
   - Is the pipeline paused? `stray --status` — look for `"paused": true`.
     If yes: `stray --resume`.
   - Is layer 1 lagging? Check `cache/summaries/<sid>.md` exists for
     the session id; if not, the extract or summarize step failed.
     `stray --diagnose <sid>` for the full breakdown.

3. **"Session X is missing"**
   - `stray --diagnose <full-uuid>` and read the output. Common causes:
     it's `is_automation: true` (filtered), it's `last_activity_at`
     older than the hot window (48h — only stays via PRIOR continuity),
     or its initiative was archived.

4. **"Costs feel high"**
   - `stray --cost month` — look at the per-layer breakdown.
   - Layer 2 (classify) at ~$0.17 × ~5 runs/day = ~$25/mo is normal.
   - Layer 1 (summarize) at ~$0.04 × N new sessions/day. If high,
     check if `--backfill` ran recently.

5. **"AI keeps marking my tasks done that aren't done"**
   - DD-011's terminal-monotone makes AI's done-flag stick. Click the
     checkbox in the dashboard to manually un-toggle (overrides AI).
   - To delete a task entirely so AI can't recreate it: 🗑️ in the UI →
     puts it in `cache/user_overrides.json` deleted_tasks tombstones.

6. **"The cat is gone / tips bubble disappeared"**
   - Check localStorage `tips-bubble-pos` — if dragged off-screen,
     `localStorage.removeItem("tips-bubble-pos")` in DevTools console
     resets to default (top-right corner).

## Examples

### User: "I have no idea what I was doing yesterday, help"

```
stray --serve
# point browser at http://127.0.0.1:9876/
# filter status=active, scan the top cards by last_activity_at
```

If that's not enough context, the card detail modal (click the card title)
shows artifacts, blockers, and a full session list with `🆕` resume buttons.

### User: "How much have I spent this month on the AI for this thing?"

```
stray --cost month
```

Shows a table broken down by layer (summarize / classify / derived) with
per-day totals.

### User: "Stop running AI in the background, I'm about to give a demo"

```
stray --pause "demo prep — back in 1h"
```

The dashboard banner shows the reason. `stray --resume` when done.

### User: "Resume the session from the HSF MR work I did last Tuesday"

Open the dashboard, find the relevant card (HSF MR cleanup-ish title),
expand the session list, click 🆕 on the matching session id.

## Repository

Source: <https://github.com/Icesource/claude-stray>

Install: `git clone https://github.com/Icesource/claude-stray.git ~/Code/claude-stray && bash ~/Code/claude-stray/bin/install.sh`

For end-to-end one-line install via this SKILL, see the install
section of the repo README.

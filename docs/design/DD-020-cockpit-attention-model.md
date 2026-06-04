# DD-020: Cockpit-aligned attention model + AI next-message suggestions

**Status**: Accepted
**Author**: Claude (with user)
**Date**: 2026-06-03
**Predecessors**: DD-013 (mechanical status), DD-014 (mechanical level),
DD-015 (cockpit), DD-018 (session interaction)

## Problem

The status/progress model predated the live *attention board*. Symptoms the
user hit: a diagnosis card marked `done` the moment it "located a root cause"
(work wasn't done); progress lagging/drifting because classify re-narrates it
every run; active work buried in 已完成 because `bandFor` trusted a stale `done`
status over live telemetry. The data model wasn't serving the cockpit's job —
*who needs me, and how do I jump back in*.

## Design — mechanical attention fields (A/C/D)

Same philosophy as DD-013/014: derive cockpit signals mechanically from Layer-1,
don't trust AI prose.

- **A — `awaiting_user`**: Layer-1 emits it ONLY when the work is blocked on the
  human (one line: the specific decision/answer needed). `classify.
  enforce_attention_fields` aggregates it from the most-recent hot session.
  `bandFor`: `needs_you` fires on `awaiting_user` (outranks `done_unread` and the
  old blocker-text regex; live `running` still wins). The strongest cockpit band
  now has a first-class signal instead of a brittle regex.
- **B — `next_step`** (field): Layer-1 emits one concrete next action; shown on
  the card as「▸ 下一步」and used by ranking. (The richer *suggestions* feature
  is below.)
- **C — progress mechanical**: `enforce_attention_fields` sets
  `progress := most-recent hot session's 当前状态` (no more AI re-narration → no
  drift). The serve real-time overlay (`_freshen_progress_from_summaries`) also
  overlays `progress`/`next_step`/`awaiting_user` when a summary is newer than
  the dashboard, so these are ~real-time, not stale-until-next-classify.
- **D — bands from signals**: `bandFor` order = needs_you(live) → running(live)
  → awaiting_user → done_unread(live) → (idle keeps an open session out of
  `done`) → status done/paused → idle. Live telemetry and explicit signals win
  over stale AI status. (Fixes: a `running`/`idle`-open card no longer collapses
  into 已完成 just because classify marked `status:done`.)

Also: a Layer-1 **done-guard** (`summarize._guard_done_status`) — mechanical
downgrade `done→active` when `下一步` is non-empty (a concrete next step ⇒ not
done), independent of model compliance.

## Design — B: AI next-message suggestions (global view, multi-choice)

Claude Code's built-in "next" gives one suggestion with no cross-session view.
The cockpit has the global view, so:

`POST /api/suggest {sid}` builds a prompt from **(a)** a compact snapshot of
OTHER active cards (name / progress / awaiting_user — the global perspective)
**+ (b)** this session's card + recent transcript, and asks a headless
`claude -p --no-session-persistence` (no jsonl → no recursion; no tools) for
**2–3 distinct, ready-to-send next messages** (JSON array, with fence/numbered
fallbacks). Cockpit「建议下一句 ▸」→ shows the options → click one → inject via
`/api/send` if a live pane exists, else copy to clipboard.

## Embedded-terminal hardening (DD-018 follow-ups, shipped here)

The in-card ttyd terminal is the cockpit's handoff落点; making it usable:
- **Persistence**: ttyd SIGHUPs its child the instant the WS drops (verified).
  So "close" = hide the iframe (keep the WS alive) → claude keeps running, reopen
  is instant, no re-resume. Multiple terminals are independent persistent iframes
  in a stack (switching toggles visibility; never tears down a sibling).
- **resume cwd**: `claude --resume` is project-scoped by cwd; `session_locations`
  stores the *latest* cwd (a subdir → "No conversation found"). Fix:
  `_resume_cwd_for` reads the authoritative cwd from the session's own jsonl.
- **Single-driver gate**: any live state (running/idle/done_unread/needs_you)
  → **warn + confirm**, not a hard block (informed consent: two `claude --resume`
  on one jsonl can conflict, but it's the user's call). `ended`/absent → open
  freely. `/api/send` checks `focus-pane-id` rc so an injected message can't land
  in the wrong (reused) pane.

## Verification

Unit tests: attention aggregation (6), `bandFor` live-override + awaiting_user
(10+4), done-guard (4), suggestion parser (3), gate (warn-not-block) — all pass.
One real Haiku `/api/suggest` produced 3 relevant, distinct, globally-aware
messages. resume-cwd fix reproduced broken→fixed end-to-end on the real session.

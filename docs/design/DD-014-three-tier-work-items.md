# DD-014: Three-tier work items (thread / card / chip)

**Status**: Accepted (V1) · Deferred (V2)
**Author**: Claude (with user)
**Date**: 2026-05-28

## Problem

Today every initiative is rendered as one full-size card. Result:

- A 4-turn one-off bug lookup eats the same visual real estate as a
  multi-week refactor that spans 8 sessions.
- The dashboard reads as a flat slab of cards with no hierarchy. Users
  literally see "I have N things in progress" instead of "I have 3
  big arcs running and a pile of small lookups."
- Long-running work that legitimately deserves emphasis gets drowned
  in incidental small work.

User framing (2026-05-27):
> *"应该把工作卡片分为大项和小项... 大项就是长时间的大工作,可以用目前
> 这种卡片展示... 小项可以用一个小标签的形式展示."*

And on hierarchy:
> *"thread / project 归属比大小重要... 一个 thread 内大项展开成卡片、小项
> 缩成 chip."*

## Decision (V1 — this DD)

Add **three visual tiers** for initiatives. Each initiative gets a new
`level` field with one of:

| level | shape | typical signal |
|---|---|---|
| `thread` | poker-stack header that hover-fans into a deck | multi-session arc, ≥ 3 sessions OR ≥ 8 tasks OR ≥ 200 user turns |
| `card` | the existing card | single substantive work unit |
| `chip` | compact tag, several per row | tiny: 1 session, ≤ 5 user turns, ≤ 1 task, < 15 minutes |

Both axes (the level **and** which thread an initiative belongs to)
are owned by Layer 2 AI. The post-process layer enforces stability;
see below.

### Schema (v3)

```json
{
  "schema_version": 3,
  "workspaces": [
    {
      "name": "...",
      "cwd": "...",
      "initiatives": [
        {
          "id": "...",
          "name": "...",
          "status": "active|paused|done|archived",
          "level": "thread|card|chip",            // NEW
          "parent_thread_id": "<id>" | null,       // NEW; only set when this initiative belongs to a thread
          "level_set_at": "2026-05-28T...Z",       // NEW; written by classify.py when level promotes
          ...existing fields...
        }
      ]
    }
  ]
}
```

`parent_thread_id` is null for free-floating cards/chips. A `thread`-
level initiative never has `parent_thread_id` (threads are themselves
the top level). Cards/chips can optionally hang off a thread.

### Promotion rules (Layer 2 prompt)

Layer 2 looks at each initiative and proposes a level using the
heuristics in the table above. Detailed thresholds are tuneable; the
prompt's job is to lean on them but not slavishly so — a 1-session
investigation that produced 5 commits and 10 tasks should still be a
card, not a chip.

### Stability rules (classify.py post-process)

The user's reported pain is **visual flicker** ("cards keep changing").
Stability is non-negotiable. Three mechanical guards:

1. **PRIOR anchoring** — a level from PRIOR is the floor; AI cannot
   lower it. Once `card`, never goes back to `chip` (without user
   action). Once `thread`, stays a thread.

2. **Promotion cooldown** — a newly-discovered initiative is born as
   `chip` regardless of AI's suggestion, **for the first 1 classify
   run**. Only on the second run, when there's PRIOR evidence, can AI
   promote it. This kills the "fanfare for what turned out to be a
   one-off" failure mode.

3. **User-initiated demotion only** — the only path from
   thread → card or card → chip is the user clicking a demote action
   in the UI (writes to `user_overrides.json`). AI has no say in
   demotion.

These three combine to give the user a one-way ratchet: levels can
only go up automatically, never down. The worst case is "this small
chip should have been a card, but I have to wait one more run" — a
soft penalty. The best case is "I never see a card flicker back to a
chip" — solved.

### Visual design (render-html.py)

Each workspace section is now subdivided into three zones, top to bottom:

1. **Thread zone** (`section.threads`) — horizontal row of stacked
   "poker decks." Each deck shows the thread title, status dot, count
   of member cards/chips, and a hover-expand animation that fans the
   member cards out for inspection.

2. **Card zone** (`section.cards`) — the existing grid of cards. Cards
   that belong to a thread are also displayed inside their thread's
   deck; the standalone card zone is for cards with
   `parent_thread_id: null`.

3. **Chip zone** (`section.chips`) — a flow-wrap row of compact chips.
   Each chip is a single line: status dot, name (truncated), task
   count badge, last-activity age. Clicking opens the existing modal.

The chip zone is intentionally information-dense — the visual
breathing room comes from the **fact** that less-important work has a
tighter footprint, not from spacing each chip out.

### Migration (v2 → v3)

`classify.py` on its first v3 run treats any existing initiative without
a `level` field as `level: "card"`, `parent_thread_id: null`. The
"promotion cooldown" then kicks in normally on the *next* run, so a
chip-sized item won't instantly stay a card forever — but for one round
the existing dashboard is byte-stable.

## Deferred (V2 — future DD)

The original design discussion also proposed **intra-session
segmentation**: a single Claude Code session that contains two
unrelated pieces of work should produce two cards, not one. This
requires:

- Layer 1 (`summarize.py` + `prompts/summarize-session.md`) to emit a
  `segments:` block enumerating turn ranges and their work units.
- Layer 2 to consume segments as the unit of grouping, not whole
  sessions. `initiative.sessions: [...]` becomes
  `initiative.segments: [{sid, turn_start, turn_end}, ...]`.
- A new stable-ID scheme for segments (today, `session_id` is the
  unit of identity).
- Migration of every existing initiative from session-based to
  segment-based references.

This is a multi-day rework with high blast radius (every cold
initiative's session refs would need to be remapped). The user's
existing data is already 86% single-session-per-initiative
(observed: 18 out of 21 active initiatives have exactly one session),
so V1 already addresses the dominant case. V2 is filed as future
work; not in V1's scope.

## Trade-offs and alternatives considered

**Why not a fourth tier (e.g., "epic" above thread)?**
Three tiers already cover small / medium / large. A fourth would
require a fifth grouping for the user to manage (workspace, epic,
thread, card, chip = too much).

**Why AI-derived level, not pure mechanical?**
Initial thinking was "compute level from session count + turn count +
duration." But pure mechanical would mis-classify a 2-turn session
that produced a major PR as a chip. The heuristics are advisory; AI
arbitrates. Post-process enforces stability, not correctness.

**Why one-way promotion ratchet?**
Visual flicker is the dominant pain. A user upset that a chip
should-have-been-a-card waits 1 run. A user upset that their cards
keep shuffling has lost trust in the tool. The asymmetry favors
trust-preserving stability.

## Invariants (enforced by post-process or prompt)

1. `level ∈ {thread, card, chip}` — any other value is a bug.
2. `parent_thread_id` if set must point to a `level: thread`
   initiative in the same workspace (`classify.py` clears dangling
   refs).
3. AI cannot lower a level relative to PRIOR. (`enforce_level_monotone`
   restores PRIOR level if AI tried to demote.)
4. A newly-discovered initiative has `level: chip` on its first round
   regardless of AI output. (`apply_promotion_cooldown` overrides.)
5. `level_set_at` advances only on actual level changes; cold
   initiatives keep their PRIOR `level_set_at`.

## References

- DD-011 — task model (`pending|done|cancelled`), the precedent for
  "AI is advisory, mechanical post-process is authoritative"
- DD-012 — task wording stability
- DD-013 — status is mechanically derived, not a sticky flag
- The conversation that produced this DD —
  `initiative=claude-stray-ui-segmentation-design` (2026-05-27)

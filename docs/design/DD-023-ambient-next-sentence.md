# DD-023: Ambient next-sentence suggestion

**Status**: Proposed (design; button already removed)
**Author**: Claude (with user)
**Date**: 2026-06-06
**Predecessors**: DD-020 (per-session attention model; `/api/suggest`), DD-021 (resources)

## Why (the user's words)

> 下一句话按钮移除，我希望的下一句话功能是悬浮在 webterminal 右侧，不需要用户点击，
> 而是在后台合适的时机根据用户当前的进展生成。

The click-to-get-a-suggestion button (`建议下一句 ▸`, DD-020 B) is the wrong
interaction: it makes the user *ask*. The cockpit's whole point is to reduce the cost
of re-engaging with a session — so the suggested next message should be **ambient**:
already there when you look, generated quietly in the background at the right moment.

The button is removed (commit 9a34ac2). The `/api/suggest` machinery
(`suggestReplies`, `_handle_suggest`, `_claude_suggest`) stays as the generator.

## Proposal

### When to generate (the "合适的时机")

Generate a suggestion **only when the session is waiting on the human and the
suggestion would be fresh** — never mid-typing, never on every event:

- Trigger on the live-state transition into **idle / needs_you / awaiting_user** (the
  agent finished a turn and is waiting). That's exactly when "what do I say next?" is
  the question.
- **Debounce**: wait N seconds of quiet after the transition (the user may already be
  typing). Cancel if the session goes active again.
- **One per turn**: key the cached suggestion by the session's latest jsonl leaf uuid;
  don't regenerate until the conversation advances. Cheap and avoids churn.
- **Cost ceiling**: only for sessions the user is plausibly looking at (e.g. the open
  terminal's sid, and/or the top needs-you cards), not all sessions. Hard cap per
  minute. Reuse the per-session-AI budget thinking from DD-020.

### Where it floats (open — real-estate conflict)

The user said "webterminal 右侧", but DD-021 put **resources** on the right. Two
candidates; pick after seeing it live:

- **Below the terminal** (a slim bar across the bottom of the `.termbox`): least
  conflict, always visible, doesn't fight the resource panel. *Leaning this way.*
- **Left gutter** (DD-021 originally reserved the left gutter for "next sentence"):
  symmetric with resources on the right, but invisible on laptops (no gutter).
- **Top of the terminal** (under the tab bar): compact, always visible.

Whatever the spot: a subtle floating card — `💬 建议：<one line>` — with **inject**
(`/api/send` → the live pane) and **copy** affordances, and a dismiss. If `/api/send`
has no live pane, fall back to copy (existing behavior).

### Behavior

- Appears quietly when ready (fade in); no spinner stealing attention.
- Stale-guards: if the user typed something or the turn advanced, drop the suggestion.
- Multiple suggestions (DD-020 produced a few): show the top one inline, the rest on
  hover/expand — but keep it lightweight.
- Respect the global pause (DD lifecycle): if the plugin's AI is paused, don't generate.

## Touch points

- `serve.py`: a background suggestion generator keyed off live-state transitions
  (the hooks already write `cache/live/<sid>.json`); cache suggestions under
  `cache/suggest/<sid>.json` keyed by leaf uuid; expose via `/api/data` or SSE so the
  cockpit shows them without polling. Reuse `_claude_suggest`.
- `cockpit.html`: render the ambient suggestion near the terminal; inject/copy/dismiss;
  drop the last bits of the old button path.
- Remove now-unused: the `建议下一句` button is gone; keep `suggestReplies`/`/api/suggest`
  as the generator (now invoked by the trigger, not a click) or fold into the bg path.

## Open questions

- **Placement** (above) — needs a live look.
- **Trigger precision**: how to avoid generating while the user is mid-thought but
  hasn't typed yet? The debounce + "regenerate only on new leaf" should cover most.
- **Generate proactively for non-open sessions?** Probably only for the few top
  needs-you cards, to keep cost sane.
- **Intrusiveness**: ambient must not nag. A single dismissible line, no animation loop.

## Rough plan

1. Background generator on live→idle/needs_you transition, cached per leaf uuid, capped.
2. Ambient render near the terminal (start with the bottom bar), inject/copy/dismiss.
3. Tune triggers + placement after using it.

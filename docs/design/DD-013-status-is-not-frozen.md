# DD-013: Initiative.status is a derived label, not a freeze flag

**Status**: Accepted
**Author**: Claude (with user)
**Date**: 2026-05-25

## Problem

Cards on the dashboard whose `status: done` was set in some past Layer 2
run **stop updating** when their underlying Claude Code session is
resumed and continued.

Concretely, on the day this was filed:

- `hsf-workspace-initialization` — `init.status = done`,
  `init.last_activity_at = 2026-05-21` (4 days ago), but the underlying
  session's `last_activity_at = 2026-05-25T07:47` (this morning) and
  `status_guess = paused`. Today's work is invisible on the card.
- `claude-code-stop-hook-bell` — `init.status = done`, latest session
  `status_guess = paused`, last activity 30 minutes ago. Same desync.
- `stray-artifacts-classification-bug` — the card that represents this
  very repo's recent work (DD-012, consolidate button, archive bucket
  fix, artifact monotonicity) — `init.status = done`. The dashboard
  has not recorded the day's actual activity.

The user's framing: *"已完成的卡片对应的会话会随后继续更新要做的事情或者
任务, 不应该出现这种不更新的情况, 最典型的例子是 claude-stray 下我们
最新的工作都没有被 dashboard 记录下来."*

## Root cause

There is **no code-level rule** that says "skip done cards." The
mechanical post-processors (`aggregate_tasks`, `aggregate_artifacts`)
run for any initiative with PRIOR data or contributing hot sessions,
regardless of status. So the data layer is correct.

The breakage is at the **AI layer**. `prompts/classify-cross-session.md`
§7 instructs Layer 2 to read each hot session's `status_guess` and
re-derive `init.status` ("most-recent session says done → done; else
paused if any paused/abandoned and no active; else active"). But this
is a *prompt instruction*, not a *mechanical guarantee*. In practice
the AI carries `PRIOR.status = done` forward out of caution — it sees
"this card was marked done last round" and treats that as a stronger
signal than the new session's `status_guess`.

The result: `status: done` accumulates **stickiness it was never
supposed to have**. Once a card has been done at any point, it tends
to stay done even when work obviously continues.

This is the third instance of the same anti-pattern:
- DD-011 / artifact monotonicity (commit `c5452a0`): AI was dropping
  artifacts. Fix: mechanical `aggregate_artifacts` post-AI.
- DD-012 (commit `679d366`): AI was rewording tasks. Fix: PRIOR
  injection into Layer 1 + mechanical slug dedup at Layer 2.
- DD-013 (this doc): AI is locking in stale `done`. Fix: mechanical
  status enforcement post-AI.

The unifying principle is *"AI is advisory; the deterministic
post-processor is authoritative for invariants the user cares about."*

## Invariant

> `init.status` is a **derived label**: it must always be the
> deterministic function of the contributing hot sessions'
> `status_guess` values, computed by the rule in §7. It is never a
> sticky flag that survives session resumption.
>
> Specifically: if any session in `init.sessions` is hot in the
> current Layer 2 batch, `init.status` is recomputed from that hot
> set's `status_guess` values — never inherited verbatim from PRIOR.

Cold initiatives (no hot session contributing) keep using §5's status
decay rule (`paused` after 3 days, `archived` after 14 days, "stay
done" if already done). That part is fine — it operates on
PRIOR.last_activity_at, not on stickiness.

## Decision

Add `enforce_hot_initiative_status(new_mm, hot_summaries)` to
`bin/classify.py`. Pseudocode:

```python
for init in every initiative in new_mm:
    contributing = [(sid, status_guess, last_activity_at)
                    for sid in init.sessions
                    if sid in hot_summaries]
    if not contributing:
        continue   # cold; §5 already handled it

    most_recent_sg = sorted(contributing, key=last_activity_at)[-1].status_guess
    all_statuses    = {c.status_guess for c in contributing}

    if most_recent_sg == "done":
        new_status = "done"
    elif "paused" in all_statuses or "abandoned" in all_statuses:
        new_status = "active" if "active" in all_statuses else "paused"
    else:
        new_status = "active"

    init.status = new_status   # unconditional — AI's output is overwritten
```

Wire it into `main()` after `enforce_cold_and_terminal_monotone` (so
the cold rule has already restored PRIOR for cold inits) and before
`aggregate_tasks`.

Update `prompts/classify-cross-session.md` §7 with a note that the
post-process enforces this — same shape as the §7a artifact-aggregation
warning.

## Why not the alternatives

- **Just strengthen the prompt** ("AI: please don't carry forward
  PRIOR.status=done"). Already tried in spirit — §7 *is* the rule.
  It doesn't hold under load. Prompt-only is the same failure mode
  that DD-011 and DD-012 already faced.
- **Add a freshness signal** (e.g. force re-evaluation when
  `session.last_activity_at > PRIOR.last_activity_at`). Heuristic and
  fragile — what threshold? Mechanical recomputation from
  `status_guess` is the right primitive; freshness is implicit.
- **Surface a "is desynced" warning in the UI**. Treats the symptom
  rather than the cause. The user wants the card to reflect reality,
  not a warning that it doesn't.

## Trade-offs accepted

- **AI's status output for hot inits becomes purely advisory.** A
  contributing session's `status_guess` is sovereign. If Layer 1
  consistently misreads a session (says "done" when the user is
  actively working), the card flips wrongly. Mitigation: Layer 1's
  `status_guess` rules in `prompts/summarize-session.md` Rule 2 are
  already conservative ("`done`: user explicitly closed it — 'ship
  it', 'merged', '完成了', '搞定'"); upgrading Layer 1's accuracy is
  always available as a separate change without re-doing this rule.
- **Cards can ping-pong** between active/paused if the user toggles a
  session mid-work. Acceptable — that *is* what's happening. Better
  than the silent freeze.
- **Manual "mark done" from the UI doesn't exist today**, so there's
  no user-locked-done to defeat. If we ever add such a button, it
  belongs in `user_overrides.json` (sticky on the user-side), not in
  `init.status`.

## Migration

No data migration needed. The next `stray --refresh` after this
change lands will re-evaluate every currently-stuck "done" card and
flip it to the correct status based on the latest contributing hot
session. Already-correct done cards (where the most recent session
is also `done`) stay `done`.

## Test plan

1. Run `python3 bin/classify.py` once. Expect DIFF output showing
   status changes for at least the cards named above
   (`hsf-workspace-initialization`,
   `claude-code-stop-hook-bell`,
   `stray-artifacts-classification-bug`).
2. Inspect dashboard.json after the run — those cards should have
   `status` matching their most-recent session's `status_guess`.
3. Re-run; status should stay stable (idempotent).

## Relationship to prior DDs

- DD-005 (lifecycle pause): orthogonal — that's a global pause of the
  whole pipeline, not a per-card status.
- DD-011 (task model): unchanged. Terminal task statuses are still
  monotone (`done` and `cancelled` don't go back to `pending`).
  DD-013 is about *initiative* status, not task status.
- DD-012 (task wording stability): same pattern (AI advisory,
  mechanical authority), different field.

## What this DD does NOT do

- Does not recompute `init.last_activity_at` (some cards have stale
  last_activity_at; that's a related but separate gap, left for a
  future change).
- Does not add a UI affordance to manually mark a card done.
- Does not change Layer 1's `status_guess` rules.

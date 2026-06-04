# DD-019: Intra-session segmentation — seal the past

**Status**: Accepted (Layer-1 in-window sealing) · in-window-only limitation noted
**Author**: Claude (with user)
**Date**: 2026-06-03
**Predecessors**: DD-016 (identity; this was its deferred non-goal), DD-013
(mechanical status), DD-015 (cockpit)

## Problem

A long Claude Code session pivots topic over time. Observed live: session
`3be97e52` finished "linkify error-message URL" work (shipped — MR 27752189,
branch `feat/authz-error-linkify`) then pivoted to "HSFOps 超管/ACL" work. The
pipeline produces ONE summary per session and binds the whole session to ONE
card, so the active 超管 work was invisible — pinned under the older, `done`
linkify card. The user wants one long session to surface as MULTIPLE cards.

DD-016 explicitly listed this ("one session → multiple initiatives over time")
as a **deferred non-goal**. This DD promotes it to a real, narrow design.

## Key insight

A session needs at most ONE *live* card (its current focus). Earlier completed
sub-work is **frozen** and needs no live binding / focus / dedup participation.
So we do NOT change the identity atom (still `session_id`). Instead we **seal**
terminal earlier sub-work into a separate card with **empty `sessions[]`**.

Empty `sessions[]` makes the sealed card automatically invisible to every
session-keyed pass — `dedup_by_session`, the cockpit live OR-loop, focus/send,
`apply_initiative_links`, status derivation — so the blast radius is ~2 new
functions instead of the ~15 a `(sid, segment)` atom would touch.

(Rejected heavier model: atom = `(sid, segNo)` with `sid#segN` keys + helpers +
"latest segment is live". Touches all session-keyed consumers; the one capability
it adds — two *live* cards for one session — is physically impossible since live
status is session-level. No forcing case → not worth it.)

## Design

1. **Layer 1** (`summarize`, Rule 13): conservatively detect a sealed boundary —
   an earlier sub-effort reached a **terminal** state (shipped/merged/abandoned,
   evidenced by a concrete artifact) AND the session pivoted to a distinctly
   different current focus. Emit it under a new `sealed_segments` frontmatter
   block (`seg_id`, `title`, `status` done|abandoned, `summary`, `sealed_at`,
   `artifacts`, `tasks`); move those artifacts/tasks out of the top-level lists.
   Default = emit nothing. Re-emit prior sealed segments **verbatim** (fed back
   via `<prior_sealed_segments>`) so they don't flicker across runs.
2. **Layer 2** (`classify.mint_sealed_initiatives`, after `aggregate_artifacts`,
   before `dedup_by_session`): mint a frozen card per sealed segment —
   `id = sealed::<artifact_key>` (stable across runs), `sessions: []`,
   `origin_session: <sid>`, `sealed: true`, frozen status, `level: card`. Strip
   the sealed artifacts/tasks from the live card bound to that sid (clean split).
   `slim_prior` hides sealed cards from the AI (mechanically owned, never
   re-clustered). Carry-forward + cold-rule keep them frozen across runs.
3. **Render** (cockpit / serve): sealed cards land in the collapsed `done` band
   (`bandFor` guard); their "进入会话/查看对话" resolve `origin_session`; a
   「会话内沉淀」marker; merge hidden.

Schema additions to `dashboard.json` initiative: `sealed`, `origin_session`,
`seg_id`, `sealed_at` (all optional, schema_version stays 3).

## Limitation (measured)

Layer-1 sealing only catches a pivot **within the last `MAX_TURNS` (12) turns**.
For `3be97e52` the linkify→超管 pivot had already scrolled out (31 user turns),
so it did **not** auto-seal — but re-summarize still surfaced the active work
(the single card flipped active + kept the linkify artifact). To split
already-scrolled pivots would need a larger turn window (costlier) or a Layer-2
"seal from summary evolution" detector. Deferred.

## Verification

Pure-function unit tests (parser / mint / strip / idempotency / zero-blast-radius
across dedup·links·status), cockpit render assertions, `/api/data` serving — all
zero-AI. One real summarize+classify confirmed the pipeline runs clean on real
data (and confirmed the conservatism bar: the model correctly did NOT over-seal).

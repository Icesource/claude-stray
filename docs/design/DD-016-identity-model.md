# DD-016: Stable initiative identity — session_id atom + persisted membership, AI as labeler

**Status**: **Superseded by DD-033** (2026-06-11). The north star (2026-06-04,
card = session) made identity trivial — `card::<session_id>` — so the whole
drift-fighting apparatus here (registry, durable merges, id stabilization)
became unnecessary and was removed. `apply_initiative_links` /
`initiative_links.json` / the merge endpoint are gone; this doc is kept as
the historical record of why identity was hard when cards were AI-clustered.
**Author**: Claude (with user)
**Date**: 2026-06-01
**Predecessors**: DD-002 (pipeline), DD-011/012/013 (AI advisory, mechanical
authority), DD-014 (levels/threads), DD-015 (cockpit; this DD was sketched
in its *Identity model* section)

## Problem

Initiative identity is an English slug the **AI mints fresh on every
classify run** (`claude-code-version-upgrade`, etc.). Stability rests
entirely on the AI choosing to reuse the prior slug. It often doesn't —
and ~1500 lines of post-process in `classify.py` exist to fight the
fallout:

- **Flicker / rename**: `name`/`summary`/`progress` and sometimes the
  slug change between runs → "the same card looks different every
  refresh".
- **Silent loss**: observed 2026-05-29, 27 initiatives → 8 across three
  runs as the AI dropped entries (drove `enforce_carry_forward_initiatives`).
- **Resurrection**: a deleted/archived card whose sessions are still hot
  gets **re-clustered under a NEW slug**, escaping the id-keyed tombstone.
  Confirmed live: `claude-code-version-upgrade` + `zellij-session-recovery`
  sit in `deleted_ids.json` yet reappear in `dashboard.json`.

Root cause: **an LLM is asked to re-derive a stateful, identity-bearing
model from scratch each run.** The clamps treat symptoms; the disease is
AI ownership of identity.

User direction (2026-06-01): make the id strategy a first-class concern
of the cockpit work. Earlier shorthand ("anchor id to session_id /
artifact") was corrected on two counts: an initiative spans *many*
sessions (so id ≠ session_id), and artifacts only appear mid-session (so
they can't anchor at birth). This DD records the corrected model.

## Goals / non-goals

**Goals**
- Identity that is **stable across runs** without relying on AI goodwill.
- Native **many-sessions-per-initiative**.
- **Deletion/archive that sticks** even while sessions stay hot.
- Keep AI doing the work only it can (clustering judgment, naming,
  summarizing, status) — *more* useful, not less.

**Non-goals**
- Intra-session segmentation (one session → multiple initiatives over
  time) — deferred (DD-014 V2).
- Re-litigating tasks/artifacts/status models (DD-011/012/013 stand).
- Auto-merging without a human-visible trail.

## Proposal — the model

```
session_id            ← ATOM. Immutable, exists at session birth, never changes.
   │  many-to-one, PERSISTED membership
   ▼
initiative            ← persisted entity in a registry (code-owned)
   - id            : minted ONCE, stored, frozen. AI cannot re-mint.
   - members[]     : set of session_ids  ← "many sessions, one initiative" lives here
   - name/summary/ : AI-owned LABELS — may change freely each run (don't affect identity)
     progress/status
   - artifacts[]   : accrue over time → ranking + membership-merge hint, NOT the key
   - tier/priority : user-/AI-set (DD-015), persisted
```

**Registry**: a new `cache/initiatives.json` — `{version, by_id: {id:
{id, members, created_at, tier, priority, ...}}}`. Code owns it; it is
the source of truth for *which work units exist and what sessions belong
to them*. dashboard.json becomes a *rendering* of registry × summaries.

**AI's role flips from owner to assigner/labeler.** Each run the AI is
given the registry (existing ids + their member session_ids + current
names) and the hot session summaries, and outputs:
1. an **assignment** per hot session: an existing `id` from the fixed
   list, or `"new"` (+ a proposed slug + name);
2. **labels** (name/summary/progress/status) — free to change.

It never mints or reshuffles ids. The deterministic post-process then:
- **new** cluster → accept the AI's proposed slug as the id *once*,
  dedupe-guard it, persist to the registry (now frozen).
- **existing** → append the session to that initiative's `members`
  (sticky: an existing member is never silently moved).
- **merge/split** → only via an explicit, logged operation (AI may
  *propose* one; surfaced for the user, not applied silently).

**Tombstones key on member session_ids, not just the id.** On
delete/archive, record the initiative's current `members` as
time-windowed session tombstones (archive already does this for its
sessions — `archived_session_ids_on_disk`; deletion must too). A
tombstoned session can't seed a fresh cluster while hot → **resurrection
is structurally impossible**, not just id-blacklisted.

**Cockpit grouping (DD-015) rides on stable keys:** project/line =
workspace `cwd` (a stable directory key); card = registry initiative id.
Neither flickers.

## Changes by component

| File | Change |
|---|---|
| `cache/initiatives.json` (new) | the registry: frozen ids + session membership + tier/priority |
| `bin/classify.py` | feed the registry to the prompt; replace "AI owns the mindmap" with: AI assigns sessions → frozen ids / labels; post-process reconciles against the registry (mint-once, sticky membership, guarded merge/split). `strip_deleted_from_prior` / `enforce_carry_forward_initiatives` become registry operations. |
| `prompts/classify-cross-session.md` | reframe the task as **assign + label** against a fixed id list, not "regenerate the taxonomy". |
| `bin/serve.py` `_handle_save` | on delete/archive, persist the initiative's member session_ids as tombstones (extend `deleted_ids.json` or a new `session_tombstones.json`), mirroring archive. |
| `deleted_ids.json` / archive | unified under one "suppressed work unit (by session set)" primitive (collapses the DD-015-diagnosed 5 overlapping suppression mechanisms). |

## Migration

- **First run builds the registry from current `dashboard.json`**: each
  existing initiative's `id` + its `sessions[]` become a registry entry;
  ids freeze from then on. No data loss — it's a snapshot of today's state.
- `deleted_ids.json` entries seed tombstones; where the deleted
  initiative's member sessions are recoverable (from prior dashboard.json
  backups / session_locations), extend them to session-level tombstones.
- The change is behind the pipeline; the dashboard schema is unchanged
  (registry is an internal source-of-truth; dashboard.json stays a render).

## Cost / risk

- **Mis-assignment**: AI may put a session under the wrong existing id.
  Far less harmful than today's flicker, and user-correctable (split).
  Mitigate with the artifact merge-hint (a session citing `MR!1234`
  already tied to X → strong signal for X).
- **Intra-session drift** (a long session changing topic) is out of
  scope; today's behavior (whole session in one initiative) is kept.
- **Registry corruption**: code-owned single file → write atomically,
  keep a `.bak`, validate on load (same discipline as DD-010's archive
  shrink-guard).
- Net effect should *delete* much of the reactive clamp code, not add to
  it — the post-process becomes "reconcile to registry", a smaller
  invariant than "guess what the AI dropped".

## Alternatives considered

- **Keep AI-minted ids + more clamps** (status quo). Rejected — the clamp
  pile only grows and resurrection still slips through (live proof).
- **id = content hash of the session set**. Rejected — membership changes
  as sessions join, so the hash (and id) would churn; defeats stability.
- **id = first session_id**. Rejected — conflates the atom with the
  aggregate; breaks when the founding session is archived but the work
  continues in later sessions.
- **Pure deterministic clustering (no AI)**. Rejected — clustering
  sessions into *meaningful* work units is exactly the judgment AI is
  good at; we keep AI for that, just deny it the id pen.

## References

- DD-015 *Identity model (corrected after review)* — the sketch this
  promotes; and *Prototype outcomes* (stable cwd key for project lines).
- DD-013 — "AI is advisory; the mechanical post-process is authoritative"
  (this DD applies that principle to identity itself).
- The 2026-06-01 diagnosis + cockpit-design conversation.

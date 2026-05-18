# DD-011: Final task model — tri-state status, drop archive

**Status**: Accepted
**Author**: Claude (with user)
**Date**: 2026-05-18

## Problem

The task model has been patched four times in three weeks: DD-008
introduced a slug-keyed cap + archive directory; DD-009 added
session-bound ownership and a completion inference path; DD-010 (after
the 2026-05-18 data-loss incident) reversed DD-009's eviction behavior
and made tasks AI-additive-only. The end result *works* but carries a
lot of dead weight:

- Tasks live in two places — `mindmap.json` and `cache/task_archive/<id>.json`
  — and the merge logic between them is 200 lines.
- Each task entry has 11 possible fields, only 3 of which are
  load-bearing (`id`, `title`, `done`). The rest (`first_seen_at`,
  `last_seen_at`, `done_at`, `done_evidence`, `sessions`, `evicted_at`,
  `eviction_reason`, `tasks_archived_count`) accreted as scar tissue
  from the eviction/over-cap path that DD-010 partially nullified.
- AI can mark a task done with evidence but **cannot** cancel a task
  that turned out to be irrelevant. The user's workaround is the 🗑️
  trash icon, which puts the task on the permanent `deleted_tasks`
  blacklist — too heavy for "this task got merged into another one"
  or "user changed their mind mid-session."
- The UI has a separate "+N archived" expander that adds visual
  complexity for a feature (overflow past 20 tasks) that almost
  never triggers in normal use.

Quote from user, 2026-05-18: *"自动熔断不着急, 我们先做 task 模型设计,
彻底的优化 task 模型, 让其变得简洁、优秀、优雅."*

## Goals / non-goals

**Goals**

- One storage location: `mindmap.json` only. Delete `cache/task_archive/`.
- One state field with three values, instead of `done: bool + archived
  flag + evicted_reason + ...`: `status: "pending" | "done" | "cancelled"`.
- AI gets the power to cancel (terminal, with evidence). User retains
  full control (toggle done, toggle cancelled, delete entirely).
- No visible task cap. Tasks are cheap and the UI can fold completed
  ones inline.
- Net reduction: ~400 lines of code, 1 directory, 1 API endpoint, 6
  redundant fields gone.

**Non-goals**

- Changing how the user deletes a task (still 🗑️ → `deleted_tasks`).
- Changing the slug-derivation algorithm (`slugify_task_title`
  stays — it's how AI continuations match PRIOR).
- Adding new status values beyond the three (no "blocked", "deferred",
  etc. — those go in `blockers[]` and `progress`).

## Proposal

### Schema

```json
{
  "id": "stable-slug",          // from slugify_task_title()
  "title": "...",                // ≤ 80 chars, in output_lang
  "status": "pending" | "done" | "cancelled",
  "evidence": "...",             // optional, ≤ 80 chars
                                 // required when AI flips pending→{done,cancelled}
                                 // free-form when user toggles
  "terminal_at": "ISO-8601"      // optional, set when status becomes non-pending
}
```

Five fields, all optional except `id`+`title`+`status`. Compared to
DD-010's task record:

| Field | DD-010 | DD-011 |
|---|---|---|
| `id` | yes | yes |
| `title` | yes | yes |
| `done` (bool) | yes | replaced by `status` |
| `status` (enum) | — | yes |
| `done_evidence` | yes | renamed → `evidence` |
| `done_at` | yes | renamed → `terminal_at` |
| `first_seen_at` | yes | **dropped** (mindmap.generated_at covers it) |
| `last_seen_at` | yes | **dropped** |
| `sessions[]` | yes | **dropped** (audit-trail noise; UI never showed it) |
| `evicted_at` | yes | **dropped** (no eviction) |
| `eviction_reason` | yes | **dropped** |

### Reachability table

| From → To | AI may do it? | User may do it? |
|---|---|---|
| `pending → done` | ✅ with `evidence` | ✅ checkbox |
| `pending → cancelled` | ✅ with `evidence` | ✅ menu |
| `done → anything` | ❌ (terminal for AI) | ✅ via task_toggles |
| `cancelled → anything` | ❌ (terminal for AI) | ✅ via task_toggles |
| delete entirely | ❌ | ✅ 🗑️ → `deleted_tasks` |

**Done-and-cancelled are terminal for AI.** This is the equivalent of
DD-010's done-monotone rule, extended to cover cancellation: once AI
calls it terminal, only the user can revive it. (Prevents thrash if AI
changes its mind round-to-round.)

User toggles cross all boundaries — same mechanism as today
(`user_overrides.json` → `task_toggles[]` with `status` instead of
`done`).

### AI behavior

In `classify-cross-session.md`:

- **§7c (tasks aggregation)** unchanged in spirit: still
  AI-additive-only. AI emits `tasks[] ≥ PRIOR.tasks[]` count. The
  pre-flight check still rejects shrink attempts.
- **§7d (terminal-state inference)** is broadened: AI may flip
  `pending → done` (with evidence of completion) OR
  `pending → cancelled` (with evidence of "no longer relevant" / "merged
  into X" / "user changed direction in the last turn"). Same evidence
  bar in both directions — concrete quote/paraphrase from a hot
  summary, ≤ 80 chars.
- **Merge guidance**: when two PRIOR tasks describe semantically the
  same work, AI may mark one as `cancelled` with
  `evidence: "merged into <other task title>"`. The "other" task is
  kept in `pending`/`done` as normal. (No data structure required —
  just a textual reference in `evidence`.)

In `summarize-session.md` Rule 12: `tasks[]` frontmatter switches from
`done: bool` to `status: pending|done|cancelled`. Layer 1 may set
`cancelled` if the user explicitly aborts a task mid-session
("forget about that one"), with a one-line `evidence` field. Layer 2
treats Layer 1 task statuses the same way it treats AI continuations.

### Storage

`cache/mindmap.json` is the only source of truth. There is no
secondary file. Migration deletes `cache/task_archive/`.

Per-initiative tasks list is unordered in storage (JSON array order
is presentation, not semantic). UI sorts: pending first (by insertion
order from PRIOR), then done (most recent `terminal_at` first), then
cancelled (most recent `terminal_at` first).

### UI

The current "+N archived tasks" expander is removed. Instead:

- A single fold/unfold control per initiative: "▶ N done · M cancelled"
  if any non-pending tasks exist. Click to inline-expand the
  non-pending tasks beneath the pending ones.
- Cancelled tasks render with strikethrough + a muted "✕ cancelled"
  badge, distinguishable from done's "✓ done".
- The evidence tooltip (✨ hover-to-see) still works for both done
  and cancelled.
- User can right-click / context-menu a pending task to set
  `status: cancelled` (same UX as the existing "mark done" checkbox,
  just a second menu item).

### Weekly report data source

`compute_weekly_signal()` in `bin/derived/_shared.py` currently scans
`cache/task_archive/` for `done_at` falling in the week. After
DD-011, it scans `mindmap.json` directly: walk every initiative's
`tasks[]`, filter to `terminal_at in week`, split into
`tasks_done_this_week` and `tasks_cancelled_this_week`.

(New field on `WeeklySignal`: `tasks_cancelled_this_week`. The weekly
report can show "cancelled X tasks: foo, bar (reason: merged)" as a
small signal — not the headline, but useful for "what did I un-decide
this week".)

## Changes by component

| File | Change |
|---|---|
| `bin/classify.py` | `aggregate_and_archive_tasks` → `aggregate_tasks` (~50 lines). Remove `load_task_archive` / `save_task_archive` / `TASK_ARCHIVE_DIR` / `MAX_VISIBLE_TASKS` / `_safe_init_id_for_filename`. Update `enforce_cold_and_done_monotone` for status field. Update `parse_tasks_from_fm` for `status:` instead of `done:`. Update `apply_user_overrides_inplace` for status toggles. |
| `prompts/classify-cross-session.md` | §7c rewrite for status. §7d rewrite to cover both `pending→done` and `pending→cancelled`. Add merge guidance. Pre-flight check for status enum. |
| `prompts/summarize-session.md` | Rule 12: `status` instead of `done`. Optional `evidence` field on tasks. |
| `bin/render-html.py` | Remove archive chip + expander. Add tri-state UI (pending checkbox, done strikethrough+✓, cancelled strikethrough+✕). Add "▶ N done · M cancelled" inline fold. Update task-toggle JS for status enum. |
| `bin/serve.py` | Delete `/api/task-history` endpoint. Delete `TASK_ARCHIVE_DIR` import. Update `/api/save` to accept status toggles. Update ping message. |
| `bin/derived/_shared.py` | `compute_weekly_signal` reads `mindmap.json` instead of `task_archive/`. Add `tasks_cancelled_this_week`. Remove `TASK_ARCHIVE_DIR` import. |
| `bin/derived/weekly_report.py` | Update prompt template to include cancelled tasks. |
| `bin/_test_task_persistence.py` | Update for tri-state. Add scenarios: AI may cancel pending; user may revive cancelled; done is still terminal for AI. |
| `bin/_migrate_dd011_tasks.py` | **New.** One-shot migration: walk `cache/task_archive/`, merge each task back into `mindmap.json`'s corresponding initiative under new schema, delete the archive directory. Idempotent. |
| `docs/design/README.md` | Add DD-011 row. Mark DD-008/009/010 as Superseded by DD-011. |
| `docs/zh-CN/design/README.md` | Same. |

## Migration

`bin/_migrate_dd011_tasks.py`:

1. Read `cache/mindmap.json`.
2. For each `cache/task_archive/<id>.json`:
   - Find the matching initiative in mindmap (by `id`).
   - For each task in the archive:
     - Look it up in `init.tasks[]` by `id`.
     - If present, **upgrade fields**:
       - `done: true` → `status: "done"`
       - `done: false` → `status: "pending"`
       - `done_evidence` → `evidence`
       - `done_at` → `terminal_at`
       - Drop `first_seen_at`, `last_seen_at`, `sessions`,
         `evicted_at`, `eviction_reason`.
     - If absent (was evicted/overflow), insert it with the upgraded
       schema. No cap.
3. Drop `tasks_archived_count` from every initiative.
4. Write `mindmap.json` atomically.
5. Delete `cache/task_archive/` (after a successful write — leave a
   `.bak` rename behind in case the user wants a rollback).
6. Run `bin/_test_task_persistence.py` and refuse to delete the
   backup if any test fails.

`--dry-run` mode prints the per-initiative diff (tasks count change,
fields renamed, fields dropped) without touching anything.

The migration is **idempotent**: running it twice is safe — the
second run sees a missing `task_archive/` and exits cleanly.

## Cost / risk

- **Token cost**: unchanged. The prompt to Haiku is the same size;
  the status enum replaces a boolean, evidence is the same field.
- **Latency**: slightly faster — Layer 2 no longer reads/writes 50+
  archive files per round. Net I/O delta: −50KB per classify run.
- **Failure modes**:
  - User toggles a cancelled task back to pending → AI sees pending
    in PRIOR and may re-cancel it. **Mitigation**: post-process applies
    user toggles BEFORE feeding PRIOR to AI (existing behavior). So
    AI sees the latest user-decided state and won't re-cancel without
    fresh evidence.
  - Migration script fails mid-run → atomic write protects
    `mindmap.json`; `task_archive/.bak` is the rollback. Worst case:
    user runs migration again after fixing the issue.
- **AI overuse of cancellation**: if Haiku starts cancelling tasks
  too eagerly, the user can disable AI cancellation by tightening §7d
  in the prompt without any code change. The status enum stays.

## Alternatives considered

- **Keep DD-010 as-is.** The simplest path. Rejected because the
  user explicitly asked for elegance ("彻底优化, 让其变得简洁、优秀、
  优雅") and DD-010's storage split + 11-field record is not that.
- **Add `cancelled` as a separate boolean (`done` + `cancelled` both
  bools).** Rejected: encodes 4 states (done+cancelled simultaneously)
  that don't exist. Enum is the right shape.
- **Make `cancelled` non-terminal for AI** (let AI un-cancel with
  evidence too). Rejected: the user said they want a way to express
  "this task is dead" with confidence. If AI can resurrect, the user
  loses that confidence and the feature degrades to "AI's
  task-ranking heuristic" — same as `progress` field.
- **Drop the slug-keyed continuation entirely**, treat each AI round
  as a fresh tasks[]. Rejected — this is what we had pre-DD-008,
  resulting in duplicate tasks on every reword and no done-monotone.
- **Migrate by re-running Layer 2** on all hot data. Rejected: doesn't
  preserve historical `done` flips that were correct; would over-rely
  on Haiku for what's a deterministic schema rewrite.

commit: a47262d

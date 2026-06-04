# DD-010 — Tasks are AI-additive-only, user-deletable-only

Status: **accepted** (implementation immediately follows)
Predecessors: DD-008 (task aggregation + archive),
DD-009 (task ownership + AI-assisted completion)
Trigger: 2026-05-18 — user reported "HSF 悬挂 MR 合并与 Release 分支
切割" card showing 0 tasks. Investigation found the archive file had
been silently overwritten to `[]`, losing 9 historical tasks.
13 archive files in total were wiped to empty during the day's
classify runs. Bug was patched in commit `b409b70`, but the user's
follow-up reframed the problem at the design level:

> AI 应该只能完成或关闭 task, 不应该可以删除它们

That is the new contract. DD-010 codifies it.

## 1 — The contract

| Actor | Permitted operations on `init.tasks[]` |
|---|---|
| AI (Layer 1 summarize.py) | Emit candidates with `{title, done}` |
| AI (Layer 2 classify.py) | Reuse PRIOR `id`, flip `done: false → true` with `done_evidence`, refine `title` wording |
| Post-process (classify.py) | Generate stable `id` slugs, dedup, cap visible, archive overflow |
| Schedulers / hooks | Never touch task content |
| User (UI 🗑️) | Mark a task tombstone via `deleted_tasks` override |
| User (UI ↩ unarchive) | Move an archived initiative back to live; tasks reappear |

**Hard rule for AI**: removing a task from `init.tasks[]` is a write
operation AI is not allowed to perform. The post-process MUST honor
this — anything that drops a PRIOR task without the user's explicit
tombstone is a bug.

This invariant is stronger than DD-008's done-monotone rule.
Done-monotone says "true cannot revert to false." DD-010 says "the
task entry itself cannot disappear." Together they make the
visible-tasks list strictly append-only from AI's perspective.

## 2 — What DD-009 got wrong (so we don't repeat it)

DD-009 §3.5 bound tasks to "current session evidence":

> Tasks under an initiative are only those evidenced by that
> initiative's current sessions' summaries.

It looked sound — pollution from past mis-assignments would self-evict
once the underlying sessions moved on. But it conflicted with the
user's actual mental model of a card:

- A card's task list is **the work plan for that initiative**.
- The plan persists across the work; sessions come and go.
- When a session in a finished initiative stops mentioning old tasks,
  it's not evidence that the tasks are bogus — it just means the
  work moved on.

DD-009's "evict on no evidence" misread "no current evidence" as
"task was wrong." For the HSF 悬挂 MR case: the 9 tasks were the
release plan, executed across 3 sessions over a week. The latest
session (`d177a840`) was a 4-turn cleanup-after-release exchange
with no `tasks:` block — DD-009's heuristic concluded the whole plan
was bogus, evicting all 9.

Combined with the secondary bug (archive overwrite when current
round = 0 tasks; patched in `b409b70`), the data was permanently
lost.

DD-010 removes both failure modes:
- No "no-evidence" eviction (this doc)
- Archive load-then-merge on every write (already shipped in `b409b70`)

## 3 — Design

### 3.1 — `aggregate_and_archive_tasks()` becomes additive

For each hot initiative, the new merge algorithm is:

```
merged = {}                         # id → canonical task record

# Step 1: carry forward EVERY PRIOR task. None can vanish.
for pt in prior_init.tasks:
    id = pt.get(id) or slugify(pt.title)
    merged[id] = pt (with id normalized)

# Step 2: add tasks from this initiative's hot session summaries.
#         Existing entries are updated (title rewording, sessions[]
#         union); new entries are inserted.
for sid in init.hot_sessions:
    for t in summary[sid].tasks:
        id = slugify(t.title)
        if id in merged:
            update title (latest wording), sessions union,
                   done = monotone(prior.done, t.done)
        else:
            insert as new

# Step 3: AI-asserted continuations (Layer 2 emit with explicit id).
#         Only update PRIOR entries — AI cannot introduce a new
#         task here, the new-task path is hot-summary only.
for t in init.ai_emit:
    if t.id and t.id in merged:
        merged[t.id].title = t.title       # latest wording
        if t.done:
            merged[t.id].done = True
            merged[t.id].done_evidence = t.done_evidence  # §7d
            merged[t.id].done_at = now

# Step 4: sort, cap visible at MAX_VISIBLE_TASKS, overflow → archive
not_done = sort(merged.where(done=false))
done     = sort(merged.where(done=true))
visible  = not_done + done[:MAX - len(not_done)]
overflow = ordered_all[len(visible):]      # only these go to archive
                                            # with eviction_reason="overflow_capped"

# Step 5: load existing archive, merge in this round, persist.
#         (Already shipped: b409b70.)
existing_archive = load_task_archive(id)
for t in ordered_all:    existing_archive[t.id] = t
for t in overflow:       existing_archive[t.id] = t   # carries
                                                       # eviction_reason
save_task_archive(id, existing_archive.values())
```

Critical changes vs DD-009:
- **No `evicted` list.** PRIOR tasks without current-round evidence
  are no longer dropped from `merged` — they stay, just with their
  original state. They participate in the sort/cap like any other
  task.
- **AI cannot introduce a brand-new id.** Without a hot-summary
  source AND without a PRIOR id match, an AI-emitted task is
  ignored (the previous accepted-AI-without-summary path created
  hallucination risk).

### 3.2 — Cold path unchanged

Cold initiative tasks remain byte-identical to PRIOR per §5. We
already only backfill missing `id` slugs in this case. With DD-010
the hot path is also incapable of shrinking tasks, so the cold path
no longer needs defensive checks beyond what's there.

### 3.3 — Classify prompt §7c update

The §7c rule changes from "rebuild tasks from current evidence" to
"carry forward every PRIOR task; add tasks from hot summaries; never
remove a task."

Pre-flight self-check gains a line:

> `tasks[]` count ≥ PRIOR `tasks[]` count for this initiative.
> (Tasks are append-only from your output's perspective.)

If AI somehow violates this (drops a PRIOR task), post-process
adds it back. The prompt rule is belt; post-process is suspenders.

### 3.4 — Migration script aligned

`bin/_migrate_dd009_tasks.py` no longer evicts. It still backfills
missing `id` fields (idempotent), but the "rebuild tasks from
canonical evidence" mode is removed. Running the migration becomes
a no-op pass-through for healthy data — DD-010 makes the post-process
correct by default.

### 3.5 — Pollution still possible — handled in UI

If AI mis-assigns a session to wrong initiative I at some past
round, the tasks added to I stay there forever (under DD-010).
That's the user's call to clean up.

The UI surface for cleanup is unchanged:
- 🗑️ icon on each task card-side or in the archive expander
- Clicking it adds `{init_id, task_title}` to `deleted_tasks`
  overrides; next classify drops it permanently from PRIOR
- For bulk cleanup, a future `stray --clean-card <id>` CLI could
  enumerate + prompt — out of scope for v1.

## 4 — Regression test

`bin/_test_task_persistence.py` covers the contract:

1. Setup: a synthetic mindmap with one initiative having 5 tasks,
   one hot session with no `tasks:` frontmatter (the historical
   failure mode), and an empty PRIOR archive.
2. Call `aggregate_and_archive_tasks(new_mm, prior, hot_summaries)`.
3. Assert `init.tasks` count ≥ 5 (no loss).
4. Assert archive file's task count ≥ pre-call (no overwrite loss).
5. Setup variant: same as (1) but PRIOR archive already has 3
   evicted entries.
6. Assert post-call archive has those 3 PRIOR entries AND any new
   ones (merge semantic).

The test is wired up to be runnable via `python3 bin/_test_task_persistence.py`
— exit 0 = pass, exit 1 = regression. Not yet hooked into CI (there
is no CI in this repo), but it's a one-command smoke test.

## 5 — What does NOT change

- DD-008's archive file (cache/task_archive/<id>.json) layout
- DD-009's §7d done-evidence flow (AI flipping done → true with
  evidence quote)
- DD-009's session-id tombstone for archived initiatives (DD-009 §3.5
  was about session-bound tasks; the session-tombstone for archived
  initiatives in classify.py main() is a separate mechanism and stays)
- The "+N archived" UI expander on cards

## 6 — Plan

1. Rewrite `aggregate_and_archive_tasks` per §3.1
2. Update `prompts/classify-cross-session.md` §7c per §3.3
3. Update `bin/_migrate_dd009_tasks.py` per §3.4
4. Add `bin/_test_task_persistence.py` per §4
5. Single commit + push
6. Document open question: bulk-clean UI (deferred)

## 7 — Open questions

1. Should we also offer a one-click "review polluted tasks" on the
   card detail modal — surface tasks evicted long ago so user
   notices and can clean? Deferred until pollution actually becomes
   a problem in normal use.
2. The current `MAX_VISIBLE_TASKS = 20` cap can still cause "natural"
   overflow into archive on heavily-used initiatives. We could let
   the user raise it via env var (already supported) or make it
   per-card. Not urgent.

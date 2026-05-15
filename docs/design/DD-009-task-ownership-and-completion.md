# DD-009 — Task ownership + AI-assisted completion

Status: **proposed** (accepted in principle; implementation deferred)
Predecessors: DD-002 (3-layer pipeline), DD-003 (artifacts/blockers),
DD-008 (task aggregation + archive)
Trigger: 2026-05-15 — user observed that
`mw-cli-hsf-qos-commands` card had:
1. 13 tasks from a different initiative (`claude-code-worktree-dashboard`)
   stuck on it permanently;
2. 5 pairs of en/zh duplicates of the same task;
3. Several "real" tasks staying ✗ even after the user shipped them.

DD-008 v1's task aggregation has three orthogonal design holes, all
of which contributed to the QoS-card mess. This doc captures the
root cause for each and proposes a coherent fix.

## 1 — The three holes

### 1.1 Tasks are not session-bound (cross-initiative pollution)

DD-008's `aggregate_and_archive_tasks()` carries forward ALL of a
PRIOR initiative's tasks into the new round, regardless of whether
those tasks are still supported by any current session in that
initiative. If at any past round AI mis-assigned task T to
initiative A, T stays in A forever.

This actually happened on 2026-05-15: during chaotic concurrent
testing, the `claude-code-worktree-dashboard` initiative was briefly
archived, leaving its session `940413c0` looking orphaned to AI's
next classify run. AI placed 940413c0's tasks under
`mw-cli-hsf-qos-commands` for one round. The dashboard was
unarchived a few minutes later — but the mis-attributed tasks
remained on the QoS card forever via PRIOR carry-forward.

Root cause: **PRIOR is treated as truth, with no mechanism to evict
stale entries.** Once an error gets in, it persists. Tasks have no
binding to a specific session, so when sessions are reassigned
between initiatives, tasks don't follow.

### 1.2 Slug-keyed dedup misses semantic duplicates

DD-008 keys task identity on `slugify(title)`. If two summaries
describe the same work with slightly different wording, two slugs,
two tasks. Specifically:

- en/zh of the same task → different slugs → dupes
- Wording change like "Implement X" vs "Add X feature" → dupes
- Reordered or expanded title → dupes

The QoS card had 5 known en/zh pairs, all the same work.

Q2's prompt fix (commit `7e7f97a`) stops NEW dupes by pinning task
title language to `output_lang`. But it does not consolidate
existing dupes, and it does not handle rewording within one
language.

### 1.3 No mechanism to mark old PRIOR pending → done

Layer 1 only marks `done: true` for work the CURRENT session
clearly finished (Rule 12 in summarize-session.md). PRIOR tasks
that pre-date this session are evaluated separately — their `done`
state is preserved (done-monotone), but there is no path to flip
them from `false` → `true` based on new evidence in a different
session's summary.

Concretely: an old task "实现 QoS limiter 配置查询"
(`done: false`) is stuck `false` even after the user shipped a PR
called "Add qos-limit query feature" — because:
- Different sessions describe it,
- Different wording → different slug,
- Layer 1 of the recent session has no view of the old task,
- Layer 2 carries forward the old task verbatim (done-monotone).

The user expects: as work ships, old tasks check themselves off.

## 2 — Goals

1. Tasks under an initiative are **only those evidenced by that
   initiative's current sessions' summaries**. Stale tasks (no
   supporting session) get archived.
2. Two ways of describing the same task converge to one entry.
3. PRIOR pending tasks get `done: true` when new session evidence
   shows the work is completed.
4. The existing `cache/task_archive/` retains everything, so nothing
   the user once saw is lost — just no longer cluttering the card.
5. The fix is content-preserving for the common case: only the
   genuinely-stale entries get evicted.

Non-goals:
- AI's free-form judgment of task importance / priority
- Cross-initiative task moves (each initiative is independent)
- Editing archived tasks (archive is append-only history)

## 3 — Design

### 3.1 Session-bound task ownership (fixes hole 1.1)

Rewrite `aggregate_and_archive_tasks()`'s candidate-collection rule:

**Old (DD-008 v1):**
```
candidates = PRIOR.tasks   # carry forward everything
           + AI emit       # whatever AI wrote
           + hot summaries' tasks (for sessions in this init)
```

**New (DD-009):**
```
# Only tasks evidenced by the initiative's current sessions count.
canonical_tasks_this_round = union of:
    each session in init.sessions[] that is hot:
        that session's frontmatter tasks
    +
    AI's emit for THIS initiative (constrained: must match a session)

# PRIOR tasks contribute ONLY for state preservation:
for each task in canonical_tasks_this_round:
    if PRIOR has a slug-matching (or semantically-matching) task:
        carry over done, first_seen_at, sessions[], done_at
    else:
        treat as new
```

Tasks that were in PRIOR but have no canonical-round support do not
appear in `init.tasks[]` this round. They are flushed to
`cache/task_archive/<init_id>.json` with `evicted_at: <now>` so the
history is preserved (and the existing "view archived" UI surfaces
them).

**Result**: when a session moves between initiatives (Layer 2
re-classify), its tasks follow it. Cross-initiative pollution is
structurally impossible — a task without a current session reference
cannot exist in `init.tasks[]`.

### 3.2 Semantic dedup at AI level (fixes hole 1.2)

Move the dedup decision FROM post-process slug match TO the AI's
classify step. Classify is already given PRIOR + hot summaries; it
has the semantic context to recognize "Implement X" ≡ "Add X
feature" ≡ "实现 X".

Extend the classify prompt:

```
For each hot session's tasks, before adding them to the
initiative's tasks[], check whether PRIOR contains a task that is
semantically the same (allowing for paraphrase, translation, or
expanded wording). If yes:
  - Reuse PRIOR's task `id` (don't generate a new one)
  - Pick the more-detailed wording as the unified `title`
  - Mark `done: true` if either is done (monotone)
The classify schema gains an optional `id` field per task so AI can
explicitly continue PRIOR entries:
  "tasks": [{"id": "<reuse-prior-or-omit>", "title": "...", "done": ...}]
```

Post-process trusts AI's `id` when provided; falls back to slug
generation when missing. Slug-level dedup remains as belt-and-
suspenders.

Migration: existing en/zh dupes will be merged on next classify run
because AI will see both PRIOR entries and pick one canonical id.
The losing id's content goes to archive.

### 3.3 AI-assisted task completion (fixes hole 1.3)

Extend the classify prompt with a new section §7d:

```
For each PRIOR pending task in a hot initiative, examine the
hot summaries' content (the # 已下的决定 / # 产物 / # 待解决
sections, plus their tasks[]) to determine whether the task has
been completed since PRIOR was generated.

A PRIOR task X is "completed" if any hot summary clearly states
the work was finished: a PR/MR merged, a feature shipped, tests
passing, or an explicit "X 完成 / done" statement that
unambiguously refers to X (or a paraphrase of X).

For each such X, in your output:
  - Keep X's `id` and `title`
  - Set `done: true`
  - Add an audit trail: optional `done_evidence: "<≤80-char
    quote from the source summary>"`

If the evidence is ambiguous (could be a different task, or just
a related discussion), DO NOT flip. The done-monotone rule means
flipping false → true is one-way; over-eager completion would
strand the user with checked tasks that aren't really done.
```

Post-process validates: if `done_evidence` is set but
`done == false`, it's a contradiction; classify.py drops the
evidence field. If `done == true` was set in PRIOR, evidence stays
optional.

### 3.4 Schema additions

`cache/mindmap.json` initiative.tasks[]:
```json
{
  "id": "stable-slug-or-prior-id",
  "title": "natural language",
  "done": true|false,
  "done_evidence": "(optional) short quote attesting completion"
}
```

`cache/task_archive/<init>.json` tasks[] gains:
```json
{
  ...,
  "evicted_at": "<ISO timestamp>",     // when this task left
                                       // visible mindmap.json
  "eviction_reason": "no_session_evidence"
                                       // why
}
```

No bump of `schema_version` — both fields are optional and
backward-compatible.

### 3.5 Post-process changes (bin/classify.py)

`aggregate_and_archive_tasks()` is rewritten:

```python
def aggregate_and_archive_tasks(new_mm, prior, hot_summaries):
    hot_tasks_by_sid = parse_tasks_from_each_hot_summary(hot_summaries)
    prior_by_id = index_prior_tasks(prior)

    for ws, init in walk(new_mm):
        if not init.has_hot_session():  # cold §5 path
            for t in init.tasks: ensure_id(t)  # backfill legacy
            continue

        # === Collect canonical-round candidates ===
        canonical = []
        for sid in init.sessions:
            if sid in hot_tasks_by_sid:
                for t in hot_tasks_by_sid[sid]:
                    canonical.append((sid, t))
        # AI may also emit tasks not present in any session's
        # frontmatter (e.g. continuity from PRIOR with a rephrase).
        # Trust AI if it provides an `id` — that's its way of saying
        # "this is a continuation, not invented."
        for t in init.tasks_emit:
            if t.get('id') and t['id'] in prior_by_id.get(init.id, {}):
                canonical.append((None, t))  # AI-asserted continuation

        # === Dedup, merge state, archive ===
        merged = merge_canonical_with_prior(canonical, prior_by_id[init.id])
        new_tasks, evicted = cap_visible_and_archive(merged, MAX_VISIBLE_TASKS)

        init['tasks'] = new_tasks
        init['tasks_archived_count'] = count_archive_excluding_visible(init.id, new_tasks)
        save_task_archive(init.id, merged + evicted)
```

### 3.6 Migration

DD-009 implementation includes a one-time migration script
`bin/_migrate_dd009_tasks.py`:

1. For every initiative in `cache/mindmap.json`:
   - Determine canonical sessions and their summaries' tasks
   - Identify PRIOR tasks with no canonical-round support → move to
     `task_archive` with `evicted_at = generated_at`,
     `eviction_reason = "dd009_migration_no_evidence"`
   - Identify en/zh sibling pairs in archive → mark merged via
     `merged_with` field linking the canonical id

2. Run a single classify pass with the new prompt to consolidate
   semantically-matched dupes.

3. Print a per-initiative summary: "kept N, evicted M, merged K".

Estimated migration cost: 1 classify run (~$0.15) + script time.

## 4 — Open questions

1. **Should AI emit `done_evidence` as a required field for
   `done: true → false → true` transitions, or always optional?**
   Lean toward required for false → true flips so we can audit
   over-eager completion in the next round. Optional for tasks AI
   creates and immediately marks done.

2. **What about tasks that the same session re-mentions across
   rounds but in different wording each time?** Today's summary
   says "Add X feature", tomorrow's says "Implement X". Two
   different slugs. AI in classify should recognize both as the
   same task. Risk: AI may rewrite history and erase one valid
   wording. Mitigation: when AI declares a continuation,
   post-process verifies the slug match against EITHER the PRIOR
   slug OR the slug derived from PRIOR title — both must point to
   the same canonical id.

3. **Migration: what if a real PRIOR task has no current session
   evidence because the session legitimately stopped being hot?**
   Example: a task created 5 days ago, the session went cold. By
   §1.1 rule, the task gets evicted to archive. But it might be a
   "real" pending task the user still cares about. Mitigation:
   the user can promote a task from archive back to visible via UI
   (out of scope V1; manual edit of task_archive JSON works as a
   workaround). The launchd 2h sweep could also re-summarize a cold
   session to "warm it up" and re-establish evidence — but that
   contradicts the DD-005 lazy-refresh principle.

4. **Cross-language migration**: AI-driven semantic dedup of the
   existing en/zh dupes assumes Haiku can recognize them. Risk:
   token cost of feeding Haiku the full PRIOR + hot summaries with
   "find duplicates" instructions. The existing classify prompt
   already does cross-session analysis at ~$0.15/run; the
   migration's incremental cost is likely under $0.30. Acceptable
   one-off.

5. **How does this interact with user manual task-delete?** When
   the user clicks ✕ on a task, it goes to `deleted_tasks` in
   overrides; classify.py drops it. With DD-009, evicted tasks
   automatically flow to archive. The two mechanisms are
   complementary — manual delete is "I never want to see this
   again" (tombstoned); auto-evict is "no current evidence, but
   may come back if the session is revisited".

## 5 — Out of scope (deliberate)

- **Cross-initiative task moves** when AI decides a task should
  belong elsewhere. Tasks belong to the initiative whose sessions
  produced them; if AI reassigns a session, its tasks follow. Mixed
  ownership isn't modeled.
- **Task priority / importance ranking**. The user can reorder
  manually if needed. (DD-006's "next-steps" feature is a separate
  consumer of the data and may add this surface.)
- **Auto-archive of completed tasks older than N days**. The cap
  (DD-008's MAX_VISIBLE_TASKS=20) already evicts oldest done; a
  time-based rule would be redundant.
- **Per-task notification when AI marks done_evidence**. Could be
  added as a UI nicety; deferred.

## 6 — Plan

| Phase | Item | Estimate |
|-------|------|----------|
| 0     | Migration script `bin/_migrate_dd009_tasks.py` + dry-run mode | small |
| 1     | Rewrite `aggregate_and_archive_tasks()` per §3.5 | medium |
| 2     | Extend classify prompt: schema gains optional `id`, §7d for completion, semantic dedup rule | small |
| 3     | Schema extension for `done_evidence` and `evicted_at` | tiny |
| 4     | UI: display `done_evidence` as tooltip on task title; "view archived" surface keeps existing shape | small |
| 5     | Run migration on existing data; spot-check on the QoS card and 2-3 other initiatives | small |
| 6     | Document migration semantics in README / ARCHITECTURE.md | tiny |

Risk: phase 5 is partly AI-driven (classify call with new prompt).
Output should be inspected by the user before committing the new
mindmap.json. Recommend running with a `--dry-run` flag that emits
the proposed mindmap.json + diff vs current, so the user can
approve.

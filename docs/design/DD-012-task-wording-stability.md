# DD-012: Task wording stability across Layer 1 reruns

**Status**: Accepted
**Author**: Claude (with user)
**Date**: 2026-05-25

## Problem

A real card on the dashboard, `service-test-record-e2e`, accumulated
**47 pending tasks** across a single 100-turn Claude Code session. The
backing session summary's `tasks:` frontmatter currently has zero
tasks. The pending list contains obvious semantic duplicates:

- `重构授权链` appears 4× under 4 different slugs
- `实现 service doc MVP` appears 3× (one bare, one with
  ` with flag-based slicing`, one ` 命令 MVP`)
- `添加测试` / `添加单测与 e2e` / `service doc 测试覆盖` / `为
  service doc 命令添加单元 + e2e 测试`
- `同步文档` 3× plus longer forms
- bilingual variants (`ops-portal service test-record OpenAPI — design +
  implementation` vs `ops-portal 服务测试记录 OpenAPI 实现 + 单元测试`)
- prefix-tagged variants (`[F1-body] ops-portal service test-record …` vs
  the same thing without `[F1-body]`)

The user can't be expected to manually ✕ 47 tasks. The list does not
converge with time; each Layer 1 rerun produces more variants.

## Root cause

Layer 1 (`bin/summarize.py`) rewrites `cache/summaries/<sid>.md` on
every rerun, including its `tasks:` frontmatter block. The prompt
(`prompts/summarize-session.md` Rule 12) instructs Layer 1 to extract
tasks from the transcript, but **does not constrain wording across
reruns**. So a long session that gets re-summarized 10 times yields
10 slightly-different phrasings of the same conceptual task.

Layer 2 (`bin/classify.py`'s `aggregate_tasks`) keys merging by
`slugify_task_title(title)` — character-level slug of the title. Two
phrasings = two slugs = two task records. DD-011's "AI can't drop"
invariant then locks both in permanently.

So we have:

- **Layer 1**: a free-form rewording engine with no cross-rerun
  stability contract.
- **DD-011 invariant**: "once a task is added, only the user can
  remove it."
- **Aggregator**: mechanical exact-slug dedup, no semantic dedup.

These three are individually defensible. Combined, they guarantee
unbounded task-list growth on any session that gets re-summarized
multiple times — i.e., every real session.

## Decision

**Amend Layer 1's contract: it must respect prior task wordings.**

Concretely:

1. `bin/summarize.py` builds a `<prior_tasks>` block listing, for each
   initiative that already lists this sid in its `sessions[]`, the
   PRIOR pending+done task titles.
2. `prompts/summarize-session.md` Rule 12 gains a hard sub-rule:
   *"If a PRIOR task title is semantically equivalent to a task you
   would write, COPY THE PRIOR TITLE BYTE-FOR-BYTE. Do not translate,
   re-tag (`[F1-body]`), summarize, or expand it. Only emit a new task
   title when the work is genuinely new — not a rephrasing."*
3. No code change to `aggregate_tasks` — the existing slug dedup
   trivially catches byte-identical titles. Once Layer 1 stops
   reinventing wording, the slug dedup is sufficient.

## Why not the alternatives

Considered and rejected:

- **Task provenance + soft-expire** (track `last_seen_round`, cancel
  tasks Layer 1 hasn't re-emitted for N rounds). Real mechanical
  guarantee against accumulation, but: (a) changes DD-011's promise
  that AI cannot remove user-stated commitments; (b) adds two new
  fields and a counter, undoing DD-011's "5 fields max" goal;
  (c) heuristic threshold (`N = ?`) is fragile.
- **AI-driven consolidation step** (extra Haiku call to mark
  semantically-duplicate tasks cancelled). Useful as a one-shot
  cleanup affordance for cards already in the bad state, but doesn't
  prevent future accumulation; costs $0.02 per card per N rounds
  forever.
- **Mechanical semantic dedup via embeddings**. Adds runtime
  dependency for a problem that's better solved upstream — once
  Layer 1 stops rewording, there's nothing to dedup.
- **Rethink DD-011's no-AI-deletion rule**. Considered but kept as
  inviolable: the original incident that motivated DD-011 (2026-05-18
  data loss) hasn't gone away. Cracking that rule for "minor cosmetic
  cleanup" is the slippery slope to recreating the failure mode.

## Trade-offs accepted

- **Trust in AI prompt adherence**: this fix is a prompt constraint,
  not a mechanical guarantee. Layer 1 (Haiku) can ignore it. We have
  no aggregator-level enforcement because semantic equivalence isn't
  mechanically computable without embeddings. Mitigation: if drift
  reappears in practice, add the one-shot "consolidate this card" UI
  button as a manual escape valve.
- **Doesn't fix existing damage**. The 47-task service-test-record
  card stays at 47 until the user manually trims or AI-consolidates.
  We picked "future prevention" over "retroactive cleanup" as the
  priority — see *Migration* below.
- **Layer 1 prompt length grows slightly** (~50–500 bytes for a
  hot initiative). Negligible cost.

## Migration

For the existing `service-test-record-e2e` (and any other
already-bloated cards): no automated migration. The user can either
(a) manually delete the ones they consider duplicates via the UI ✕
button, or (b) archive the whole card and let the next session start
fresh.

A future DD could revisit whether to ship a "Consolidate duplicates"
button on the card detail modal — explicitly user-triggered, makes
one AI call per click, with a preview before applying. Not in
DD-012 scope.

## Test plan

1. `python3 bin/summarize.py <sid> --dry-run` for a session that
   maps to an initiative with existing tasks → confirm the dumped
   prompt contains `<prior_tasks>` with the right titles.
2. `python3 bin/summarize.py <sid> --force` on the same session →
   confirm the new `cache/summaries/<sid>.md` reuses PRIOR titles
   verbatim rather than rephrasing.
3. Run the full pipeline; `stray --diagnose <sid>` and watch the
   task count on the resulting card. Expectation: it stops growing
   on reruns. New work in the session still surfaces as new tasks.

## Relationship to DD-011

DD-012 is a clarifying amendment, not a replacement:

- DD-011 still owns the storage model, the tri-state status, and
  the "AI is additive-only at Layer 2" invariant.
- DD-012 adds a wording-stability contract one layer up (Layer 1),
  where the original wording-instability was coming from.
- Neither rule deletes data the user touched.

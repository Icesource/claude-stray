# DD-001: Two-pass classification — per-session AI summaries replace hard compression

**Status**: **Superseded by [DD-002](DD-002-ai-pipeline-redesign.md)**
**Author**: bby
**Date**: 2026-05-13

> ⚠️ This document has been superseded by
> [DD-002](DD-002-ai-pipeline-redesign.md). DD-002 is the unified
> design built on DD-001 + subsequent discussion. It adds hot/cold
> stratification, mtime dirty tracking, concurrency model, file
> layout, and end-to-end walkthroughs. This doc remains for history.

中文版：[../zh-CN/design/DD-001-two-pass-classification.md](../zh-CN/design/DD-001-two-pass-classification.md)

## Problem

The card content for an actively-worked session lags the actual state
of the work, sometimes by hours.

### Concrete case

In session `cbbeb23c-b6f9-4eb4-926e-7e4046c856d4`, the user (bby) was
debugging EagleEye trace IP=null in HSF. Real-life arc of the session:

```
T+0    "调研 EagleEye 链路追踪服务端 IP 为空的问题"
T+30m  "等 arthas watch 抓数据"                       ← stuck here in card
T+90m  "为啥 logRemoteIp 要传本机 IP" (root-cause hunt)
T+95m  AI gives full explanation of HSF_CLIENT span semantics
T+110m "把问题记录一个 Aone ISSUE"
T+115m AI writes /tmp/aone-issue-hsf-eagleeye.md
T+120m "确认, 指派给我"
```

After T+120, the user opened the dashboard. The card said:

> 进度：发现关键线索…用户收集了带 @s0 前缀的 EagleEye data 样本，
> 当前等待用 arthas watch 在本地跟踪 EagleEyeUtil.logRemoteAddress
> 抓取现场数据。

That progress text is from **T+30**. The 90 minutes of root-cause
analysis and ISSUE filing are invisible.

### Why

`bin/extract.py` produces a per-session summary capped at:

- `first_user_prompt`: 400 chars
- `recent_user_prompts`: last 5, each 400 chars (was 3 × 300 before this
  doc was written)
- `last_assistant_summary`: first 1500 chars of the most recent assistant
  text reply (was first paragraph only)
- `edited_files`: list of files (no content)
- `task_events`: TaskCreate/TaskUpdate strings
- `recap`: Claude Code's `away_summary`, may be hours stale
- `tools_used`: tool names

Total per session: **~1.5 KB structured JSON**.

The classifier (`prompts/classify.md`) then sees 200 such summaries
(~300 KB total) and must in one pass:

1. Group them into initiatives (cross-session decisions)
2. Per initiative, write name + summary + progress + tasks + sessions
3. Maintain continuity with PRIOR_MINDMAP
4. Respect DELETED_IDS

Output budget for Haiku 4.5 is ~10 KB — 50 bytes per initiative on
average. **The classifier is being asked to do too much with too little
information density.**

### Why bumping limits won't fix it

The `last_assistant_summary` constant change from "first paragraph" to
"1500 chars" is what unblocked the EagleEye case. But it's structural
luck:

- If the session's last assistant turn is a 3000-char deep technical
  reply, we keep the first 1500 chars — possibly missing the conclusion
- If the relevant content is in turn N-3, we never see it
- The classifier sees text fragments, not narrative — it has to
  reconstruct intent and progress from disconnected snippets

The classifier output quality is bounded by the information density of
its input. The input is a lossy compression that throws away the very
thing that matters (narrative). We can tune the compression heuristics,
but the ceiling is low.

## Goals

1. **Per-session content stays current within ~1 minute of the user's
   last assistant turn.** A card for an active session should never
   describe a state older than the last few prompts.
2. **Cross-session classification accuracy stays at least as good as
   today.** Initiative grouping, status decay, continuity — all still
   work.
3. **Cost stays under ~$3/hour during active work** (current Haiku
   refresh at 5-min cooldown is ~$2.5/hour).
4. **Latency for "user finishes a turn → card updates" drops below
   30 seconds** in the common case.

## Non-goals

- Real-time streaming updates (Server-Sent Events, websockets). Polling
  every 8s is fine.
- Reducing the human-written prompt to nothing. The two-pass split adds
  prompts; that's OK if each is shorter and clearer.
- Removing the periodic full reclassification. We still need it for
  cross-session structural cleanup.

## Proposal: two passes

```
[Stop hook fires for session X]
     │
     ▼
extract.py — incremental jsonl read (UNCHANGED)
     │
     ▼
summarize.py [NEW]
     reads cache/sessions/X.json AND last N turns of X.jsonl raw
     prompt: classify-session.md (NEW)
     model: Haiku, ~5KB prompt → ~500 tokens out, ~$0.01, 5-10s
     writes cache/summaries/X.md  (structured markdown)
     │
     ▼
[conditional]
classify.py [REWRITTEN refresh.sh logic]
     reads ALL cache/summaries/*.md
     prompt: classify-cross-session.md (rewrite of current classify.md)
     model: Haiku, ~40KB prompt → ~5KB out, ~$0.05, 30s
     writes cache/dashboard.json
```

### Pass 1: `bin/summarize.py` — one session in, one summary out

**Input** (full text, no further compression):

- `cache/sessions/X.json` (the existing extracted skeleton)
- Tail of the raw jsonl — last K user-assistant turns or last L KB
  (proposed K=10 turns, L=30 KB, whichever is smaller)

**Output**: `cache/summaries/X.md`

Schema is markdown so future review is easy. Structured frontmatter +
sections:

```markdown
---
session_id: cbbeb23c-b6f9-4eb4-926e-7e4046c856d4
cwd: /Users/bby/Code/pandora/pandora-sar/hsf
last_activity_at: 2026-05-13T09:19:46.447Z
status_guess: active  # active | paused | done | abandoned
updated_at: 2026-05-13T09:25:00Z
---

# Goal
What the user set out to do. One paragraph.

# Current state
Where the work stands AS OF the last assistant turn. Not "what AI did"
but "what's been figured out / what's blocked / what's the next handoff."

# Decisions made
Bulleted list of concrete decisions or conclusions that survived to the
latest turn. (Things the user said "ok" to or AI committed to in code.)

# Artifacts
- /tmp/aone-issue-hsf-eagleeye.md (created)
- src/main/java/.../EagleEyeHttpHook.java (planned edit, not yet written)

# Next step
What the user or AI said the next step is. If the session was abandoned
mid-thought, say so.

# Open questions
Anything unresolved that the user is waiting on.

# Tasks (proposed)
- [ ] task title 1
- [x] task title 2 (completed: brief evidence)
```

The classifier in pass 2 reads these directly without further parsing —
the markdown is the structured representation.

**Prompt** (`prompts/summarize-session.md`, new):

Short. Tells Haiku to read the raw turns and the skeleton and produce
the markdown above. Heavy use of "the LAST turn is the most authoritative;
prefer recent over recap; if user says X, X is what's happening."

### Pass 2: cross-session classifier — rewritten

**Input**:

- `cache/summaries/*.md` for all live sessions
- PRIOR_MINDMAP (dashboard.json)
- DELETED_IDS
- OUTPUT_LANG

**No more** `aggregate_input.json` — summaries replace it. Total prompt
size drops from ~300 KB → ~40 KB.

**Output**: same `cache/dashboard.json` schema as today.

**Prompt** (`prompts/classify-cross-session.md`, rewrite of today's
`classify.md`):

The classifier's job shrinks: group, name, status-decay, respect
continuity. Per-initiative "what's happening" comes straight from
summaries — the classifier doesn't have to synthesize narrative, it just
picks the right summary text and trims.

### Trigger strategy

Per the user's confirmed choice (always-summarize, conditional-classify):

| Trigger | Pass 1 | Pass 2 |
|---|---|---|
| Stop hook | ALWAYS for the session that fired (~$0.01) | ONLY if pass-1 produced material change AND classify-cooldown clear |
| SessionStart hook | ALWAYS | same condition |
| LaunchAgent (2h) | for any session changed since last summarize | yes |
| `stray --refresh` | for all sessions changed since last summarize | yes, force |
| `POST /api/refresh` | same as --refresh | same |

"Material change" detection (so we don't burn Haiku on every Stop):
diff the new `summaries/X.md` against the previous version on disk;
ignore frontmatter (timestamps change every turn); if the `# Current
state`, `# Next step`, or `# Tasks (proposed)` sections changed, trigger
pass 2. Otherwise pass-1 alone is enough — the HTML hot-poll picks up
the new summary content directly.

### Independent cooldowns

Replace today's single `last_ai_run.epoch` with two markers:

- `cache/last_summarize_run.epoch` — gates pass 1, default 60s cooldown
- `cache/last_classify_run.epoch` — gates pass 2, default 300s cooldown

Cheaper pass (1) cycles 5x faster than expensive pass (2). Even at full
saturation pass 1 runs at most 60/hr × $0.01 = $0.60/hr and pass 2 at
12/hr × $0.05 = $0.60/hr. Total worst-case $1.20/hr vs today's $2.50/hr.

## Changes by component

| File | Change |
|---|---|
| `bin/summarize.py` | NEW. Reads a session's jsonl tail + summary, calls Haiku, writes `cache/summaries/<sid>.md` |
| `bin/extract.py` | Trim — drops `first_user_prompt`, `recent_user_prompts`, `last_assistant_summary`, `recap` from the JSON shape (no longer needed). Keeps timestamps, cwd, message counts, edited_files (still useful as machine-readable signals). New "is_summarized" flag set after pass 1 |
| `bin/aggregate.py` | DELETED. Pass 2 reads `summaries/*.md` directly |
| `bin/refresh.sh` | Rewritten dispatch: optional pass-1 (per session_id passed in via env or scanned dirty), conditional pass-2. Two separate cooldowns. Apply-overrides + repairs unchanged |
| `bin/refresh-bg.sh` | Pass through `CLAUDE_SESSION_ID` from hook stdin so refresh.sh can target pass 1 |
| `prompts/classify.md` | DELETED. Replaced by two new prompts: |
| `prompts/summarize-session.md` | NEW. ~80 lines, focused on one session |
| `prompts/classify-cross-session.md` | NEW. ~200 lines, simpler than today's classify.md (no per-initiative narrative synthesis required) |
| `bin/render-html.py` | Optional: surface summary content inline in cards as a "📝 详细" expand button, reading `cache/summaries/<sid>.md` |
| `bin/diagnose.py` | Add a `[2.5]` stage between extract and aggregate: "Pass 1 summary present?" check |
| `cache/summaries/` | NEW dir, one `.md` per active session_id |
| `docs/ARCHITECTURE.md` | Update pipeline diagram + cache file table |

## Migration

The first refresh after upgrade runs pass 1 for every session in
`cache/sessions/` that doesn't yet have a `cache/summaries/` companion.
That's ~200 sessions × $0.01 = ~$2 one-time cost. Then steady state.

Old `aggregate_input.json` and `prompts/classify.md` are kept on disk for
one release as fallback; the rewrite checks for `cache/summaries/` and
falls back to legacy pipeline if absent (e.g. classifier prompt
malformed and pass 1 produced nothing usable).

After two weeks of stable operation, delete the legacy code paths.

## Cost / risk

### Cost worst case (assuming Haiku at current rates)

| Path | Frequency | Per-call | $/hr |
|---|---|---|---|
| Pass 1 on Stop hook | Up to 60/hr (1/min ceiling from cooldown) | ~$0.01 | $0.60 |
| Pass 2 conditional | Up to 12/hr (5-min cooldown) | ~$0.05 | $0.60 |
| Migration backfill | One-time | $2 | one-shot |

Steady-state worst case **$1.20/hr** vs current **$2.50/hr**. Idle cost
is near zero (both passes hit cooldown).

### Risks

| Risk | Mitigation |
|---|---|
| Pass 1 produces wrong / hallucinated summary | The summary lives on disk and the user can review it (rendered in HTML behind a "📝" button). If wrong, `rm cache/summaries/<sid>.md` and re-run. AI run is bounded — one session per call |
| Pass 2 prompt loses context that the old classifier had | Side-by-side run during migration: keep old pipeline running for one week, compare DIFFs |
| Disk usage from `cache/summaries/` | Each summary ~2-5 KB; 200 sessions ~600 KB. Garbage-collect summaries whose session jsonl is gone |
| `cache/summaries/<sid>.md` and `cache/dashboard.json` drift | Pass 2 always reads the LATEST summaries dir; drift window is at most one pass-1 cycle (60s) |
| Two cooldowns more confusing than one | Document clearly; `stray --diagnose` reports both |

## Alternatives considered

### A. Just keep bumping extract limits

We did this for `last_assistant_summary` (first-paragraph → 1500 chars)
and it unblocked the EagleEye case. But it's a heuristic ceiling, not a
fix. Sessions whose relevant content lives outside the chosen window
are still mis-classified. **Rejected.**

### B. Switch classifier to Sonnet

Sonnet 4.6 is 3-5x the cost of Haiku per token. Same compressed input
still means same information-density ceiling. Better model on bad input
gets you ~20% improvement, not 5x. Cost goes from $2.5/hr → $10/hr.
**Rejected.**

### C. Stop hook only feeds the current session, no cross-classification

User's initial intuition. But then "this new session is part of an
existing initiative" requires the AI to see other sessions. We'd lose
cross-session grouping entirely. **Rejected** in favor of two-pass.

### D. Per-session classification, no cross-pass

Like B, but instead of a separate classifier we have each summary
directly produce its own initiative entry. The mindmap is just a
collation of session-level outputs. Loses the ability to merge multiple
sessions into one initiative — which is a core feature (e.g. one
"ChangeFree refactor" initiative spans ~5 sessions over a week).
**Rejected.**

### E. Stream-based incremental updates (SSE / websockets)

Sounds nice, adds a lot of moving parts (server reconnect, client
state reconciliation, message ordering). The polling-every-8s
implemented in P9.4 is already fast enough for the user's "card auto
updates" requirement. **Rejected** as premature.

## Open questions for review

1. **Storage format for summaries: markdown vs JSON?** Markdown is
   readable by humans (a user can `cat cache/summaries/<sid>.md`); JSON
   is unambiguous for the cross-classifier. Current proposal is
   markdown with YAML frontmatter — best of both. Alternative: pure JSON
   with a separate `render-summary.py` for human view.

2. **How many turns / chars of raw jsonl does pass 1 see?** Proposed
   K=10 turns or L=30 KB. Long technical sessions might need more; very
   chatty sessions might need fewer. Could start at 30 KB and adjust
   from empirical data.

3. **Should pass 2 run BEFORE pass 1 in `stray --refresh`?** When the
   user explicitly asks for a full refresh, do we want to re-summarize
   everything (slow but thorough) or just re-classify on existing
   summaries (fast)? Probably: `--refresh` triggers both passes; add a
   `--refresh-classify-only` for the fast version.

4. **Cleanup of stale summaries.** When a `cache/sessions/<sid>.json`
   disappears (e.g. user deleted the jsonl), do we keep
   `cache/summaries/<sid>.md`? Proposed: yes, treat as archive — never
   delete summaries unless explicitly asked.

## Implementation plan (if approved)

1. Write `prompts/summarize-session.md` + iterate on 3 hand-picked
   sessions until output quality satisfies bby's eyeball
2. Implement `bin/summarize.py`, including dirty-detection (mtime
   compare on `cache/sessions/<sid>.json` vs `cache/summaries/<sid>.md`)
3. Migration backfill script: run pass 1 over all existing sessions
4. Rewrite `prompts/classify-cross-session.md` based on summary input
5. Modify `refresh.sh` for two-pass dispatch with independent cooldowns
6. Update `render-html.py` to surface summaries in the card UI
7. Update `diagnose.py` to walk pass 1 too
8. Side-by-side run for one week: keep old pipeline, compare outputs
9. Remove legacy after green light

Estimated effort: ~2 days of focused work for code, ~1 week of bake-in
observation.

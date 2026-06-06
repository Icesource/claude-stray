# DD-025: Parallel sub-cards — human-orchestrated, conflict-aware triage

**Status**: Proposed (design; informed by industry + Claude Code research)
**Author**: Claude (with user)
**Date**: 2026-06-06
**Predecessors**: DD-018 (single-driver), DD-022 (worktree first-class),
project pivot "card = one session"

## Why

The user wants a main task to fan out into parallel sub-tasks, each a **sub-card**
under the main card, each in its own worktree, individually driveable and visible —
fixing the CLI multi-agent UX gap (poor visualization, hard switching, hard to talk
to each agent). Two prior research passes (Claude Code internals + industry survey)
sharpened both the *how* and the *what not to build*.

## What the industry research settled (decision inputs)

**The market converged on one model that actually works:** *human-as-orchestrator over
parallel independent sessions, coordinated through PR/issue review* (OpenAI Codex 3M
WAU, GitHub Copilot coding agent GA both landed here). Orchestrator-worker (Devin
Managed Devins, Qoder 专家团, Roo Boomerang) is the optional second layer. Autonomous
self-coordinating **peer "teams"** (Claude agent-teams) are the rarest, most expensive,
most confusing, least proven.

**The universal complaints are all OVERSIGHT problems, not execution problems:**
1. Monitoring/reviewing N concurrent agents causes context-switching that **eats the
   parallelism gain** ("parallelism is not productivity" — explicit in Cursor + Windsurf
   reception). → *an attention-allocation problem.*
2. **Semantic merge conflicts**: worktrees stop filesystem collisions but not two agents
   editing the same shared file on separate branches (AgenticFlict: 27.67% of AI-agent
   PRs had conflicts, rising with PR size).
3. **Cost/credit burn** is the #1 gripe everywhere (Qoder credits gone in hours; Claude
   teams ~$1–2.6k/mo/dev; Windsurf pricing confusion).
4. **Legibility wins hearts**: Qoder 专家团's praised "躺着当 CTO" feeling comes from a
   **canvas of named-role cards with per-agent progress bars + status (运行中/等待确认/
   已完成) + summary docs** — *visible orchestration*, not raw parallelism.

**Implication for claude-stray:** these pains *validate* a triage/oversight layer over
rebuilding orchestration. The cockpit already IS the thing Qoder users rave about
(cards + attention bands + per-session summaries) — just applied across *all* sessions
instead of one orchestrated task. Sub-cards extend it to parallel work. **This is the
north star, not a detour.**

## What the Claude Code research settled (build inputs)

- **Don't** build on agent-teams / teammates: lead-tied, land in a separate
  `subagents/agent-<id>.jsonl` namespace (verified on disk), not standalone
  human-resumable, experimental, expensive.
- **Do** reuse the native spawn primitive: `claude --bg --name <slug> "<prompt>"`
  → background session auto-isolated in `.claude/worktrees/<slug>/` (persistent,
  human-addressable), returns a session id, observable via its own jsonl +
  `claude agents --json`. Worktree + semantic name + observability **for free**.
  (Or keep our existing `/api/new-session` ttyd path — choice below.)
- Claude Code records **no parent/child link** between sessions → we track it ourselves.
- Sending a message to a child: we already have **`/api/send`** (inject via tmux/ttyd) —
  no agent-comms bus to build.

## Proposal: parallel sub-cards as a legible oversight layer

### The model (deliberately constrained)

**Human-as-orchestrator + parallel independent sub-sessions + attention triage.**
The cockpit provides three things and *only* three:

1. **A spawn primitive** — a parent card can fan out N sub-tasks; each is a *real,
   independent* claude session in its own worktree (semantic name), nested under the
   parent. Spawned via `claude --bg --name` or `/api/new-session` (see open question).
   The **decomposition** ("what are the sub-tasks") is decided by the human or the
   parent claude session — **not** by claude-stray.
2. **Global visibility for the parent** — the parent card aggregates its children's
   live status + one-line progress (read-only; reuses existing per-session summaries +
   live state). This satisfies "父卡理应有全局视野" with zero orchestration: it's
   rendering, not coordinating.
3. **Conflict-aware triage** (the differentiator no product nails) — when ≥2 sibling
   sub-cards' worktrees touch the **same files**, surface a **⚠ 可能冲突** warning on
   the parent. This directly attacks complaint #2, and is pure observation (diff the
   worktrees / `git diff --name-only` per child, intersect).

Attention bands (needs_you → running → idle → done) apply per sub-card; the parent
shows a roll-up. Each sub-card is independently driveable (its own terminal) and
message-able (`/api/send`).

### The red line (north star)

**We do NOT build:** a task-decomposition engine, an autonomous parent-agent loop that
polls/parses children and decides next steps, or a custom agent-to-agent comms bus.
That is "重造 agent". If programmatic coordination is wanted, it's the parent claude
session's job (via Claude Code's own subagents/workflows); we only *visualize* the
resulting independent sessions. The cockpit is the **legible oversight layer**, full
stop — which is exactly the unmet need the industry survey surfaced.

### Data model

- Card gains `parent_session_id` (and the parent implicitly has children = cards whose
  parent_session_id == its session). Nested render under the parent.
- Reuse DD-022 `code_location` (mechanical worktree/branch from cwd) — the sub-card's
  worktree is already known mechanically.
- Sibling conflict set computed at read time (no new persisted state).

## Open questions

- **`claude --bg` vs `/api/new-session` (ttyd)** as the spawn substrate. `--bg` gives
  worktree + supervisor + observability free but is "background, attach-on-demand" and
  research-preview ("may change"); our ttyd path is "a terminal you watch" and stable.
  Likely: offer `--bg` for fire-and-forget sub-tasks, ttyd for ones you drive — or start
  with the ttyd path we already have + DD-022 worktree, and adopt `--bg` later.
- **Who decomposes?** Human picks sub-tasks in a dialog, vs. the parent claude session
  emits them (it could call a `/stray spawn-subtask` skill / our endpoint). Start with
  human-driven (pure triage); allow agent-initiated spawn later without us coordinating.
- **Cost surfacing** (industry's #1 gripe): show per-sub-card token spend on the parent
  roll-up — cheap differentiator.
- **Conflict signal fidelity**: filename-overlap is a coarse first cut; semantic overlap
  is the real problem but harder. Ship filename-overlap first, label it as such.

## Rough plan (after DD-022 phase A lands — worktree data must be mechanical first)

1. `parent_session_id` on cards + nested sub-card render + parent status roll-up.
2. Spawn-as-sub-card from the new-task dialog (parent linkage + DD-022 worktree).
3. Conflict-aware ⚠ on siblings sharing files; optional per-card cost roll-up.
4. (Later) agent-initiated spawn (parent session calls our endpoint) — still no
   coordination loop on our side.

Sequence: DD-022 (mechanical worktree) is the prerequisite — sub-cards lean on it.

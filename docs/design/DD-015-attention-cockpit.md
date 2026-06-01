# DD-015: Attention cockpit — live session telemetry & interactive control

**Status**: Proposed — **top priority** (supersedes the DD-014 hero/three-tier layout as the primary product direction)
**Author**: Claude (with user)
**Date**: 2026-06-01

## Problem

Every layout we have shipped — the original card grid, and the DD-014
hero / thread-card-chip redesign — has the same product failure: **it is
still "a big pile."** The user's words:

> "无论是之前的卡片视图,还是现在优化后的,信息依然杂乱……通过 stray
> dashboard 我并不能感受到一个更简洁更清晰更完整上层的视图。之前的卡片
> 是一大堆,现在还是一大堆。"

> "问题的根源在于用户体验、信息分层、简洁、聚合、交互等等方面都不好,
> 它不一定是某个点去优化能解决的,我认为应该有一种更好的产品形态。"

The root cause is **not styling**. It is that stray was built as a
*visualization of work* ("how do I display all the initiatives?"),
which structurally produces a flat, equal-weight, taxonomy-sorted wall —
i.e. it reproduces the chaos it was meant to dissolve. The product has
**no opinion** about what matters, so it offloads scanning and
prioritization back onto the human, which is exactly the pain it exists
to remove.

Two further structural gaps make it a rear-view mirror rather than a
control surface:

1. **No live state.** We only summarize *after* the fact, in the `Stop`
   hook. The user cannot see, per session: is it running now? has it
   finished and been idle (waiting on me) for how long? what's the
   suggested next step? The single most expensive waste in a long-task /
   high-concurrency workflow — *an agent that finished and is sitting
   idle while the human doesn't know* — is invisible today.

2. **No way to act.** The dashboard is read-only. To act on a card the
   user must leave stray, find the right terminal/session, and re-enter
   context manually. The cost of context-switching between concurrent
   works is high, which directly suppresses the concurrency stray is
   supposed to enable.

### Product north star (the thing every decision serves)

> In the era where AI runs long tasks, give the human an **attention
> cockpit**: see at a glance *which works are in flight and where each
> one stands*, know *which one needs me now*, and *switch into any of
> them at near-zero cost* to push it forward. The scarce resource is
> the human's attention and decisions — the product's job is to
> allocate it.

## Goals / non-goals

**Goals**

- A single high-altitude view that is **concise without hiding the
  concurrency portfolio** — all *live* work stays visible; only *dead*
  work (done / long-parked) collapses.
- Organize by **attention state** (needs-you / AI-running / idle /
  done), not by workspace taxonomy.
- **Live, per-session** status with an *idle-since* timer, pushed in
  real time.
- A **per-session "next step"** suggestion.
- **Click a card/session → a web terminal** that shows the recent
  conversation and lets the user type to drive the session forward,
  including *attaching to a session that is currently running* (the
  user runs claude inside zellij).

**Non-goals**

- Not removing breadth. We explicitly reject the "inbox-zero" framing
  (see Alternatives). Conciseness comes from **density + ranking +
  visual weight**, not from reducing the number of items.
- Not redesigning identity/pipeline here — see *Identity model* below
  for the corrected sketch; full design tracked separately (candidate
  **DD-016**).
- Not a remote/multi-user tool. Strictly localhost, single user.

## Principles (the reframe)

1. **简洁 = 密度 + 排序 + 视觉权重,不是减少数量.** The old wall was
   bad because every card was an equal-weight fat tile at one altitude,
   sorted by workspace. 12 live works *can* be scanned in one sweep if
   each is one dense line, ranked by "does this need me", and visually
   weighted (the one that needs you is loud; the humming ones are quiet
   but present). Breadth and conciseness are not opposites.

2. **Project/line is the primary spatial grouping; attention is the
   visual weight + ranking.** (Revised after prototyping — the original
   "attention, not workspace" over-rotated: flat attention bands read as
   "all sessions dumped together", and the human switches context *by
   project*.) Group by workspace/cwd — a **stable** key (the directory,
   not an AI-minted id). Within a project, rank + visually weight by
   attention (needs-you loud, running calm, idle dim); sort projects by
   their most-urgent item so cross-project urgency still surfaces. A
   flat "by attention" view stays available as a toggle. See *Prototype
   outcomes*.

3. **Altitude / progressive disclosure.** Default = highest altitude
   (a one-line situational header + dense ranked rows). Drill into a
   row for full context; drill again into the terminal to act.

4. **Artifacts (MR / 需求 / PR / issue links) are the trustworthy
   spine.** They are deterministically extracted, human-meaningful, and
   — unlike AI-generated names/summaries — they do not flicker between
   runs. So: render them prominently on every work row; use their
   presence as a *ranking/importance signal* (real MR + 需求 > AI
   chatter), and — once present — as a strong *membership/merge hint*
   (a session referencing `MR!1234` already tied to initiative X →
   assign to X). They emerge *during* a session, so they are **not** the
   identity key (see *Identity model*) — they enrich ranking, grouping,
   and the row spine, not id creation. The user called this the one
   feature that works well; we lean into it.

## Identity model (corrected after review)

This DD does **not** redesign identity (full design → candidate DD-016),
but the earlier shorthand "anchor id to session_id / artifact" was wrong
on two counts the user flagged, so the corrected model is recorded here:

- **`session_id` is the immutable atom** (exists at session birth, never
  changes). It is the *substrate*; the initiative id is **not** equal to
  it.
- **An initiative is a *persisted set* of session_ids** with its own
  **code-minted, stored-once** id (may be seeded from the founding
  session). → *multiple sessions per initiative is native* — it is
  literally the membership set. (Answers objection #1.)
- **The AI is an assigner/labeler, not the id owner.** Each run it only
  answers, for a (mostly new) session: "which existing initiative id —
  from this fixed list — does this belong to, or is it new?" Existing
  memberships are frozen; merges/splits are explicit, guarded, logged
  ops. The AI can never re-mint a fresh slug for old work — which is
  what causes today's flicker / duplication / resurrection.
- **Artifacts are not the identity key.** They emerge *during* a session
  (objection #2), so they cannot anchor identity at birth. They serve as
  (a) a ranking/importance signal and (b) a strong *membership/merge
  hint* once present. They enrich grouping and display, not id creation.
- **Tombstones key on member session_ids, not just the id** (the archive
  path already does time-windowed session tombstoning; deletion must
  too) — so a deleted initiative's still-hot sessions stay tombstoned
  instead of re-clustering under a new slug. (Also fixes the live
  resurrection bug found in the diagnosis.)

**This narrows AI's *identity* power, not its intelligence.** AI still
owns every semantic job: per-session summarize, naming, progress, the
cockpit's state classification (needs-you / running / blocked),
`next_step`, artifact extraction, and *proposing* merges/splits. We
remove only its ability to mint/rewrite ids each run — the one thing it
does badly and that drives today's instability. Its effort is redirected
from re-deriving a fragile taxonomy (which the post-process then largely
discards) to the judgments that can't be mechanized — a *better* use of
AI, not a smaller one.

## Decision — the cockpit layout

> **This is an information wireframe, not a visual spec.** The ASCII
> below fixes only *priority and what each row carries* — deliberately
> not the look. It reads as crude on purpose; **do not implement it
> literally.** Typography, density, color, and motion are settled in a
> separate hi-fi HTML prototype pass with real `dashboard.json` data,
> iterated for aesthetics before any visual is locked.

A single ranked board. All *live* work visible as one dense row each,
banded by attention state, idle-sorted within bands. Dead work
collapses.

```
12 进行中 · 2 等你 · 5 AI在跑 · 5 闲置        [今天完成 6 ▸] [搁置 9 ▸]
━━ ⚠ 等你 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
● HSF 单元化路由调试    AI卡在灰度决策·等你 2h12m   🔗MR!1234 需求#567  [→]
● dubbo attachment 转换 测试挂了要你看              🔗MR!2201          [→]
━━ ◐ AI 在跑 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
● claude-stray 重构    ▓▓▓▓▓░ 正在改前端           🔗MR!88            [→]
● mw-cli 单元列表       ▓▓▓░░░ 正在写实现           需求#430           [→]
  …(还有 3 条,行更矮、色更淡)
━━ ○ 闲置 / 等输入 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
· kryo classloader     3 天没动                    🔗MR!77
  …
━━ ✓ 今天完成 (6) ▸    ⏸ 搁置 (9) ▸ ━━━━━━━━━━━━━━━━━━━━━━━━━
```

Row anatomy: status dot · **work name** · live activity / blocker /
idle-timer · **artifact links (spine)** · `[→]` enter terminal.

**Granularity.** Live state and the terminal are inherently
*per-session*; a card is a *cluster of sessions*. Resolution:

- A card row shows the **aggregate** state (worst/most-urgent of its
  sessions: needs-you > running > idle).
- Expanding a card reveals its **live sessions**, each with its own
  status dot and `[→]`.
- A single-session card's `[→]` enters its session directly; a
  multi-session card's `[→]` opens a session picker (default = the most
  recently active).

## Prototype outcomes (2026-06-01) — validated decisions

An interactive hi-fi prototype on real `dashboard.json` data lives at
`docs/design/prototypes/dd-015-cockpit/` (open `index.html`). The
**interaction model is settled**; visual polish is deferred. Locked in:

- **Two views (toggle):** `按项目` (default) and `按注意力` (flat bands).
- **Stream rollup = high-altitude default:** each project/line collapses
  to one summary line (counts + most-urgent snippet + per-item status
  strip + timer); the most-urgent stream auto-expands. Line → its items
  → item detail + actions. (Fixes "still a big pile" — ~7 calm lines.)
- **Tiers:** `主线` (persistent work) vs `支线 · 个人/兴趣`; user-/AI-set.
- **Draggable priority:** streams reorder by drag, persisted; AI may
  propose an order (not yet wired).
- **Mindmap nav** (`全部 → 项目 → 任务`): collapsible top overview, curved
  connectors, click a node to jump/expand.
- **Animated status icons** (not flat dots): spinner = running, pulsing
  ring = needs-you, hollow = idle, ✓ = done, ⏸ = paused.
- **Light + dark themes**, toggle, persisted.
- Deferred: further visual/aesthetic polish.

## Capability A — live session telemetry (hooks → state → SSE)

Extend the hook set (today only `Stop` + `SessionStart`). Each hook
appends to a per-session live-state file `cache/live/<session_id>.json`;
`serve.py` watches the dir and pushes changes over **SSE** to the
cockpit.

| Event | Hook | Writes |
|---|---|---|
| user sent a prompt, AI working | `UserPromptSubmit` | `state: running`, `started_at` |
| AI turn ended | `Stop` | `state: idle`, `idle_since` |
| AI needs permission / input | `Notification` | `state: needs_you`, `reason` |
| session opened | `SessionStart` | register; capture **zellij coords** (`$ZELLIJ_SESSION_NAME`, `$ZELLIJ_PANE_ID`, cwd) |
| session ended | `SessionEnd` | deregister |

`idle_since` powers the cockpit's most important sort: within the
idle/needs-you bands, **the longest-waiting session ranks first** — this
is the "don't let a finished agent sit idle" signal.

`serve.py` gains `GET /api/events` (SSE). The cockpit subscribes once
and updates rows in place (no full re-render — also fixes the existing
`board.innerHTML=''` teardown-on-every-poll problem from the frontend
diagnosis). Polling `/api/data` every 8s is retired in favor of push.

Risk surface: **zero new RCE surface.** Pure hooks + files + read-only
SSE. This is why it ships first.

## Capability B — per-session next step

`bin/summarize.py` (Layer 1) already reads the whole session. Add a
`next_step` field to its frontmatter (prompt change in
`prompts/summarize-session.md`). It surfaces on the row ("建议:跑集成
测试 / 等你确认灰度策略") and in the terminal header. Cheap, low risk.

## Capability C — web terminal (look at recent conversation + drive it)

Click `[→]` → a panel with a **hybrid view**:

- **Top**: the last N turns of the conversation, rendered from the
  session jsonl as readable bubbles (read-only, easy to scan).
- **Bottom**: a live terminal (`xterm.js`) + input, attached to the
  actual session.

Two attach modes, by live state:

- **Session is running** (the user runs claude in **zellij** — confirmed)
  → attach to its zellij pane using the coords captured at
  `SessionStart`. Real two-way mirror + control of the live TUI.
- **Session is idle / ended** → spawn `claude --resume <session_id>` in
  a fresh PTY. Resume replays context; the user types to continue.

**Transport.** Recommended: spawn **`ttyd`** (tiny single binary,
`brew install ttyd`) bound to `127.0.0.1` on an ephemeral port with a
one-time token, fronting either `zellij attach …` or `claude --resume
…`; embed it in the panel. This avoids implementing WebSocket+PTY in
Python's stdlib `http.server` and keeps with the project's
"POSIX-tools, no heavy deps" leaning. Alternative: a vendored Python
WS↔PTY bridge (more code, one fewer external dep). Decide at build time
(open question Q3).

## Security model (Capability C only)

> **Deferred — not a current concern.** Stage 1 (telemetry) and Stage 2
> (next-step) have **zero** security surface, so security does not block
> the priority path. This section applies only when Capability C is
> actually built; design it then.

Capability C turns serve.py from a **read-only viewer** into a **local
service that can spawn shells and send messages to AI** — a localhost
RCE surface. The user has explicitly accepted this trade-off. Required
controls:

- Bind strictly to `127.0.0.1`; never `0.0.0.0`.
- Per-terminal **one-time token** in the URL; reject unauthenticated WS/
  ttyd connections.
- **Off by default**, enabled by an explicit flag (e.g.
  `stray --serve --enable-terminal`); the flag state is shown in the UI.
- Telemetry (A) and next-step (B) remain on the safe read-only path and
  are unaffected by this flag.

## Decisions locked (from the design conversation)

- **The user runs claude inside zellij** → attach-to-live (Capability C
  mode 1) is feasible via zellij pane coordinates.
- **The user accepts** stray becoming a PTY-spawning / message-sending
  local control console (gated as above).
- Product axis is **attention-state**, not workspace; breadth is
  preserved (no inbox-zero).

## Changes by component

| File | Change |
|---|---|
| `~/.claude/settings.json` (installer) | register `UserPromptSubmit`, `Notification`, `SessionEnd` hooks (add to existing `Stop`, `SessionStart`) |
| `bin/` hook scripts | new tiny scripts that write `cache/live/<sid>.json`; `SessionStart` also records zellij coords |
| `bin/serve.py` | `GET /api/events` (SSE) watching `cache/live/`; terminal launcher (`ttyd`/bridge) behind `--enable-terminal`; token auth |
| `bin/render-html.py` | replace card wall with the cockpit board; SSE client + in-place row updates (drop full-`render()` polling); artifact spine on rows; terminal panel (xterm/iframe) + hybrid conversation view |
| `bin/summarize.py` + `prompts/summarize-session.md` | emit `next_step` per session |
| `bin/install.sh` / installer | new hooks; optional ttyd presence check |
| `docs/design/README.md` | index row for DD-015 |

## Migration

- Live-state files are **additive** (`cache/live/`); absent files →
  session simply shows no live state (graceful for pre-upgrade
  sessions). No dashboard.json schema change required for A/B.
- The cockpit reads the *same* dashboard.json initiatives; it is a new
  presentation, so no data migration. DD-014 `level`/`parent_thread_id`
  fields become advisory inputs to banding (or are dropped — see Q2).
- New hooks are idempotent and safe to add to existing installs.

## Cost / risk

- **Telemetry/SSE**: negligible token/CPU cost; main risk is stale
  state if a hook misfires → add a heartbeat + "last seen" so a crashed
  session decays to `unknown` rather than lying as `running`.
- **next_step**: a few extra output tokens per Layer-1 summary.
- **Terminal**: the real risk concentration (RCE surface, ttyd
  dependency, zellij-attach mechanics). Mitigated by flag-gating,
  localhost+token, and shipping it last.
- **zellij attach** mechanics (mapping session_id → pane, attaching
  without disrupting the user's own zellij client) need a POC (Q1).

## Alternatives considered

- **Inbox / triage (show only "needs you", collapse the rest).** First
  proposal. Rejected: an inbox optimizes for emptying to zero and hides
  the concurrency portfolio, which *reduces* the user's ability to
  juggle and choose — the opposite of the goal. User: *"如果收件箱中
  呈现的任务太少,可能会降低并发度,用户也难以把控当前重要的事情。"*
  The cockpit keeps all live work; only dead work collapses.

- **Keep iterating the DD-014 hero/thread layout.** Rejected: DD-014's
  thread tier ships with **0 populated members** (every thread is an
  empty shell), filter/search only touch `.card` so they don't filter
  the hero/threads/rail, and effort went into visual reskins while the
  real pain (no triage, no live state, no action) was untouched. Pretty
  walls don't fix a missing opinion.

- **Narrative-only digest** ("状态播报" paragraph). Kept as the cockpit's
  one-line header, not the whole view — prose alone is too vague to
  juggle 10 works from.

- **Chat box instead of a real terminal** (`claude -p --resume` headless,
  rendered as bubbles). Rejected as the primary path: loses the
  interactive TUI, permission prompts, and the live-attach story the
  user asked for. The hybrid view keeps a rendered conversation *and* a
  real terminal.

## Staging (this is the priority order)

1. **Stage 1 — live telemetry + cockpit** (A): hooks → `cache/live/` →
   SSE → cockpit board with live status + idle-sort + artifact spine.
   No security surface. **Highest value/effort ratio — start here.**
2. **Stage 2 — next step** (B): summarizer field + row display.
3. **Stage 3 — web terminal** (C): idle `--resume` first, then
   zellij attach-to-live; flag-gated, token, localhost.

## Open questions (verify before/at build)

- **Q1**: zellij attach mechanics — how to map `session_id` → zellij
  pane and attach a *second* viewer without stealing the user's focus.
  Needs a POC.
- **Q2**: do DD-014 `level`/`parent_thread_id` survive as banding hints,
  or are they retired now that bands are attention-state driven?
- **Q3**: terminal transport — `ttyd` (external binary) vs a vendored
  Python WS↔PTY bridge.
- **Q4**: confirm the exact current Claude Code hook names/payloads and
  `claude --resume` flag behavior (cutoff-era assumption; verify against
  the installed version).

## Carry-over from the current dashboard (must not lose)

- **The pixel cat + tips bubble.** The current dashboard has a walking
  pixel cat that surfaces tips. Deliberately *not* drawn in the cockpit
  prototype, but it **must be carried over when implementing** — the
  user values it. It fits the cockpit as an ambient idle-corner element
  and a natural channel for `next_step` / wellness tips (cf. DD-006).

## References

- The diagnosis conversation that produced this DD (2026-06-01): product
  reframe (visualization → attention cockpit), the breadth-vs-triage
  correction, and artifacts-as-spine.
- The architecture diagnosis (same session): AI-minted-slug identity
  instability, 5 overlapping suppression mechanisms, the 6.9k-line
  render-html monolith. The corrected identity model (see *Identity
  model* above) is the convergent fix — full design out of scope here
  (candidate DD-016).
- DD-014 — the hero/three-tier layout this supersedes as primary
  direction.
- DD-006 — card-derived AI features (weekly report, next-steps, tips):
  `next_step` here is the per-session, live counterpart.

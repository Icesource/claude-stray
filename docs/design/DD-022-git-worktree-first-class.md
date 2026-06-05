# DD-022: Git worktree as a first-class workspace

**Status**: Proposed (design; not yet implemented)
**Author**: Claude (with user)
**Date**: 2026-06-06
**Predecessors**: DD-018 (session interaction / single-driver), DD-021 (resources),
project pivot "card = one session"

## Why (the user's words)

> 当新建任务卡片的时候，能够自动新建一个 worktree 并与之关联，worktree 目录要有
> 统一的管理模式，最好 worktree 目录名称能体现任务的语义而不是无意义的编号；
> 若有多个任务必须在一个 worktree 工作，dashboard 能显示它们是关联的并警示用户
> 最好不要并行去对话修改。

Two concrete problems today:

1. **Worktree data is missing / wrong.** A card's 代码位置 shows `branch` but never the
   worktree path. Measured: **0 `worktree` artifacts** across the whole dashboard,
   because Rule 10 asks the AI to *extract* a worktree path from the transcript and
   transcripts essentially never state it. AI extraction is the wrong mechanism.
2. **Worktrees aren't a first-class concept.** New tasks land wherever the user
   happens to `cd`; there's no auto-creation, no naming convention, no way to see
   that two cards share a working directory.

## Research: what Claude Code already gives us (DD-022 leans on this)

(From the Claude Code docs — https://code.claude.com/docs/en/worktrees.md, sessions.md)

- **Native worktree support exists**: `claude --worktree <name>` (`-w`) creates a
  git worktree at **`.claude/worktrees/<name>/`** on branch **`worktree-<name>`**
  (from `origin/HEAD`/HEAD), and starts a **new session in it**. There are
  `EnterWorktree`/`ExitWorktree` tools; the desktop app makes a worktree per session.
- **Session is directory-bound**, not worktree-bound: `claude --resume <sid>` re-runs
  in the session's original cwd (and resets out-of-project cwds unless `--add-dir`).
- **Naming convention**: semantic `<name>` under `.claude/worktrees/`; recommend
  gitignoring `.claude/worktrees/`. Auto-gen fallback is `<adj>-<adj>-<animal>`.
- **Concurrency hazard is real but unenforced**: two *resumes of the same session*
  interleave one transcript (use `--fork-session`/`/branch`). Two *different* sessions
  in the *same worktree* don't corrupt transcripts but **race the git index + files**.
  Claude Code does **not** auto-detect either — it's operator discipline.
- **No SDK/API to query a session's worktree/branch.** External tools must **infer
  from cwd** (map session cwd → `git worktree list`) or parse Bash outputs.

**Key takeaway:** the worktree association must be **mechanical, from the session's
cwd** (which the cockpit already reads from the jsonl) — never AI-extracted. And our
existing single-driver invariant (DD-018) is the same hazard Claude Code documents,
so we're philosophically aligned: extend it to "single driver per *worktree*", not
just per session.

## Proposal

### A. Mechanical worktree association (fixes the data bug) — phase 1

Stop asking the AI for worktree paths. Instead, `serve.py`/`classify.py` derive, for
each session, a mechanical `worktree` from its **cwd**:

- For a session's cwd, run (cached) `git -C <cwd> rev-parse --show-toplevel` +
  `git worktree list --porcelain` (or check `--git-common-dir` ≠ `--git-dir`).
- If cwd is a linked worktree: record `{path: <worktree root>, branch: <branch>,
  is_worktree: true, main: <main repo root>}`. If it's the main checkout:
  `is_worktree: false` (still record branch).
- Surface this as the card's **代码位置** (replacing the AI `worktree`/`branch`
  artifacts). Drop the Rule 10 `worktree` type and de-emphasize `branch` extraction —
  the mechanical value is always right and free.

This alone makes 代码位置 trustworthy (real path + real branch), which is what the
user actually wanted to see.

### B. New task → auto worktree (semantic name) — phase 2

Extend the `＋ 新建任务` flow (`/api/new-session`): optionally **create a worktree**
for the new task instead of a bare `cd`.

- Use Claude Code's native path: `claude --worktree <slug>` so we inherit its
  conventions (`.claude/worktrees/<slug>/`, branch `worktree-<slug>`, gitignore).
- **Semantic name**: ask for a one-line task description in the new-task dialog and
  derive a kebab **slug** from it (e.g. "修 HSF 鉴权超时" → `hsf-authz-timeout`),
  not `new-<hash>`. Keep a short uniquifier only on collision.
- The dialog gains: working repo (existing picker) + "在新 worktree 里开" toggle +
  task-name field. Off → today's behavior (plain `claude` in cwd).
- Once the session has activity, the card materializes (existing pipeline) and its
  代码位置 already shows the worktree (phase A, mechanical).

### C. Unified view + multi-task-same-worktree warning — phase 3

- **Group/associate** cards by worktree: if ≥2 live cards resolve to the **same
  worktree path**, the dashboard links them visually and shows a **⚠ warning**:
  「这些任务在同一个 worktree，别并行对话修改」(they race files + the git index).
  Detection is mechanical (same resolved worktree root). This is the user's
  "显示关联 + 警示" ask.
- Tie into the **single-driver gate** (DD-018): the gate already blocks a second
  `resume` of a live session. Extend the *warning* (not a hard block) to "another
  live session is editing this worktree".
- Optional **worktree column/lens**: list worktrees, each with its card(s), branch,
  and dir (one-click `cd`/open) — makes worktree usage "natural and clear".

## Schema / touch points

- `dashboard.json` card: add `code_location: {worktree, branch, is_worktree, main_repo}`
  (mechanical), gradually replacing AI `branch`/`worktree` artifacts.
- `serve.py`: cwd→worktree resolver (cached, POSIX `git` shell-outs); `/api/new-session`
  gains `{worktree: bool, task_name}`; multi-card-same-worktree detection for the warning.
- `cockpit.html`: render 代码位置 from `code_location`; worktree warning badge; new-task
  dialog fields.
- `prompts/summarize-session.md`: drop `worktree` artifact type; soften `branch`.

## Open questions

- **Auto-create: opt-in or default?** Lean opt-in (toggle, remembered) — not every task
  wants a worktree; some are throwaway or in the main checkout.
- **Worktree root**: follow Claude Code's `.claude/worktrees/` per-repo (gitignored), or
  a central `~/worktrees/<repo>/<slug>`? Default to the native `.claude/worktrees/` so
  `claude --worktree` "just works".
- **Lifecycle**: when a card is archived/done, offer to remove its worktree
  (`git worktree remove`)? Or leave it (safer). Probably surface, don't auto-remove.
- **Does the "multiple tasks in one worktree" scenario even happen?** Likely rare and
  usually an accident → the value is *detecting + warning*, not supporting it well.

## Rough plan

1. **Phase A** (small, high value): cwd→worktree resolver + `code_location` on cards +
   render it. Fixes the data bug immediately, no AI.
2. **Phase B**: new-task worktree toggle + semantic slug + `claude --worktree`.
3. **Phase C**: same-worktree association + warning; optional worktree lens.

Phase A is worth doing first regardless of B/C — it's the actual bug the user hit.

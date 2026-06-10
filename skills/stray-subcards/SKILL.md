---
name: stray-subcards
description: |
  Fan out parallel SUB-CARDS from the current Claude Code conversation via
  claude-stray (`stray spawn`), pull their progress (`stray subtasks`), and
  relay a message into one (`stray send`). Activate when the user says any
  of: 子卡 / 子任务 / 拆成子卡 / 拆出去并行 / 并行子卡 / fan out / spawn a
  sub-card / sub-task under stray — or asks how their sub-cards are doing.
  Also activate to PROPOSE a split when the conversation just produced a
  list of clearly independent work items (propose only — never spawn
  without explicit user confirmation). Do NOT use the built-in Task /
  sub-agent tools as a substitute: those are invisible to the stray
  dashboard and are NOT sub-cards.
---

# stray-subcards — fan out parallel sub-cards from a conversation

## What a sub-card is

`stray spawn "<task>"` gives a sub-task its own **git worktree + branch +
resumable Claude Code session + a card nested under the current card** on the
stray dashboard (http://127.0.0.1:9876/). The user watches all of them there,
opens any card's embedded terminal to drive it, and later **merges the branch
back from the dashboard** (an AI merge-agent resolves conflicts; the user
lands the fast-forward).

This is the ONLY way to create a real sub-card. The built-in Task tool /
background agents are stray-invisible — never present them as sub-cards.

## The three primitives

| Action | Command | Notes |
|---|---|---|
| Fan out one sub-task | `stray spawn "<task>" [--name <slug>]` | One call per sub-task. Uses `$CLAUDE_CODE_SESSION_ID` as parent — run it via the Bash tool inside this session, from the repo directory the work belongs to. |
| Pull progress digest | `stray subtasks` | Low-token JSON of this session's children (status/progress/blockers/next step). On demand only — never poll in a loop. |
| Relay one message | `stray send <session_id> "<text>"` | Human-directed, one-shot nudge into a child's live terminal. |

## Workflow (the rules that matter)

1. **The user decides the split.** Two entry shapes:
   - The user explicitly asks ("把这三件事拆成子卡并行") → draft the split.
   - You notice the conversation just produced N clearly independent items →
     you MAY propose once: "这几件互相独立,要拆成子卡并行跑吗?" — and stop.
2. **Show the split before spawning.** List the planned cards (name + the
   exact task prompt each child will be seeded with) and get an explicit yes.
   Adjust granularity to whatever the user says — they own the cut.
3. **Spawn one `stray spawn` per item** (Bash tool). Each child starts
   IMMEDIATELY in its own worktree; report the created card names back.
4. **Write each task prompt self-contained**: the child session has no access
   to this conversation. Include file paths, acceptance criteria, and the
   instruction to commit its work (un-committed work cannot be merged back).
5. **Progress on demand only.** When the user asks how the children are
   doing, run `stray subtasks` and summarize. No autonomous polling loops.
6. **Merge closure happens in the cockpit, not here.** When children look
   done, remind the user: open http://127.0.0.1:9876/ and click 合并 on the
   sub-card (an AI merge-agent resolves conflicts, then 落地 fast-forwards
   the parent branch and auto-closes the card). Do not run `git merge`
   yourself and do not try to trigger the merge from this conversation.

## Failure modes

- `spawn 失败(serve 没在跑?)` → the dashboard isn't up; ask the user to run
  `stray --serve` (or check `STRAY_PORT` if they moved it off 9876).
- "无 $CLAUDE_CODE_SESSION_ID" from `stray subtasks` → the command must run
  inside a Claude Code session (Bash tool), not a plain shell.
- spawn requires the cwd to be inside a git repository, and `tmux` installed.

## What NOT to do

- Never spawn without the user's explicit confirmation of the split.
- Never substitute the built-in Task tool / `claude agents` for a sub-card.
- Never run an autonomous coordination loop over the children — single
  driver is the product's core principle; the human steers from the cockpit.

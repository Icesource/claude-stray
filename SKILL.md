---
name: stray
description: |
  claude-stray is a local web dashboard at http://127.0.0.1:9876/
  that visualizes the user's Claude Code session history as cards.
  It is read primarily by the HUMAN, not by you. Activate this SKILL
  when the user wants to (1) install or uninstall claude-stray, or
  (2) ask you to perform a small management action on the dashboard
  — open it, refresh its cache, pause/resume the plugin's own AI
  pipeline, or check how much THIS PLUGIN has spent. Do NOT activate
  for general Claude Code questions, total Claude usage costs, or
  agent-driven analysis of the user's work — none of those are what
  this tool does.
---

# stray — Claude Code dashboard (human-facing)

## What this is

A self-hosted web dashboard at `http://127.0.0.1:9876/` that turns
the user's Claude Code session jsonl files into a cards view. The
**user reads it** — there's a sidebar, status filters, blocker chips,
weekly report, tips bubble, a walking pixel cat, etc. It is a
**visualization tool for the human**, not a query interface for an
AI agent.

## What this is NOT (be honest with the user)

| If the user says | This SKILL does NOT do that |
|---|---|
| "What am I working on" | We can offer to open the dashboard so they see it themselves. We do NOT narrate the cards. |
| "How much have I spent on Claude this month" | We only track AI costs from claude-stray's own pipeline calls — Layer 1 summarize / Layer 2 classify / derived features. The user's broader Claude Code usage is not tracked here. Say so explicitly. |
| "Pause Claude / stop the AI" | We can only pause **this plugin's** background pipeline. Claude Code itself keeps running normally. |
| "Tell me about my HSF MR work" | We can open the dashboard. We do NOT summarize the cards in chat — the dashboard already does that. |

When ambiguous, ask: "Do you mean the claude-stray plugin, or
Claude Code overall?"

## When to activate

Narrow triggers — only these:

1. **Install / uninstall** — user wants to set up claude-stray on
   their machine, or remove it.
2. **Open the dashboard** — user wants the browser tab opened (`stray --serve`).
3. **Refresh the cache** — user wants the latest sessions reflected
   on the dashboard (`stray --refresh`).
4. **Pause / resume the plugin** — user wants to temporarily stop
   this plugin's background AI pipeline (e.g. before a demo).
5. **Check the plugin's own cost** — user asks specifically about
   this plugin's AI spend.

If you're not sure the user is talking about this plugin, **ask**
before invoking commands.

## Install

```bash
git clone https://github.com/Icesource/claude-stray.git ~/Code/claude-stray
cd ~/Code/claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # makes this SKILL active locally
```

`bin/install.sh` sets up: slash commands `/stray` + `/stray-refresh`,
shell wrapper `~/.local/bin/stray`, and Claude Code Stop +
SessionStart hooks (so the dashboard updates automatically as the
user finishes sessions). It does not run any AI calls.

After install, suggest the user open the dashboard:

```bash
stray --serve
```

— this opens `http://127.0.0.1:9876/` in their default browser.

## Management commands (use sparingly, on user request)

| User asks | Run |
|---|---|
| "Open the dashboard" | `stray --serve` (background it if user is mid-task) |
| "Refresh the dashboard / re-classify" | `stray --refresh` (~$0.17 with Haiku) |
| "Pause the claude-stray plugin" (with optional reason) | `stray --pause "<reason>"` |
| "Resume the claude-stray plugin" | `stray --resume` |
| "How much has this plugin cost me?" | `stray --cost` (default = today + last 7 days) |
| "Diagnose why session X isn't on the dashboard" | `stray --diagnose <session-id>` |

Full flag list is in `bin/stray --help` — read it on demand rather
than memorizing.

## Uninstall

```bash
cd ~/Code/claude-stray
bash bin/uninstall.sh           # default — safe, leaves user data
bash bin/uninstall.sh --purge   # also wipes cache + (y/N) session transcripts
```

Default removes the 5 things claude-stray put on the user's machine:
slash commands, shell wrappers, this SKILL (`~/.claude/skills/stray/`),
the Stop/SessionStart hook entries in `~/.claude/settings.json`, and
any leftover macOS launchd plist. Repo source, local cache, and the
user's Claude Code session transcripts are intentionally kept.

`--purge` additionally wipes the local `cache/` and prompts before
deleting `~/.claude/projects/-Users-<you>-Code-claude-stray/`
(the user's actual conversation transcripts — irreversible).

## Repository

<https://github.com/Icesource/claude-stray>

For deeper docs (architecture, design decisions, troubleshooting),
read the repo's `docs/` tree on demand. Don't preload that context
unless the user is actively troubleshooting.

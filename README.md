# claude-stray

A local companion for Claude Code that turns your session history into a
playful, AI-classified work dashboard. Cards, tasks, weekly recaps, cost
tracking — plus a walking pixel cat who reads you poetry.

[中文文档](docs/README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Roadmap](docs/ROADMAP.md) · [Release model](docs/RELEASE.md) · [Changelog](CHANGELOG.md)

![dashboard preview](docs/assets/screenshots/en/01-overview.png)

<details>
<summary>More screenshots</summary>

| | |
|---|---|
| ![card detail](docs/assets/screenshots/en/02-card-detail.png) | Card detail: blockers, artifacts, tri-state tasks, sessions to resume |
| ![tips bubble](docs/assets/screenshots/en/03-tips-bubble.png) | Walking pixel cat + the rotating tips bubble (drag it anywhere, click to cycle) |
| ![weekly report](docs/assets/screenshots/en/04-weekly-modal.png) | Auto-generated weekly report (Fri 12:00 local) |
| ![status filter](docs/assets/screenshots/en/05-filter-active.png) | Status filter + sidebar workspaces |

</details>

## What it does

`claude-stray` watches your `~/.claude/projects/*.jsonl` session files,
sends them through a 3-layer Haiku pipeline (extract → per-session
summarize → cross-session classify), and renders the result as:

- A **dashboard** at `http://127.0.0.1:9876/` with one card per
  initiative — summary, progress, tasks (tri-state: pending / done /
  cancelled), blockers, artifacts (CR / MR / PR / issue / branch),
  workspace sidebar, status filters, search.
- A **weekly report** auto-generated every Friday at noon.
- **Next-steps suggestions** — 3 data-anchored recommendations on
  what to focus on.
- A **tips bubble** with 20 curated, source-linked entries per batch
  (poems, etymology, programming history) — rotates every 25 s, drag
  the bubble anywhere on the page.
- **Cost tracking** — `stray --cost` shows token spend per layer
  per day / week / month.
- **Lifecycle pause/resume** — kill switch on the dashboard banner
  so AI doesn't run during demos / focused time.

Nothing leaves your machine except outbound Anthropic API calls.

## Install

### Option A — one-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

This is plain shell — Claude Code is not involved in the install path.
The script does pre-flight checks, clones the repo into
`~/.claude-stray/` (override with `INSTALL_DIR=/your/path`), runs
`bin/install.sh`, and installs the SKILL into `~/.claude/skills/stray/`.

> **About `~/.claude-stray/`.** This is the tool's own home directory
> — same convention as `~/.fzf`, `~/.nvm`, `~/.oh-my-zsh`. Don't
> `mv` it or `rm -rf` it manually; the slash commands, the hooks,
> and the `stray` CLI all hold absolute paths into it. Updates are
> `cd ~/.claude-stray && git pull` (or rerun the curl-pipe). To
> change location, use `bin/uninstall.sh` first then reinstall with
> `INSTALL_DIR=<new path>`.

Want to read the script before piping?
[`bin/quick-install.sh`](bin/quick-install.sh).

Tweakable via env vars before the pipe:

```bash
INSTALL_DIR=~/code/claude-stray \
INSTALL_REF=v0.6.1 \
LANG_CHOICE=en \
NO_SKILL=1 \
  curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

### Option B — manual, fully transparent

```bash
git clone https://github.com/Icesource/claude-stray.git ~/.claude-stray
cd ~/.claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # optional — installs the SKILL so the main agent auto-uses stray
```

`bin/install.sh` sets up:

- Slash commands `/stray` and `/stray-refresh` (plus legacy `/mindmap*`
  aliases, removed in v0.7)
- `~/.local/bin/stray` shell wrapper (plus a `mindmap` alias)
- Claude Code `Stop` + `SessionStart` hooks at
  `~/.claude/settings.json`

### After install

```
/stray-refresh        # in Claude Code — first refresh takes ~30-120s
stray --serve         # in terminal — opens http://127.0.0.1:9876/
```

After the first refresh, the dashboard updates on every session via
the hooks; the in-process scheduler handles tips (every 2h) and the
weekly report (Fri noon).

> **A note on installing via Claude Code prompts.** Earlier drafts of
> this README suggested pasting `Read <SKILL URL> and install it` into
> Claude Code. Claude Code (rightly) treats that pattern as a prompt-
> injection vector and refuses. The install must run in plain shell;
> the SKILL only kicks in after install to help the main Claude Code
> agent use the tool naturally.

### Requirements

- Python 3.9+
- `claude` CLI logged in (Claude Code Pro/Max subscription works —
  no separate API key needed)
- macOS or Linux (Windows via WSL)

## Usage

### CLI

```bash
stray --serve              # dashboard at http://127.0.0.1:9876/ (recommended)
stray                      # terminal tree of current cache (zero AI call)
stray --refresh            # force re-classify, then render
stray --cost               # today + last-7-days cost breakdown
stray --cost month         # full month breakdown
stray --diagnose [SID]     # why doesn't session X show up?
stray --pause "demo prep"  # kill switch — no background AI until --resume
stray --resume             # release kill switch
stray --weekly-report      # generate last week's report
stray --next-steps         # 3 suggestions on what to focus on next
stray --help               # full flag list
```

`mindmap` works as a legacy alias for every flag; both names point at
the same script.

### Slash commands

```
/stray              # render cached dashboard tree in the chat
/stray-refresh      # force refresh then render
```

### Inside Claude Code

The SKILL (see [Option A](#option-a--one-line-install-via-skill))
makes the main Claude Code agent aware of stray. Once installed, you
can just ask:

- "What am I working on this week?"
- "How much have I spent on Claude this month?"
- "Show me what's blocked"
- "Resume my HSF MR cleanup session from Tuesday"

Without explicit `stray` invocations.

## Costs

Three-layer pipeline runs lazily — only when a hook fires or the
dashboard scheduler ticks. Per-layer typical costs (Haiku-4.5):

| Layer | When | Per run |
|---|---|---|
| Layer 1 — summarize | Stop hook per session | ~$0.04 |
| Layer 2 — classify | Coalesced; ~5×/day in active use | ~$0.17 |
| Tips | Every 2 h while `--serve` is up | ~$0.08 |
| Weekly report | Fri 12:00 local | $0.10–$0.50 |
| Next-steps | After each classify | ~$0.05 |
| Wellness | Piggybacks on tips; only fires if signal | ~$0.02 max |

Hard guards: 15-minute cooldown on classify, dirty-tracking skips
unchanged sessions, daily budget cap via `--max-budget-usd` on every
`claude -p` invocation.

Watch live: `stray --cost` (default: today + 7-day table) or
`stray --cost month`.

Override defaults:

| Env var | Default | Effect |
|---|---|---|
| `CLAUDE_WORKTREE_MODEL` | `claude-haiku-4-5-20251001` | Layer 2 model |
| `CLAUDE_WORKTREE_COOLDOWN_SECS` | `900` | Min secs between classifies |
| `CLAUDE_WORKTREE_TIMEOUT` | `600` | `claude -p` timeout |

## Data model

Initiatives → sessions → tasks. The full schema and the design
decisions behind it live in [`docs/design/`](docs/design/). Recent
landmarks:

- [DD-002](docs/design/DD-002-ai-pipeline-redesign.md) — 3-layer
  pipeline architecture
- [DD-005](docs/design/DD-005-lifecycle.md) — opt-in pause/resume
- [DD-006](docs/design/DD-006-card-derived-ai-features.md) — weekly /
  next-steps / tips / wellness
- [DD-011](docs/design/DD-011-task-model-final.md) — tri-state task
  model, single-store data, no archive directory

## Troubleshooting

Most issues are one of:

1. **Dashboard empty** — run `stray --refresh` once
2. **Card didn't update** — hooks may be missing; rerun `bin/install.sh`
3. **Session missing** — `stray --diagnose <sid>` walks the pipeline
   and tells you which step dropped it
4. **Costs feel high** — `stray --cost month` for the per-layer
   breakdown; common culprits documented in
   [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

The SKILL ([`SKILL.md`](SKILL.md)) embeds the full decision tree so
Claude Code can walk users through it without `--diagnose`.

## Uninstall

```bash
bash bin/uninstall.sh           # default — safe, leaves your data alone
bash bin/uninstall.sh --purge   # also wipes cache + session transcripts (y/N gated)
```

Default removes the 5 things we put on your machine: slash commands,
CLI wrappers, the SKILL at `~/.claude/skills/stray/`, hook entries in
`~/.claude/settings.json` (backed up first), and any leftover macOS
launchd plist. Repo source + local cache + Claude Code session
transcripts are intentionally kept — they're your data.

`--purge` additionally clears `cache/` and prompts before deleting
the session transcripts. After it finishes, print the
`rm -rf` command for the repo source itself (can't self-delete
mid-script).

## License

MIT — see [LICENSE](LICENSE).

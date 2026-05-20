# claude-stray

A local companion for Claude Code that turns your session history into a
playful, AI-classified work dashboard. Cards, tasks, weekly recaps, cost
tracking — plus a walking pixel cat who reads you poetry.

[中文文档](docs/README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Roadmap](docs/ROADMAP.md) · [Release model](docs/RELEASE.md) · [Changelog](CHANGELOG.md)

![dashboard preview](docs/assets/dashboard-preview.png)
<!-- if the screenshot is missing, the dashboard ships at http://127.0.0.1:9876/ -->

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

### Option A — one-line install via SKILL (recommended)

Paste this into Claude Code:

```
Read https://raw.githubusercontent.com/Icesource/claude-stray/main/SKILL.md and install it.
```

Claude Code will:

1. Read the SKILL definition (see [`SKILL.md`](SKILL.md)) so it knows
   when to activate the dashboard and which `stray` commands to call.
2. Walk you through the `git clone` + `bin/install.sh` if you don't
   have the repo yet.

After install, ask Claude Code things like "what am I working on" or
"how much have I spent this month" and the SKILL takes over.

### Option B — manual install

```bash
git clone https://github.com/Icesource/claude-stray.git ~/Code/claude-stray
cd ~/Code/claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # optional — installs the SKILL so the main agent auto-uses stray
```

`bin/install.sh` sets up:

- Slash commands `/stray` and `/stray-refresh` (plus legacy `/mindmap*`
  aliases, removed in v0.7)
- `~/.local/bin/stray` shell wrapper (plus a `mindmap` alias)
- Claude Code `Stop` + `SessionStart` hooks at
  `~/.claude/settings.json`

Then in Claude Code:

```
/stray-refresh
```

First refresh takes ~30–120 s. After that the dashboard updates on
every session via the hooks; the in-process scheduler handles tips
(every 2 h) and the weekly report (Fri noon).

```bash
stray --serve              # open http://127.0.0.1:9876/
```

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
bash bin/uninstall.sh
```

Removes slash commands, CLI wrappers, hooks, and any leftover
launchd plist. Repo itself is untouched — delete manually if you want.

## License

MIT — see [LICENSE](LICENSE).

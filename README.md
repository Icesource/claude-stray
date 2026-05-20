# claude-stray

AI-powered terminal tree of your Claude Code work — auto-classifies sessions
into projects with progress tracking.

[中文文档](docs/README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Roadmap](docs/ROADMAP.md)

## What it does

Reads your Claude Code session history, uses AI to classify sessions into
projects, and renders a live work overview right in your terminal:

```
Claude Code Worktree  (generated 2m ago)
────────────────────────────────────────────────────────────
├── my-saas-app  [● active]  4m ago  6 sessions
│   ~/code/my-saas-app
│   Building user authentication and dashboard features.
│   progress: OAuth integration done. Working on role-based
│             access control for the admin panel.
│   tasks:
│     ├─ ✓ Set up OAuth2 login flow
│     ├─ ✓ Design dashboard layout
│     ├─ ○ Implement RBAC for admin panel
│     └─ ○ Add unit tests for auth middleware
│
├── data-pipeline  [● active]  2h ago  8 sessions
│   ~/code/data-pipeline
│   ETL pipeline for processing analytics events from Kafka.
│   progress: Kafka consumer and transform stages complete.
│             Writing the BigQuery sink connector.
│   tasks:
│     ├─ ✓ Kafka consumer with offset tracking
│     ├─ ✓ JSON schema validation stage
│     ├─ ○ BigQuery sink connector
│     └─ ○ Dead-letter queue handling
│
├── blog-redesign  [◐ paused]  5d ago  3 sessions
│   ~/code/blog
│   Migrating blog from Jekyll to Astro with new theme.
│   progress: Content migration done. Paused waiting for
│             design review from the team.
│   tasks:
│     ├─ ✓ Migrate markdown content
│     ├─ ✓ Set up Astro project structure
│     └─ ○ Apply new theme and deploy
│
└── archived (2)
    ├─ dotfiles (shell config cleanup)    (10d ago, 2s)
    └─ scratch-pad (one-off experiments)  (21d ago, 5s)
```

## Install

```bash
git clone https://github.com/Icesource/claude-stray.git ~/code/claude-stray
cd ~/code/claude-stray
bash bin/install.sh
```

One command does everything: installs slash commands, CLI wrapper, Claude Code
hooks, and macOS LaunchAgent (if on macOS). No model calls during install.

Then open Claude Code and run:

```
/mindmap-refresh
```

This generates your first worktree (takes ~30–120s). You can see the
model's classification progress in real time. After that, the tree
refreshes automatically in the background — just use `mindmap` or
`/mindmap` to view it.

### Requirements

- Python 3.9+
- `claude` CLI installed and logged in
- Active Claude Code subscription (Pro/Max) — uses your existing quota, no
  separate API key needed
- macOS or Linux (Windows via WSL)

## Usage

### Terminal (instant, zero model cost)

```bash
mindmap              # show cached tree
mindmap --refresh    # force refresh, then show
```

Inside Claude Code, use `!` to get the same instant output:

```
!mindmap
!mindmap --refresh
```

### Slash commands (tab-complete, goes through model)

```
/mindmap             # show cached tree
/mindmap-refresh     # force refresh, then show
```

## Auto-refresh

The tree stays fresh automatically — no manual refresh needed in normal use:

- **After every Claude Code response** — the `Stop` hook triggers a background
  refresh
- **On session start** — the `SessionStart` hook ensures data is current when
  you return
- **Every 2 hours** — macOS LaunchAgent fallback (Linux users can add a cron
  job; see install output)

All refreshes run in the background and never block your work.

## Cost & Performance

Classification uses **Haiku** by default — fast and cheap. Three layers of
protection prevent unnecessary spending:

1. **Cooldown** (15 min) — skips AI call if last refresh was recent
2. **Hash shortcut** — skips AI call if session data hasn't changed
3. **Incremental extraction** — only reads new bytes from session files

| Scenario | Cost |
|----------|------|
| Within cooldown window | **$0** (AI call skipped) |
| Session data unchanged | **$0** (hash shortcut) |
| Typical refresh (~100 sessions) | ~$0.01–0.05 |

Every AI call logs token usage to `~/Library/Logs/claude-stray.log`
(macOS) or `~/.local/state/claude-stray/refresh.log` (Linux):

```
[refresh] usage: in=18200 (+0 cache-create) out=1500 cost=$0.0234 prompt=42KB elapsed=15s
```

Override defaults via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_WORKTREE_COOLDOWN_SECS` | `900` (15 min) | Min seconds between AI calls |
| `CLAUDE_WORKTREE_MODEL` | `claude-haiku-4-5-20251001` | Model for classification |
| `CLAUDE_WORKTREE_TIMEOUT` | `600` (10 min) | Timeout for `claude -p` call |

## Project Statuses

| Status | Icon | When |
|--------|------|------|
| active | `●` | Activity within 3 days |
| paused | `◐` | 3–14 days idle, or has resume signals |
| done | `✓` | Explicitly finished |
| archived | `▪` | >14 days idle, no resume signal |

## Comparison

| | claude-stray | [Claude Code Canvas](https://github.com/raulriera/claude-code-canvas) | [Claude Code Viewer](https://github.com/d-kimuson/claude-code-viewer) |
|---|---|---|---|
| AI project classification | Yes | No | No |
| Progress / task tracking | Yes | No | No |
| Terminal-native (zero deps) | Yes | No (browser) | No (browser) |
| Auto background refresh | Yes | No | No |
| Session replay | No | No | Yes |

## How it works

1. **`extract.py`** — Incrementally reads `~/.claude/projects/**/*.jsonl`,
   writes per-session summaries. Prefers Claude Code's native `away_summary`
   when present.
2. **`aggregate.py`** — Filters noise, sorts by recency, emits compact JSON.
3. **`refresh.sh`** — Feeds sessions + classifier prompt to `claude -p`
   (reusing your subscription auth), produces `cache/mindmap.json`.
4. **`render.py`** — Reads the JSON and prints a colored ANSI tree (stdlib
   only, no pip).

## Troubleshooting

- **"No mindmap cache found"** — run `mindmap --refresh` or
  `bash bin/refresh.sh`.
- **Hooks not firing** — verify with `jq .hooks ~/.claude/settings.json`.
  Hooks only apply to sessions started *after* installation.
- **"Not logged in"** — run `claude /login`.
- **Stale data** — run `mindmap --refresh` and check the log for errors.

## Uninstall

```bash
bash bin/uninstall.sh
```

Removes slash commands, CLI wrapper, Claude Code hooks, and macOS LaunchAgent.
The repo itself is left untouched — delete it manually if you want.

## License

MIT

# claude-stray

**An attention cockpit for Claude Code.**

You run many things in Claude Code in parallel. Some are mid-run, some
are waiting on *you*, some finished hours ago, some you forgot about.
The hard part isn't doing the work — it's knowing, at a glance, **who's
waiting on you, where each thing stands, and how to drop back into any
of them at near-zero cost.**

`claude-stray` is a small local dashboard that sits on top of Claude
Code and does exactly that: it reads your sessions, has AI summarize
each one's progress and collect the resources it produced (MRs, issues,
docs), and lays them out as cards **ranked by what needs your
attention** — needs-you → running → idle → done. Click into any card to
read where it's at, see its MR/issue links, or **open a terminal right
in the card** to pick the work back up.

It is **not** another agent. It reuses Claude Code for the actual work;
its whole job is triage + handoff — helping you spend attention well
across everything in flight.

One-line install. No login. Nothing leaves your machine except the
summary calls to Anthropic. Auto-syncs your existing history on first
launch, then keeps itself fresh in the background — every time a Claude
Code session ends, the matching card updates.

[中文文档](docs/README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Roadmap](docs/ROADMAP.md) · [Release model](docs/RELEASE.md) · [Changelog](CHANGELOG.md)

![dashboard preview](docs/assets/screenshots/en/01-overview.png)

## What you get

A dashboard at `http://127.0.0.1:9876/` with three views — **by
attention**, **by project**, and **archive** — over the same cards:

- **Attention bands, live.** Every piece of work is sorted into
  **需要你 / running / idle / done**, driven by real-time telemetry from
  Claude Code hooks. A session that's actively generating shows
  *running*; one that ended waiting on your decision shows *needs-you*
  with the specific question. You see the whole board at once and know
  where to look first.
- **AI-summarized, per card.** Each card carries a one-line *what this
  is*, the **latest progress** (auto, kept current), tri-state tasks
  (pending / done / cancelled), blockers, a **next step**, and the
  external resources it touched — **MR / PR / CR / issue**. Resources
  are sticky: once an MR is on a card it stays until you remove it; the
  AI never silently drops a link.
- **Jump back in, in place.** Open a card's session as an **embedded
  terminal** right inside the cockpit (`claude --resume`, no new
  window), or jump to its live pane. With `tmux`/`screen` installed the
  terminal even survives a page refresh.
- **AI "next message" suggestions.** Ask a card for 2–3 ready-to-send
  next prompts — generated with a view across *all* your active work,
  not just that one session.
- **A weekly recap** every Friday at noon, and **next-step
  suggestions** drawn from your own data (not generic advice).
- **Pause / resume** the background AI any time, from the banner.

Nothing leaves your machine except the Anthropic calls that generate
the summaries.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

Plain shell — Claude Code isn't involved in the install. The script
clones into `~/.claude-stray/`, sets up the `/stray` slash command, the
`stray` shell wrapper, and the Claude Code hooks that keep the dashboard
fresh. Read it first if you like:
[`bin/quick-install.sh`](bin/quick-install.sh).

> **About `~/.claude-stray/`** — the tool's own home (like `~/.fzf`,
> `~/.nvm`). Don't `mv`/`rm -rf` it manually; the slash command, hooks,
> and `stray` CLI hold absolute paths into it. Update with
> `cd ~/.claude-stray && git pull` (or rerun the curl-pipe). To relocate,
> `bin/uninstall.sh` first, then reinstall with `INSTALL_DIR=<path>`.

Override defaults via env vars before the pipe:

```bash
INSTALL_DIR=~/code/claude-stray INSTALL_REF=stable LANG_CHOICE=en NO_SKILL=1 \
  curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

### Manual install (fully transparent)

```bash
git clone https://github.com/Icesource/claude-stray.git ~/.claude-stray
cd ~/.claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # optional — lets Claude Code recognize the tool
```

### Requirements

- Python 3.9+
- `claude` CLI **logged in** (a Claude Code Pro/Max subscription is fine —
  no separate API key). The background analysis can't run without it.
- macOS or Linux (Windows via WSL)

**Optional** (the in-card terminal degrades gracefully without them):

- `ttyd` — embed a real terminal in a card (`brew install ttyd`).
- `tmux` (or `screen`, usually preinstalled on macOS) — keep an embedded
  terminal alive **and repainted** across a page refresh
  (`brew install tmux`). Without it the terminal still works; it just
  re-`resume`s on reload. (`abduco`/`dtach` do **not** work here — they
  don't replay the screen, so a TUI reattaches black.)

## First run (what to expect)

```bash
stray --serve     # dashboard at http://127.0.0.1:9876/
```

- On the first launch with an empty cache, the dashboard kicks a
  background analysis of your recent sessions (~1–2 min). The page shows
  a **"first sync…"** state and fills in as cards are produced; if it
  fails it tells you why (most often `claude` isn't logged in — check
  with `claude -p hi`).
- It uses a little Haiku — **~$0.3–0.5** for a handful of sessions.
- Only sessions from the **last ~48h** sync on first run (older ones
  refresh lazily when you revisit them). To pull in your full history
  now, run `stray --backfill`.

After that you don't have to do anything: every Claude Code session you
finish updates its card in the background.

## Usage

```bash
stray --serve              # the dashboard (the usual)
stray                      # terminal tree of the current cache (no AI)
stray --refresh            # re-classify now, then render
stray --backfill           # summarize ALL history, not just the last 48h
stray --cost [month]       # today + 7-day (or full-month) cost breakdown
stray --diagnose [SID]     # "why doesn't session X show up?"
stray --pause "reason"     # pause background AI …
stray --resume             #   … and release it
stray --weekly-report      # last week's recap
stray --next-steps         # 3 suggestions on what to focus on next
stray --help               # full flag list
```

Inside Claude Code, `/stray` renders the cached dashboard in the chat.
The dashboard's ⟳ button (top-right) is the everyday "refresh now".

### Inside Claude Code conversations

If you ran `bin/install-skill.sh`, the main Claude Code agent learns
about stray and can answer things like *"what am I working on this
week?"*, *"show me what's blocked"*, *"how much have I spent this
month?"* without you typing `stray`.

## Costs

`claude-stray` is lazy — it only calls the API when a session ends or a
scheduler tick fires. Typical per-run costs on Haiku-4.5:

| Job | When | Cost / run |
|---|---|---|
| Per-session summary | each session ends | ~$0.04 |
| Cross-session classify | ~5×/day in active use | ~$0.17 |
| Next-message suggestions | when you ask a card | ~$0.02 |
| Weekly report | Fri 12:00 local | $0.10–$0.50 |

Guards: a cooldown on classify, unchanged sessions are skipped, and
every call goes out under a daily budget cap. Watch live with
`stray --cost`.

## How it works (briefly)

The sessions Claude Code already writes to `~/.claude/projects/` flow
through a small lazy pipeline: **extract** (read new transcript bytes)
→ **summarize** (one AI pass per session → progress, tasks, resources,
next step) → **classify/assemble** (lay the cards out into the board) →
**serve** (the cockpit + live status via hooks). The detailed design
notes live under [`docs/`](docs/) — start with
[ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Troubleshooting

1. **Dashboard empty / "sync failed"** — the page now states the cause;
   the usual one is `claude` not logged in (`claude -p hi`). Re-run with
   `stray --refresh` once fixed.
2. **A card didn't update** — Claude Code hooks may have drifted;
   `bash bin/install.sh` reinstalls them safely.
3. **Session not showing** — `stray --diagnose <sid>` walks the pipeline
   and says which step dropped it.
4. **In-card terminal black on refresh** — install `tmux`
   (`brew install tmux`) for refresh-proof terminals.

More in [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Uninstall

```bash
bash bin/uninstall.sh           # default — keeps your data
bash bin/uninstall.sh --purge   # also wipes cache + transcripts (y/N gated)
```

Default removes the slash command, the `stray` CLI, the optional SKILL,
and the hook entries in `~/.claude/settings.json` (backed up first).
Repo source, local cache, and your Claude Code transcripts stay — they're
your data.

## License

MIT — see [LICENSE](LICENSE).

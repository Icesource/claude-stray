# DD-005 — Lifecycle / opt-in operation model

Status: **proposed** (discussion captured 2026-05-15; no work scheduled)
Predecessors: DD-002 (3-layer pipeline), DD-004 (circuit breaker)
Trigger: user observation 2026-05-15 — "现在对于用户来说是无法感知到
启动与停止的生命周期的, 用户安装之后就开始不间断的在后台一直运行
并消耗额度, 用户也没办法手动停止"

## 1 — Problem

After `bin/install.sh` is run, the tool runs forever:
- Stop hook + SessionStart hook fire on every CC interaction, globally
- LaunchAgent fires every 2h regardless of user presence
- Pipeline burns budget even when the user has no intention of looking
  at the dashboard for days

The user has no first-class way to:
- Pause for the weekend / vacation
- "Just run while I'm using the dashboard"
- See at a glance whether the pipeline is currently active
- Resume cleanly after a pause without losing the data captured during

The kill switch (`cache/.refresh-disabled`, born from the P15 cost
incident) is currently the only stop button, but:
- It's discovered by reading code, not surfaced in UI
- Removing it requires terminal access
- No status indicator in dashboard/CLI tells you it's engaged

### 1.1 — The architectural tension

The user proposes: "only run while `stray --serve` is up". This
conflicts with the incremental design — the pipeline needs to keep
ingesting Stop hooks to keep `cache/sessions/` current. If you skip
hooks while the server is down, you either (a) miss data permanently
or (b) face a huge catch-up backfill when the server starts.

The real tension is:

| What's cheap?                          | What's expensive?                                |
|----------------------------------------|--------------------------------------------------|
| Layer 0 (jsonl parsing, file I/O)      | Layer 1 (per-session AI summarize, ~$0.03 each)  |
| Reading state.json byte offsets        | Layer 2 (cross-session classify, ~$0.17 each)    |
| Recording session_locations.json       |                                                  |

Solution shape: **split data capture (cheap, always on) from AI work
(expensive, opt-in)**. Layer 0 keeps running so data is never lost.
Layer 1/2 are gated.

## 2 — Goals

1. **User controls AI spend**, with one obvious surface in both UI
   and CLI.
2. **No data loss** during paused periods. When the user un-pauses,
   the dashboard catches up to the current truth.
3. **Default behavior remains friendly** — first-time install should
   still produce a useful dashboard without the user reading a manual.
4. **Failure modes are visible** — kill switch / pause state is
   surfaced; you can't accidentally leave it paused for weeks and
   wonder why nothing updates.

Non-goals:
- Per-workspace pausing (just one global switch)
- Calendar-based auto-pause ("pause Saturday/Sunday") — DD-004's
  budget cap covers the abuse case; calendar is a separate ask
- Removing the LaunchAgent — it's still useful as a heartbeat for
  long-uptime users

## 3 — Design options

### 3.1 — Option A: "Server-mode-only AI" (the user's proposal)

```
Always-on:        Layer 0 (extract.py) — runs every hook fire
Paused by default: Layer 1 + Layer 2
Active during:    stray --serve is up
                  + a grace window (5 min) after server closes
                  + manual stray --refresh always works
```

Mechanism:
- `bin/serve.py` writes `cache/.serve-pid` on start, removes on clean
  exit (+ launchd janitor cleans stale ones).
- `bin/refresh-bg.sh` skips Layer 1/2 unless `.serve-pid` exists with
  a live process, OR `cache/.always-on` flag is set, OR the call is
  forced (manual `--refresh`).
- Dashboard shows a status pill ("AI active" / "AI paused — data only").

**Pros**:
- Strong mental model: "If my browser tab is open, AI is working"
- AI cost is correlated to user attention
- One click to start, one Ctrl-C to stop

**Cons**:
- Latency on first visit: open browser → catch up all dirty sessions
  → first classify can take 1–3 minutes before any cards update.
  Could be mitigated by showing "catching up: N/M sessions" progress.
- Doesn't help users who never run `--serve` and rely on the CLI tree
- LaunchAgent's "I haven't checked in 2h, run a sweep" loses meaning

### 3.2 — Option B: "Explicit pause/resume CLI + UI button"

```
Always-on:        everything (current behavior)
User control:     stray --pause / stray --resume
                  Dashboard button: pause/resume
Status indicator: dashboard banner + mindmap CLI exit messages
```

Mechanism:
- `stray --pause` writes `cache/.refresh-disabled` with reason
- `stray --resume` removes it (also via `POST /api/lifecycle`)
- Dashboard shows pause state in the top bar with a toggle
- `mindmap` CLI prints `[paused since YYYY-MM-DD HH:MM]` near the
  top of output when paused
- LaunchAgent and Stop hooks both honor the flag

**Pros**:
- Minimal architecture change — pipeline stays as-is
- Builds on the kill switch we already have
- Works regardless of whether server is up

**Cons**:
- User still has to *know* to pause; doesn't address "burning money
  while I'm not looking"
- Requires discipline to remember to resume — risk of leaving paused
  for weeks accidentally

### 3.3 — Option C: "Quota-based auto-pause" (DD-004 with teeth)

```
Always-on:        everything
Auto-pause when:  daily/weekly budget reached → kill switch engaged
                  banner says "auto-paused, hit $X today"
                  user clicks "resume now" or waits for tomorrow
```

Mechanism: same as DD-004's circuit breaker but with a default budget
of, say, $0.50/day for casual users.

**Pros**:
- Zero user effort
- Cost-anchored: you can't accidentally spend more than $0.50

**Cons**:
- The budget might pause exactly when you need fresh data the most
- Doesn't address "I want it off this weekend"
- Doesn't surface the pause meaningfully outside the banner

### 3.4 — Option D: Compose A + B + C

Most realistic answer. Each option solves a different ask:

- **A** ("active only while dashboard is up") = answers "I don't want
  it running when I'm not paying attention"
- **B** (explicit pause/resume) = answers "I want a manual off-switch"
- **C** (budget guard) = answers "I never want a surprise bill"

A default install can ship with C enabled (DD-004's daily cap, say
$1.00/day) and offer A as an opt-in (`stray --mode serve-only`).
Option B's pause/resume is the manual override layer over both.

## 4 — Recommended path

A two-phase rollout:

**Phase 1 — Option B + DD-004 (small, foundational)**

1. Wire `stray --pause` / `stray --resume` commands. Pause writes
   the kill switch + reason file. Resume removes both. (DD-004 already
   describes the kill switch enhancement.)
2. Add dashboard banner: red bar when paused, with a "Resume now"
   button.
3. Add a status line to `mindmap` CLI output: `[paused since X]`.
4. Implement DD-004's daily budget cap with a friendly default
   ($1.00/day for the install, configurable via env or
   `cache/config.json`).

**Phase 2 — Option A (mode switch)**

1. Add a "lifecycle mode" to `cache/config.json`:
   - `auto` — always on (current behavior)
   - `serve-only` — Layer 1/2 only run while `stray --serve` is up,
     plus 5min grace
   - `manual` — Layer 0 always; Layer 1/2 only on explicit `--refresh`
2. `bin/install.sh` asks during first install which mode to enable
   (default `auto` with budget cap from Phase 1).
3. `stray --mode <name>` switches at any time.
4. Dashboard shows the active mode in the top bar.

This gives users a smooth glide from "least surprise" (auto + budget
cap) to "minimum cost" (manual) without forcing a single trade-off.

## 5 — Open questions

1. **Catch-up UX in `serve-only` mode**: when the user opens the
   dashboard after a 3-day pause, what do they see while we catch up?
   A "catching up: N/M sessions" indicator? An estimate of cost? A
   confirmation prompt ("This will cost ~$X, continue?")?
2. **First-install default**: `auto` is friendliest but costs the
   most. Should the installer prompt? Or default to `manual` and
   teach the user to switch?
3. **Where does the 5-minute grace come from?** Hand-picked. Worth
   re-examining once we have real users on Option A.
4. **Interaction with LaunchAgent**: in `serve-only` mode, the
   LaunchAgent's 2h sweep becomes a no-op. Do we uninstall it? Leave
   it as a safety net?
5. **Single-instance vs multi-instance dashboard**: if two browser
   tabs are open on different `stray --serve` runs (different ports)
   how do we decide "AI is active"? Probably just `any pid file with
   a live process`.

## 6 — Out of scope

- **Per-initiative pausing** — too granular; the user has a single
  attention budget.
- **Scheduled pauses** ("pause every Saturday") — DD-004's budget cap
  is the right tool for this kind of constraint.
- **Multi-user lifecycle** — see DD-002 §13.3, loopback-only by design.
- **Remote pause from another machine** — same reason.

## 7 — Plan (when scheduled)

| Phase | Item | Estimate |
|-------|------|----------|
| 1.1   | `stray --pause` / `--resume` + `cache/.refresh-disabled.reason` sidecar | tiny |
| 1.2   | Dashboard pause banner + resume button | small |
| 1.3   | `mindmap` CLI status line | tiny |
| 1.4   | DD-004 budget cap (depends on DD-004 phases 0-1) | small |
| 2.1   | `cache/config.json` lifecycle mode field + read paths | small |
| 2.2   | `.serve-pid` write/clean | tiny |
| 2.3   | `refresh-bg.sh` mode gating | tiny |
| 2.4   | First-install mode prompt in `install.sh` | small |
| 2.5   | Dashboard mode indicator + switcher | small |

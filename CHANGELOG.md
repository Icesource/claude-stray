# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org) with the 0.x relaxation
described in [docs/RELEASE.md](docs/RELEASE.md).

## [Unreleased]

### Added

- **Three-tier work items** (DD-014, commits `d321620` + `270805d`).
  Every initiative now carries a `level` of `thread`, `card`, or
  `chip`, plus an optional `parent_thread_id` linking a card/chip into
  a thread. Schema is v3.

  The dashboard splits each workspace into three tiers:

  - **Threads** render as poker-style stacked decks at the top of the
    workspace, with two rotated backplate cards behind giving the
    "stack of paper" look. Hover spreads the stack; clicking opens
    the thread's full card. Member cards/chips appear as compact
    pills inside the deck.
  - **Cards** keep the existing grid layout, now scoped to
    initiatives without a parent thread.
  - **Chips** are compact pill-shaped tags for tiny work — 1-session
    lookups, one-off questions. They sit at the bottom of each
    workspace and open as a popover when clicked.

  Stability follows the DD-011/012/013 mechanical-floor pattern:

  - `apply_promotion_cooldown` forces every newly-discovered
    initiative to `chip` on its first round (no "fanfare for a
    one-off" failure mode).
  - `enforce_level_monotone` makes `level` a one-way ratchet —
    chip → card → thread only, never reverse. AI demotion attempts
    are reverted.
  - Cold initiatives freeze `level` / `parent_thread_id` /
    `level_set_at` byte-identically to PRIOR, matching the existing
    §5 cold rule.

  Migration is transparent: v2 dashboard.json renders as all-cards
  (the existing layout) until the next pipeline run produces real
  AI-assigned levels. `level: "card"` is the default for every
  v2 initiative.

## [v0.7.0] — 2026-05-26

A "make the dashboard tell the truth" release. Three classes of bugs
showed up after extended use: artifacts silently disappearing from
cards, task lists growing without bound, and `done` cards detaching
from continued session activity. Each got a design doc (DD-011 amend
through DD-013) and a mechanical guarantee — AI is now advisory; the
post-process is authoritative for anything the user cares about. Plus
an in-place auto-updater so users actually get future fixes.

### Added

- **Artifact monotonicity** (commit `c5452a0`). MR / PR / CR / issue /
  commit links no longer vanish when AI rewrites a card. After Layer 2,
  a mechanical aggregator unions PRIOR + every contributing session's
  frontmatter + AI output, keyed by `url → (type, ref_id) → (type, title)`.
  Once an artifact's status reaches `merged|closed|wontfix|released|
  stale|rolled-back|pushed`, it's frozen. Each artifact row in the
  modal grew a ✕ button writing to `user_overrides.json:hidden_artifacts`
  (persistent — only the user removes artifacts).
- **DD-012 — Layer 1 reuses PRIOR task wordings** (commit `679d366`).
  `bin/summarize.py` now feeds the session's existing initiative tasks
  back into the Layer 1 prompt; Rule 12 in `prompts/summarize-session.md`
  forbids translating, retagging (`[F1-body]`), or expanding a PRIOR
  title. Stops the unbounded growth where every Layer 1 rerun produced
  a slightly-different phrasing that became a new permanent task.
- **DD-012 tail — Consolidate-duplicates button** (commit `e02fc84`).
  When a card has ≥ 8 pending tasks, a ✨ "Consolidate duplicates"
  button appears in the footer. Click → Haiku scans the list, returns
  groups of `{keep, cancel}` with reasons → preview modal → confirm
  pushes cancellations through the existing `task_toggles` override.
  Tested on a 41-pending card: 7 groups, 9 cancels, ~$0.01.
- **DD-013 — `init.status` is mechanically derived** (commit `0963540`).
  AI was carrying `PRIOR.status: done` forward even when the underlying
  session had clearly resumed. New `enforce_hot_initiative_status` in
  `classify.py` recomputes status for every hot initiative directly
  from contributing sessions' `status_guess`, overwriting AI's output.
  Done cards no longer freeze when work continues.
- **Auto-update** (this release).
  - `stray --check-updates` — print installed vs. latest tag.
  - `stray --update` — `git pull --ff-only` to the latest tag.
  - `stray --serve` startup checks at most every 24h and, when running
    interactively, prompts `y/N` to upgrade in place.
  - Dashboard green banner when a new version is available, with an
    "Update now" button (POST `/api/update`) and "Not today" dismissal
    that stays hidden until a newer version ships.
  - Backed by `bin/_updates.py` + `cache/update_state.json` + a daemon
    thread in `serve.py` that re-checks every 24 hours.

### Fixed

- **Archive zone bucketing** (commit `6cc7eef`). Cards archived today
  were appearing under "上周归档" / "更早归档" because the UI keyed
  buckets on `init.last_activity_at` (when the work happened) instead
  of `archived_at` (when the card was archived). The persisted
  timestamp is now preferred. Buckets older than this week also
  collapse by default; click the header to expand.
- **Frontmatter parser robustness** (in commit `0963540`). Layer 1
  sometimes drops the closing `---` fence on a summary file. The
  strict parser then treated the whole file as bodiless, which made
  `is_hot()` return False and silently dropped the session out of
  every Layer 2 batch. The parser now falls back to the first
  markdown heading (`^# `) as the boundary.

### Changed

- **`stray --serve` auto-syncs on first run** (commit `c4d02b2`). When
  `cache/dashboard.json` is missing or empty, serve kicks
  `pipeline-run.sh --all-dirty --force-classify` in the background so
  a fresh install reaches a populated dashboard within a minute or two
  without the user having to know about `--refresh`.
- **`/stray-refresh` slash command retired** (in commit `c4d02b2`).
  Redundant alongside `stray --refresh` from the shell, the dashboard's
  🔄 button, and the new auto-sync. `bin/install.sh` sweeps up the
  obsolete file on the next install; `bin/uninstall.sh` already
  cleaned it.
- **README rewritten for a wider audience** (commit `f038ff0`). Both
  English and Chinese open with the user problem ("you're juggling
  five things in Claude Code, they blur together") and position the
  tool as a Claude Code plugin that auto-summarizes and classifies.
  Implementation jargon (`jsonl`, "3-layer Haiku pipeline", DD-XXX,
  etc.) is gone from the top-level README and tucked under `docs/`.

### Promo / docs

- **Promo screenshots** for both English and Chinese README
  (`docs/assets/screenshots/{en,zh-CN}/01-overview.png` ... `05-filter-active.png`).
- **Reproducer kit** at `bin/_screenshots/` — mock-data generators
  (`make-mock-zh-CN.py`, `make-mock-en.py`), the Playwright capture
  script (`playwright-shots.js`), and a README that walks through the
  "pause + stash + RO-lock + shoot + restore" dance.

## [v0.6.1] — 2026-05-20

Hotfix: safer install story. v0.6.0's recommended "paste `Read URL
and install it` into Claude Code" pattern is correctly blocked by
Claude Code's prompt-injection guard and shouldn't have been the
default. Replaced with a plain `curl | bash` flow, and moved the
default install location out of the user's project directory.

### Added

- **`bin/quick-install.sh`** — one-line installer. Standard usage:
  ```
  curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
  ```
  Pre-flight checks (git, python3 ≥ 3.9, claude CLI), clones to
  `~/.claude-stray/` (override via `INSTALL_DIR`), runs
  `bin/install.sh` + `bin/install-skill.sh`. Tweakable via
  `INSTALL_REF` (branch/tag), `LANG_CHOICE`, `NO_SKILL=1`.

### Changed

- **Default install location: `~/.claude-stray/`** (was `~/Code/claude-stray/`).
  Matches the `~/.fzf` / `~/.nvm` / `~/.oh-my-zsh` convention — the
  directory is the tool's own home, not the user's dev workspace.
  Existing installs at the old path keep working (install.sh
  operates on whatever directory it's run from); the change applies
  only to new installs via `quick-install.sh`.
- **README install path** (en + zh-CN): "Option A" is now the
  `curl … | bash` one-liner. The "Read URL and install it" prompt-
  in-Claude-Code pattern is gone — Claude Code correctly flags it as
  prompt injection.
- **SKILL.md** Install section: instructs the agent to send users to
  a terminal command, NOT to suggest pasting "Read URL and install"
  into the chat. Install path references updated to `~/.claude-stray/`.

## [v0.6.0] — 2026-05-20

Rebrand + SKILL-based install + tips quality pass.

### Changed

- **Rename: `claude-code-worktree` → `claude-stray`.** The project is
  rebranded to `claude-stray` — short, references the pixel cat
  mascot, and (intentionally) signals "Claude Code companion tool" via
  the `claude-` prefix. Touches the project name, the CLI binary
  (`mindmap` → `stray`), slash commands (`/mindmap*` → `/stray*`), and
  canonical data files (`cache/mindmap.json` → `cache/dashboard.json`,
  `cache/mindmap.html` → `cache/dashboard.html`).
- Tips additions: rotation cadence is 2h (was 6h), batch size is 20
  with intentional 8/6/3/3 split (curiosity-heavy), required
  `source_url` on curiosity + wisdom tips, anti-fabrication prompt
  rule, scenic wisdom tone.
- Tips bubble UI: walking pixel cat mascot (CC0 sprite from
  OpenGameArt), draggable position with localStorage persistence,
  inline `↗` source link per tip, Fisher-Yates shuffle so categories
  don't cluster across rotations.

### Added

- **`SKILL.md` for one-line install via the main Claude Code agent.**
  `bin/install-skill.sh` drops the markdown into
  `~/.claude/skills/stray/`. The SKILL is deliberately restrained:
  its frontmatter leads with "read primarily by the HUMAN, not by
  you" so the agent doesn't try to narrate the dashboard. Activates
  only for install/uninstall and the small set of management
  actions (open, refresh, pause/resume the plugin, check this
  plugin's own cost). Includes a "What this is NOT" table that
  steers the agent away from over-reaching prompts like "how much
  have I spent on Claude" (the plugin only tracks ITS OWN AI cost,
  not total Claude usage) or "pause Claude" (the plugin can only
  pause its own pipeline).
- **README rewrite** (English + zh-CN) — dashboard-first framing,
  SKILL install promoted as the recommended path, per-layer cost
  table updated, troubleshooting points at `stray --diagnose`.
- **`stable` branch + `v0.5.0` tag.** `docs/RELEASE.md` documents the
  branch model (`main` for dev / `stable` for daily-use / topic
  branches for features), SemVer rules, release checklist, and
  hotfix path. Daily use should now run `git checkout stable`.
- Legacy aliases preserved through the rename: `~/.local/bin/mindmap`
  symlinks to `bin/stray`, and `/mindmap` + `/mindmap-refresh` slash
  commands install alongside `/stray` + `/stray-refresh`. Both will
  be removed in v0.7.0.
- `bin/_migrate_to_stray.sh` — one-shot migration script that renames
  local cache files, updates `~/.claude/settings.json` hook paths,
  and moves `~/.claude/skills/mindmap/` if present.
- `bin/uninstall.sh --purge` mode for squeaky-clean removal: also
  wipes `cache/`, prompts y/N before deleting the Claude Code
  session transcripts at
  `~/.claude/projects/-Users-<you>-Code-claude-stray/`, and prints
  the `rm -rf` command for the repo source itself. Default
  uninstall now also removes `~/.claude/skills/stray/` (was leaking
  before) and warns if `bin/serve.py` is still running.

### Fixed

- **Artifact URL synthesis.** Layer 1 (`prompts/summarize-session.md`)
  was reading the URL-pattern table as a construction template
  whenever a session mentioned an MR/CR/issue by number only.
  Result: hallucinated URLs like
  `code.aone.alibaba-inc.com/merge_requests/<id>` for environments
  whose real Aone host is
  `code.alibaba-inc.com/<group>/<repo>/codereview/<id>`. Both prompts
  now lead with "NEVER synthesize a URL" and accept artifacts with
  `ref_id` but no `url`. Layer 2 dedup falls back to (`type`,
  `ref_id`) when `url` is absent on either side.

### Roadmap

- `P16 — Tips quiz (spaced reinforcement)`: persist every shown tip,
  weekly cloze / MC / free-recall quiz so the rotating content
  actually sticks. Source URL is the trust anchor on every answer.
- `P17 — Persona accretion (digital twin prompt)`: hook-driven
  distillation of the user's tone, style, frustration triggers into
  an accumulating persona file that can seed any future agent with
  the user's voice.

## [v0.5.0] — 2026-05-19

First versioned release. Everything from project inception through the
tips-bubble redesign is collapsed into this single entry — earlier
commits weren't grouped under a tag.

### Added

- **AI pipeline (DD-001 → DD-002)**: three-layer extract / summarize /
  classify pipeline, hot/cold session stratification, dirty tracking,
  coalesced Layer-2 triggers via `pipeline-run.sh`.
- **Card dashboard** (`bin/render-html.py`): per-initiative cards,
  workspaces sidebar, status filter chips, search, sticky toolbar.
- **Card detail modal (DD-003)**: artifact extraction (CR / MR / PR /
  issue / branch / commit / tag / doc), blocker tracking, blocker chip
  on cards.
- **Lifecycle pause/resume (DD-005)**: opt-in pipeline lifecycle —
  the user can pause AI work from the dashboard (`POST /api/lifecycle`),
  banner appears when paused, all background AI calls become no-ops
  until resumed.
- **Cost alarm (DD-004 partial)**: cost-log snapshot helper, console
  warning on serve startup when daily budget is hot.
- **Derived AI features (DD-006)**: weekly report (`bin/derived/
  weekly_report.py`), next-steps suggestions, tips ticker, wellness
  nudges. All run on the in-serve scheduler.
- **Tips bubble (multiple iterations)**: header ticker → bottom-right
  banner → floating speech bubble with walking pixel cat (CC0 asset
  from OpenGameArt, inlined as data URL). Draggable to any position
  with localStorage persistence. Per-tip `↗` source link opens
  canonical references in a new tab.
- **Local server** (`bin/serve.py`): unified HTTP front for the
  dashboard, override saves, AI refresh trigger, derived scheduler.
- **Task model (DD-008 → DD-011)**: tri-state status
  (`pending | done | cancelled`) stored only in `mindmap.json`. AI is
  additive-only; user has full toggle/delete authority. Earlier DDs
  (008/009/010) superseded by DD-011's single-store design.
- **Versioning & release docs** (this release): branch model
  (`main` for dev, `stable` for what runs locally, topic branches for
  features), SemVer 0.x rules, `CHANGELOG.md`. See
  [docs/RELEASE.md](docs/RELEASE.md).

### Changed

- **Tip cadence** reduced from 6h to 2h (`bin/serve.py`,
  `bin/derived/tips.py`) so the rotation feels fresh across a workday.
- **Tip batch size** raised from 4 to 20 with an intentional 8/6/3/3
  split (curiosity-heavy) and required `source_url` on every curiosity
  and wisdom tip; anti-fabrication rules in the prompt.
- **Tips rotation order** shuffled (Fisher-Yates) so categories don't
  cluster in a single block.

### Removed

- `cache/task_archive/` directory and `/api/task-history` endpoint
  (folded back into `mindmap.json` per DD-011). Migration handled by
  `bin/_migrate_dd011_tasks.py`.

### Fixed

- `task_archive` getting wiped to `[]` when a round had zero current
  tasks (pre-DD-011, but kept here for historical context).
- `pollAndApply` not refreshing lifecycle state until the mindmap
  itself changed.
- Archive expander button doing nothing because of browser dialog
  suppression on `window.confirm` — replaced with a custom in-page
  modal.

[Unreleased]: https://github.com/Icesource/claude-stray/compare/v0.6.1...HEAD
[v0.6.1]: https://github.com/Icesource/claude-stray/releases/tag/v0.6.1
[v0.6.0]: https://github.com/Icesource/claude-stray/releases/tag/v0.6.0
[v0.5.0]: https://github.com/Icesource/claude-stray/releases/tag/v0.5.0

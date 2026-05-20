# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org) with the 0.x relaxation
described in [docs/RELEASE.md](docs/RELEASE.md).

## [Unreleased]

### Added

- **Promo screenshots** for both English and Chinese README
  (`docs/assets/screenshots/{en,zh-CN}/01-overview.png` ... `05-filter-active.png`).
- **Reproducer kit** at `bin/_screenshots/` — mock-data generators
  (`make-mock-zh-CN.py`, `make-mock-en.py`), the Playwright capture
  script (`playwright-shots.js`), and a README that walks through the
  "pause + stash + RO-lock + shoot + restore" dance. Run it after a
  UI change to refresh the screenshots without leaking real session
  data.

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

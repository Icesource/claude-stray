# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org) with the 0.x relaxation
described in [docs/RELEASE.md](docs/RELEASE.md).

## [Unreleased]

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

[Unreleased]: https://github.com/Icesource/claude-stray/compare/v0.5.0...HEAD
[v0.5.0]: https://github.com/Icesource/claude-stray/releases/tag/v0.5.0

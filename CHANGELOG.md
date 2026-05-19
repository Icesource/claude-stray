# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org) with the 0.x relaxation
described in [docs/RELEASE.md](docs/RELEASE.md).

## [Unreleased]

(nothing yet — start of a new iteration cycle)

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

[Unreleased]: https://github.com/Icesource/claude-code-worktree/compare/v0.5.0...HEAD
[v0.5.0]: https://github.com/Icesource/claude-code-worktree/releases/tag/v0.5.0

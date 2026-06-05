# DD-024: Test system + dead-code cleanup + data-model consolidation

**Status**: Proposed (design; not yet implemented)
**Author**: Claude (with user)
**Date**: 2026-06-06

## Why (the user's words)

> 项目一直没有测试体系，基本靠手测或你用无头浏览器测。眼下项目雏形已成，当前版本
> 已经挺不错了，接下来更侧重小 feature 完善、体验优化，不会大改产品形态了，因此
> 应该开始建立测试体系，并借助这个机会梳理废弃无用代码、优化数据模型等等。

The product form is now stable (card = one session; cockpit + ttyd; triage + handoff).
Future work is small features and polish. That's exactly the moment to add a **safety
net** so polish doesn't regress core behavior — and to **pay down debt** left by the
pivots (DD-016 identity → card=session; the DD-021 resource-panel churn).

Today there is **no `tests/`**. Verification has been: the user hand-testing, and me
running ad-hoc node/python snippets + headless-Chrome screenshots. That doesn't persist.

## The shape of the codebase (what we're testing/cleaning)

- Pipeline: `extract.py`(293) → `summarize.py`(652, AI) → `classify.py`(2232, AI +
  lots of mechanical post-processing) → `dashboard.json`.
- `serve.py`(2024): HTTP API + ttyd orchestration.
- `cockpit.html`: vanilla-JS UI (the product surface).
- Legacy: `render-html.py`(**6957**) + `render-tree.py`(264) — the static "classic"
  views behind `/classic`. Almost certainly mostly dead now that `cockpit.html` is THE
  UI. `_migrate_dd011_tasks.py` (one-shot), `_test_task_persistence.py` (one ad-hoc test).
- Pivot debris still in tree: `dedup_by_session`, `apply_initiative_links`,
  `initiative_links.json`, `mint_sealed_initiatives`, `thread` level,
  `repair_short_session_ids` — the card=session pivot (CLAUDE.md) says these should go.

## Proposal

### 1. Test layers (fast, deterministic, no AI in CI)

- **Unit — Python pure functions** (highest value): `classify.artifact_key`,
  the dedup/`aggregate_artifacts`/`enforce_*` mechanical passes, `extract` parsing,
  `summarize` frontmatter parse, `serve` helpers (`_ttyd_patched_index`,
  `_resume_cwd_for`, cwd→worktree resolver from DD-022, the live-status gate). These
  are where the real logic + past bugs live (artifact dedup, sealed segments, bands).
- **Unit — cockpit JS pure functions**: `extArts/locArts/dedupe/artKey/httpUrl/
  groupByType/bandFor/resLbl`. Extract them so node can import them, then formalize the
  ad-hoc node tests I've been writing into a real suite.
- **Integration — pipeline on fixtures**: feed canned `cache/sessions/*.json` +
  `cache/summaries/*.md` through `classify` (mechanical path) and snapshot the
  resulting `dashboard.json` (golden file). No AI — summaries are fixtures.
- **Integration — serve endpoints**: in-process `serve.Handler` against a temp
  cache dir; assert `/api/data`, dedup, archive-weeks, terminal-gate responses.
- **E2E (thin, optional, not in CI gate)**: one headless-Chrome smoke — cockpit renders
  rows from a fixture `dashboard.json`, terminal modal opens. Keep minimal (flaky).
- **AI-touching code**: never in CI. Test the *prompt contract* by feeding recorded
  transcripts and asserting on the *parsing*, not the model output.

### 2. Approach: characterization first, then cleanup

1. Write **characterization tests** that pin current behavior (golden `dashboard.json`
   from real fixtures, snapshot of key API responses). This is the safety net.
2. **Then** delete dead code and refactor under the net, re-running snapshots.

### 3. Dead-code cleanup (do under the net)

Candidates (verify each before deleting):
- **`render-html.py` (6957) + `render-tree.py` + `/classic`**: if the classic view is no
  longer used, retire it (huge LOC win). Confirm with the user first — it may be a
  fallback they value.
- **Pivot debris**: `dedup_by_session`, `apply_initiative_links`, `initiative_links.json`,
  `mint_sealed_initiatives`, `thread` level, `repair_short_session_ids` — remove per the
  card=session pivot once tests confirm cards still assemble (per-session card + cwd group).
- **One-shots**: `_migrate_dd011_tasks.py`, stale `_test_task_persistence.py` (fold into
  the new suite).
- **Cockpit**: `chipsRow` (now uncalled after the row-chip removal), any CSS left by the
  fan/deck/scatter iterations, the removed-button paths.

### 4. Data-model consolidation

- Document + version the **`dashboard.json` schema** (card shape, `artifacts`,
  `sealed`/`origin_session`, the DD-022 `code_location`) in one place.
- Inventory the **cache files** (`state.json`, `summaries/`, `live/`, `terminals.json`,
  `sync_status.json`, `initiative_links.json`, `last_ai_run.epoch`, …): which are live,
  which are pivot leftovers; prune and document each.
- Normalize artifact shape (the dedup/url-precedence fixes from DD-021 should be the
  one canonical `artifact_key`).

## Tooling

- **pytest** for Python (dev-only dep; the runtime stays stdlib-only per macOS
  portability). Tests live in `tests/`, fixtures in `tests/fixtures/`.
- **node --test** (or a tiny runner) for the extracted cockpit JS functions.
- A `make test` / `bin/test` entry that runs both, fast (< a few seconds, no AI, no net).
- Optional pre-push hook; CI later if the repo gets one.

## Open questions

- **Retire `/classic` + `render-html.py`?** Biggest cleanup win but needs the user's OK.
- **pytest as a dev dependency** acceptable (runtime stays stdlib)? Assume yes.
- **How far to push the data-model refactor** vs. just documenting it — start by
  documenting + pruning obviously-dead files, defer structural changes.

## Rough plan

1. `tests/` scaffold + `bin/test` runner; unit tests for the Python mechanical passes
   (artifact_key/dedup/aggregate) and the cockpit JS pure fns — the safety net.
2. Golden-`dashboard.json` characterization from a small fixture set.
3. Cleanup pass: confirm + remove pivot debris and (with OK) the classic renderer.
4. Data-model doc + cache-file inventory + prune.

Sequence matters: **net first, then cut.**

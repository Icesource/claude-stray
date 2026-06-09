# DD-024 cleanup audit — what is actually dead vs. only *looks* dead

**Status**: Audit complete; classic page retired per user decision (2026-06-09)
**Author**: Claude (tech-debt worktree, branch `worktree-tech-debt`)
**Date**: 2026-06-09
**Companion to**: [DD-024-test-system-and-cleanup.md](DD-024-test-system-and-cleanup.md)

## TL;DR

The DD-024 design doc *hypothesized* a long list of dead code (the 6957-line
`render-html.py`, the `/classic` route, and the card=session "pivot debris":
`dedup_by_session`, `apply_initiative_links`, `initiative_links.json`,
`mint_sealed_initiatives`, `repair_short_session_ids`, the `thread` level).

**None of it was mechanically dead** — every item was still wired into the live
`classify.py` pipeline and/or `serve.py` routes. So none of it qualified for a
"confirmed-zero-reference" auto-delete. The split that followed:

- **`render-html.py` / `/classic`** — live, but the **user then decided to retire it**
  (the cockpit is the only UI). Done as a deliberate refactor: pet feature migrated
  first, then deleted. See *"Retired (user-approved)"* below.
- **Pivot debris** (`dedup_by_session`, `apply_initiative_links`, …, `thread` level) —
  still live, **left in place**, documented under *"DO NOT DELETE"* for a human.

**What WAS deleted** (separate commits, each grep-proven before cutting):

| Item | Commit | Note |
|---|---|---|
| `chipsRow` JS + orphaned `.chip.more` CSS in `cockpit.html` | `771c044` | defined, zero callers; `chip()` still used so it stays |
| `render-html.py` (6957 lines) + `/classic` + `/dashboard.html` routes + their serve.py/classify.py wiring | `560f032` | user-approved retirement; cockpit is the only UI |
| `bin/stray --html` flag; `--open` repointed to `--serve` | `080e484` | both were classic static-page entry points; `--open` now opens the live cockpit |

Plus non-deletions: `test_worktree.py` made worktree-robust (`7ac42b5`, `bin/test`
now 9/9); the pet/tips feature migrated into `cockpit.html` (`c52cc9d`).

---

## Retired (user-approved) — `render-html.py` + `/classic`

This was live (regenerated after every data write, served on `/classic` and
`/dashboard.html`), so it never qualified for an automatic delete. The user decided
on 2026-06-09 that the classic page is unused and the **cockpit is the only UI**, so it
was retired as a deliberate, verified refactor:

1. **Migrated the 桌宠 (pet + tips bubble)** — the one classic-only feature worth
   keeping — into `cockpit.html` (`c52cc9d`). Sprite inlined as base64 (cockpit is a
   static file); data still comes from the existing `/api/derived`. Verified headless:
   bubble renders, click cycles, no JS errors, no overlap with `.disc`/toast.
2. **Deleted `render-html.py`** and removed its wiring (`560f032`): `/classic` +
   `/dashboard.html` routes, `RENDER_HTML`/`HTML_FILE`, the render-html call in
   `regenerate_html()`/`regen_html()`, and the `HTML_FILE` branch of `_maybe_regen_html`.
3. **Fixed `bin/stray`** (`080e484`): `--html`/`--open` had `exec`'d the now-deleted
   script. `--html` removed; `--open`/`-o` repointed to `--serve` (cockpit is dynamic
   and needs the server); `--tree` kept (render-tree only).

**Kept on purpose:**
- **`render-tree.py` + `/mindmap-tree.html`** — a *separate* markmap export view, not
  part of "classic". It does not import `render-html.py` (has its own internal
  `render_html()`), reads `dashboard.json` directly. `regenerate_html()`/`regen_html()`
  now run only it. Future cleanup candidate if the export view is also unwanted, but the
  user only scoped "classic", so it stays.
- **`bin/assets/pet/` (cat-walk.png + README)** — no longer read at runtime (cockpit
  inlines the base64), but it's the **source sprite + CC0 attribution record**. Deleting
  it would lose provenance, so it stays.

---

## DO NOT DELETE — looks dead, is actually live

Each entry: the claim, the grep, and *why it's still load-bearing*.

### 1. (historical) `render-html.py` + `/classic` — now retired, see section above

Originally documented here as "live, do not auto-delete." The user has since approved
its retirement; it was removed as a deliberate refactor (above). The original evidence
that proved it was *not* mechanically dead:

```
bin/serve.py    RENDER_HTML constant + regenerate_html() (4 call sites) + /classic route
bin/classify.py regen_html() ran render-html.py at the end of every classify run
```

The remaining entries below (sections 2–6) are the card=session "pivot debris" — **still
live and still in the tree**, left for a human. Each is wired into the live `classify.py`
assembly run and/or a `serve.py` endpoint, so retiring any of them is a behavioral
refactor (do it under the DD-024 characterization tests), not a mechanical delete.

### 2. `dedup_by_session` (classify.py)

**Claim:** card=session pivot debris.

**Reality: live**, and called from *two* places including a serve.py API path.

```
bin/classify.py:576  def dedup_by_session(mindmap) -> int
bin/classify.py:2209 dedup_n = dedup_by_session(new_mm)        # main pipeline
bin/serve.py:1027    classify.dedup_by_session(data["mindmap"]) # an HTTP handler re-dedups
```

The card=session model is exactly *why* a session-keyed dedup pass exists (one card per
session id). This looks like the mechanism that *implements* the pivot, not leftover from
before it. **Do not remove without understanding what serve.py:1027 guards.**

### 3. `apply_initiative_links` + `initiative_links.json` + `load_initiative_links`

**Claim:** pivot debris (DD-016 merges).

**Reality: live durable-merge feature** with a write endpoint and re-apply on every run.

```
bin/classify.py:51   LINKS_FILE = CACHE_DIR / "initiative_links.json"  # DD-016 durable merges
bin/classify.py:615  def apply_initiative_links(mindmap) -> int
bin/classify.py:2212 merged_n = apply_initiative_links(new_mm)         # main pipeline
bin/serve.py:1404    # endpoint records a user-declared merge into initiative_links.json
bin/serve.py:1438    n = classify.apply_initiative_links(d)            # re-applied on demand
```

There is a user-facing "merge these" action whose persistence *is* `initiative_links.json`.
Deleting the file/functions would silently drop a working feature and break that endpoint.

### 4. `mint_sealed_initiatives` (classify.py)

```
bin/classify.py:696  def mint_sealed_initiatives(new_mm, all_summaries, deleted_ids)
bin/classify.py:2202 sealed_n = mint_sealed_initiatives(new_mm, all_summaries, deleted_ids)
```

Live — first mechanical step of the assembly run (creates sealed per-session
initiatives, then dedup → links). Central to assembly, not debris.

### 5. `repair_short_session_ids` (classify.py)

```
bin/classify.py:1910 def repair_short_session_ids(mindmap, hot_sids) -> int
bin/classify.py:2139 repaired = repair_short_session_ids(new_mm, hot_sids)
```

Live in the main pipeline. Repairs truncated session ids — directly relevant to the
card=session identity model (a card's identity *is* its session id), so removing it
would risk identity bugs.

### 6. The `thread` level (DD-014 three-tier)

**Claim:** thread hierarchy is pivot debris.

**Reality: live** across classify.py and the cockpit UI.

```
bin/classify.py:62   LEVELS = ("chip", "card", "thread")
bin/classify.py:1403 def normalize_parent_thread_id(new_mm) -> int   (called :2174)
bin/classify.py:1461/1491 mechanical level assignment with thread-stickiness  (called :2168+)
bin/cockpit.html:531 const LV={thread:'主线',card:'卡',chip:'片'};       # UI label map
```

`chip`/`card`/`thread` is the active level enum; the cockpit renders all three. Not dead.

---

## DELIBERATELY NOT DELETED — borderline (no *runtime* caller, but not safe)

These have **no code invocation** (only doc/CHANGELOG references), so a naive "is it
imported?" check calls them dead. They are **upgrade-path / coverage** assets, so deleting
them is a product decision, not a mechanical cleanup. Left for a human.

### `_migrate_dd011_tasks.py` (one-shot) and `_migrate_to_stray.sh` (one-shot)

```
# no runtime entrypoint invokes either:
grep -rn '_migrate_dd011\|_migrate_to_stray' bin/stray bin/install.sh bin/quick-install.sh \
        bin/pipeline-run.sh bin/refresh-bg.sh bin/layer2-trigger.sh install.sh   -> (empty)
# only historical references:
_migrate_dd011_tasks  -> CHANGELOG.md, DD-011, DD-024
_migrate_to_stray     -> CHANGELOG.md
```

They are *manual* migration scripts (collapse `task_archive/` → DD-011 schema; rename the
old `mindmap` install → `stray`). A user upgrading across those versions still runs them by
hand. Safe to delete **only** once we declare those upgrade paths unsupported. → human call.

### `_test_task_persistence.py` (ad-hoc test)

```
# not in the bin/test runner, no code imports it; referenced only in release docs:
_test_task_persistence -> docs/RELEASE.md:108, docs/zh-CN/RELEASE.md, DD-010, DD-011, DD-024
```

It is the **only** task-persistence test in the repo (tests/ has `test_subcards`,
`test_worktree` — no task test). DD-024's plan is to *fold it into the new suite*, not drop
it. Deleting it now loses coverage. → fold-in, don't delete (separate task).

---

## Method (so this is reproducible)

For each symbol/file: `grep -rn '<name>' --include='*.py' --include='*.sh' --include='*.html'`
across the repo (excluding `.git/` and the definition file itself), then read each hit to
classify it as *live call* / *historical doc* / *definition only*. Only "definition only,
zero callers" qualifies for deletion under the brief's "确证无任何引用" bar. A full
defined-but-unreferenced scan of top-level `def`s in `classify.py`/`serve.py`/`summarize.py`/
`extract.py`/`render-html.py` surfaced **no** orphan functions.

## Recommendation for the human

The big LOC win is **done**: `render-html.py` + `/classic` retired (−6957 lines), with the
one feature worth keeping (the pet) migrated to the cockpit first. What remains is the
**pivot-code consolidation** (sections 2–6) — `dedup_by_session`, `apply_initiative_links`/
`initiative_links.json`, `mint_sealed_initiatives`, `repair_short_session_ids`, the `thread`
level. Those are **deliberate refactors**, each behind a working route or pipeline step —
exactly the kind DD-024 says to do *under the test net*. Sequence: (1) land the
characterization tests DD-024 proposes, (2) then cut, re-running snapshots. This audit is
that net's blast-radius map.

Smaller open items: `render-tree.py`/`/mindmap-tree.html` (the markmap export — kept, since
the user only scoped "classic") and the one-shot migration scripts / ad-hoc
`_test_task_persistence.py` (see the borderline section above).

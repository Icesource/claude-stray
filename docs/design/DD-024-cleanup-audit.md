# DD-024 cleanup audit — what is actually dead vs. only *looks* dead

**Status**: Audit complete (evidence-based)
**Author**: Claude (tech-debt worktree, branch `feat/dd-022-worktree`)
**Date**: 2026-06-09
**Companion to**: [DD-024-test-system-and-cleanup.md](DD-024-test-system-and-cleanup.md)

## TL;DR

The DD-024 design doc *hypothesized* a long list of dead code (the 6957-line
`render-html.py`, the `/classic` route, and the card=session "pivot debris":
`dedup_by_session`, `apply_initiative_links`, `initiative_links.json`,
`mint_sealed_initiatives`, `repair_short_session_ids`, the `thread` level).

**I grepped every one. None of them are dead.** They are all still wired into the
live `classify.py` pipeline and/or `serve.py` HTTP routes. Removing them is a real
refactor with behavioral risk — **not** a safe "confirmed-zero-reference" delete —
so per the worktree brief they are **left in place** and documented here for a human
to decide.

**What WAS safely deleted** (separate commits, each grep-proven zero-reference):

| Item | Commit | Evidence |
|---|---|---|
| `chipsRow` JS + orphaned `.chip.more` CSS in `cockpit.html` | `771c044` | `grep -n chipsRow bin/cockpit.html` → only the definition line; `chip()` itself still used at line 636 so it stays |

Plus a test-system fix (not a deletion): `test_worktree.py` was brittle to running
inside a worktree — fixed in `7ac42b5` so `bin/test` is 9/9 green here.

---

## DO NOT DELETE — looks dead, is actually live

Each entry: the claim, the grep, and *why it's still load-bearing*.

### 1. `render-html.py` (6957 lines) + `render-tree.py` + the `/classic` route

**Claim (DD-024):** legacy static views, "almost certainly mostly dead now that
`cockpit.html` is THE UI."

**Reality: live.** It is regenerated after *every* data write and served on two routes.

```
bin/serve.py:53    RENDER_HTML = REPO_ROOT / "bin" / "render-html.py"
bin/serve.py:555   def regenerate_html(): subprocess.run([sys.executable, str(RENDER_HTML)] ...)
bin/serve.py:1440  threading.Thread(target=regenerate_html, daemon=True).start()
bin/serve.py:1519  threading.Thread(target=regenerate_html, daemon=True).start()
bin/serve.py:1639  threading.Thread(target=regenerate_html, daemon=True).start()
bin/serve.py:1960  regenerate_html()
bin/serve.py:988   if path in ("/dashboard.html", "/classic"):  -> serves HTML_FILE
bin/classify.py:1945 def regen_html(): for script in ("render-html.py","render-tree.py"): subprocess.run(...)
bin/classify.py:2226 regen_html()      # end of every classify run
```

So the classic dashboard is still produced by the pipeline and still reachable at
`/classic` and `/dashboard.html`. The cockpit (`/`) is the *default* page, but classic
is a live fallback, not dead code.

**Why not delete:** it's the single biggest LOC win, but it's wired into the pipeline
and a user-facing URL. DD-024 itself says retiring it "needs the user's OK." Decision
for a human: do we drop `/classic` + stop calling `regen_html()`/`regenerate_html()`
and delete both renderers? If yes it's a coordinated change across `serve.py` (routes +
`regenerate_html` + 4 call sites + `_maybe_regen_html`), `classify.py` (`regen_html`),
and docs.

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

The real LOC win (retire `render-html.py`/`render-tree.py`/`/classic`) and the pivot-code
consolidation are **deliberate refactors**, each behind a working route or pipeline step —
exactly the kind DD-024 says to do *under the test net*. Sequence: (1) land the
characterization tests DD-024 proposes, (2) then cut, re-running snapshots. This audit is
that net's blast-radius map.

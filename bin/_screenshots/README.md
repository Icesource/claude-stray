# Reproducer for promo screenshots

Regenerate `docs/assets/screenshots/{en,zh-CN}/` after the dashboard
UI changes.

## Prerequisites

- Repo cloned, `bash bin/install.sh` already run
- `stray --serve` running (the screenshot script hits
  http://127.0.0.1:9876/)
- Playwright skill installed at `~/.claude/skills/playwright-skill/`

## How it works

1. **Pause the pipeline** so the Stop hook can't overwrite our mock
   data mid-shoot:
   ```bash
   bin/stray --pause "screenshot session"
   ```

2. **Stash your real cache** (the script clobbers `cache/dashboard.json`):
   ```bash
   mkdir -p /tmp/stray-bak
   cp -a cache/dashboard.{json,html} cache/derived /tmp/stray-bak/
   mv cache/archive /tmp/stray-archive-stash   # hide real archived count
   mkdir cache/archive
   ```

3. **Pick a language** and run the mock script:
   ```bash
   python3 bin/_screenshots/make-mock-zh-CN.py    # writes zh-CN cards
   #   — or —
   python3 bin/_screenshots/make-mock-en.py       # also flips config.lang=en
   ```

4. **Lock dashboard files RO** while the screenshot script runs (so a
   stray classify can't race in):
   ```bash
   python3 bin/render-html.py
   chmod 444 cache/dashboard.{json,html}
   ```

5. **Shoot**:
   ```bash
   cd ~/.claude/skills/playwright-skill && \
     OUT_PREFIX=/tmp/shot- node run.js \
       /path/to/claude-stray/bin/_screenshots/playwright-shots.js
   ```
   Outputs `/tmp/shot1-overview.png` through `/tmp/shot5-filter-active.png`.

6. **Copy to repo**:
   ```bash
   cp /tmp/shot1-overview.png      docs/assets/screenshots/<lang>/01-overview.png
   # ... 02-05 ...
   ```

7. **Restore everything**:
   ```bash
   chmod 644 cache/dashboard.{json,html}
   cp -a /tmp/stray-bak/* cache/
   rmdir cache/archive && mv /tmp/stray-archive-stash cache/archive
   # flip config.lang back to your real language
   bin/stray --resume
   python3 bin/render-html.py
   ```

## Why the dance

- `stray --serve` polls `cache/dashboard.json` and re-renders HTML on
  changes. Locking the file RO prevents an async classify from racing
  in mid-shoot.
- The archive sidebar count is built from `cache/archive/*/*.json` on
  disk, NOT from `dashboard.json`. Stashing the directory keeps the
  count honest to the mock.
- The pause is belt + suspenders — if a classify was already running
  when we set the kill switch, it can still complete one writeback
  before stopping, so the chmod is the real guard.

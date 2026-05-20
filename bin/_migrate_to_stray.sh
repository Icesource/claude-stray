#!/usr/bin/env bash
# Migrate an existing claude-code-worktree install to claude-stray.
#
# What this fixes on your machine:
#   - cache/mindmap.json   → cache/dashboard.json   (data file rename, v0.6.0)
#   - cache/mindmap.html   → cache/dashboard.html
#   - ~/.claude/skills/mindmap/  → ~/.claude/skills/stray/   (if you had it)
#   - claude-code-worktree path strings in ~/.claude/settings.json hooks
#
# What this does NOT do:
#   - Rename your repo directory (~/Code/claude-code-worktree/ →
#     ~/Code/claude-stray/). That's a `mv` you should run manually so
#     you can update your shell history / bookmarks at the same time.
#   - Modify CHANGELOG.md historical entries or PLAN.md.
#
# Idempotent — safe to re-run. Print-only first with --dry-run.
#
# Usage:
#   bash bin/_migrate_to_stray.sh --dry-run
#   bash bin/_migrate_to_stray.sh

set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  echo "=== DRY RUN — nothing will be changed ==="
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME"
CHANGES=0

step() { echo; echo "▶ $1"; }
do_or_say() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would: $*"
  else
    echo "  $*"
    "$@"
  fi
  CHANGES=$((CHANGES + 1))
}

# 1. Cache data files ---------------------------------------------------------
step "Renaming cache data files"
for pair in "mindmap.json:dashboard.json" "mindmap.html:dashboard.html"; do
  old="${pair%%:*}"
  new="${pair##*:}"
  src="$REPO_ROOT/cache/$old"
  dst="$REPO_ROOT/cache/$new"
  if [ -f "$src" ] && [ ! -e "$dst" ]; then
    do_or_say mv "$src" "$dst"
  elif [ -f "$src" ] && [ -e "$dst" ]; then
    echo "  skip: both $old and $new exist (probably already migrated). Keeping $new, deleting stale $old."
    [ "$DRY_RUN" -eq 0 ] && rm "$src"
  else
    echo "  skip: $old not present"
  fi
done

# 2. ~/.claude/skills/ rename (only if user had an installed SKILL.md) -------
step "Renaming ~/.claude/skills/mindmap → ~/.claude/skills/stray (if present)"
OLD_SKILL="$HOME_DIR/.claude/skills/mindmap"
NEW_SKILL="$HOME_DIR/.claude/skills/stray"
if [ -d "$OLD_SKILL" ] && [ ! -e "$NEW_SKILL" ]; then
  do_or_say mv "$OLD_SKILL" "$NEW_SKILL"
elif [ -d "$OLD_SKILL" ] && [ -e "$NEW_SKILL" ]; then
  echo "  skip: both exist; deleting old $OLD_SKILL"
  [ "$DRY_RUN" -eq 0 ] && rm -rf "$OLD_SKILL"
else
  echo "  skip: no installed skill at $OLD_SKILL"
fi

# 3. Settings.json hook paths -------------------------------------------------
step "Updating ~/.claude/settings.json hook paths"
SETTINGS="$HOME_DIR/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  if grep -q "claude-code-worktree" "$SETTINGS"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  would: replace 'claude-code-worktree' with 'claude-stray' in $SETTINGS"
      echo "         and back it up to $SETTINGS.bak.<timestamp>"
    else
      cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
      python3 - "$SETTINGS" <<'PY'
import json, sys
p = sys.argv[1]
with open(p) as f:
    data = f.read()
# String-level replace inside the JSON — simpler than walking the tree.
data = data.replace("claude-code-worktree", "claude-stray")
with open(p, "w") as f:
    f.write(data)
PY
      echo "  updated $SETTINGS (backup at .bak.<timestamp>)"
    fi
    CHANGES=$((CHANGES + 1))
  else
    echo "  skip: $SETTINGS has no 'claude-code-worktree' references"
  fi
else
  echo "  skip: $SETTINGS not found"
fi

# 4. ~/.local/bin compat ------------------------------------------------------
step "Shell wrapper compat (~/.local/bin)"
LOCAL_BIN="$HOME_DIR/.local/bin"
if [ -L "$LOCAL_BIN/mindmap" ] || [ -L "$LOCAL_BIN/stray" ]; then
  echo "  re-run bin/install.sh to refresh both 'stray' and 'mindmap' symlinks"
else
  echo "  skip: no existing symlinks found"
fi

# 5. Report -------------------------------------------------------------------
echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== DRY RUN done. $CHANGES change(s) would apply. Re-run without --dry-run to apply. ==="
else
  echo "=== migration done. $CHANGES change(s) applied. ==="
  echo
  echo "Next steps you should do manually:"
  echo "  1. (optional) rename the repo directory:"
  echo "       mv $REPO_ROOT $(dirname "$REPO_ROOT")/claude-stray"
  echo "     If you do this, also re-run bin/install.sh from the new location"
  echo "     so the symlinks and hook paths point at the new directory."
  echo "  2. Restart any running serve.py — the running process has the old"
  echo "     cache/mindmap.json path baked into memory; restart picks up"
  echo "     the new cache/dashboard.json."
fi

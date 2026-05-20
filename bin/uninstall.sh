#!/usr/bin/env bash
# Uninstall claude-stray (also catches the legacy claude-code-worktree
# install). Removes everything we put on the user's machine *except*
# the data the user might still want — Claude Code session jsonl
# files and the repo source tree. Pass --purge to also wipe those.
#
# What this removes by default:
#   1. Slash commands       (~/.claude/commands/{stray,stray-refresh,
#                            mindmap,mindmap-refresh}.md)
#   2. Shell wrappers       (~/.local/bin/{stray,mindmap})
#   3. SKILL                (~/.claude/skills/stray/)
#   4. Claude Code hooks    (Stop + SessionStart entries in
#                            ~/.claude/settings.json — settings.json
#                            backed up to .bak.<timestamp> first)
#   5. Legacy launchd plist (com.claude-code-worktree.plist /
#                            com.claude-stray.plist if either still
#                            lying around)
#
# What this leaves alone by default:
#   - The repo source directory (e.g. ~/Code/claude-stray) — prints a
#     hint at the end so the user can rm it themselves.
#   - The local cache (cache/ inside the repo) — same.
#   - The user's Claude Code session jsonl files at
#     ~/.claude/projects/-Users-<you>-Code-claude-stray/ — those are
#     conversation transcripts, your data, not ours.
#
# With --purge: also rm -rf the cache/ directory and the repo dir,
# AND offer to drop the session transcripts (with a strong y/N prompt
# since that's irreversible).
#
# Usage:
#   bash bin/uninstall.sh
#   bash bin/uninstall.sh --purge

set -euo pipefail

PURGE=0
if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

HOME_DIR="$HOME"
OS="$(uname)"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Uninstalling claude-stray..."
echo

# Helpful warning if serve.py is still running — its file handles
# will release on shutdown anyway, but the user usually wants to know.
if pgrep -f "bin/serve.py" >/dev/null 2>&1; then
  echo "  ⚠  bin/serve.py is still running. Ctrl-C it before uninstalling"
  echo "     (or run:  pkill -f 'bin/serve.py'  ) so the dashboard port"
  echo "     is released cleanly."
  echo
fi

# 1. Slash commands — both new (/stray) and legacy (/mindmap) names
for cmd in stray stray-refresh mindmap mindmap-refresh; do
  link="$HOME_DIR/.claude/commands/$cmd.md"
  if [ -L "$link" ] || [ -f "$link" ]; then
    rm "$link"
    echo "[1/5] removed slash command: /$cmd"
  fi
done

# 2. Shell wrapper — both new and legacy aliases
for cli in stray mindmap; do
  BIN_LINK="$HOME_DIR/.local/bin/$cli"
  if [ -L "$BIN_LINK" ] || [ -f "$BIN_LINK" ]; then
    rm "$BIN_LINK"
    echo "[2/5] removed shell wrapper: $BIN_LINK"
  fi
done

# 3. SKILL directory
SKILL_DIR="$HOME_DIR/.claude/skills/stray"
if [ -d "$SKILL_DIR" ]; then
  rm -rf "$SKILL_DIR"
  echo "[3/5] removed SKILL: $SKILL_DIR"
fi
# Legacy SKILL name from before the rename — clean it up too.
LEGACY_SKILL="$HOME_DIR/.claude/skills/mindmap"
if [ -d "$LEGACY_SKILL" ]; then
  rm -rf "$LEGACY_SKILL"
  echo "[3/5] removed legacy SKILL: $LEGACY_SKILL"
fi

# 4. Claude Code hooks
SETTINGS="$HOME_DIR/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  python3 - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
hooks = data.get("hooks", {})
removed = 0
for event in list(hooks.keys()):
    before = len(hooks[event])
    hooks[event] = [
        e for e in hooks[event]
        if not any(
            "refresh-bg.sh" in h.get("command", "")
            and ("claude-code-worktree" in h["command"] or "claude-stray" in h["command"] or "claude-mindmap" in h["command"])
            for h in e.get("hooks", [])
        )
    ]
    removed += before - len(hooks[event])
    if not hooks[event]:
        del hooks[event]
if not hooks:
    data.pop("hooks", None)
json.dump(data, open(path, "w"), indent=2, ensure_ascii=False)
print(f"[4/5] removed {removed} hook entries from {path}")
PY
else
  echo "[4/5] no settings.json found, skipping"
fi

# 5. Legacy launchd plist cleanup
if [ "$OS" = "Darwin" ]; then
  REMOVED_PLIST=0
  for PLIST in \
      "$HOME_DIR/Library/LaunchAgents/com.claude-code-worktree.plist" \
      "$HOME_DIR/Library/LaunchAgents/com.claude-stray.plist"; do
    if [ -f "$PLIST" ]; then
      launchctl unload "$PLIST" 2>/dev/null || true
      rm "$PLIST"
      echo "[5/5] removed obsolete launchd job: $(basename "$PLIST")"
      REMOVED_PLIST=1
    fi
  done
  [ "$REMOVED_PLIST" -eq 0 ] && echo "[5/5] no obsolete launchd plists found"
else
  echo "[5/5] (skipped — not macOS)"
fi

echo

# ----- --purge: optionally wipe cache + repo dir + session jsonls ----------
if [ "$PURGE" -eq 1 ]; then
  echo "── --purge mode: also wiping local data ────────────────────"

  # Cache
  if [ -d "$REPO_ROOT/cache" ]; then
    rm -rf "$REPO_ROOT/cache"
    echo "  removed $REPO_ROOT/cache/"
  fi

  # Session transcripts (under ~/.claude/projects/) — these are CC
  # user data, not ours. Strong y/N prompt because they're your
  # actual conversation history.
  SESSIONS_DIR_PATTERN="$HOME_DIR/.claude/projects/$(echo "$REPO_ROOT" | tr '/' '-')"
  if [ -d "$SESSIONS_DIR_PATTERN" ]; then
    echo
    echo "  Found Claude Code session transcripts at:"
    echo "    $SESSIONS_DIR_PATTERN"
    count=$(find "$SESSIONS_DIR_PATTERN" -name "*.jsonl" -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "    ($count session(s) — your conversation history with Claude Code in this project)"
    echo
    printf "  Also delete these? [y/N] "
    read -r REPLY
    if [ "${REPLY:-N}" = "y" ] || [ "${REPLY:-N}" = "Y" ]; then
      rm -rf "$SESSIONS_DIR_PATTERN"
      echo "  removed session transcripts"
    else
      echo "  kept session transcripts at $SESSIONS_DIR_PATTERN"
    fi
  fi

  # Repo directory itself. Have to schedule this for AFTER the script
  # exits, because we're currently inside it (PWD on a soon-deleted dir
  # is fine on Unix but rm-ing while bash is sourcing scripts isn't).
  echo
  echo "  Repo dir $REPO_ROOT will be removed after this script exits."
  echo "  To do it now, run:    rm -rf $REPO_ROOT"
  echo "  Squeaky clean."
else
  echo "Done. The following are intentionally left alone:"
  echo "  - Repo source:           $REPO_ROOT"
  echo "  - Local cache:           $REPO_ROOT/cache/"
  echo "  - Session transcripts:   ~/.claude/projects/-Users-<you>-Code-claude-stray/"
  echo
  echo "To wipe everything in one go, rerun with --purge:"
  echo "  bash bin/uninstall.sh --purge"
fi

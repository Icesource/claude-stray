#!/usr/bin/env bash
# Uninstall claude-stray (also catches the legacy claude-code-worktree
# install): remove slash commands, shell wrapper, and Claude Code hooks
# (also evicts an obsolete launchd job if a previous install left one
# behind).
set -euo pipefail

HOME_DIR="$HOME"
OS="$(uname)"

echo "Uninstalling claude-stray..."
echo

# 1. Slash commands — both new (/stray) and legacy (/mindmap) names
for cmd in stray stray-refresh mindmap mindmap-refresh; do
  link="$HOME_DIR/.claude/commands/$cmd.md"
  if [ -L "$link" ] || [ -f "$link" ]; then
    rm "$link"
    echo "[1/3] removed slash command: /$cmd"
  fi
done

# 2. Shell wrapper — both new and legacy aliases
for cli in stray mindmap; do
  BIN_LINK="$HOME_DIR/.local/bin/$cli"
  if [ -L "$BIN_LINK" ] || [ -f "$BIN_LINK" ]; then
    rm "$BIN_LINK"
    echo "[2/3] removed shell wrapper: $BIN_LINK"
  fi
done

# 3. Claude Code hooks
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
print(f"[3/3] removed {removed} hook entries from {path}")
PY
else
  echo "[3/3] no settings.json found, skipping"
fi

# Legacy cleanup: earlier versions of the installer added a 2h
# launchd job. Remove it if still present so an `uninstall` from a
# new install still cleans up old artifacts.
if [ "$OS" = "Darwin" ]; then
  for PLIST in \
      "$HOME_DIR/Library/LaunchAgents/com.claude-code-worktree.plist" \
      "$HOME_DIR/Library/LaunchAgents/com.claude-stray.plist"; do
    if [ -f "$PLIST" ]; then
      launchctl unload "$PLIST" 2>/dev/null || true
      rm "$PLIST"
      echo "[cleanup] removed obsolete launchd job: $(basename "$PLIST")"
    fi
  done
fi

echo
echo "Done. The repo itself is untouched — delete it manually if you want:"
echo "  rm -rf $(cd "$(dirname "$0")/.." && pwd)"

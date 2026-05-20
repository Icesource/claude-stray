#!/usr/bin/env bash
# One-step installer for claude-stray.
# Sets up: slash commands, shell wrapper, Claude Code hooks.
# Does NOT trigger a model call. Does NOT install a launchd timer —
# the dashboard's own scheduler (`stray --serve`) now handles
# periodic derived features; the Stop/SessionStart hooks handle the
# main pipeline in real time.
#
# Backward compatibility: also installs a `mindmap` symlink pointing
# at `stray`, plus the legacy /mindmap and /mindmap-refresh slash
# commands, so users with muscle memory or scripts from before the
# rename keep working. These compat aliases will be removed in v0.7.
#
# Usage: bash bin/install.sh [--lang zh-CN|en]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME"
OS="$(uname)"

# --- Parse args --------------------------------------------------------------
LANG_CHOICE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --lang)
      LANG_CHOICE="$2"
      shift 2
      ;;
    --lang=*)
      LANG_CHOICE="${1#--lang=}"
      shift
      ;;
    -h|--help)
      echo "Usage: bash bin/install.sh [--lang zh-CN|en]"
      echo "  --lang   Output language for dashboard content (default: zh-CN)"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

case "${LANG_CHOICE:-zh-CN}" in
  zh-CN|en) ;;
  *)
    echo "Unsupported --lang: $LANG_CHOICE (use zh-CN or en)" >&2
    exit 1
    ;;
esac
LANG_CHOICE="${LANG_CHOICE:-zh-CN}"

echo "Installing claude-stray (lang=$LANG_CHOICE)..."
echo

# --- 0. Write config ---------------------------------------------------------
CACHE_DIR="$REPO_ROOT/cache"
CONFIG_FILE="$CACHE_DIR/config.json"
mkdir -p "$CACHE_DIR"
python3 - "$CONFIG_FILE" "$LANG_CHOICE" <<'PY'
import json, os, sys
path, lang = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except Exception:
        data = {}
data["lang"] = lang
data.setdefault("version", 1)
json.dump(data, open(path, "w"), indent=2, ensure_ascii=False)
PY
echo "[0/3] wrote config: $CONFIG_FILE (lang=$LANG_CHOICE)"


# --- 1. Slash commands -------------------------------------------------------
# Commands use __REPO__ as a placeholder; we substitute and copy (not symlink)
# so the installed command always has the correct absolute path.
# Install both the new (stray) and legacy (mindmap) names so existing
# muscle memory keeps working through one deprecation window.
COMMANDS_DIR="$HOME_DIR/.claude/commands"
mkdir -p "$COMMANDS_DIR"
for cmd in stray stray-refresh; do
  src="$REPO_ROOT/commands/$cmd.md"
  dst="$COMMANDS_DIR/$cmd.md"
  sed "s|__REPO__|$REPO_ROOT|g" "$src" > "$dst"
  echo "[1/3] installed slash command: /$cmd"
done
# Legacy aliases — same content, alternate filename. Remove these when
# v0.7 drops compat.
for alias_pair in "mindmap:stray" "mindmap-refresh:stray-refresh"; do
  legacy="${alias_pair%%:*}"
  current="${alias_pair##*:}"
  src="$REPO_ROOT/commands/$current.md"
  dst="$COMMANDS_DIR/$legacy.md"
  sed "s|__REPO__|$REPO_ROOT|g" "$src" > "$dst"
  echo "[1/3]   alias: /$legacy → /$current"
done

# --- 2. Shell wrapper --------------------------------------------------------
LOCAL_BIN="$HOME_DIR/.local/bin"
mkdir -p "$LOCAL_BIN"
BIN_LINK="$LOCAL_BIN/stray"
if [ -L "$BIN_LINK" ] || [ -f "$BIN_LINK" ]; then
  rm "$BIN_LINK"
fi
ln -s "$REPO_ROOT/bin/stray" "$BIN_LINK"
echo "[2/3] linked shell wrapper: stray -> $REPO_ROOT/bin/stray"
# Legacy alias — same target. Remove in v0.7.
LEGACY_LINK="$LOCAL_BIN/mindmap"
if [ -L "$LEGACY_LINK" ] || [ -f "$LEGACY_LINK" ]; then
  rm "$LEGACY_LINK"
fi
ln -s "$REPO_ROOT/bin/stray" "$LEGACY_LINK"
echo "[2/3]   alias: mindmap -> $REPO_ROOT/bin/stray"
if ! echo ":$PATH:" | grep -q ":$LOCAL_BIN:"; then
  echo "      WARNING: $LOCAL_BIN is not in \$PATH"
  echo "      Add to your shell rc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# --- 3. Claude Code hooks (Stop + SessionStart) ------------------------------
SETTINGS="$HOME_DIR/.claude/settings.json"
HOOK_CMD="bash $REPO_ROOT/bin/refresh-bg.sh"

if [ ! -f "$SETTINGS" ]; then
  echo "{}" > "$SETTINGS"
fi
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"

python3 - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, sys
path, hook_cmd = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)

hooks = data.setdefault("hooks", {})

# Clean up any stale entries (e.g. from a previous install path or rename).
for event in list(hooks.keys()):
    hooks[event] = [
        e for e in hooks[event]
        if not any(
            "refresh-bg.sh" in h.get("command", "")
            and ("claude-code-worktree" in h["command"] or "claude-stray" in h["command"] or "claude-mindmap" in h["command"])
            for h in e.get("hooks", [])
        )
    ]

def ensure_hook(event_name: str) -> None:
    entries = hooks.setdefault(event_name, [])
    entries.append({
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

ensure_hook("Stop")
ensure_hook("SessionStart")

with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
PY
echo "[3/3] installed Claude Code hooks (Stop + SessionStart)"

# --- 4. Cleanup any pre-existing launchd timer ------------------------------
# Earlier versions of this installer added a 2h launchd job as a "hook
# missed" backup. We removed that — the hook is reliable, the
# `stray --serve` scheduler now handles derived features (tips,
# weekly, etc.), and the 2h job clashed with the lazy-refresh
# principle (it kept running even when no one was looking at the
# dashboard). If we find an existing plist from an older install, evict it.
if [ "$OS" = "Darwin" ]; then
  for OLD_PLIST in \
      "$HOME_DIR/Library/LaunchAgents/com.claude-code-worktree.plist" \
      "$HOME_DIR/Library/LaunchAgents/com.claude-stray.plist"; do
    if [ -f "$OLD_PLIST" ]; then
      launchctl unload "$OLD_PLIST" 2>/dev/null || true
      rm -f "$OLD_PLIST"
      echo "[cleanup] removed obsolete launchd 2h job: $(basename "$OLD_PLIST")"
    fi
  done
fi

echo
if [ "$LANG_CHOICE" = "zh-CN" ]; then
  echo "完成！打开 Claude Code 后运行："
  echo
  echo "  /stray-refresh"
  echo
  echo "首次生成需 ~30-120 秒，之后会在后台自动刷新。"
  echo "随时查看：stray 或 /stray  (老名字 mindmap 仍兼容)"
  echo "切换语言：bash bin/install.sh --lang en"
else
  echo "Done! Open Claude Code and run:"
  echo
  echo "  /stray-refresh"
  echo
  echo "This generates your first dashboard (takes ~30-120s)."
  echo "After that, it refreshes automatically in the background."
  echo "View it anytime with:  stray  or  /stray  (legacy 'mindmap' still works)"
  echo "Switch language:  bash bin/install.sh --lang zh-CN"
fi

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
for cmd in stray; do
  src="$REPO_ROOT/commands/$cmd.md"
  dst="$COMMANDS_DIR/$cmd.md"
  sed "s|__REPO__|$REPO_ROOT|g" "$src" > "$dst"
  echo "[1/3] installed slash command: /$cmd"
done
# Sweep up the obsolete /stray-refresh + /mindmap-refresh installs from
# previous versions. `stray --serve` now auto-syncs on first run, the
# dashboard's 🔄 button covers manual refresh, and `stray --refresh`
# stays available from the shell — so the slash-command duplicate is
# retired. Quiet about it; this is post-cleanup, not user-facing news.
for old in stray-refresh mindmap-refresh; do
  rm -f "$COMMANDS_DIR/$old.md"
done
# Legacy alias — keep /mindmap working through one deprecation window
# (removed in v0.7).
for alias_pair in "mindmap:stray"; do
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

# --- 3. Claude Code hooks ----------------------------------------------------
# refresh-bg.sh (Stop, SessionStart) runs the AI pipeline + records live state.
# live-hook.sh (UserPromptSubmit, Notification, SessionEnd) only records live
# state (DD-015 Stage 1) — it must NOT trigger the pipeline on every prompt.
SETTINGS="$HOME_DIR/.claude/settings.json"
HOOK_CMD="bash $REPO_ROOT/bin/refresh-bg.sh"
LIVE_CMD="bash $REPO_ROOT/bin/live-hook.sh"

if [ ! -f "$SETTINGS" ]; then
  echo "{}" > "$SETTINGS"
fi
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"

python3 - "$SETTINGS" "$HOOK_CMD" "$LIVE_CMD" <<'PY'
import json, sys
path, hook_cmd, live_cmd = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    data = json.load(f)

hooks = data.setdefault("hooks", {})
OURS = ("refresh-bg.sh", "live-hook.sh")
PATHS = ("claude-code-worktree", "claude-stray", "claude-mindmap")

# Clean up our own prior entries (any install path / rename) so re-running
# the installer never stacks duplicate hooks.
for event in list(hooks.keys()):
    hooks[event] = [
        e for e in hooks[event]
        if not any(
            any(s in h.get("command", "") for s in OURS)
            and any(p in h.get("command", "") for p in PATHS)
            for h in e.get("hooks", [])
        )
    ]

def ensure_hook(event_name: str, cmd: str) -> None:
    entries = hooks.setdefault(event_name, [])
    for e in entries:  # dedupe by exact command
        if any(h.get("command") == cmd for h in e.get("hooks", [])):
            return
    entries.append({"hooks": [{"type": "command", "command": cmd}]})

ensure_hook("Stop", hook_cmd)
ensure_hook("SessionStart", hook_cmd)
ensure_hook("UserPromptSubmit", live_cmd)
ensure_hook("Notification", live_cmd)
ensure_hook("SessionEnd", live_cmd)

with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
PY
echo "[3/3] installed Claude Code hooks (Stop, SessionStart + live: UserPromptSubmit, Notification, SessionEnd)"

# Optional: in-browser terminal (DD-015). Off by default; needs ttyd. Never required.
if ! command -v ttyd >/dev/null 2>&1; then
  echo "      (optional) in-browser terminal needs ttyd — install it to enable:"
  case "$OS" in
    Darwin) echo "         brew install ttyd" ;;
    *)      echo "         apt install ttyd   # or your distro's package / https://github.com/tsl0922/ttyd" ;;
  esac
  echo "      with ttyd installed, the cockpit's 在终端打开 opens a browser terminal;"
  echo "      without it, that action falls back to opening a zellij pane."
fi

# --- 4. Resource-collection global prompt (DD-021) --------------------------
# Nudge Claude (globally) to print the FULL URL/path of any external resource it
# creates (MR/PR/CR/ISSUE/deployment, or a doc), so claude-stray can collect them
# and surface them next to the work. Written as a marked block in
# ~/.claude/CLAUDE.md (user memory, loaded every session); removed on uninstall.
# Skip with NO_RESOURCE_PROMPT=1.
if [ "${NO_RESOURCE_PROMPT:-0}" != "1" ]; then
  python3 - "$HOME_DIR/.claude/CLAUDE.md" <<'PY'
import sys, os
path = sys.argv[1]
START = "<!-- claude-stray:resource-prompt START -->"
END = "<!-- claude-stray:resource-prompt END -->"
body = ("When you create or reference an external resource through a CLI/skill "
        "(`gh`, `a1`/aone, etc.) — an MR/PR, CR, ISSUE, deployment, or release — "
        "print its **full URL** in your reply. When you create or substantially "
        "edit a document, print its **full path**. One short line is enough. "
        "(This lets claude-stray collect the resources a session produced and "
        "surface them next to the work — do not invent URLs you don't have.)\n\n"
        "When the user asks to start a **sub-card** (子卡 / 子任务 / fan out a "
        "parallel sub-task) under claude-stray, start EACH one by running this "
        "shell command: `stray spawn \"<task>\"` (one call per sub-task). "
        "IMPORTANT: do NOT use your built-in Task / sub-agent tool, and do NOT use "
        "`claude agents` background agents (Agent View) for this — those are "
        "claude-stray-invisible and are NOT sub-cards. `stray spawn` is the only "
        "thing that makes a real sub-card: it gives the sub-task its own git "
        "worktree + a resumable session + a card nested under this one. Let the "
        "USER decide the split — don't fan out on your own. Pull progress with "
        "`stray subtasks`; relay a message into one with `stray send <session_id> "
        "\"...\"`. On demand only — no autonomous loop.)")
block = (START + "\n<!-- managed by claude-stray; removed on uninstall -->\n"
         + body + "\n" + END + "\n")
os.makedirs(os.path.dirname(path), exist_ok=True)
txt = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
if START in txt and END in txt:
    txt = txt[:txt.index(START)] + block.rstrip("\n") + txt[txt.index(END) + len(END):]
else:
    if txt and not txt.endswith("\n\n"):
        txt = txt.rstrip("\n") + "\n\n"
    txt += block
open(path, "w", encoding="utf-8").write(txt)
PY
  echo "[4/4] added resource-collection prompt to ~/.claude/CLAUDE.md (skip: NO_RESOURCE_PROMPT=1)"
fi

# --- 5. Cleanup any pre-existing launchd timer ------------------------------
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
  echo "完成！现在在终端运行："
  echo
  echo "  stray --serve"
  echo
  echo "首次会自动扫描你的 Claude Code 历史会话生成卡片（~30-120 秒），"
  echo "之后每次会话结束都会自动更新。"
  echo "也可以用 /stray 在 Claude Code 里查看（老名字 /mindmap 仍兼容）。"
  echo "切换语言：bash bin/install.sh --lang en"
else
  echo "Done! Now in your terminal run:"
  echo
  echo "  stray --serve"
  echo
  echo "First launch auto-scans your Claude Code history into cards (~30-120s);"
  echo "every session afterwards updates the dashboard automatically."
  echo "Or use /stray inside Claude Code (legacy /mindmap still works)."
  echo "Switch language:  bash bin/install.sh --lang zh-CN"
fi

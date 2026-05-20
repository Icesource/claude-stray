#!/usr/bin/env bash
# One-line installer for claude-stray.
#
# Standard usage (curl-pipe-bash):
#
#   curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
#
# What it does:
#   1. Pre-flight checks  (git, python3 >= 3.9, claude CLI logged in)
#   2. Clone the repo to ~/Code/claude-stray (or update if it exists)
#   3. Run bin/install.sh  (slash commands, CLI wrapper, hooks)
#   4. Run bin/install-skill.sh  (~/.claude/skills/stray/, unless --no-skill)
#   5. Print next-step hints
#
# Knobs (set as env vars BEFORE the pipe, e.g. `INSTALL_DIR=~/foo curl ... | bash`):
#   INSTALL_DIR    where to clone the repo  (default: ~/.claude-stray —
#                  same convention as ~/.fzf, ~/.nvm, ~/.oh-my-zsh; the
#                  tool manages this directory, users don't touch it)
#   INSTALL_REF    branch/tag to checkout   (default: stable — the released line)
#   LANG_CHOICE    zh-CN | en               (default: zh-CN)
#   NO_SKILL=1     skip SKILL install
#
# Read me before piping: source is at
#   https://github.com/Icesource/claude-stray/blob/main/bin/quick-install.sh

set -euo pipefail

# --- knobs -------------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-$HOME/.claude-stray}"
INSTALL_REF="${INSTALL_REF:-stable}"
LANG_CHOICE="${LANG_CHOICE:-zh-CN}"
NO_SKILL="${NO_SKILL:-0}"
REPO_URL="${REPO_URL:-https://github.com/Icesource/claude-stray.git}"

# --- pretty print -------------------------------------------------------------
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
dim()    { printf "\033[2m%s\033[0m\n"  "$*"; }
step()   { printf "\n\033[1m▶ %s\033[0m\n" "$*"; }
die()    { red "✗ $*"; exit 1; }

# --- pre-flight checks -------------------------------------------------------
step "[1/4] Pre-flight checks"

command -v git >/dev/null     || die "git not found. Install git and re-run."
command -v python3 >/dev/null || die "python3 not found. Install Python 3.9+ and re-run."

PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PY_MAJ=${PY_VER%.*}
PY_MIN=${PY_VER#*.}
if [ "$PY_MAJ" -lt 3 ] || { [ "$PY_MAJ" -eq 3 ] && [ "$PY_MIN" -lt 9 ]; }; then
  die "Python $PY_VER found, need 3.9+. Upgrade and re-run."
fi
dim "  python3 $PY_VER ✓"
dim "  git $(git --version | awk '{print $3}') ✓"

if ! command -v claude >/dev/null; then
  yellow "  ⚠  'claude' CLI not on PATH. The dashboard will install but the"
  yellow "      Stop/SessionStart hooks need it to actually classify sessions."
  yellow "      Install Claude Code from https://claude.com/code first if you"
  yellow "      haven't already."
else
  dim "  claude CLI ✓"
fi

case "$LANG_CHOICE" in
  zh-CN|en) ;;
  *) die "LANG_CHOICE must be 'zh-CN' or 'en', got '$LANG_CHOICE'" ;;
esac

# --- clone / update ----------------------------------------------------------
step "[2/4] Cloning repo to $INSTALL_DIR (ref=$INSTALL_REF)"

if [ -d "$INSTALL_DIR/.git" ]; then
  dim "  repo already present — fetching and checking out $INSTALL_REF"
  cd "$INSTALL_DIR"
  git fetch --tags origin
  git checkout "$INSTALL_REF"
  git pull --ff-only origin "$INSTALL_REF" 2>/dev/null || dim "  (not a fast-forward — leaving as-is)"
elif [ -e "$INSTALL_DIR" ]; then
  die "$INSTALL_DIR exists but is not a git repo. Move or remove it and re-run."
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --branch "$INSTALL_REF" "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
green "  done: $(git rev-parse --short HEAD) on $INSTALL_REF"

# --- main installer ----------------------------------------------------------
step "[3/4] Running bin/install.sh"
bash "$INSTALL_DIR/bin/install.sh" --lang "$LANG_CHOICE"

# --- skill (opt-out via NO_SKILL=1) ------------------------------------------
step "[4/4] Installing SKILL ($([ "$NO_SKILL" = "1" ] && echo skip || echo into ~/.claude/skills/stray))"
if [ "$NO_SKILL" = "1" ]; then
  dim "  skipped (NO_SKILL=1). To install later: bash $INSTALL_DIR/bin/install-skill.sh"
else
  bash "$INSTALL_DIR/bin/install-skill.sh"
fi

# --- next steps --------------------------------------------------------------
echo
green "════════════════════════════════════════════════════════════"
green "  claude-stray installed at $INSTALL_DIR"
green "════════════════════════════════════════════════════════════"
echo
if [ "$LANG_CHOICE" = "zh-CN" ]; then
  echo "下一步:"
  echo
  echo "  1. 在 Claude Code 里跑一次 /stray-refresh"
  echo "     首次约需 30–120 秒,会自动分类你最近的所有 session"
  echo
  echo "  2. 启动 dashboard:"
  echo "       stray --serve"
  echo "     浏览器会自动打开 http://127.0.0.1:9876/"
  echo
  echo "  老版本 mindmap 命名兼容仍可用(mindmap、/mindmap)。v0.7 后移除。"
else
  echo "Next steps:"
  echo
  echo "  1. In Claude Code, run:  /stray-refresh"
  echo "     First refresh takes 30–120s while it classifies your sessions."
  echo
  echo "  2. Open the dashboard:"
  echo "       stray --serve"
  echo "     The browser will open at http://127.0.0.1:9876/"
  echo
  echo "  Legacy 'mindmap' command names still work; removed in v0.7."
fi
echo
dim "  Uninstall any time:  bash $INSTALL_DIR/bin/uninstall.sh"
dim "  Or squeaky clean:    bash $INSTALL_DIR/bin/uninstall.sh --purge"

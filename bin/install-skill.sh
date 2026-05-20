#!/usr/bin/env bash
# Install SKILL.md into ~/.claude/skills/stray/ so the main Claude Code
# Agent auto-activates it when the user asks about their work.
#
# Idempotent. Re-run any time to refresh after a SKILL.md change.
#
# Usage:
#   bash bin/install-skill.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME"
SKILL_SRC="$REPO_ROOT/SKILL.md"
SKILL_DIR="$HOME_DIR/.claude/skills/stray"
SKILL_DST="$SKILL_DIR/SKILL.md"

if [ ! -f "$SKILL_SRC" ]; then
  echo "Error: $SKILL_SRC not found." >&2
  exit 1
fi

mkdir -p "$SKILL_DIR"
cp "$SKILL_SRC" "$SKILL_DST"
echo "[ok] installed: $SKILL_DST"
echo
echo "Activates automatically the next time you ask Claude Code about"
echo "your current work, costs, blocked items, weekly recap, etc."
echo
echo "To remove later:"
echo "  rm -rf $SKILL_DIR"

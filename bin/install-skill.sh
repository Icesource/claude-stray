#!/usr/bin/env bash
# Install the stray SKILLs into ~/.claude/skills/ so the main Claude Code
# Agent auto-activates them:
#   stray           — dashboard management actions (open/refresh/pause/cost)
#   stray-subcards  — fan out parallel sub-cards from a conversation (DD-032)
#
# Idempotent. Re-run any time to refresh after a SKILL change.
#
# Usage:
#   bash bin/install-skill.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$HOME/.claude/skills"

install_one() {
  local src="$1" name="$2"
  if [ ! -f "$src" ]; then
    echo "Error: $src not found." >&2
    exit 1
  fi
  mkdir -p "$SKILLS_DIR/$name"
  cp "$src" "$SKILLS_DIR/$name/SKILL.md"
  echo "[ok] installed: $SKILLS_DIR/$name/SKILL.md"
}

install_one "$REPO_ROOT/SKILL.md" "stray"
install_one "$REPO_ROOT/skills/stray-subcards/SKILL.md" "stray-subcards"

echo
echo "Activates automatically the next time you ask Claude Code about your"
echo "current work / costs (stray), or ask to fan out sub-cards (stray-subcards)."
echo
echo "To remove later:"
echo "  rm -rf $SKILLS_DIR/stray $SKILLS_DIR/stray-subcards"

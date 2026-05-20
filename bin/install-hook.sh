#!/usr/bin/env bash
# Install Claude Code hooks for claude-stray.
# NOTE: install.sh already includes this step. This script exists for
# re-installing hooks independently if needed.
#
# Merges Stop and SessionStart hooks into ~/.claude/settings.json so that
# the worktree refreshes after every response turn and on session start.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
HOOK_CMD="bash $REPO_ROOT/bin/refresh-bg.sh"

if [ ! -f "$SETTINGS" ]; then
  echo "{}" > "$SETTINGS"
fi

# Back up before modifying.
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"

python3 - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, sys
path, hook_cmd = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)

hooks = data.setdefault("hooks", {})

def ensure_hook(event_name: str) -> None:
    entries = hooks.setdefault(event_name, [])
    # Each entry is {"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}
    # We use an empty matcher (applies to all).
    for entry in entries:
        for h in entry.get("hooks", []):
            if h.get("command") == hook_cmd:
                return  # already installed
    entries.append({
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

ensure_hook("Stop")
ensure_hook("SessionStart")

with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"[install-hook] updated {path}")
print("  - Stop hook: fires after every response turn")
print("  - SessionStart hook: fires on session open")
PY

echo
echo "Done. Hooks will apply to new Claude Code sessions."
echo "To verify:  jq .hooks $SETTINGS"
echo "To remove:  edit $SETTINGS and drop the matching entries."

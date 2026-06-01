#!/usr/bin/env bash
# DD-015 Stage 1 — lightweight hook for live session telemetry.
#
# Wired to UserPromptSubmit / Notification / SessionEnd. Unlike
# refresh-bg.sh, this does NOT run the AI pipeline — it only records the
# session's live status (a pure disk write). It returns immediately and
# never fails, so it is safe on high-frequency events like prompt submit.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cat 2>/dev/null | python3 "$REPO_ROOT/bin/live-state.py" 2>/dev/null || true
exit 0

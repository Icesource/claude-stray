#!/usr/bin/env bash
# DD-015 Stage 1 — lightweight hook for live session telemetry.
#
# Wired to UserPromptSubmit / Notification / SessionEnd. Unlike
# refresh-bg.sh, this does NOT run the AI pipeline — it only records the
# session's live status (a pure disk write). It returns immediately and
# never fails, so it is safe on high-frequency events like prompt submit.
set -u
# Resolve REPO_ROOT to the MAIN worktree (never a linked worktree), so the live
# write lands in the cache/ the server reads. See bin/_repo-root.sh. The
# `|| true` + :- fallback keep the hook working even if the helper is missing.
. "$(dirname "$0")/_repo-root.sh" 2>/dev/null || true
REPO_ROOT="${STRAY_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PAYLOAD="$(cat 2>/dev/null || true)"
printf '%s' "$PAYLOAD" | python3 "$REPO_ROOT/bin/live-state.py" 2>/dev/null || true
# 父←子信息同步(惰性):有未告知的子卡动态时输出一行 → UserPromptSubmit 的
# stdout 会作为上下文附进该轮。无动态时无输出,零开销。见 bin/subcard-context.py。
printf '%s' "$PAYLOAD" | python3 "$REPO_ROOT/bin/subcard-context.py" 2>/dev/null || true
exit 0

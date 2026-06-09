# Sourced by stray shell entry hooks (refresh-bg.sh / live-hook.sh) and the
# installer. Sets + exports STRAY_REPO_ROOT to the MAIN git worktree so live
# writes land in the cache/ the server reads — never a linked worktree's cache/.
#
# Why: a global Claude Code hook registered (by install.sh run from a worktree)
# as `bash .claude/worktrees/<x>/bin/refresh-bg.sh` would otherwise derive its
# REPO_ROOT from that worktree and write cache/live there, where serve (reading
# the main checkout) never sees it — the "card frozen on an old event" bug.
#
# Honors an already-exported STRAY_REPO_ROOT (a parent hook resolved it once),
# so nested python children skip the git call. POSIX sh + git only.

__stray_resolve_repo_root() {
  if [ -n "${STRAY_REPO_ROOT:-}" ]; then
    printf '%s' "$STRAY_REPO_ROOT"
    return
  fi
  here="$(cd "$(dirname "$0")/.." && pwd)"
  common="$(git -C "$here" rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -n "$common" ]; then
    case "$common" in
      /*) main="$(cd "$(dirname "$common")" 2>/dev/null && pwd || true)" ;;
      *)  main="$(cd "$here/$(dirname "$common")" 2>/dev/null && pwd || true)" ;;
    esac
    [ -n "${main:-}" ] && here="$main"
  fi
  printf '%s' "$here"
}

STRAY_REPO_ROOT="$(__stray_resolve_repo_root)"
export STRAY_REPO_ROOT

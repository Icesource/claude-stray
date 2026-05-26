#!/usr/bin/env python3
"""Auto-update helpers for claude-stray.

The installed repo at REPO_ROOT (default ~/.claude-stray) is a plain
git clone. Updates are `git pull --ff-only`. Versions are git tags
(semver), so `git describe --tags --abbrev=0` is the canonical local
version string and the remote refs/tags/* set is the canonical remote.

Public API:
    check(force=False)         -> dict snapshot, also writes cache state
    pull_latest()              -> dict {ok, before, after, output}
    read_state()               -> dict (last check + version cache)
    compare_versions(a, b)     -> -1 / 0 / 1   (semver-ish, missing == oldest)
    summarize_changes(a, b)    -> short text (last N commit subjects on a..b)

Throttling is the caller's responsibility — `check()` always does the
fetch when called. `should_check()` exposes the 24-hour gate so
serve startup + the background thread can both use the same policy.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "cache" / "update_state.json"
CHECK_INTERVAL = timedelta(hours=24)
# Bound on how many commits to summarize when reporting "what changed".
MAX_LOG_LINES = 10
# Bound the git fetch / pull operations so a wedged remote doesn't
# block serve startup forever.
GIT_TIMEOUT_SECS = 25


# ---------- subprocess wrappers ---------------------------------------------


def _git(*args: str, timeout: int = GIT_TIMEOUT_SECS) -> tuple[int, str, str]:
    """Run a git command inside REPO_ROOT. Returns (rc, stdout, stderr).
    Never raises — failure modes (offline, not-a-repo, etc.) are
    expected and the caller decides what to do."""
    try:
        res = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out"
    except Exception as e:
        return 1, "", str(e)


def is_git_repo() -> bool:
    rc, _, _ = _git("rev-parse", "--is-inside-work-tree", timeout=5)
    return rc == 0


def is_dirty() -> bool:
    """Working tree has uncommitted changes (excluding untracked)."""
    rc, out, _ = _git("status", "--porcelain", "-uno", timeout=5)
    return rc == 0 and bool(out.strip())


# ---------- version helpers -------------------------------------------------


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _parse(v: str) -> tuple[int, int, int] | None:
    """Return (major, minor, patch) or None if unparseable.
    Pre-release suffix is ignored for compare purposes."""
    if not v:
        return None
    m = _SEMVER.match(v.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def compare_versions(a: str, b: str) -> int:
    """Return -1/0/1 for a<b / a==b / a>b. Unparseable -> oldest."""
    pa, pb = _parse(a), _parse(b)
    if pa is None and pb is None:
        return 0
    if pa is None:
        return -1
    if pb is None:
        return 1
    if pa == pb:
        return 0
    return -1 if pa < pb else 1


def local_version() -> str:
    """Most recent git tag reachable from HEAD. Empty string if none."""
    rc, out, _ = _git("describe", "--tags", "--abbrev=0", timeout=5)
    if rc == 0 and out:
        return out
    return ""


def fetch_remote_tags() -> bool:
    """git fetch --tags origin. Returns True on success."""
    rc, _, _ = _git("fetch", "--tags", "--quiet", "origin")
    return rc == 0


def remote_version() -> str:
    """Highest semver tag known to the local git after a fetch.

    Implementation: list refs/tags/*, parse semver, return the max.
    This works without internet once we've fetched."""
    rc, out, _ = _git("tag", "--list", "v*.*.*", "--sort=-v:refname", timeout=5)
    if rc != 0 or not out:
        return ""
    for line in out.splitlines():
        line = line.strip()
        if _parse(line):
            return line
    return ""


# ---------- state -----------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except OSError:
        pass  # state file is a hint, not load-bearing


def should_check(*, force: bool = False) -> bool:
    """24-hour throttle. Caller passes force=True to override (e.g.
    when the user explicitly invokes `stray --check-updates`)."""
    if force:
        return True
    st = read_state()
    last = st.get("last_checked_at")
    if not last:
        return True
    try:
        t = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - t >= CHECK_INTERVAL


# ---------- public check + pull ---------------------------------------------


def check(*, force: bool = False, offline_ok: bool = True) -> dict:
    """Fetch remote tags (best-effort) and compute behind/ahead snapshot.

    Returns a dict:
        {
          "ok":          True if we have at least a local version,
          "online":      True if the fetch succeeded,
          "local":       "v0.7.0" or "",
          "remote":      "v0.7.0" or "",
          "behind":      True if local < remote (semver),
          "checked_at":  iso timestamp,
          "skipped":     True if throttled and force=False,
          "error":       str if anything went wrong,
        }

    Always writes the new state on a real check. On a throttled call
    (skipped=True) returns the previously-cached snapshot."""
    if not is_git_repo():
        return {"ok": False, "online": False, "local": "", "remote": "",
                "behind": False, "checked_at": _now_iso(),
                "skipped": False, "error": "not a git repo"}

    if not should_check(force=force):
        st = read_state()
        st["skipped"] = True
        return st

    local = local_version()
    online = fetch_remote_tags() if not offline_ok or True else False
    remote = remote_version()
    behind = (compare_versions(local, remote) < 0) if (local and remote) else False

    snap = {
        "ok": bool(local),
        "online": online,
        "local": local,
        "remote": remote,
        "behind": behind,
        "checked_at": _now_iso(),
        "skipped": False,
        "error": "" if (local or remote) else "no tags found locally or remotely",
    }
    # Preserve a last_skipped_at if the user said no in interactive prompt;
    # serve startup honors it to avoid pestering.
    prior = read_state()
    if prior.get("last_user_dismissed_at"):
        snap["last_user_dismissed_at"] = prior["last_user_dismissed_at"]
    snap["last_checked_at"] = snap["checked_at"]
    write_state(snap)
    return snap


def pull_latest() -> dict:
    """Run `git pull --ff-only origin main`. Refuses if the working
    tree has uncommitted changes (avoids tripping on user edits to a
    SKILL or commands/ override)."""
    if not is_git_repo():
        return {"ok": False, "error": "not a git repo"}
    if is_dirty():
        return {"ok": False, "error":
                "local has uncommitted changes — not pulling. Commit/stash first."}

    before = local_version() or _git("rev-parse", "--short", "HEAD")[1]
    # --ff-only is the safe default: if remote diverged we want a loud
    # failure, not a merge commit nobody asked for.
    rc, out, err = _git("pull", "--ff-only", "--tags", "origin", "main",
                         timeout=60)
    after = local_version() or _git("rev-parse", "--short", "HEAD")[1]
    if rc != 0:
        return {"ok": False, "before": before, "after": after,
                "output": (out + "\n" + err).strip(),
                "error": err or "git pull --ff-only failed"}
    # Refresh state so the dashboard reflects the new local immediately.
    snap = read_state()
    snap["local"] = after
    snap["behind"] = False
    snap["checked_at"] = _now_iso()
    snap["last_pulled_at"] = _now_iso()
    write_state(snap)
    return {"ok": True, "before": before, "after": after,
            "output": out.strip()}


def mark_user_dismissed() -> None:
    """User said 'no' at the interactive prompt. Don't re-ask for 24h."""
    st = read_state()
    st["last_user_dismissed_at"] = _now_iso()
    write_state(st)


def user_dismissed_recently() -> bool:
    st = read_state()
    last = st.get("last_user_dismissed_at")
    if not last:
        return False
    try:
        t = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - t < CHECK_INTERVAL


# ---------- changelog excerpt -----------------------------------------------


def summarize_changes(before_ref: str, after_ref: str) -> list[str]:
    """Return up to MAX_LOG_LINES commit subjects between before..after.

    Quietly returns [] on any failure (refs might not exist, the
    remote tag set might be incomplete, etc.)."""
    rng = f"{before_ref}..{after_ref}"
    rc, out, _ = _git("log", "--oneline", "--no-decorate", rng, timeout=5)
    if rc != 0 or not out:
        return []
    lines = []
    for line in out.splitlines()[:MAX_LOG_LINES]:
        # strip the leading short SHA so it reads as a list of changes
        parts = line.split(" ", 1)
        lines.append(parts[1] if len(parts) > 1 else line)
    return lines


# ---------- CLI for `stray --check-updates` / `--update` --------------------


def cli_check(*, force: bool = True) -> int:
    snap = check(force=force)
    local = snap.get("local") or "(none)"
    remote = snap.get("remote") or "(unknown)"
    if not snap.get("online"):
        print("claude-stray update check: offline (couldn't reach origin).")
        print(f"  installed: {local}")
        return 1
    if snap.get("behind"):
        print(f"claude-stray update available:  {local} → {remote}")
        changes = summarize_changes(local, "origin/main")
        if changes:
            print("\nRecent changes since your version:")
            for c in changes:
                print(f"  · {c}")
        print("\nRun `stray --update` to install.")
        return 0
    print(f"claude-stray is up to date  ({local})")
    return 0


def cli_update() -> int:
    snap = check(force=True)
    if not snap.get("online"):
        print(f"Can't reach origin — aborting. ({snap.get('error') or 'offline'})")
        return 1
    if not snap.get("behind"):
        print(f"Already up to date  ({snap.get('local') or '?'})")
        return 0
    print(f"Updating  {snap.get('local')} → {snap.get('remote')} …")
    result = pull_latest()
    if not result.get("ok"):
        print(f"Update failed: {result.get('error')}")
        if result.get("output"):
            print(result["output"])
        return 1
    print(f"Updated  {result.get('before')} → {result.get('after')}.")
    print("Restart `stray --serve` to pick up the new version.")
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        sys.exit(cli_update())
    sys.exit(cli_check())

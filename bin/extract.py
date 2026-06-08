#!/usr/bin/env python3
"""
Incrementally extract session summaries from Claude Code jsonl logs.

Reads ~/.claude/projects/**/*.jsonl, tracks per-file (mtime, byte_offset) in
cache/state.json, and writes per-session summaries to cache/sessions/<id>.json.

Prefers the native `away_summary` recap when present; otherwise falls back to
the first user prompt as a lightweight stand-in (Level-1 AI summarization can
fill this later).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
STATE_FILE = CACHE_DIR / "state.json"


@dataclass
class SessionSummary:
    session_id: str
    cwd: str | None = None
    source_file: str = ""
    started_at: str | None = None
    last_activity_at: str | None = None
    message_count: int = 0
    user_message_count: int = 0
    first_user_prompt: str | None = None
    recap: str | None = None  # away_summary content (latest wins)
    tools_used: list[str] = field(default_factory=list)
    # --- progress signals (richer input for the classifier) ---
    recent_user_prompts: list[str] = field(default_factory=list)  # last 3 real prompts
    last_assistant_summary: str | None = None  # first paragraph of most recent text reply
    edited_files: list[str] = field(default_factory=list)  # unique Write/Edit targets
    task_events: list[str] = field(default_factory=list)  # "created: …" / "completed: …"
    is_automation: bool = False  # set true for self-referential classify/agent runs


def load_state() -> dict[str, dict[str, Any]]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict[str, dict[str, Any]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def load_session(session_id: str) -> SessionSummary | None:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    # Drop unknown keys so SessionSummary(**data) doesn't choke after a
    # schema change. New fields pick up their dataclass defaults.
    valid = {f.name for f in SessionSummary.__dataclass_fields__.values()}
    return SessionSummary(**{k: v for k, v in data.items() if k in valid})


def save_session(summary: SessionSummary) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{summary.session_id}.json"
    path.write_text(json.dumps(asdict(summary), indent=2, ensure_ascii=False))


def extract_text_from_message(msg: Any) -> str:
    """Claude Code message content can be a string or a list of blocks."""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)
    return ""


RECENT_PROMPT_LIMIT = 5
EDITED_FILES_LIMIT = 20
TASK_EVENTS_LIMIT = 20
PROMPT_TRIM = 400
# last_assistant_summary previously captured only the first paragraph,
# which often missed the actual content (when the assistant opened with
# "Good question, let me think..."). Now we keep up to this many chars
# from the full text. 1500 fits comfortably in the prompt while capturing
# meaningful technical reasoning.
SUMMARY_TRIM = 1500
# Self-referential detection: refresh.sh / summarize.py / classify.py each
# feed a prompt template to `claude -p`, which CC itself logs as a new
# session (new jsonl). Those self-invocations must be skipped so the tool
# doesn't summarize-its-own-summarize-prompt in an infinite loop. Match
# the leading sentence of every prompt template under prompts/.
#
# Marker miss = silent runaway cost: on 2026-05-14 the P14 cutover renamed
# both prompts but left the old marker, so 1642 self-recursive sessions
# accumulated overnight at $0.03 each (~$51 lost). Update this list any
# time a prompt template is added or its opening line is reworded.
AUTOMATION_PROMPT_MARKERS = (
    "You are analyzing a developer's Claude Code session history",   # legacy P13 classify
    "You are summarizing a single Claude Code session",              # Layer 1 summarize
    "You are doing cross-session classification",                    # Layer 2 classify
)


def _is_automation_prompt(text: str) -> bool:
    return any(text.lstrip().startswith(m) for m in AUTOMATION_PROMPT_MARKERS)


def _summarize_assistant(text: str, limit: int = SUMMARY_TRIM) -> str:
    """
    Return up to `limit` characters of the assistant's text. Tries to
    end on a sentence boundary so the cut isn't mid-word. Keeps full
    text when short. Strips empty leading lines.

    Previously this took just the first paragraph; that lost content
    when the reply opened with a stock preamble like "Good question, let
    me think about this." The classifier needs the actual reasoning.
    """
    text = text.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Prefer last paragraph break, then sentence terminator, then newline
    for sep in ("\n\n", "。", ". ", "\n"):
        idx = cut.rfind(sep)
        if idx > limit * 0.5:
            return cut[: idx + len(sep)].strip()
    return cut.strip()


def apply_record(summary: SessionSummary, rec: dict[str, Any]) -> None:
    t = rec.get("type")
    ts = rec.get("timestamp")
    if ts:
        if summary.started_at is None or ts < summary.started_at:
            summary.started_at = ts
        if summary.last_activity_at is None or ts > summary.last_activity_at:
            summary.last_activity_at = ts
    if summary.cwd is None:
        summary.cwd = rec.get("cwd")

    if t == "user":
        summary.message_count += 1
        msg = rec.get("message") or {}
        # Skip tool_result pseudo-user messages: real prompts have string or text blocks
        text = extract_text_from_message(msg).strip()
        if text and not rec.get("toolUseResult"):
            summary.user_message_count += 1
            if summary.first_user_prompt is None:
                summary.first_user_prompt = text[:PROMPT_TRIM]
                if _is_automation_prompt(text):
                    summary.is_automation = True
            summary.recent_user_prompts.append(text[:PROMPT_TRIM])
            if len(summary.recent_user_prompts) > RECENT_PROMPT_LIMIT:
                summary.recent_user_prompts = summary.recent_user_prompts[-RECENT_PROMPT_LIMIT:]
    elif t == "assistant":
        summary.message_count += 1
        msg = rec.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = block.get("name")
                    if name and name not in summary.tools_used:
                        summary.tools_used.append(name)
                    inp = block.get("input") or {}
                    # Track files touched by Write/Edit for concrete "what got done" signal.
                    if name in ("Write", "Edit", "NotebookEdit"):
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if fp and fp not in summary.edited_files:
                            summary.edited_files.append(fp)
                            if len(summary.edited_files) > EDITED_FILES_LIMIT:
                                summary.edited_files = summary.edited_files[-EDITED_FILES_LIMIT:]
                    # Task tool usage is a direct progress log when the user relies on it.
                    elif name == "TaskCreate":
                        subj = (inp.get("subject") or "").strip()
                        if subj:
                            summary.task_events.append(f"created: {subj[:120]}")
                    elif name == "TaskUpdate":
                        status = (inp.get("status") or "").strip()
                        tid = inp.get("taskId")
                        if status and tid:
                            summary.task_events.append(f"{status}: #{tid}")
                    if len(summary.task_events) > TASK_EVENTS_LIMIT:
                        summary.task_events = summary.task_events[-TASK_EVENTS_LIMIT:]
                elif btype == "text":
                    txt = block.get("text", "")
                    if txt:
                        text_parts.append(txt)
            if text_parts:
                combined = "\n\n".join(text_parts).strip()
                if combined:
                    summary.last_assistant_summary = _summarize_assistant(combined)
    elif t == "system":
        if rec.get("subtype") == "away_summary":
            content = rec.get("content")
            if isinstance(content, str) and content.strip():
                summary.recap = content.strip()


def process_file(path: Path, state: dict[str, dict[str, Any]]) -> int:
    """Read a single jsonl, return number of records applied."""
    key = str(path)
    stat = path.stat()
    prev = state.get(key, {})
    prev_mtime = prev.get("mtime", 0)
    prev_offset = prev.get("offset", 0)

    if stat.st_mtime == prev_mtime and stat.st_size == prev.get("size", 0):
        return 0

    # If file shrank (rotation/rewrite), restart from 0.
    start = prev_offset if stat.st_size >= prev_offset else 0

    session_id = path.stem
    summary = load_session(session_id) or SessionSummary(
        session_id=session_id, source_file=key
    )

    applied = 0
    with path.open("rb") as f:
        f.seek(start)
        for raw in f:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            apply_record(summary, rec)
            applied += 1

    if applied:
        save_session(summary)

    state[key] = {
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "offset": stat.st_size,
    }
    return applied


def main() -> int:
    if not PROJECTS_DIR.exists():
        print(f"projects dir not found: {PROJECTS_DIR}", file=sys.stderr)
        return 1

    state = load_state()
    # Real Claude Code sessions live under cwd-encoded project dirs (the abs path
    # with '/'→'-', so they start with '-'). Claude Code's teammate / subagent
    # transcripts live in a special `subagents/` namespace (and aren't standalone
    # human sessions) — exclude it so agent-teams mode never leaks junk cards into
    # the cockpit. (We card only independent, human-drivable sessions.)
    _SKIP_NS = {"subagents"}
    files = sorted(f for f in PROJECTS_DIR.glob("*/*.jsonl")
                   if f.parent.name not in _SKIP_NS)
    total_applied = 0
    touched_files = 0

    for f in files:
        applied = process_file(f, state)
        if applied:
            touched_files += 1
            total_applied += applied

    save_state(state)
    print(
        f"scanned {len(files)} files, updated {touched_files}, "
        f"applied {total_applied} new records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

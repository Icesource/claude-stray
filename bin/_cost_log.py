#!/usr/bin/env python3
"""
Shared helper: log a single AI call's cost & token usage to
cache/cost_log.jsonl (append-only JSONL).

Used by every script that calls `claude -p` — currently refresh.sh
(Layer 2 / legacy classify), in the future summarize.py and classify.py
will use the same.

Per DD-002 §12.5 the file is the contract: any tool that wants to
report cost should append a record matching this schema.

Schema (one JSON object per line):

  {
    "at":                    ISO-8601 UTC timestamp
    "layer":                 free-form label, e.g. "classify",
                             "summarize", "suggest"
    "session_id":            optional sid this call targeted (Layer 1)
                             null for cross-session calls (Layer 2)
    "model":                 model identifier ("claude-haiku-4-5-...")
    "input_tokens":          raw input tokens
    "cache_creation_tokens": tokens written into prompt cache
    "cache_read_tokens":     tokens read from prompt cache
    "output_tokens":         output tokens
    "cost_usd":              dollar cost reported by claude -p envelope
    "duration_s":            wall-clock seconds for the call
    "ok":                    bool — true if the AI call returned usable output
  }

Append is POSIX-atomic up to PIPE_BUF (4096 bytes). Each record is
< 400 bytes, so concurrent writers are safe without a lock.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_LOG = REPO_ROOT / "cache" / "cost_log.jsonl"


def log_cost(
    *,
    layer: str,
    envelope: dict | None,
    duration_s: float,
    session_id: str | None = None,
    model: str | None = None,
    ok: bool = True,
) -> None:
    """Append one cost record to cache/cost_log.jsonl.

    envelope: the JSON returned by `claude -p --output-format json`.
              Pass None if the call failed before producing one — we'll
              record a row with zero usage and ok=false.
    """
    usage = (envelope or {}).get("usage") or {}
    record = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "layer": layer,
        "session_id": session_id,
        "model": model or _detect_model(envelope),
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cost_usd": float((envelope or {}).get("total_cost_usd", 0) or 0),
        "duration_s": round(float(duration_s), 2),
        "ok": bool(ok),
    }
    try:
        COST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(COST_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        # Never let logging failure poison the caller.
        print(f"[cost-log] failed to append: {e}", file=sys.stderr)


def _detect_model(envelope: dict | None) -> str | None:
    if not envelope:
        return None
    # `claude -p` envelope carries `modelUsage` dict keyed by model id.
    mu = envelope.get("modelUsage") or {}
    if mu:
        return next(iter(mu.keys()), None)
    return None


# Allow this module to be invoked as a CLI for testing:
#   echo '{"usage":{}}' | python3 _cost_log.py classify 12.3
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: _cost_log.py <layer> <duration_s> [session_id]", file=sys.stderr)
        sys.exit(2)
    envelope_json = sys.stdin.read()
    try:
        env = json.loads(envelope_json) if envelope_json.strip() else None
    except json.JSONDecodeError:
        env = None
    log_cost(
        layer=sys.argv[1],
        envelope=env,
        duration_s=float(sys.argv[2]),
        session_id=sys.argv[3] if len(sys.argv) > 3 else None,
    )

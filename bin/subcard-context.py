#!/usr/bin/env python3
"""父←子信息同步,惰性版(取代曾经的 send-keys 主动注入)。

UserPromptSubmit hook 的 stdout 会作为上下文附进该轮对话 —— 这是「天然同步点」:
父卡的 claude 本来就要醒来跑一轮,这时把子卡动态作为一行上下文带给它,
零额外对话轮、零假 user 消息、零状态污染(对比 push 注入:会触发父卡跑一轮、
污染 jsonl/总结、把父卡状态顶成 running,还有在权限对话框上误触 Enter 的风险)。

只在有「未告知的变化」时输出(每父卡记 last-told 状态做去重):
  - 新出现的子卡(用户手动分派了任务,父 agent 需要知道,避免重复做);
  - 子卡转 needs_you(卡住等用户)/ done_unread(干完了)。
无变化 → 不输出任何东西(该轮上下文零开销)。

stdin: hook JSON payload(取 session_id;只处理 UserPromptSubmit)。
永不失败、永不阻塞(任何异常都静默吞掉,exit 0)。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from _repo_root import repo_root
    REPO_ROOT = repo_root()
except Exception:
    REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_stdin() -> dict:
    try:
        import select
        if sys.stdin.isatty():
            return {}
        r, _, _ = select.select([sys.stdin], [], [], 0.5)
        if not r:
            return {}
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _live_status(cache_dir: Path, sid: str) -> str:
    try:
        return (json.loads((cache_dir / "live" / f"{sid}.json").read_text())
                .get("status") or "")
    except Exception:
        return ""


def digest(parent_sid: str, created_doc: dict, live_lookup, told: dict) -> tuple[str, dict]:
    """Pure: compute the one-line context for `parent_sid` + the updated told-state.
    Returns ("", told) when nothing new. `live_lookup(sid) -> status str`."""
    NOTIFY_STATUSES = {"needs_you": "等你确认", "done_unread": "已完成待查看"}
    children = {}
    for ent in (created_doc or {}).values():
        if isinstance(ent, dict) and ent.get("sid") and ent.get("parent") == parent_sid:
            children[ent["sid"]] = ent
    # prune told-state for children that no longer exist (closed/merged)
    told = {sid: st for sid, st in (told or {}).items() if sid in children}
    bits = []
    for sid, ent in children.items():
        rec = told.get(sid) or {}
        name = ent.get("name") or ent.get("worktree_name") or sid[:8]
        if not rec.get("created"):
            task = (ent.get("initial_task") or "").strip().splitlines()[0][:50] if ent.get("initial_task") else ""
            bits.append("新建「" + name + "」(" + sid[:8] + (")处理:" + task if task else ")"))
            rec["created"] = True
        status = live_lookup(sid) or ""
        if status in NOTIFY_STATUSES and rec.get("status") != status:
            bits.append("「" + name + "」→ " + NOTIFY_STATUSES[status])
        rec["status"] = status
        told[sid] = rec
    if not bits:
        return "", told
    line = ("[stray] 子卡动态(知悉即可,按需 `stray subtasks` 拉详情):"
            + ";".join(bits[:5]))
    return line, told


def main() -> int:
    payload = _read_stdin()
    if (payload.get("hook_event_name") or "") not in ("", "UserPromptSubmit"):
        return 0
    sid = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not sid:
        return 0
    cache = REPO_ROOT / "cache"
    try:
        created = json.loads((cache / "created-cards.json").read_text())
    except Exception:
        return 0
    state_dir = cache / "subcard-notify"
    state_file = state_dir / f"{sid}.json"
    try:
        told = json.loads(state_file.read_text())
    except Exception:
        told = {}
    line, told2 = digest(sid, created, lambda c: _live_status(cache, c), told)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = str(state_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(told2, f, ensure_ascii=False)
        os.replace(tmp, state_file)
    except Exception:
        pass
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)

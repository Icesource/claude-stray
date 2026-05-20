#!/usr/bin/env python3
"""
Render cache/dashboard.json as a shell-style tree with ANSI colors.

Supports both schemas:
  v1 (legacy): {"projects": [{...tasks: [...]}]}     — 2 levels
  v2 (new):    {"workspaces": [{initiatives: [...]}]} — 3 levels

Zero external dependencies — just stdlib. Honors NO_COLOR and non-TTY stdout
(strips colors when piped).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_FILE = REPO_ROOT / "cache" / "dashboard.json"
CONFIG_FILE = REPO_ROOT / "cache" / "config.json"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


BOLD = "1"
DIM = "2"
BLUE = "34"
GREEN = "32"
YELLOW = "33"
RED = "31"
CYAN = "36"
MAGENTA = "35"

STATUS_STYLE = {
    "active": ("●", GREEN),
    "paused": ("◐", YELLOW),
    "done": ("✓", DIM),
    "archived": ("▪", DIM),
}


LOCALE = {
    "zh-CN": {
        "header": "Claude Code 工作图",
        "generated": "生成于",
        "no_projects": "  （还没有项目数据 —— 运行 mindmap --refresh）",
        "progress": "进度",
        "tasks": "任务",
        "archived_section": "已归档",
        "session": "会话",
        "initiative": "子项目",
        "linked": "关联",
        "status_active": "进行中",
        "status_paused": "已暂停",
        "status_done": "已完成",
        "status_archived": "已归档",
        "just_now": "刚刚",
        "ago_s": "{}秒前",
        "ago_m": "{}分钟前",
        "ago_h": "{}小时前",
        "ago_d": "{}天前",
        "no_cache": "未找到 mindmap 缓存，请运行：",
    },
    "en": {
        "header": "Claude Code Worktree",
        "generated": "generated",
        "no_projects": "  (no projects — run mindmap --refresh)",
        "progress": "progress",
        "tasks": "tasks",
        "archived_section": "archived",
        "session": "session",
        "initiative": "initiative",
        "linked": "linked",
        "status_active": "active",
        "status_paused": "paused",
        "status_done": "done",
        "status_archived": "archived",
        "just_now": "just now",
        "ago_s": "{}s ago",
        "ago_m": "{}m ago",
        "ago_h": "{}h ago",
        "ago_d": "{}d ago",
        "no_cache": "No mindmap cache found. Run:",
    },
}


def get_lang() -> str:
    env = os.environ.get("CLAUDE_WORKTREE_LANG")
    if env in LOCALE:
        return env
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            lang = cfg.get("lang")
            if lang in LOCALE:
                return lang
        except (json.JSONDecodeError, OSError):
            pass
    return "zh-CN"


L = LOCALE[get_lang()]


def humanize_age(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    now = datetime.now(timezone.utc)
    delta = now - t
    s = int(delta.total_seconds())
    if s < 0:
        return L["just_now"]
    if s < 60:
        return L["ago_s"].format(s)
    if s < 3600:
        return L["ago_m"].format(s // 60)
    if s < 86400:
        return L["ago_h"].format(s // 3600)
    return L["ago_d"].format(s // 86400)


def short_cwd(cwd: str | None) -> str:
    if not cwd:
        return ""
    home = str(Path.home())
    if cwd.startswith(home):
        return "~" + cwd[len(home):]
    return cwd


def wrap_indent(text: str, indent: str, width: int) -> list[str]:
    """
    Wrap text to fit width. CJK-aware: treats non-ASCII chars as width 2.
    Splits on spaces if present; for CJK (often spaceless) splits on chars.
    """
    if not text:
        return []

    def cell_width(ch: str) -> int:
        return 2 if ord(ch) > 0x2E80 else 1

    def visible_width(s: str) -> int:
        return sum(cell_width(ch) for ch in s)

    # Detect spaceless CJK-dominant text
    has_space = " " in text
    tokens = text.split() if has_space else list(text)
    sep = " " if has_space else ""

    lines: list[str] = []
    cur = indent
    cur_w = visible_width(indent)
    for tok in tokens:
        tok_w = visible_width(tok)
        added = (1 if sep == " " and cur != indent else 0) + tok_w
        if cur != indent and cur_w + added > width:
            lines.append(cur)
            cur = indent + tok
            cur_w = visible_width(indent) + tok_w
        else:
            if cur != indent and sep == " ":
                cur += " "
                cur_w += 1
            cur += tok
            cur_w += tok_w
    if cur.strip():
        lines.append(cur)
    return lines


def render_tasks(tasks: list[dict], pipe: str, term_width: int) -> list[str]:
    out: list[str] = []
    if not tasks:
        return out
    out.append(f"{pipe}{c(DIM, L['tasks'] + ':')}")
    for ti, task in enumerate(tasks):
        tlast = ti == len(tasks) - 1
        tbranch = "  └─ " if tlast else "  ├─ "
        done = task.get("done")
        mark = c(GREEN, "✓") if done else c(YELLOW, "○")
        title = task.get("title", "")
        if done:
            title = c(DIM, title)
        out.append(f"{pipe}{tbranch}{mark} {title}")
    return out


def render_initiative(init: dict, parent_pipe: str, is_last: bool, term_width: int) -> list[str]:
    """Render one initiative under a workspace. parent_pipe is the workspace's pipe."""
    out: list[str] = []
    branch = "└── " if is_last else "├── "
    sub_pipe = parent_pipe + ("    " if is_last else "│   ")

    status = init.get("status", "?")
    icon, color = STATUS_STYLE.get(status, ("?", MAGENTA))
    status_label = L.get(f"status_{status}", status)
    name = c(BOLD, init.get("name", "unnamed"))
    status_tag = c(color, f"[{icon} {status_label}]")
    age_tag = c(DIM, humanize_age(init.get("last_activity_at")))
    sess_count = len(init.get("sessions", []))
    sess_tag = c(DIM, f"{sess_count} {L['session']}")

    out.append(f"{parent_pipe}{branch}{name}  {status_tag}  {age_tag}  {sess_tag}")

    linked = init.get("linked_cwds") or []
    if linked:
        linked_short = ", ".join(short_cwd(x) for x in linked)
        out.append(f"{sub_pipe}{c(DIM, L['linked'] + ': ' + linked_short)}")

    summary = (init.get("summary") or "").strip()
    if summary:
        out.extend(wrap_indent(summary, sub_pipe, term_width))

    progress = (init.get("progress") or "").strip()
    if progress:
        label_plain = L["progress"] + ": "
        cont_indent = f"{sub_pipe}{' ' * len(label_plain)}"
        wrapped = wrap_indent(progress, cont_indent, term_width)
        if wrapped:
            body = wrapped[0][len(cont_indent):]
            wrapped[0] = f"{sub_pipe}{c(CYAN, label_plain)}{body}"
        out.extend(wrapped)

    out.extend(render_tasks(init.get("tasks") or [], sub_pipe, term_width))
    return out


def render_workspace(ws: dict, is_last_ws: bool, term_width: int) -> list[str]:
    out: list[str] = []
    branch = "└── " if is_last_ws else "├── "
    pipe = "    " if is_last_ws else "│   "

    name = c(BOLD, c(BLUE, ws.get("name", "unnamed")))
    age_tag = c(DIM, humanize_age(ws.get("last_activity_at")))
    initiatives = ws.get("initiatives") or []
    init_n = len(initiatives)
    init_label = L["initiative"] + ("s" if get_lang() == "en" and init_n != 1 else "")
    n_tag = c(DIM, f"{init_n} {init_label}")

    cwd = short_cwd(ws.get("cwd"))
    cwd_tag = c(DIM, cwd) if cwd else ""

    out.append(f"{branch}{name}  {age_tag}  {n_tag}  {cwd_tag}".rstrip())

    for ii, init in enumerate(initiatives):
        ilast = ii == init_n - 1
        out.extend(render_initiative(init, pipe, ilast, term_width))
        if not ilast:
            out.append(pipe.rstrip())

    return out


# ---------- v1 (legacy) renderer ---------------------------------------------


def render_legacy_project(proj: dict, is_last: bool, has_archived_after: bool, term_width: int) -> list[str]:
    out: list[str] = []
    last = is_last and not has_archived_after
    branch = "└── " if last else "├── "
    pipe = "    " if last else "│   "

    status = proj.get("status", "?")
    icon, color = STATUS_STYLE.get(status, ("?", MAGENTA))
    status_label = L.get(f"status_{status}", status)
    name = c(BOLD, c(BLUE, proj.get("name", "unnamed")))
    status_tag = c(color, f"[{icon} {status_label}]")
    age_tag = c(DIM, humanize_age(proj.get("last_activity_at")))
    sess_count = len(proj.get("sessions", []))
    sess_tag = c(DIM, f"{sess_count} {L['session']}")

    out.append(f"{branch}{name}  {status_tag}  {age_tag}  {sess_tag}")

    cwd = short_cwd(proj.get("cwd") if isinstance(proj.get("cwd"), str) else None)
    if cwd:
        out.append(f"{pipe}{c(DIM, cwd)}")

    summary = (proj.get("summary") or "").strip()
    if summary:
        out.extend(wrap_indent(summary, pipe, term_width))

    progress = (proj.get("progress") or "").strip()
    if progress:
        label_plain = L["progress"] + ": "
        cont_indent = f"{pipe}{' ' * len(label_plain)}"
        wrapped = wrap_indent(progress, cont_indent, term_width)
        if wrapped:
            body = wrapped[0][len(cont_indent):]
            wrapped[0] = f"{pipe}{c(CYAN, label_plain)}{body}"
        out.extend(wrapped)

    out.extend(render_tasks(proj.get("tasks") or [], pipe, term_width))
    return out


def render_legacy(data: dict, term_width: int) -> list[str]:
    out: list[str] = []
    projects = data.get("projects", [])
    if not projects:
        out.append(c(DIM, L["no_projects"]))
        return out

    live = [p for p in projects if p.get("status") != "archived"]
    archived = [p for p in projects if p.get("status") == "archived"]

    for pi, proj in enumerate(live):
        is_last = pi == len(live) - 1
        out.extend(render_legacy_project(proj, is_last, bool(archived), term_width))
        if not (is_last and not archived):
            out.append("│")

    if archived:
        archived_label = L["archived_section"]
        out.append(f"└── {c(DIM, f'{archived_label} ({len(archived)})')}")
        for ai, proj in enumerate(archived):
            alast = ai == len(archived) - 1
            abranch = "    └─ " if alast else "    ├─ "
            name = proj.get("name", "unnamed")
            age = humanize_age(proj.get("last_activity_at"))
            sess_n = len(proj.get("sessions", []))
            line = f"{abranch}{name}  ({age}, {sess_n})"
            out.append(c(DIM, line))

    return out


# ---------- main dispatcher --------------------------------------------------


def render(data: dict) -> str:
    out: list[str] = []
    generated = data.get("generated_at", "?")

    header = c(BOLD, L["header"])
    age = c(DIM, f"  ({L['generated']} {humanize_age(generated)})")
    out.append(f"{header}{age}")
    out.append(c(DIM, "─" * 60))

    try:
        term_width = max(60, min(100, os.get_terminal_size().columns)) if sys.stdout.isatty() else 100
    except OSError:
        term_width = 100

    if "workspaces" in data:
        # v2 schema
        workspaces = data.get("workspaces", [])
        if not workspaces:
            out.append(c(DIM, L["no_projects"]))
            return "\n".join(out)

        archived_ws = []
        live_ws = []
        for ws in workspaces:
            inits = ws.get("initiatives") or []
            if inits and all(i.get("status") == "archived" for i in inits):
                archived_ws.append(ws)
            else:
                live_ws.append(ws)

        for wi, ws in enumerate(live_ws):
            is_last = wi == len(live_ws) - 1 and not archived_ws
            out.extend(render_workspace(ws, is_last, term_width))
            if not is_last:
                out.append("│")

        if archived_ws:
            count = sum(len(ws.get("initiatives") or []) for ws in archived_ws)
            archived_label = L["archived_section"]
            out.append(f"└── {c(DIM, f'{archived_label} ({count})')}")
            flat = [(ws, init) for ws in archived_ws for init in (ws.get("initiatives") or [])]
            for ai, (ws, init) in enumerate(flat):
                alast = ai == len(flat) - 1
                abranch = "    └─ " if alast else "    ├─ "
                ws_name = ws.get("name", "")
                name = init.get("name", "unnamed")
                age = humanize_age(init.get("last_activity_at"))
                sess_n = len(init.get("sessions", []))
                line = f"{abranch}{ws_name} / {name}  ({age}, {sess_n})"
                out.append(c(DIM, line))
    else:
        # v1 legacy schema
        out.extend(render_legacy(data, term_width))

    return "\n".join(out)


def main() -> int:
    if not DASHBOARD_FILE.exists():
        print(
            c(YELLOW, L["no_cache"]) + "\n  mindmap --refresh",
            file=sys.stderr,
        )
        return 1
    data = json.loads(DASHBOARD_FILE.read_text())
    print(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

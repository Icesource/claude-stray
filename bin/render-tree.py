#!/usr/bin/env python3
"""
Render cache/dashboard.json as a single-file markmap (mind-map view).

This is the EXPORT/visualization view. The primary UI is the card-based
dashboard rendered by render-html.py. The tree view is useful for:
- Bird's eye visualization across many initiatives
- Sharing a snapshot (single HTML file)
- Presentations / overview screenshots

Uses markmap-autoloader (CDN). Single-file output: cache/mindmap-tree.html
"""

from __future__ import annotations

import html as html_lib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_FILE = REPO_ROOT / "cache" / "dashboard.json"
CONFIG_FILE = REPO_ROOT / "cache" / "config.json"
OUTPUT_FILE = REPO_ROOT / "cache" / "mindmap-tree.html"


LOCALE = {
    "zh-CN": {
        "page_title": "Claude Code 工作图 · 脑图视图",
        "header": "Claude Code 工作图 · 脑图",
        "generated": "生成于",
        "back": "← 回到卡片视图",
        "progress": "进度",
        "summary": "摘要",
        "tasks": "任务",
        "sessions": "会话",
        "linked": "关联",
        "archived": "已归档",
        "initiative": "子项目",
        "no_data": "（无项目数据，请运行 mindmap --refresh）",
        "status_active": "进行中",
        "status_paused": "已暂停",
        "status_done": "已完成",
        "status_archived": "已归档",
        "hint": "提示：点击节点折叠/展开；滚轮缩放；拖拽平移",
        "just_now": "刚刚",
        "ago_s": "{}秒前", "ago_m": "{}分钟前", "ago_h": "{}小时前", "ago_d": "{}天前",
    },
    "en": {
        "page_title": "Claude Code Worktree · Tree View",
        "header": "Claude Code Worktree · Tree",
        "generated": "generated",
        "back": "← Back to card view",
        "progress": "progress",
        "summary": "summary",
        "tasks": "tasks",
        "sessions": "sessions",
        "linked": "linked",
        "archived": "archived",
        "initiative": "initiative",
        "no_data": "(no data — run mindmap --refresh)",
        "status_active": "active",
        "status_paused": "paused",
        "status_done": "done",
        "status_archived": "archived",
        "hint": "Tip: click to fold/unfold; scroll to zoom; drag to pan",
        "just_now": "just now",
        "ago_s": "{}s ago", "ago_m": "{}m ago", "ago_h": "{}h ago", "ago_d": "{}d ago",
    },
}

STATUS_EMOJI = {"active": "🟢", "paused": "🟡", "done": "✅", "archived": "⚪"}


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
        except Exception:
            pass
    return "zh-CN"


def humanize_age(iso: str | None, L: dict) -> str:
    if not iso:
        return "?"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    s = int((datetime.now(timezone.utc) - t).total_seconds())
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
    return "~" + cwd[len(home):] if cwd.startswith(home) else cwd


def md_escape(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.replace("\n", " ").replace("\r", " ").split())


def build_initiative_md(init: dict, L: dict, indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    status = init.get("status", "?")
    emoji = STATUS_EMOJI.get(status, "❓")
    status_label = L.get(f"status_{status}", status)
    name = md_escape(init.get("name", "unnamed"))
    age = humanize_age(init.get("last_activity_at"), L)
    sess_count = len(init.get("sessions", []))

    header = f"{emoji} **{name}** `[{status_label}]` *{age}* · {sess_count} {L['sessions']}"
    lines.append(f"{pad}- {header}")
    child_pad = " " * (indent + 2)

    linked = init.get("linked_cwds") or []
    if linked:
        lines.append(f"{child_pad}- {L['linked']}: `{md_escape(', '.join(short_cwd(x) for x in linked))}`")

    if init.get("summary"):
        lines.append(f"{child_pad}- {L['summary']}: {md_escape(init['summary'])}")
    if init.get("progress"):
        lines.append(f"{child_pad}- {L['progress']}: {md_escape(init['progress'])}")

    tasks = init.get("tasks") or []
    if tasks:
        lines.append(f"{child_pad}- {L['tasks']} ({len(tasks)})")
        task_pad = " " * (indent + 4)
        for t in tasks:
            mark = "✓" if t.get("done") else "○"
            title = md_escape(t.get("title", ""))
            if t.get("done"):
                lines.append(f"{task_pad}- {mark} ~~{title}~~")
            else:
                lines.append(f"{task_pad}- {mark} {title}")

    sessions = init.get("sessions") or []
    if sessions:
        sample = ", ".join(f"`{s[:8]}`" for s in sessions[:6])
        more = f" (+{len(sessions) - 6})" if len(sessions) > 6 else ""
        lines.append(f"{child_pad}- {L['sessions']}: {sample}{more}")
    return lines


def build_markdown(data: dict, L: dict) -> str:
    lines = [f"# {L['header']}", ""]
    workspaces = data.get("workspaces") or []
    if not workspaces:
        lines.append(f"- {L['no_data']}")
        return "\n".join(lines)
    archived_ws, live_ws = [], []
    for ws in workspaces:
        inits = ws.get("initiatives") or []
        if inits and all(i.get("status") == "archived" for i in inits):
            archived_ws.append(ws)
        else:
            live_ws.append(ws)
    for ws in live_ws:
        name = md_escape(ws.get("name", "unnamed"))
        cwd = short_cwd(ws.get("cwd"))
        inits = ws.get("initiatives") or []
        age = humanize_age(ws.get("last_activity_at"), L)
        cwd_part = f" · `{cwd}`" if cwd else ""
        lines.append(f"- **{name}** *{age}* · {len(inits)} {L['initiative']}{cwd_part}")
        for init in inits:
            lines.extend(build_initiative_md(init, L, indent=2))
    if archived_ws:
        count = sum(len(ws.get("initiatives") or []) for ws in archived_ws)
        lines.append(f"- 🗄️ {L['archived']} ({count})")
        for ws in archived_ws:
            for init in (ws.get("initiatives") or []):
                lines.extend(build_initiative_md(init, L, indent=2))
    return "\n".join(lines)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
  #root { display: flex; flex-direction: column; height: 100%; }
  header { padding: 8px 16px; border-bottom: 1px solid #e4e4e7; display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; background: #fafafa; }
  header h1 { margin: 0; font-size: 14px; font-weight: 600; }
  header .meta { font-size: 12px; color: #71717a; }
  header .hint { font-size: 11px; color: #a1a1aa; margin-left: auto; }
  header a.back { font-size: 12px; color: #2563eb; text-decoration: none; padding: 2px 8px; border: 1px solid #e4e4e7; border-radius: 4px; }
  header a.back:hover { background: white; }
  .markmap { flex: 1; min-height: 0; }
  .markmap > svg { width: 100%; height: 100%; }
</style>
<script>window.markmap = { autoLoader: { manual: false } };</script>
<script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
</head>
<body>
<div id="root">
  <header>
    <a class="back" href="dashboard.html">__BACK__</a>
    <h1>__HEADER__</h1>
    <span class="meta">__GENERATED__</span>
    <span class="hint">__HINT__</span>
  </header>
  <div class="markmap" data-options='{"colorFreezeLevel": 2, "initialExpandLevel": 3}'>
<script type="text/template">
__MARKDOWN__
</script>
  </div>
</div>
</body>
</html>
"""


def render_html(data: dict, L: dict, lang: str) -> str:
    md = build_markdown(data, L)
    age = humanize_age(data.get("generated_at", ""), L)
    out = HTML_TEMPLATE
    out = out.replace("__LANG__", lang)
    out = out.replace("__TITLE__", html_lib.escape(L["page_title"]))
    out = out.replace("__HEADER__", html_lib.escape(L["header"]))
    out = out.replace("__GENERATED__", html_lib.escape(f"{L['generated']} {age}"))
    out = out.replace("__HINT__", html_lib.escape(L["hint"]))
    out = out.replace("__BACK__", html_lib.escape(L["back"]))
    out = out.replace("__MARKDOWN__", md)
    return out


def main() -> int:
    if not DASHBOARD_FILE.exists():
        print(f"No mindmap cache found at {DASHBOARD_FILE}", file=sys.stderr)
        return 1
    data = json.loads(DASHBOARD_FILE.read_text())
    lang = get_lang()
    html = render_html(data, LOCALE[lang], lang)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

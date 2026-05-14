#!/usr/bin/env python3
"""
Render cache/mindmap.json as a single-file dashboard HTML.

Layout: card-based, no third-party UI lib. Each initiative is a card
under its workspace section. Cards self-contain all actions (toggle task,
archive, delete, focus pane). Filter chips + keyword search at the top.

Persistence:
- Immediate: window.localStorage (instant in-browser feedback)
- Optional: File System Access API writes back to cache/ so the next AI
  refresh sees the user's edits.

Single-file output: cache/mindmap.html
"""

from __future__ import annotations

import html as html_lib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MINDMAP_FILE = REPO_ROOT / "cache" / "mindmap.json"
CONFIG_FILE = REPO_ROOT / "cache" / "config.json"
LOCATIONS_FILE = REPO_ROOT / "cache" / "session_locations.json"
ARCHIVE_DIR = REPO_ROOT / "cache" / "archive"
OUTPUT_FILE = REPO_ROOT / "cache" / "mindmap.html"


LOCALE = {
    "zh-CN": {
        "page_title": "Claude Code 工作图",
        "header": "Claude Code 工作图",
        "generated": "生成于",
        "filter_all": "全部",
        "filter_active": "进行中",
        "filter_paused": "已暂停",
        "filter_done": "已完成",
        "filter_archived": "已归档",
        "tree_view": "🌳 脑图视图",
        "nav_title": "工作区",
        "archive_zone": "🗄️ 已归档",
        "archive_empty": "暂无已归档项",
        "from_workspace": "来自",
        "search_placeholder": "搜索…",
        "no_match": "没有匹配的子项目",
        "status_active": "进行中",
        "status_paused": "已暂停",
        "status_done": "已完成",
        "status_archived": "已归档",
        "summary": "摘要",
        "progress": "进度",
        "tasks": "任务",
        "sessions": "会话",
        "linked": "关联",
        "initiative": "子项目",
        "tasks_meta": "{} 个任务 · {} 已完成",
        "sessions_meta": "{} 个会话",
        "show_done_tasks": "展开 {} 个已完成",
        "hide_done_tasks": "收起已完成",
        "show_more_sessions": "展开剩余 {} 个会话",
        "hide_more_sessions": "收起",
        "btn_archive": "归档",
        "btn_delete": "删除",
        "btn_unarchive": "取消归档",
        "btn_focus": "聚焦此 pane",
        "btn_newpane": "新 pane 中 resume",
        "btn_copy": "复制 resume 命令",
        "no_pane": "未记录 pane",
        "confirm_archive": "归档 \"{}\" ?\n归档后下次 AI refresh 不再处理它，但完整数据会保存在 cache/archive/。",
        "confirm_delete": "永久删除 \"{}\" ?\nID 会进入 tombstone，AI 即使看到新证据也不会重新创建它。",
        "confirm_delete_task": "删除任务 \"{}\" ?\n该 task 加入 tombstone，AI 不再生成。",
        "sync_idle": "未同步",
        "sync_local": "本地已暂存 {} 项变更",
        "sync_disk": "已写入 cache/",
        "sync_server": "通过 server 自动同步",
        "sync_connect": "🔌 授权写入 cache/",
        "sync_connected": "✓ 已连接",
        "sync_download": "📥 下载补丁",
        "sync_unsupported": "浏览器不支持 File System Access；改用下载补丁",
        "helper_offline": "本地 helper 离线（mindmap --serve 启用跳转）",
        "helper_online": "✓ helper :{}",
        "data_stale_banner": "↻ 服务端有新数据 — 点击应用",
        "manual_refresh": "🔄 触发 AI 重新分析",
        "refresh_started": "已触发后台刷新，稍后会有新数据提示",
        "toast_jumped": "已切换到 pane {}",
        "toast_already_focused": "已经在 pane {}",
        "toast_new_pane": "已在新 pane 启动",
        "toast_copied": "已复制",
        "toast_helper_down": "未连接 helper — 命令已复制",
        "toast_pane_gone": "pane {} 已关闭",
        "just_now": "刚刚",
        "ago_s": "{}秒前",
        "ago_m": "{}分钟前",
        "ago_h": "{}小时前",
        "ago_d": "{}天前",
        "empty_no_data": "(还没有数据，请运行 mindmap --refresh)",
        "ws_collapsed": "▶",
        "ws_expanded": "▼",
        "blocker_chip": "{} 卡点",
        "pending_chip": "{} 待处理",
        "blocker_top_label": "卡点",
        "modal_blockers": "卡点",
        "modal_artifacts": "产出 / 链接",
        "modal_no_blockers": "（无卡点）",
        "modal_no_artifacts": "（无 artifact）",
        "modal_open_external": "外链",
        "modal_close": "关闭",
        "modal_status_pending": "待处理",
        "modal_status_open": "进行中",
        "modal_status_approved": "已批准",
        "modal_status_merged": "已合并",
        "modal_status_closed": "已关闭",
        "modal_status_released": "已发布",
        "modal_status_unknown": "未知",
        "modal_status_active": "活跃",
        "modal_status_stale": "陈旧",
        "modal_status_pushed": "已推送",
        "modal_status_local": "本地",
        "modal_status_live": "上线中",
        "modal_status_rolled_back": "已回滚",
        "modal_status_wontfix": "wontfix",
    },
    "en": {
        "page_title": "Claude Code Worktree",
        "header": "Claude Code Worktree",
        "generated": "generated",
        "filter_all": "All",
        "filter_active": "Active",
        "filter_paused": "Paused",
        "filter_done": "Done",
        "filter_archived": "Archived",
        "tree_view": "🌳 Tree view",
        "nav_title": "Workspaces",
        "archive_zone": "🗄️ Archive",
        "archive_empty": "Nothing archived yet",
        "from_workspace": "from",
        "search_placeholder": "Search…",
        "no_match": "No matching initiatives",
        "status_active": "active",
        "status_paused": "paused",
        "status_done": "done",
        "status_archived": "archived",
        "summary": "Summary",
        "progress": "Progress",
        "tasks": "Tasks",
        "sessions": "Sessions",
        "linked": "Linked",
        "initiative": "initiative",
        "tasks_meta": "{} tasks · {} done",
        "sessions_meta": "{} sessions",
        "show_done_tasks": "Show {} done",
        "hide_done_tasks": "Hide done",
        "show_more_sessions": "Show {} more",
        "hide_more_sessions": "Show less",
        "btn_archive": "Archive",
        "btn_delete": "Delete",
        "btn_unarchive": "Unarchive",
        "btn_focus": "Focus this pane",
        "btn_newpane": "Resume in new pane",
        "btn_copy": "Copy resume command",
        "no_pane": "no pane recorded",
        "confirm_archive": "Archive \"{}\" ?\nFuture AI refreshes will skip it, but full data lives in cache/archive/.",
        "confirm_delete": "Delete \"{}\" permanently?\nIts ID enters the tombstone list; AI won't recreate it.",
        "confirm_delete_task": "Delete task \"{}\" ?\nGoes to tombstone; AI won't bring it back.",
        "sync_idle": "not synced",
        "sync_local": "{} pending changes",
        "sync_disk": "saved to cache/",
        "sync_server": "auto-syncing via server",
        "sync_connect": "🔌 Grant cache/ access",
        "sync_connected": "✓ connected",
        "sync_download": "📥 Download patch",
        "sync_unsupported": "Browser lacks File System Access — using download fallback",
        "helper_offline": "Helper offline (run `mindmap --serve` for jump)",
        "helper_online": "✓ helper :{}",
        "data_stale_banner": "↻ Server has new data — click to load",
        "manual_refresh": "🔄 Run AI refresh",
        "refresh_started": "Background refresh kicked off; you'll see an update banner when done",
        "toast_jumped": "Focused pane {}",
        "toast_already_focused": "Already on pane {}",
        "toast_new_pane": "Launched in new pane",
        "toast_copied": "Copied",
        "toast_helper_down": "Helper offline — command copied",
        "toast_pane_gone": "Pane {} is gone",
        "just_now": "just now",
        "ago_s": "{}s ago",
        "ago_m": "{}m ago",
        "ago_h": "{}h ago",
        "ago_d": "{}d ago",
        "empty_no_data": "(no data yet — run mindmap --refresh)",
        "ws_collapsed": "▶",
        "ws_expanded": "▼",
        "blocker_chip": "{} blockers",
        "pending_chip": "{} pending",
        "blocker_top_label": "Blocker",
        "modal_blockers": "Blockers",
        "modal_artifacts": "Artifacts",
        "modal_no_blockers": "(no blockers)",
        "modal_no_artifacts": "(no artifacts)",
        "modal_open_external": "open",
        "modal_close": "Close",
        "modal_status_pending": "pending",
        "modal_status_open": "open",
        "modal_status_approved": "approved",
        "modal_status_merged": "merged",
        "modal_status_closed": "closed",
        "modal_status_released": "released",
        "modal_status_unknown": "unknown",
        "modal_status_active": "active",
        "modal_status_stale": "stale",
        "modal_status_pushed": "pushed",
        "modal_status_local": "local",
        "modal_status_live": "live",
        "modal_status_rolled_back": "rolled back",
        "modal_status_wontfix": "wontfix",
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


def humanize_age(iso: str | None, L: dict) -> str:
    if not iso:
        return "?"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    now = datetime.now(timezone.utc)
    s = int((now - t).total_seconds())
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


def load_locations() -> dict:
    if not LOCATIONS_FILE.exists():
        return {}
    try:
        data = json.loads(LOCATIONS_FILE.read_text())
        return data.get("by_session_id") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_archived_items() -> list:
    """
    Load all archived initiatives from cache/archive/<workspace>/<id>.json.

    These were physically removed from mindmap.json by refresh.sh but the
    full initiative payload is preserved on disk. The HTML needs them so
    the archive zone keeps showing items even after the AI refresh that
    consumed them.

    Returns list of {ws_name, ws_cwd, init, archived_at} entries.
    """
    if not ARCHIVE_DIR.is_dir():
        return []
    out = []
    for ws_dir in sorted(ARCHIVE_DIR.iterdir()):
        if not ws_dir.is_dir():
            continue
        for f in sorted(ws_dir.glob("*.json")):
            try:
                rec = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            init = rec.get("initiative")
            if not isinstance(init, dict) or not init.get("id"):
                continue
            out.append({
                "ws_name": rec.get("from_workspace") or ws_dir.name,
                "ws_cwd": None,
                "init": init,
                "archived_at": rec.get("archived_at"),
            })
    return out


# ---------- HTML template -----------------------------------------------
# The CSS/JS lives in this template. Python only injects data + i18n.

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root {
  --bg: #fafafa;
  --card-bg: #ffffff;
  --border: #e4e4e7;
  --border-hover: #d4d4d8;
  --text: #18181b;
  --text-dim: #52525b;
  --text-mute: #a1a1aa;
  --accent: #2563eb;
  --green: #16a34a;
  --green-bg: #dcfce7;
  --amber: #ca8a04;
  --amber-bg: #fef3c7;
  --red: #dc2626;
  --red-bg: #fee2e2;
  --slate: #64748b;
  --slate-bg: #f1f5f9;
  --shadow: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-hover: 0 4px 12px rgba(0,0,0,0.08);
  --radius: 8px;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }

/* ---------- Header ---------- */
header.top {
  position: sticky; top: 0; z-index: 10;
  background: rgba(250,250,250,0.95);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
header.top h1 { font-size: 15px; font-weight: 600; margin: 0; }
header.top .meta { color: var(--text-dim); font-size: 12px; }
header.top .grow { flex: 1; }
header.top .status-pill {
  font-size: 11px; padding: 3px 10px;
  background: var(--slate-bg); color: var(--text-dim);
  border-radius: 999px; display: inline-flex; align-items: center; gap: 6px;
}
header.top .status-pill.online { background: var(--green-bg); color: var(--green); }
header.top .sync-btn, header.top button.sync-btn {
  font-size: 12px; padding: 4px 12px; border: 1px solid var(--border);
  background: white; border-radius: 6px; cursor: pointer; color: var(--text);
  text-decoration: none; display: inline-flex; align-items: center; gap: 4px;
}
header.top button.sync-btn:hover { background: var(--bg); border-color: var(--border-hover); }
header.top button.refresh-btn { background: var(--text); color: white; border-color: var(--text); }
header.top button.refresh-btn:hover { opacity: 0.9; }
header.top .data-stale {
  font-size: 12px; padding: 4px 12px;
  background: var(--accent); color: white; border: none; border-radius: 6px;
  cursor: pointer; display: none;
  animation: pulse 2s infinite;
}
header.top .data-stale.show { display: inline-flex; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* ---------- Toolbar ---------- */
nav.toolbar {
  padding: 10px 24px; border-bottom: 1px solid var(--border);
  background: white;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
nav.toolbar .chips { display: flex; gap: 4px; }
nav.toolbar .chip {
  font-size: 12px; padding: 4px 12px; border-radius: 999px;
  border: 1px solid var(--border); background: white; cursor: pointer;
  color: var(--text-dim); display: inline-flex; align-items: center; gap: 6px;
}
nav.toolbar .chip:hover { border-color: var(--border-hover); }
nav.toolbar .chip.active {
  background: var(--text); color: white; border-color: var(--text);
}
nav.toolbar .chip .count {
  font-size: 10px; opacity: 0.7;
  background: rgba(255,255,255,0.18); padding: 1px 6px; border-radius: 999px;
}
nav.toolbar .chip:not(.active) .count {
  background: var(--slate-bg);
}
nav.toolbar input.search {
  flex: 1; min-width: 180px; max-width: 360px;
  font: inherit; padding: 5px 12px; border: 1px solid var(--border);
  border-radius: 6px; background: white;
}
nav.toolbar input.search:focus { outline: none; border-color: var(--accent); }

/* ---------- Layout: nav + board ---------- */
.layout { display: flex; align-items: flex-start; }

/* ---------- Side nav ---------- */
aside.nav-side {
  width: 250px; flex-shrink: 0;
  position: sticky; top: 96px;
  max-height: calc(100vh - 96px);
  overflow-y: auto; overflow-x: hidden;
  padding: 16px 12px 32px;
  border-right: 1px solid var(--border);
  background: var(--bg);
}
aside.nav-side .nav-title {
  font-size: 10px; font-weight: 700; color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.08em;
  padding: 0 8px 10px;
}
aside.nav-side ul.ws-nav { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1px; }
aside.nav-side li.ws-link {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 6px;
  cursor: pointer; font-size: 13px; color: var(--text-dim);
  user-select: none;
}
aside.nav-side li.ws-link:hover { background: white; color: var(--text); }
aside.nav-side li.ws-link.current { background: var(--text); color: white; }
aside.nav-side li.ws-link .ws-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--text-mute); flex-shrink: 0;
}
aside.nav-side li.ws-link.has-active .ws-dot { background: var(--green); }
aside.nav-side li.ws-link.has-paused .ws-dot { background: var(--amber); }
aside.nav-side li.ws-link.all-done .ws-dot { background: var(--slate); }
aside.nav-side li.ws-link .ws-name {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
aside.nav-side li.ws-link .ws-count {
  font-size: 10px; background: var(--slate-bg); color: var(--text-mute);
  padding: 1px 7px; border-radius: 999px; flex-shrink: 0;
}
aside.nav-side li.ws-link.current .ws-count {
  background: rgba(255,255,255,0.2); color: white;
}
aside.nav-side li.ws-link.in-current-group {
  color: var(--text); font-weight: 500;
}

/* Sub-list: initiatives under each workspace */
aside.nav-side ul.init-sub {
  list-style: none; padding: 0; margin: 2px 0 6px 13px;
  display: flex; flex-direction: column; gap: 1px;
  border-left: 1px solid var(--border);
}
aside.nav-side li.init-link {
  display: flex; align-items: center; gap: 7px;
  padding: 4px 8px 4px 10px;
  font-size: 12px; line-height: 1.4;
  color: var(--text-mute);
  cursor: pointer; user-select: none;
  border-radius: 4px;
  margin-left: -1px;
  border-left: 2px solid transparent;
}
aside.nav-side li.init-link:hover { color: var(--text); background: white; }
aside.nav-side li.init-link.current {
  color: var(--text); font-weight: 500;
  background: white;
  border-left-color: var(--accent);
}
aside.nav-side li.init-link .init-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--text-mute); flex-shrink: 0;
}
aside.nav-side li.init-link.s-active .init-dot { background: var(--green); }
aside.nav-side li.init-link.s-paused .init-dot { background: var(--amber); }
aside.nav-side li.init-link.s-done .init-dot { background: var(--slate); }
aside.nav-side li.init-link.s-archived .init-dot { background: var(--text-mute); }
aside.nav-side li.init-link .init-name {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* ---------- Board ---------- */
main.board { flex: 1; min-width: 0; padding: 16px 24px 80px; }
section.workspace { scroll-margin-top: 90px; }
article.card { scroll-margin-top: 100px; }

/* ---------- Archive zone ---------- */
section.archive-zone {
  margin-top: 32px;
  padding-top: 16px;
  border-top: 2px dashed var(--border);
  scroll-margin-top: 90px;
}
section.archive-zone > header.archive-head {
  display: flex; align-items: baseline; gap: 10px; padding: 8px 4px;
  cursor: pointer; user-select: none;
  color: var(--text-dim);
}
section.archive-zone > header.archive-head:hover { color: var(--accent); }
section.archive-zone > header.archive-head .ws-toggle {
  font-size: 10px; color: var(--text-mute); width: 14px;
}
section.archive-zone > header.archive-head h2 { font-size: 14px; font-weight: 600; margin: 0; }
section.archive-zone > header.archive-head .ws-meta { font-size: 12px; color: var(--text-mute); }
section.archive-zone.collapsed .archive-body { display: none; }
section.archive-zone div.archive-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 10px;
}
section.archive-zone article.card {
  opacity: 0.75; padding: 12px; font-size: 13px;
}
section.archive-zone article.card:hover { opacity: 1; }
section.archive-zone article.card .from-ws {
  font-size: 10px; color: var(--text-mute); margin-top: -2px;
}
section.archive-zone article.card .from-ws code {
  background: var(--slate-bg); padding: 1px 6px; border-radius: 3px;
}

section.workspace { margin-bottom: 24px; }
section.workspace > header.ws-head {
  display: flex; align-items: baseline; gap: 10px; padding: 8px 4px;
  cursor: pointer; user-select: none;
}
section.workspace > header.ws-head:hover { color: var(--accent); }
section.workspace > header.ws-head .ws-toggle {
  font-size: 10px; color: var(--text-mute); width: 14px; display: inline-block;
}
section.workspace > header.ws-head h2 { font-size: 15px; font-weight: 600; margin: 0; }
section.workspace > header.ws-head .ws-meta { font-size: 12px; color: var(--text-mute); }
section.workspace.collapsed .ws-body { display: none; }

div.ws-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 14px;
}

/* ---------- Card ---------- */
article.card {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px;
  box-shadow: var(--shadow);
  transition: box-shadow 0.15s, border-color 0.15s;
  position: relative;
}
article.card:hover { box-shadow: var(--shadow-hover); border-color: var(--border-hover); }
article.card.hidden { display: none; }
article.card.archived { opacity: 0.7; }

.card-head { display: flex; align-items: flex-start; gap: 8px; }
.card-head h3 {
  font-size: 14px; font-weight: 600; margin: 0; flex: 1;
  line-height: 1.4; word-break: break-word;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
  margin-top: 7px; flex-shrink: 0;
}
.status-dot.active { background: var(--green); }
.status-dot.paused { background: var(--amber); }
.status-dot.done { background: var(--slate); }
.status-dot.archived { background: var(--text-mute); }

.status-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 4px;
  white-space: nowrap;
}
.status-badge.active { background: var(--green-bg); color: var(--green); }
.status-badge.paused { background: var(--amber-bg); color: var(--amber); }
.status-badge.done { background: var(--slate-bg); color: var(--slate); }
.status-badge.archived { background: var(--slate-bg); color: var(--text-mute); }
.status-badge.blocker { background: var(--red-bg); color: var(--red); cursor: pointer; }
.status-badge.pending { background: #dbeafe; color: var(--accent); cursor: pointer; }
.status-badge.blocker:hover, .status-badge.pending:hover { filter: brightness(0.95); }

.blocker-preview {
  margin: 6px 0 0; padding: 6px 10px;
  background: var(--red-bg); color: var(--red);
  border-radius: 4px; font-size: 12px; line-height: 1.4;
  cursor: pointer;
}
.blocker-preview:hover { filter: brightness(0.96); }
.blocker-preview .lbl { font-weight: 600; margin-right: 6px; }

.card.has-modal-target { cursor: pointer; }
.card.has-modal-target:hover { border-color: var(--border-hover); }

/* Detail modal */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: flex-start; justify-content: center;
  z-index: 1000;
  padding: 8vh 16px;
}
.modal {
  background: white; border-radius: 8px;
  max-width: 720px; width: 100%; max-height: 84vh;
  overflow: auto;
  padding: 24px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
}
.modal-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.modal-head h2 { flex: 1; margin: 0; font-size: 18px; line-height: 1.3; }
.modal-close {
  background: none; border: none; cursor: pointer;
  font-size: 22px; color: var(--text-mute); padding: 2px 6px;
  line-height: 1; border-radius: 4px;
}
.modal-close:hover { color: var(--text-dim); background: var(--bg); }
.modal-section { margin-bottom: 18px; }
.modal-section:last-child { margin-bottom: 0; }
.modal-section h3 {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--text-mute); margin: 0 0 8px; font-weight: 600;
}
.modal-section ul { margin: 0; padding: 0; list-style: none; }
.modal-section ul.modal-blockers-list li {
  padding: 6px 10px; margin-bottom: 4px;
  background: var(--red-bg); color: var(--red);
  border-radius: 4px; font-size: 13px;
}
.modal-section ul.modal-artifacts-list li {
  padding: 8px 10px; margin-bottom: 6px;
  background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; font-size: 13px;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.modal-section ul.modal-artifacts-list li .art-type {
  font-size: 10px; padding: 2px 6px; border-radius: 3px;
  background: var(--slate-bg); color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.modal-section ul.modal-artifacts-list li .art-status {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: var(--slate-bg); color: var(--slate);
}
.modal-section ul.modal-artifacts-list li .art-status.pending,
.modal-section ul.modal-artifacts-list li .art-status.open { background: #dbeafe; color: var(--accent); }
.modal-section ul.modal-artifacts-list li .art-status.approved,
.modal-section ul.modal-artifacts-list li .art-status.active,
.modal-section ul.modal-artifacts-list li .art-status.live { background: var(--amber-bg); color: var(--amber); }
.modal-section ul.modal-artifacts-list li .art-status.merged,
.modal-section ul.modal-artifacts-list li .art-status.released,
.modal-section ul.modal-artifacts-list li .art-status.pushed { background: var(--green-bg); color: var(--green); }
.modal-section ul.modal-artifacts-list li .art-title {
  flex: 1; word-break: break-word; color: var(--text-dim);
}
.modal-section ul.modal-artifacts-list li a.art-link {
  color: var(--accent); text-decoration: none; font-size: 12px;
  padding: 2px 6px; border: 1px solid var(--border);
  border-radius: 3px;
}
.modal-section ul.modal-artifacts-list li a.art-link:hover {
  background: var(--bg); border-color: var(--accent);
}
.modal-section p.modal-empty { margin: 0; color: var(--text-mute); font-size: 12px; }

.card-meta {
  display: flex; gap: 12px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-mute); margin-top: 6px; margin-bottom: 12px;
}
.card-meta .id-tag code {
  background: var(--slate-bg); padding: 1px 6px; border-radius: 3px;
  color: var(--text-dim);
}
.card-meta .linked-tag code { background: var(--amber-bg); color: var(--amber); padding: 1px 6px; border-radius: 3px; }

.card-section { margin-bottom: 10px; }
.card-section .label {
  font-size: 11px; font-weight: 600; color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;
  display: flex; align-items: baseline; gap: 8px;
}
.card-section .label .label-meta { font-weight: 400; text-transform: none; letter-spacing: 0; }
.card-section p.body { margin: 0; color: var(--text-dim); font-size: 13px; line-height: 1.55; }

/* Tasks list */
ul.tasks-list { list-style: none; margin: 0; padding: 0; }
ul.tasks-list li.task {
  display: flex; align-items: flex-start; gap: 8px; padding: 4px 4px 4px 0;
  font-size: 13px; line-height: 1.45; border-radius: 4px;
  position: relative;
}
ul.tasks-list li.task:hover { background: var(--bg); }
ul.tasks-list li.task input[type=checkbox] { margin-top: 3px; cursor: pointer; flex-shrink: 0; }
ul.tasks-list li.task .task-title { flex: 1; word-break: break-word; }
ul.tasks-list li.task[data-done="true"] .task-title { text-decoration: line-through; color: var(--text-mute); }
ul.tasks-list li.task .task-del {
  background: none; border: none; cursor: pointer; padding: 0 6px;
  color: var(--text-mute); opacity: 0; font-size: 13px; line-height: 1;
}
ul.tasks-list li.task:hover .task-del { opacity: 1; }
ul.tasks-list li.task .task-del:hover { color: var(--red); }
ul.tasks-list li.task.hidden-done { display: none; }

button.expand-toggle {
  background: none; border: none; padding: 4px 0; cursor: pointer;
  color: var(--text-mute); font-size: 12px; text-align: left; display: block;
}
button.expand-toggle:hover { color: var(--accent); }

/* Sessions */
ul.sessions-list { list-style: none; margin: 0; padding: 0; }
ul.sessions-list li.session {
  display: flex; align-items: center; gap: 8px; padding: 4px 4px 4px 0;
  font-size: 12px;
}
ul.sessions-list li.session.hidden-sess { display: none; }
ul.sessions-list li.session code.sid {
  background: var(--slate-bg); padding: 1px 6px; border-radius: 3px;
  font-size: 11px; color: var(--text-dim);
}
ul.sessions-list li.session .pane-info { color: var(--text-mute); font-size: 11px; flex: 1; }
ul.sessions-list li.session .pane-info.dim { font-style: italic; opacity: 0.6; }
ul.sessions-list li.session .sess-actions { display: flex; gap: 2px; }
ul.sessions-list li.session .sess-btn {
  background: white; border: 1px solid var(--border); border-radius: 4px;
  padding: 1px 6px; font-size: 11px; cursor: pointer; line-height: 1.4;
}
ul.sessions-list li.session .sess-btn:hover { background: var(--bg); border-color: var(--border-hover); }

/* Footer actions */
footer.card-actions {
  display: flex; gap: 6px; flex-wrap: wrap;
  margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border);
}
footer.card-actions button {
  font-size: 12px; padding: 4px 10px; border: 1px solid var(--border);
  background: white; border-radius: 5px; cursor: pointer; color: var(--text-dim);
}
footer.card-actions button:hover { background: var(--bg); border-color: var(--border-hover); color: var(--text); }
footer.card-actions button.danger:hover { background: var(--red-bg); border-color: var(--red); color: var(--red); }

/* Toast */
#toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: var(--text); color: white; padding: 8px 16px;
  border-radius: 6px; font-size: 12px; opacity: 0;
  transition: opacity 0.2s, transform 0.2s; pointer-events: none;
  max-width: 90vw; text-align: center;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* Empty state */
.empty-state {
  text-align: center; padding: 60px 20px;
  color: var(--text-mute); font-size: 14px;
}

/* Responsive */
@media (max-width: 900px) {
  aside.nav-side { display: none; }
}
@media (max-width: 720px) {
  header.top, nav.toolbar, main.board { padding-left: 12px; padding-right: 12px; }
  div.ws-body { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<header class="top">
  <h1>__HEADER__</h1>
  <span class="meta">__GENERATED__</span>
  <span class="grow"></span>
  <button class="data-stale" id="data-stale" type="button">__DATA_STALE__</button>
  <button class="sync-btn" id="manual-refresh" type="button" title="__MANUAL_REFRESH__">🔄</button>
  <a class="sync-btn" href="mindmap-tree.html">__TREE_VIEW__</a>
  <span class="status-pill" id="sync-status">__SYNC_IDLE__</span>
  <button class="sync-btn" id="sync-toggle">__SYNC_CONNECT__</button>
  <span class="status-pill" id="helper-state"></span>
</header>

<nav class="toolbar">
  <div class="chips" id="status-chips">
    <button class="chip active" data-status="all">__FILTER_ALL__ <span class="count" id="count-all">0</span></button>
    <button class="chip" data-status="active">__FILTER_ACTIVE__ <span class="count" id="count-active">0</span></button>
    <button class="chip" data-status="paused">__FILTER_PAUSED__ <span class="count" id="count-paused">0</span></button>
    <button class="chip" data-status="done">__FILTER_DONE__ <span class="count" id="count-done">0</span></button>
    <button class="chip" data-status="archived">__FILTER_ARCHIVED__ <span class="count" id="count-archived">0</span></button>
  </div>
  <input type="search" class="search" id="search-input" placeholder="__SEARCH_PLACEHOLDER__">
</nav>

<div class="layout">
  <aside class="nav-side">
    <div class="nav-title">__NAV_TITLE__</div>
    <ul class="ws-nav" id="ws-nav"></ul>
  </aside>
  <main class="board" id="board"></main>
</div>

<div id="toast"></div>

<script id="mindmap-data" type="application/json">__DATA_JSON__</script>
<script id="i18n-data" type="application/json">__I18N_JSON__</script>
<script id="locations-data" type="application/json">__LOCATIONS_JSON__</script>
<script id="archived-data" type="application/json">__ARCHIVED_JSON__</script>

<script>
(function() {
  'use strict';
  // These are LET (not const) — when the server reports new data, we swap
  // them in place and re-render without a page reload.
  let DATA = JSON.parse(document.getElementById('mindmap-data').textContent);
  const I18N = JSON.parse(document.getElementById('i18n-data').textContent);
  let LOCATIONS = JSON.parse(document.getElementById('locations-data').textContent);
  // Archived items loaded from cache/archive/ — already removed from
  // mindmap.json but we keep them visible in the archive zone here.
  let ARCHIVED_PERSISTED = JSON.parse(document.getElementById('archived-data').textContent);
  const STORAGE_KEY = 'claude-code-worktree:overrides:v1';
  const COLLAPSE_KEY = 'claude-code-worktree:ws-collapsed:v1';
  const FILTER_KEY = 'claude-code-worktree:filter:v1';
  const HELPER_PORTS = [9876, 9877, 9878];

  const DONE_SHOW_LIMIT = 2;       // show this many done tasks by default
  const SESS_SHOW_LIMIT = 3;        // show this many sessions by default

  // When loaded via http://, the page is served by serve.py and we can
  // POST directly to the same origin for persistence (no File System
  // Access permission needed). When loaded via file://, we fall back to
  // FSA / download-patch flow.
  const SERVER_MODE = (location.protocol === 'http:' || location.protocol === 'https:');
  const SERVER_ORIGIN = SERVER_MODE ? location.origin : null;

  let helperPort = null;
  // In server mode, helper is the SAME origin — no need to scan ports.

  // ---------- State (overrides + UI prefs) -------------------------------
  function emptyOverrides() {
    return { task_toggles: [], archived: [], deleted: [], deleted_tasks: [] };
  }
  function loadOverrides() {
    try { return Object.assign(emptyOverrides(), JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')); }
    catch (e) { return emptyOverrides(); }
  }
  function saveOverrides() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
    updateSyncStatus();
    if (SERVER_MODE) scheduleServerSync();
    else scheduleDiskSync();
  }
  const overrides = loadOverrides();

  function loadCollapsed() {
    try { return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '[]')); }
    catch (e) { return new Set(); }
  }
  function saveCollapsed() { localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsedWs])); }
  const collapsedWs = loadCollapsed();

  let currentFilter = localStorage.getItem(FILTER_KEY) || 'all';
  let currentSearch = '';

  // ---------- Index (re-buildable on hot refresh) -----------------------
  let initById = {};
  function rebuildIndex() {
    initById = {};
    for (const ws of (DATA.workspaces || [])) {
      for (const init of (ws.initiatives || [])) {
        initById[init.id] = { ws_name: ws.name, ws_cwd: ws.cwd, init: init };
      }
    }
    // Persisted archive items (rescued from disk after refresh removed them)
    for (const entry of (ARCHIVED_PERSISTED || [])) {
      const init = entry.init;
      if (!init || !init.id || initById[init.id]) continue;
      init.status = 'archived';
      initById[init.id] = {
        ws_name: entry.ws_name || 'unknown',
        ws_cwd: entry.ws_cwd || null,
        init: init,
        persisted: true,
      };
    }
  }
  rebuildIndex();

  // Compute the effective initiative (data + overrides applied)
  function effective(initId) {
    const base = initById[initId];
    if (!base) return null;
    const init = JSON.parse(JSON.stringify(base.init));
    for (const tt of overrides.task_toggles) {
      if (tt.init_id !== initId) continue;
      const t = init.tasks?.find(x => x.title === tt.task_title);
      if (t) t.done = tt.done;
    }
    init.tasks = (init.tasks || []).filter(t => !overrides.deleted_tasks.some(dt => dt.init_id === initId && dt.task_title === t.title));
    return { ws_name: base.ws_name, ws_cwd: base.ws_cwd, init: init };
  }

  function effectiveStatus(initId) {
    if (overrides.archived.indexOf(initId) !== -1) return 'archived';
    const eff = effective(initId);
    return eff ? eff.init.status : 'unknown';
  }

  function isDeleted(initId) {
    return overrides.deleted.indexOf(initId) !== -1;
  }

  // ---------- Helpers ----------------------------------------------------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  }
  function humanizeAge(iso) {
    if (!iso) return '?';
    const t = new Date(iso); const s = Math.floor((Date.now() - t.getTime()) / 1000);
    if (s < 0) return I18N.just_now;
    if (s < 60) return I18N.ago_s.replace('{}', s);
    if (s < 3600) return I18N.ago_m.replace('{}', Math.floor(s/60));
    if (s < 86400) return I18N.ago_h.replace('{}', Math.floor(s/3600));
    return I18N.ago_d.replace('{}', Math.floor(s/86400));
  }
  function shortCwd(p) { return p; /* server already shortened */ }
  function toastEl() { return document.getElementById('toast'); }
  let toastTimer = null;
  function toast(msg) {
    const t = toastEl();
    t.textContent = msg;
    t.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
  }

  // ---------- Render -----------------------------------------------------
  function render() {
    const board = document.getElementById('board');
    board.innerHTML = '';

    const workspaces = DATA.workspaces || [];
    if (!workspaces.length) {
      board.innerHTML = '<div class="empty-state">' + esc(I18N.empty_no_data) + '</div>';
      updateCounts();
      return;
    }

    // Collect archived initiatives separately for the bottom zone.
    // "archived" = either AI-determined status, user-archived override, or
    // persisted in cache/archive/ from a prior session.
    const archivedList = []; // [{ws_name, ws_idx, init}]
    const seenInArchive = new Set();

    workspaces.forEach((ws, wsIdx) => {
      // Split: archived inits get peeled off into archivedList
      const liveInits = [];
      for (const init of (ws.initiatives || [])) {
        if (isDeleted(init.id)) continue;
        if (effectiveStatus(init.id) === 'archived') {
          archivedList.push({ ws_name: ws.name, ws_idx: wsIdx, init: init });
          seenInArchive.add(init.id);
        } else {
          liveInits.push(init);
        }
      }
      // Skip workspaces left with no live inits (all archived).
      if (liveInits.length === 0) return;

      const wsSec = document.createElement('section');
      wsSec.className = 'workspace' + (collapsedWs.has(ws.name) ? ' collapsed' : '');
      wsSec.setAttribute('data-ws-name', ws.name);
      wsSec.setAttribute('data-ws-idx', String(wsIdx));
      wsSec.id = 'ws-' + wsIdx;

      const wsHead = document.createElement('header');
      wsHead.className = 'ws-head';
      wsHead.innerHTML =
        '<span class="ws-toggle">' + (collapsedWs.has(ws.name) ? I18N.ws_collapsed : I18N.ws_expanded) + '</span>' +
        '<h2>' + esc(ws.name) + '</h2>' +
        '<span class="ws-meta">' + (ws.initiatives || []).length + ' ' + I18N.initiative +
        (ws.cwd ? ' · <code>' + esc(shortCwd(ws.cwd)) + '</code>' : '') + '</span>';
      wsHead.addEventListener('click', () => {
        if (collapsedWs.has(ws.name)) collapsedWs.delete(ws.name);
        else collapsedWs.add(ws.name);
        saveCollapsed();
        render();
      });
      wsSec.appendChild(wsHead);

      const wsBody = document.createElement('div');
      wsBody.className = 'ws-body';
      for (const initRaw of liveInits) {
        wsBody.appendChild(renderCard(initRaw.id));
      }
      wsSec.appendChild(wsBody);
      board.appendChild(wsSec);
    });

    // Also pull in items persisted to cache/archive/ (already swept from
    // mindmap.json by refresh.sh). They are in initById tagged as `persisted`.
    for (const id in initById) {
      if (seenInArchive.has(id) || isDeleted(id)) continue;
      const rec = initById[id];
      if (rec.persisted) {
        archivedList.push({ ws_name: rec.ws_name, ws_idx: -1, init: rec.init });
      }
    }

    // ---- Archive zone (collapsed by default) -----------------------------
    if (archivedList.length > 0) {
      const isCollapsed = !collapsedWs.has('__archive_open__'); // open marker
      const arcSec = document.createElement('section');
      arcSec.className = 'archive-zone' + (isCollapsed ? ' collapsed' : '');
      arcSec.id = 'archive-zone';

      const head = document.createElement('header');
      head.className = 'archive-head';
      head.innerHTML =
        '<span class="ws-toggle">' + (isCollapsed ? I18N.ws_collapsed : I18N.ws_expanded) + '</span>' +
        '<h2>' + esc(I18N.archive_zone) + '</h2>' +
        '<span class="ws-meta">' + archivedList.length + ' ' + esc(I18N.initiative) + '</span>';
      head.addEventListener('click', () => {
        if (collapsedWs.has('__archive_open__')) collapsedWs.delete('__archive_open__');
        else collapsedWs.add('__archive_open__');
        saveCollapsed();
        render();
      });
      arcSec.appendChild(head);

      const body = document.createElement('div');
      body.className = 'archive-body';
      for (const entry of archivedList) {
        const card = renderCard(entry.init.id);
        // Add a "from <workspace>" tag at the top of the card meta
        const fromTag = document.createElement('div');
        fromTag.className = 'from-ws';
        fromTag.innerHTML = esc(I18N.from_workspace) + ' <code>' + esc(entry.ws_name) + '</code>';
        // Insert right after card-head (before card-meta)
        const meta = card.querySelector('.card-meta');
        if (meta) meta.parentNode.insertBefore(fromTag, meta);
        else card.insertBefore(fromTag, card.firstChild);
        body.appendChild(card);
      }
      arcSec.appendChild(body);
      board.appendChild(arcSec);
    }

    renderNav(archivedList);
    setupScrollSpy();
    applyFilter();
    updateCounts();
  }

  // ---------- Side nav (two levels: workspace > initiative) -------------
  function scrollToCard(initId) {
    const card = document.querySelector('article.card[data-init-id="' + CSS.escape(initId) + '"]');
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function scrollToWs(idx) {
    const sec = document.getElementById('ws-' + idx);
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function expandWsIfCollapsed(wsName, then) {
    if (collapsedWs.has(wsName)) {
      collapsedWs.delete(wsName);
      saveCollapsed();
      render();
      setTimeout(then, 60);
    } else {
      then();
    }
  }
  function renderNav(archivedList) {
    archivedList = archivedList || [];
    const nav = document.getElementById('ws-nav');
    if (!nav) return;
    nav.innerHTML = '';
    const workspaces = DATA.workspaces || [];
    workspaces.forEach((ws, idx) => {
      // Filter to live (non-archived, non-deleted) inits — same as main view
      const liveInits = (ws.initiatives || []).filter(i =>
        !isDeleted(i.id) && effectiveStatus(i.id) !== 'archived'
      );
      if (liveInits.length === 0) return;  // workspace fully archived — skip from main nav

      const statuses = liveInits.map(i => effectiveStatus(i.id));
      let dotCls = '';
      if (statuses.indexOf('active') !== -1) dotCls = 'has-active';
      else if (statuses.indexOf('paused') !== -1) dotCls = 'has-paused';
      else if (statuses.every(s => s === 'done')) dotCls = 'all-done';

      const wsLi = document.createElement('li');
      wsLi.className = 'ws-link ' + dotCls;
      wsLi.setAttribute('data-ws-idx', String(idx));
      wsLi.innerHTML =
        '<span class="ws-dot"></span>' +
        '<span class="ws-name" title="' + esc(ws.name) + '">' + esc(ws.name) + '</span>' +
        '<span class="ws-count">' + liveInits.length + '</span>';
      wsLi.addEventListener('click', () => {
        expandWsIfCollapsed(ws.name, () => scrollToWs(idx));
      });
      nav.appendChild(wsLi);

      const subUl = document.createElement('ul');
      subUl.className = 'init-sub';
      subUl.setAttribute('data-ws-idx', String(idx));
      liveInits.forEach(initRaw => {
        const status = effectiveStatus(initRaw.id);
        const eff = effective(initRaw.id);
        const displayName = eff ? eff.init.name : initRaw.name;
        const initLi = document.createElement('li');
        initLi.className = 'init-link s-' + status;
        initLi.setAttribute('data-init-id', initRaw.id);
        initLi.setAttribute('data-ws-idx', String(idx));
        initLi.innerHTML =
          '<span class="init-dot"></span>' +
          '<span class="init-name" title="' + esc(displayName) + '">' + esc(displayName) + '</span>';
        initLi.addEventListener('click', () => {
          expandWsIfCollapsed(ws.name, () => scrollToCard(initRaw.id));
        });
        subUl.appendChild(initLi);
      });
      nav.appendChild(subUl);
    });

    // Single bottom entry for the archive zone
    if (archivedList.length > 0) {
      const sep = document.createElement('li');
      sep.style.cssText = 'margin-top: 12px; border-top: 1px solid var(--border); padding-top: 8px; list-style: none;';
      sep.setAttribute('aria-hidden', 'true');
      nav.appendChild(sep);

      const arcLi = document.createElement('li');
      arcLi.className = 'ws-link';
      arcLi.setAttribute('data-archive', 'true');
      arcLi.innerHTML =
        '<span class="ws-dot" style="background: var(--text-mute);"></span>' +
        '<span class="ws-name">' + esc(I18N.archive_zone) + '</span>' +
        '<span class="ws-count">' + archivedList.length + '</span>';
      arcLi.addEventListener('click', () => {
        // Ensure zone is expanded
        if (!collapsedWs.has('__archive_open__')) {
          collapsedWs.add('__archive_open__');
          saveCollapsed();
          render();
          setTimeout(() => document.getElementById('archive-zone')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
        } else {
          document.getElementById('archive-zone')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
      nav.appendChild(arcLi);
    }
  }

  // Scroll spy: track which card is currently topmost in the viewport;
  // highlight the matching nav sub-item AND its parent workspace.
  let _spyObserver = null;
  function setupScrollSpy() {
    if (_spyObserver) _spyObserver.disconnect();
    _spyObserver = new IntersectionObserver((entries) => {
      const intersecting = entries.filter(e => e.isIntersecting);
      if (intersecting.length === 0) return;
      intersecting.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      const topCard = intersecting[0].target;
      const initId = topCard.getAttribute('data-init-id');
      const wsSec = topCard.closest('section.workspace');
      const wsIdx = wsSec ? wsSec.getAttribute('data-ws-idx') : null;
      document.querySelectorAll('aside.nav-side li.init-link').forEach(li => {
        li.classList.toggle('current', li.getAttribute('data-init-id') === initId);
      });
      document.querySelectorAll('aside.nav-side li.ws-link').forEach(li => {
        const same = li.getAttribute('data-ws-idx') === wsIdx;
        li.classList.toggle('in-current-group', same);
        li.classList.toggle('current', false); // sub-item gets the strong highlight; ws gets subtle
      });
    }, {
      // header (~48) + toolbar (~50) ≈ 98 — observe cards entering the
      // upper third of the viewport
      rootMargin: '-100px 0px -60% 0px',
      threshold: 0,
    });
    document.querySelectorAll('article.card').forEach(c => _spyObserver.observe(c));
  }

  function renderCard(initId) {
    const eff = effective(initId);
    if (!eff) return document.createDocumentFragment();
    const init = eff.init;
    const isArchived = overrides.archived.indexOf(initId) !== -1;
    const status = isArchived ? 'archived' : init.status;

    const card = document.createElement('article');
    card.className = 'card' + (isArchived ? ' archived' : '');
    card.setAttribute('data-init-id', initId);
    card.setAttribute('data-status', status);

    // Head
    const head = document.createElement('div');
    head.className = 'card-head';
    const blockers = Array.isArray(init.blockers) ? init.blockers : [];
    const artifacts = Array.isArray(init.artifacts) ? init.artifacts : [];
    const pendingArts = artifacts.filter(a => a && ['pending', 'open', 'unknown'].indexOf(a.status) !== -1 && ['cr', 'mr', 'pr', 'issue'].indexOf(a.type) !== -1);
    let headHtml =
      '<span class="status-dot ' + status + '"></span>' +
      '<h3>' + esc(init.name) + '</h3>' +
      '<span class="status-badge ' + status + '">' + esc(I18N['status_' + status] || status) + '</span>' +
      '<span class="status-badge">' + esc(humanizeAge(init.last_activity_at)) + '</span>';
    if (blockers.length) {
      headHtml += '<span class="status-badge blocker" data-open-modal="blockers" title="' + esc(blockers[0]) + '">🚨 ' + esc(I18N.blocker_chip.replace('{}', blockers.length)) + '</span>';
    }
    if (pendingArts.length) {
      headHtml += '<span class="status-badge pending" data-open-modal="artifacts" title="' + esc(pendingArts.map(a => a.title || a.url).slice(0,3).join(' / ')) + '">🔗 ' + esc(I18N.pending_chip.replace('{}', pendingArts.length)) + '</span>';
    }
    head.innerHTML = headHtml;
    card.appendChild(head);

    // Meta
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    const linked = init.linked_cwds || [];
    meta.innerHTML =
      '<span class="id-tag"><code>' + esc(init.id) + '</code></span>' +
      (linked.length ? '<span class="linked-tag">' + esc(I18N.linked) + ': <code>' + linked.map(x => esc(shortCwd(x))).join(', ') + '</code></span>' : '');
    card.appendChild(meta);

    // Summary
    if (init.summary) {
      card.appendChild(buildSection(I18N.summary, '<p class="body">' + esc(init.summary) + '</p>'));
    }
    // Progress
    if (init.progress) {
      card.appendChild(buildSection(I18N.progress, '<p class="body">' + esc(init.progress) + '</p>'));
    }
    // Top blocker preview (under progress)
    if (blockers.length) {
      const bp = document.createElement('div');
      bp.className = 'blocker-preview';
      bp.setAttribute('data-open-modal', 'blockers');
      bp.innerHTML = '⚠ <span class="lbl">' + esc(I18N.blocker_top_label) + ':</span>' + esc(blockers[0]);
      card.appendChild(bp);
    }

    // Tasks
    const tasks = init.tasks || [];
    if (tasks.length) {
      const doneCount = tasks.filter(t => t.done).length;
      const labelMeta = I18N.tasks_meta.replace('{}', tasks.length).replace('{}', doneCount);
      const taskSection = document.createElement('div');
      taskSection.className = 'card-section tasks-section';
      taskSection.innerHTML =
        '<div class="label">' + esc(I18N.tasks) + ' <span class="label-meta">' + esc(labelMeta) + '</span></div>';
      const ul = document.createElement('ul');
      ul.className = 'tasks-list';
      // Order: open first, then most recent done first (we don't have timestamps,
      // so just preserve original order within each group)
      const opens = tasks.filter(t => !t.done);
      const dones = tasks.filter(t => t.done);
      for (const t of opens) ul.appendChild(buildTaskLi(initId, t, false));
      // Show first DONE_SHOW_LIMIT done tasks, rest hidden
      for (let i = 0; i < dones.length; i++) {
        const hide = i >= DONE_SHOW_LIMIT;
        ul.appendChild(buildTaskLi(initId, dones[i], hide));
      }
      taskSection.appendChild(ul);
      if (dones.length > DONE_SHOW_LIMIT) {
        const btn = document.createElement('button');
        btn.className = 'expand-toggle';
        btn.setAttribute('data-state', 'collapsed');
        btn.textContent = '▾ ' + I18N.show_done_tasks.replace('{}', dones.length - DONE_SHOW_LIMIT);
        btn.addEventListener('click', () => {
          const isCollapsed = btn.getAttribute('data-state') === 'collapsed';
          ul.querySelectorAll('li.hidden-done').forEach(li => li.classList.remove('hidden-done'));
          if (isCollapsed) {
            btn.setAttribute('data-state', 'expanded');
            btn.textContent = '▴ ' + I18N.hide_done_tasks;
            // Re-hide them after the toggle is "expanded->collapsed". Done in else.
          } else {
            // toggling back: re-hide
            btn.setAttribute('data-state', 'collapsed');
            btn.textContent = '▾ ' + I18N.show_done_tasks.replace('{}', dones.length - DONE_SHOW_LIMIT);
            const items = ul.querySelectorAll('li.task[data-done="true"]');
            for (let i = DONE_SHOW_LIMIT; i < items.length; i++) items[i].classList.add('hidden-done');
          }
        });
        taskSection.appendChild(btn);
      }
      card.appendChild(taskSection);
    }

    // Sessions
    const sessions = init.sessions || [];
    if (sessions.length) {
      const sect = document.createElement('div');
      sect.className = 'card-section sessions-section';
      sect.innerHTML = '<div class="label">' + esc(I18N.sessions) + ' <span class="label-meta">' + esc(I18N.sessions_meta.replace('{}', sessions.length)) + '</span></div>';
      const ul = document.createElement('ul');
      ul.className = 'sessions-list';
      for (let i = 0; i < sessions.length; i++) {
        const sid = sessions[i];
        const hide = i >= SESS_SHOW_LIMIT;
        ul.appendChild(buildSessionLi(initId, sid, eff.ws_cwd, hide));
      }
      sect.appendChild(ul);
      if (sessions.length > SESS_SHOW_LIMIT) {
        const btn = document.createElement('button');
        btn.className = 'expand-toggle';
        btn.setAttribute('data-state', 'collapsed');
        btn.textContent = '▾ ' + I18N.show_more_sessions.replace('{}', sessions.length - SESS_SHOW_LIMIT);
        btn.addEventListener('click', () => {
          const isCollapsed = btn.getAttribute('data-state') === 'collapsed';
          if (isCollapsed) {
            ul.querySelectorAll('li.hidden-sess').forEach(li => li.classList.remove('hidden-sess'));
            btn.setAttribute('data-state', 'expanded');
            btn.textContent = '▴ ' + I18N.hide_more_sessions;
          } else {
            btn.setAttribute('data-state', 'collapsed');
            btn.textContent = '▾ ' + I18N.show_more_sessions.replace('{}', sessions.length - SESS_SHOW_LIMIT);
            const items = ul.querySelectorAll('li.session');
            for (let i = SESS_SHOW_LIMIT; i < items.length; i++) items[i].classList.add('hidden-sess');
          }
        });
        sect.appendChild(btn);
      }
      card.appendChild(sect);
    }

    // Footer
    const foot = document.createElement('footer');
    foot.className = 'card-actions';
    if (!isArchived) {
      const ab = document.createElement('button');
      ab.innerHTML = '📦 ' + esc(I18N.btn_archive);
      ab.addEventListener('click', () => {
        if (!confirm(I18N.confirm_archive.replace('{}', init.name))) return;
        overrides.archived.push(initId); saveOverrides(); render();
      });
      foot.appendChild(ab);
    } else {
      const ub = document.createElement('button');
      ub.innerHTML = '↩ ' + esc(I18N.btn_unarchive);
      ub.addEventListener('click', () => {
        overrides.archived = overrides.archived.filter(x => x !== initId);
        saveOverrides(); render();
      });
      foot.appendChild(ub);
    }
    const db = document.createElement('button');
    db.className = 'danger';
    db.innerHTML = '🗑️ ' + esc(I18N.btn_delete);
    db.addEventListener('click', () => {
      if (!confirm(I18N.confirm_delete.replace('{}', init.name))) return;
      overrides.deleted.push(initId); saveOverrides(); render();
    });
    foot.appendChild(db);
    card.appendChild(foot);

    // Make card clickable: anywhere on the card (except interactive descendants)
    // opens the detail modal. The badge/preview also have data-open-modal hints
    // that scroll the modal to the right section.
    if (blockers.length || artifacts.length) {
      card.classList.add('has-modal-target');
      card.addEventListener('click', (ev) => {
        // Ignore clicks on interactive elements
        const t = ev.target;
        if (!t) return;
        if (t.closest('button, a, input, .task-del, .sess-btn, ul.tasks-list, ul.sessions-list, .expand-toggle, footer.card-actions')) {
          return;
        }
        const focusKey = t.closest('[data-open-modal]')?.getAttribute('data-open-modal') || null;
        openDetailModal(initId, focusKey);
      });
    }

    return card;
  }

  // -- Detail modal ------------------------------------------------------

  function openDetailModal(initId, focusSection) {
    const eff = effective(initId);
    if (!eff) return;
    const init = eff.init;
    const blockers = Array.isArray(init.blockers) ? init.blockers : [];
    const artifacts = Array.isArray(init.artifacts) ? init.artifacts : [];

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) closeDetailModal(); });

    const modal = document.createElement('div');
    modal.className = 'modal';
    overlay.appendChild(modal);

    // Head
    const head = document.createElement('div');
    head.className = 'modal-head';
    head.innerHTML =
      '<h2>' + esc(init.name) + '</h2>' +
      '<button class="modal-close" title="' + esc(I18N.modal_close) + '">✕</button>';
    head.querySelector('.modal-close').addEventListener('click', closeDetailModal);
    modal.appendChild(head);

    // Blockers section
    const bSec = document.createElement('div');
    bSec.className = 'modal-section';
    bSec.id = 'modal-sec-blockers';
    let bHtml = '<h3>' + esc(I18N.modal_blockers) + ' (' + blockers.length + ')</h3>';
    if (blockers.length) {
      bHtml += '<ul class="modal-blockers-list">';
      for (const b of blockers) bHtml += '<li>⚠ ' + esc(b) + '</li>';
      bHtml += '</ul>';
    } else {
      bHtml += '<p class="modal-empty">' + esc(I18N.modal_no_blockers) + '</p>';
    }
    bSec.innerHTML = bHtml;
    modal.appendChild(bSec);

    // Artifacts section
    const aSec = document.createElement('div');
    aSec.className = 'modal-section';
    aSec.id = 'modal-sec-artifacts';
    let aHtml = '<h3>' + esc(I18N.modal_artifacts) + ' (' + artifacts.length + ')</h3>';
    if (artifacts.length) {
      // Sort: pending/open first, then approved, then merged/closed
      const order = { pending: 0, open: 0, unknown: 1, approved: 2, active: 2, live: 2, merged: 3, released: 3, pushed: 3, closed: 4, wontfix: 4, 'rolled-back': 4, stale: 4, local: 4 };
      const sorted = artifacts.slice().sort((x, y) => (order[x.status] ?? 5) - (order[y.status] ?? 5));
      aHtml += '<ul class="modal-artifacts-list">';
      for (const a of sorted) {
        const statusLabel = I18N['modal_status_' + (a.status || 'unknown').replace('-', '_')] || a.status || '?';
        const statusCls = (a.status || 'unknown').replace(/[^a-z]/g, '');
        const title = a.title || a.ref_id || a.url;
        const safeUrl = (a.url || '').replace(/"/g, '&quot;');
        aHtml +=
          '<li>' +
            '<span class="art-type">' + esc(a.type || '?') + '</span>' +
            '<span class="art-status ' + esc(statusCls) + '">' + esc(statusLabel) + '</span>' +
            '<span class="art-title">' + esc(title) + '</span>' +
            (a.url ? '<a class="art-link" target="_blank" rel="noopener" href="' + safeUrl + '">' + esc(I18N.modal_open_external) + ' ↗</a>' : '') +
          '</li>';
      }
      aHtml += '</ul>';
    } else {
      aHtml += '<p class="modal-empty">' + esc(I18N.modal_no_artifacts) + '</p>';
    }
    aSec.innerHTML = aHtml;
    modal.appendChild(aSec);

    document.body.appendChild(overlay);
    // Esc to close
    document.addEventListener('keydown', modalKeyHandler);

    // Optional scroll to a specific section
    if (focusSection === 'artifacts') {
      modal.querySelector('#modal-sec-artifacts')?.scrollIntoView({ block: 'start', behavior: 'instant' });
    } else if (focusSection === 'blockers') {
      modal.querySelector('#modal-sec-blockers')?.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  function closeDetailModal() {
    document.querySelectorAll('.modal-overlay').forEach(o => o.remove());
    document.removeEventListener('keydown', modalKeyHandler);
  }

  function modalKeyHandler(ev) {
    if (ev.key === 'Escape') closeDetailModal();
  }

  function buildSection(label, innerHtml) {
    const d = document.createElement('div');
    d.className = 'card-section';
    d.innerHTML = '<div class="label">' + esc(label) + '</div>' + innerHtml;
    return d;
  }

  function buildTaskLi(initId, task, hidden) {
    const li = document.createElement('li');
    li.className = 'task' + (hidden ? ' hidden-done' : '');
    li.setAttribute('data-task-title', task.title);
    li.setAttribute('data-done', task.done ? 'true' : 'false');
    li.innerHTML =
      '<input type="checkbox" ' + (task.done ? 'checked' : '') + '>' +
      '<span class="task-title">' + esc(task.title) + '</span>' +
      '<button class="task-del" title="' + esc(I18N.btn_delete) + '">✕</button>';

    li.querySelector('input').addEventListener('change', (e) => {
      const done = e.target.checked;
      // Replace prior toggle for same (init, title)
      overrides.task_toggles = overrides.task_toggles.filter(tt => !(tt.init_id === initId && tt.task_title === task.title));
      overrides.task_toggles.push({ init_id: initId, task_title: task.title, done: done, at: new Date().toISOString() });
      saveOverrides();
      // Live-update: replace this card in place
      replaceCard(initId);
    });
    li.querySelector('.task-del').addEventListener('click', () => {
      if (!confirm(I18N.confirm_delete_task.replace('{}', task.title))) return;
      overrides.deleted_tasks.push({ init_id: initId, task_title: task.title, at: new Date().toISOString() });
      saveOverrides();
      replaceCard(initId);
    });
    return li;
  }

  function buildSessionLi(initId, sid, ws_cwd, hidden) {
    const li = document.createElement('li');
    li.className = 'session' + (hidden ? ' hidden-sess' : '');
    li.setAttribute('data-sid', sid);
    const loc = LOCATIONS[sid];
    const sidShort = sid.length > 12 ? sid.substring(0, 8) + '…' : sid;
    const paneHtml = (loc && loc.zellij_pane_id)
      ? '<span class="pane-info">@ pane ' + esc(loc.zellij_pane_id) + ' (' + esc(loc.zellij_session || '?') + ')</span>'
      : '<span class="pane-info dim" title="' + esc(I18N.no_pane) + '">(' + esc(I18N.no_pane) + ')</span>';
    li.innerHTML =
      '<code class="sid" title="' + esc(sid) + '">' + esc(sidShort) + '</code>' + paneHtml +
      '<div class="sess-actions">' +
        ((loc && loc.zellij_pane_id) ? '<button class="sess-btn act-focus" title="' + esc(I18N.btn_focus) + '">🎯</button>' : '') +
        '<button class="sess-btn act-newpane" title="' + esc(I18N.btn_newpane) + '">🆕</button>' +
        '<button class="sess-btn act-copy" title="' + esc(I18N.btn_copy) + '">📋</button>' +
      '</div>';

    const resumeCwd = ws_cwd || (loc && loc.cwd) || '';
    const resumeCmd = (resumeCwd ? 'cd ' + resumeCwd + ' && ' : '') + 'claude --resume ' + sid;

    const focusBtn = li.querySelector('.act-focus');
    if (focusBtn) {
      focusBtn.addEventListener('click', async () => {
        if (helperPort && loc && loc.zellij_pane_id) {
          const res = await helperCall('focus', { pane: loc.zellij_pane_id, session: loc.zellij_session });
          if (res.ok) {
            if (res.body && res.body.noop) toast(I18N.toast_already_focused.replace('{}', loc.zellij_pane_id));
            else toast(I18N.toast_jumped.replace('{}', loc.zellij_pane_id));
            return;
          }
          if (res.status === 404) {
            if (confirm(I18N.toast_pane_gone.replace('{}', loc.zellij_pane_id) + ' — 在新 pane 中 resume?')) {
              const r2 = await helperCall('newpane', { sid: sid, cwd: resumeCwd });
              if (r2.ok) toast(I18N.toast_new_pane);
            }
            return;
          }
        }
        const cmd = 'zellij' + (loc.zellij_session ? ' --session ' + loc.zellij_session : '') + ' action focus-pane-id ' + loc.zellij_pane_id;
        navigator.clipboard.writeText(cmd).then(() => toast(I18N.toast_helper_down));
      });
    }
    li.querySelector('.act-newpane').addEventListener('click', async () => {
      if (helperPort) {
        const res = await helperCall('newpane', { sid: sid, cwd: resumeCwd });
        if (res.ok) { toast(I18N.toast_new_pane); return; }
      }
      const newPaneCmd = 'zellij run -f -- bash -lc ' + JSON.stringify(resumeCmd);
      navigator.clipboard.writeText(newPaneCmd).then(() => toast(I18N.toast_helper_down));
    });
    li.querySelector('.act-copy').addEventListener('click', () => {
      navigator.clipboard.writeText(resumeCmd).then(() => toast(I18N.toast_copied + ': ' + resumeCmd));
    });
    return li;
  }

  // Replace a single card in place — used for live updates so we don't
  // have to re-render the whole board on every task toggle.
  function replaceCard(initId) {
    const old = document.querySelector('article.card[data-init-id="' + CSS.escape(initId) + '"]');
    if (!old) return;
    if (isDeleted(initId)) { old.remove(); updateCounts(); return; }
    const fresh = renderCard(initId);
    old.replaceWith(fresh);
    applyFilter();
    updateCounts();
  }

  // ---------- Filter + search -------------------------------------------
  function applyFilter() {
    const cards = document.querySelectorAll('article.card');
    const search = currentSearch.toLowerCase().trim();
    cards.forEach(c => {
      const status = c.getAttribute('data-status');
      let visible = (currentFilter === 'all' || status === currentFilter);
      if (visible && search) {
        const txt = c.textContent.toLowerCase();
        visible = txt.indexOf(search) !== -1;
      }
      c.classList.toggle('hidden', !visible);
    });
    // Hide workspaces with all cards hidden? Keep visible but show "no match"?
    // For now: workspaces stay visible; the header is still useful as TOC.
    // Show global no-match indicator if zero cards visible.
    const anyVisible = !![...cards].find(c => !c.classList.contains('hidden'));
    let empty = document.getElementById('global-empty');
    if (!anyVisible && cards.length > 0) {
      if (!empty) {
        empty = document.createElement('div');
        empty.id = 'global-empty';
        empty.className = 'empty-state';
        empty.textContent = I18N.no_match;
        document.getElementById('board').appendChild(empty);
      }
    } else if (empty) {
      empty.remove();
    }
  }

  function updateCounts() {
    const counts = { all: 0, active: 0, paused: 0, done: 0, archived: 0 };
    for (const id of Object.keys(initById)) {
      if (isDeleted(id)) continue;
      const s = effectiveStatus(id);
      counts.all += 1;
      counts[s] = (counts[s] || 0) + 1;
    }
    document.getElementById('count-all').textContent = counts.all;
    document.getElementById('count-active').textContent = counts.active;
    document.getElementById('count-paused').textContent = counts.paused;
    document.getElementById('count-done').textContent = counts.done;
    document.getElementById('count-archived').textContent = counts.archived;
  }

  // Toolbar wiring
  document.querySelectorAll('#status-chips .chip').forEach(c => {
    if (c.getAttribute('data-status') === currentFilter) c.classList.add('active');
    else c.classList.remove('active');
    c.addEventListener('click', () => {
      currentFilter = c.getAttribute('data-status');
      localStorage.setItem(FILTER_KEY, currentFilter);
      document.querySelectorAll('#status-chips .chip').forEach(x => x.classList.toggle('active', x === c));
      applyFilter();
    });
  });
  document.getElementById('search-input').addEventListener('input', (e) => {
    currentSearch = e.target.value;
    applyFilter();
  });

  // ---------- Server sync (preferred when on http://) -------------------
  let serverDebounce = null;
  function scheduleServerSync() {
    if (serverDebounce) clearTimeout(serverDebounce);
    serverDebounce = setTimeout(serverSave, 400);
  }
  async function serverSave() {
    // Build the payload the server expects.
    const archivedData = {};
    for (const id of overrides.archived) {
      const rec = initById[id];
      if (rec) archivedData[id] = { ws_name: rec.ws_name, ws_cwd: rec.ws_cwd, init: rec.init };
    }
    const payload = {
      task_toggles: overrides.task_toggles,
      deleted_tasks: overrides.deleted_tasks,
      archived: overrides.archived,
      archived_data: archivedData,
      deleted: overrides.deleted,
    };
    try {
      const r = await fetch(SERVER_ORIGIN + '/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        document.getElementById('sync-status').textContent = I18N.sync_server;
        document.getElementById('sync-status').classList.add('online');
      } else {
        toast('保存失败 (HTTP ' + r.status + ')');
      }
    } catch (e) { toast('保存失败：' + e.message); }
  }

  // ---------- File System Access sync (fallback for file://) ------------
  let dirHandle = null;
  let syncDebounce = null;
  const $syncBtn = document.getElementById('sync-toggle');
  const $syncStatus = document.getElementById('sync-status');

  async function connectDisk() {
    if (!window.showDirectoryPicker) { toast(I18N.sync_unsupported); downloadPatch(); return; }
    try {
      dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
      $syncBtn.textContent = I18N.sync_connected;
      $syncBtn.disabled = true;
      await writeOverridesToDisk();
      updateSyncStatus();
    } catch (e) { /* cancelled */ }
  }
  async function writeOverridesToDisk() {
    if (!dirHandle) return;
    try {
      const ov = { version: 1, task_toggles: overrides.task_toggles, deleted_tasks: overrides.deleted_tasks, updated_at: new Date().toISOString() };
      await writeFile(dirHandle, 'user_overrides.json', JSON.stringify(ov, null, 2));
      const del = { version: 1, initiatives: overrides.deleted.map(id => ({ id: id, deleted_at: new Date().toISOString() })), updated_at: new Date().toISOString() };
      await writeFile(dirHandle, 'deleted_ids.json', JSON.stringify(del, null, 2));
      if (overrides.archived.length) {
        let arc; try { arc = await dirHandle.getDirectoryHandle('archive', { create: true }); } catch (e) {}
        if (arc) {
          for (const id of overrides.archived) {
            const rec = initById[id]; if (!rec) continue;
            const wsDir = await arc.getDirectoryHandle(safeName(rec.ws_name), { create: true });
            const payload = { archived_at: new Date().toISOString(), archived_by: 'user', from_workspace: rec.ws_name, initiative: rec.init };
            await writeFile(wsDir, id + '.json', JSON.stringify(payload, null, 2));
          }
        }
      }
      $syncStatus.textContent = I18N.sync_disk;
    } catch (e) { console.error('Disk sync failed:', e); toast('磁盘同步失败: ' + e.message); }
  }
  async function writeFile(dir, name, content) {
    const fh = await dir.getFileHandle(name, { create: true });
    const w = await fh.createWritable(); await w.write(content); await w.close();
  }
  function safeName(s) { return (s || 'unknown').replace(/[^a-zA-Z0-9_.-]/g, '_'); }
  function scheduleDiskSync() {
    if (!dirHandle) return;
    if (syncDebounce) clearTimeout(syncDebounce);
    syncDebounce = setTimeout(writeOverridesToDisk, 500);
  }
  function updateSyncStatus() {
    const pending = overrides.task_toggles.length + overrides.deleted_tasks.length + overrides.archived.length + overrides.deleted.length;
    if (SERVER_MODE) {
      $syncStatus.textContent = I18N.sync_server;
      $syncStatus.classList.add('online');
      return;
    }
    if (dirHandle) { $syncStatus.textContent = I18N.sync_disk; $syncStatus.classList.add('online'); }
    else if (pending > 0) { $syncStatus.textContent = I18N.sync_local.replace('{}', pending); $syncStatus.classList.remove('online'); }
    else { $syncStatus.textContent = I18N.sync_idle; $syncStatus.classList.remove('online'); }
  }
  // In server mode the sync button is irrelevant (no FSA permission to grant).
  if (SERVER_MODE) {
    $syncBtn.style.display = 'none';
  } else {
    $syncBtn.addEventListener('click', connectDisk);
    if (!window.showDirectoryPicker) { $syncBtn.textContent = I18N.sync_download; }
  }
  function downloadPatch() {
    const payload = { version: 1, generated_at: new Date().toISOString(), overrides: overrides,
      archived_initiatives_full: overrides.archived.map(id => initById[id]).filter(Boolean) };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'mindmap-patch-' + Date.now() + '.json'; a.click();
    URL.revokeObjectURL(url); toast('已下载补丁');
  }
  updateSyncStatus();

  // ---------- Helper (mindmap --serve) ----------------------------------
  const $helperState = document.getElementById('helper-state');
  function helperBase() {
    if (SERVER_MODE) return SERVER_ORIGIN;        // same origin
    if (helperPort) return 'http://127.0.0.1:' + helperPort;
    return null;
  }
  async function pingHelper() {
    // In server mode, the same origin IS the helper. Mark online instantly.
    if (SERVER_MODE) {
      $helperState.textContent = I18N.helper_online.replace('{}', new URL(SERVER_ORIGIN).port || '80');
      $helperState.classList.add('online');
      helperPort = 'same-origin';
      return;
    }
    for (const port of HELPER_PORTS) {
      try {
        const r = await fetch('http://127.0.0.1:' + port + '/ping', { method: 'GET', mode: 'cors' });
        if (r.ok) {
          const j = await r.json().catch(() => ({}));
          if (j && j.service === 'claude-code-worktree') {
            helperPort = port;
            $helperState.textContent = I18N.helper_online.replace('{}', port);
            $helperState.classList.add('online');
            return;
          }
        }
      } catch (e) {}
    }
    $helperState.textContent = I18N.helper_offline;
    $helperState.classList.remove('online');
  }
  async function helperCall(action, payload) {
    const base = helperBase();
    if (!base) return { ok: false, reason: 'no-helper' };
    try {
      const r = await fetch(base + '/' + action, {
        method: 'POST', mode: 'cors',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
      });
      let body = {}; try { body = await r.json(); } catch (e) {}
      return { ok: r.ok, status: r.status, body: body };
    } catch (e) { return { ok: false, reason: 'network', error: e.message }; }
  }
  pingHelper();
  if (!SERVER_MODE) setInterval(pingHelper, 30000);

  // ---------- Data freshness — silent hot-refresh (server mode) ---------
  // When refresh.sh runs in the background, mindmap.json changes. We poll
  // /api/data every 8s and swap in the new data + re-render silently.
  // No banner, no reload — the page just updates in place. Scroll position
  // is preserved across re-renders.
  let lastGeneratedAt = DATA.generated_at || '';
  const $manualRefresh = document.getElementById('manual-refresh');
  const $stale = document.getElementById('data-stale');
  if ($stale) $stale.style.display = 'none';  // unused in silent mode

  async function pollAndApply() {
    if (!SERVER_MODE) return;
    try {
      const r = await fetch(SERVER_ORIGIN + '/api/data');
      if (!r.ok) return;
      const j = await r.json();
      const srvGen = j?.mindmap?.generated_at || '';
      if (!srvGen) return;
      // Also detect changes in the archive directory (file count proxy)
      const newArcCount = (j.archived || []).length;
      const oldArcCount = (ARCHIVED_PERSISTED || []).length;
      if (srvGen === lastGeneratedAt && newArcCount === oldArcCount) {
        return;  // nothing new
      }
      // Apply: swap data + re-render in place.
      applyFreshData(j);
    } catch (e) { /* server gone or transient */ }
  }

  function applyFreshData(payload) {
    const scrollY = window.scrollY;
    if (payload.mindmap) DATA = payload.mindmap;
    if (payload.locations && payload.locations.by_session_id) {
      LOCATIONS = payload.locations.by_session_id;
    } else if (payload.locations) {
      LOCATIONS = payload.locations;
    }
    ARCHIVED_PERSISTED = payload.archived || [];
    lastGeneratedAt = DATA.generated_at || lastGeneratedAt;
    rebuildIndex();
    render();
    // Preserve scroll
    window.scrollTo({ top: scrollY, behavior: 'instant' });
    // Subtle toast so user knows data refreshed (skip on first apply at boot)
    if (window.__ccwBooted) toast('数据已更新');
    window.__ccwBooted = true;
  }

  if (SERVER_MODE) {
    // First poll runs slightly delayed so the boot render isn't fighting it.
    setTimeout(pollAndApply, 3000);
    setInterval(pollAndApply, 8000);
  }

  // Manual AI refresh button (server mode wires to /api/refresh; file:// hides it)
  if (SERVER_MODE) {
    $manualRefresh.addEventListener('click', async () => {
      $manualRefresh.disabled = true;
      try {
        const r = await fetch(SERVER_ORIGIN + '/api/refresh', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true })
        });
        if (r.ok || r.status === 202) toast(I18N.refresh_started);
        else toast('refresh failed: ' + r.status);
      } catch (e) { toast('refresh failed: ' + e.message); }
      // Re-enable after a beat (refresh.sh takes ~30-120s)
      setTimeout(() => { $manualRefresh.disabled = false; }, 5000);
    });
  } else {
    $manualRefresh.style.display = 'none';
  }

  // ---------- Boot -------------------------------------------------------
  render();
})();
</script>
</body>
</html>
"""


def render_html(data: dict, L: dict, lang: str) -> str:
    generated_iso = data.get("generated_at", "")
    generated_age = humanize_age(generated_iso, L)
    locations = load_locations()
    archived_items = load_archived_items()
    i18n_for_js = {k: L[k] for k in L}

    # Pre-process: shorten cwds for display
    workspaces = []
    for w in (data.get("workspaces") or []):
        ws_copy = {
            "name": w.get("name"),
            "cwd": short_cwd(w.get("cwd")),
            "initiatives": [],
        }
        for i in (w.get("initiatives") or []):
            init_slim = {
                "id": i.get("id"),
                "name": i.get("name"),
                "status": i.get("status"),
                "summary": i.get("summary"),
                "progress": i.get("progress"),
                "tasks": i.get("tasks") or [],
                "sessions": i.get("sessions") or [],
                "linked_cwds": i.get("linked_cwds") or [],
                "last_activity_at": i.get("last_activity_at"),
            }
            if i.get("artifacts"):
                init_slim["artifacts"] = i["artifacts"]
            if i.get("blockers"):
                init_slim["blockers"] = i["blockers"]
            ws_copy["initiatives"].append(init_slim)
        workspaces.append(ws_copy)
    slim = {
        "schema_version": data.get("schema_version", 2),
        "generated_at": data.get("generated_at"),
        "workspaces": workspaces,
    }

    def json_for_script(obj):
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    out = HTML_TEMPLATE
    out = out.replace("__LANG__", lang)
    out = out.replace("__TITLE__", html_lib.escape(L["page_title"]))
    out = out.replace("__HEADER__", html_lib.escape(L["header"]))
    out = out.replace("__GENERATED__", html_lib.escape(f"{L['generated']} {generated_age}"))
    out = out.replace("__SYNC_IDLE__", html_lib.escape(L["sync_idle"]))
    out = out.replace("__SYNC_CONNECT__", html_lib.escape(L["sync_connect"]))
    out = out.replace("__FILTER_ALL__", html_lib.escape(L["filter_all"]))
    out = out.replace("__FILTER_ACTIVE__", html_lib.escape(L["filter_active"]))
    out = out.replace("__FILTER_PAUSED__", html_lib.escape(L["filter_paused"]))
    out = out.replace("__FILTER_DONE__", html_lib.escape(L["filter_done"]))
    out = out.replace("__FILTER_ARCHIVED__", html_lib.escape(L["filter_archived"]))
    out = out.replace("__SEARCH_PLACEHOLDER__", html_lib.escape(L["search_placeholder"]))
    out = out.replace("__TREE_VIEW__", html_lib.escape(L["tree_view"]))
    out = out.replace("__NAV_TITLE__", html_lib.escape(L["nav_title"]))
    out = out.replace("__DATA_STALE__", html_lib.escape(L["data_stale_banner"]))
    out = out.replace("__MANUAL_REFRESH__", html_lib.escape(L["manual_refresh"]))
    out = out.replace("__DATA_JSON__", json_for_script(slim))
    out = out.replace("__I18N_JSON__", json_for_script(i18n_for_js))
    out = out.replace("__LOCATIONS_JSON__", json_for_script(locations))
    out = out.replace("__ARCHIVED_JSON__", json_for_script(archived_items))
    return out


def main() -> int:
    if not MINDMAP_FILE.exists():
        print(f"No mindmap cache found at {MINDMAP_FILE}", file=sys.stderr)
        print("Run: bash bin/refresh.sh", file=sys.stderr)
        return 1
    data = json.loads(MINDMAP_FILE.read_text())
    lang = get_lang()
    L = LOCALE[lang]
    html = render_html(data, L, lang)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

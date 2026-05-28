#!/usr/bin/env python3
"""
Render cache/dashboard.json as a single-file dashboard HTML.

Layout: card-based, no third-party UI lib. Each initiative is a card
under its workspace section. Cards self-contain all actions (toggle task,
archive, delete, focus pane). Filter chips + keyword search at the top.

Persistence:
- Immediate: window.localStorage (instant in-browser feedback)
- Optional: File System Access API writes back to cache/ so the next AI
  refresh sees the user's edits.

Single-file output: cache/dashboard.html
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
LOCATIONS_FILE = REPO_ROOT / "cache" / "session_locations.json"
ARCHIVE_DIR = REPO_ROOT / "cache" / "archive"
OUTPUT_FILE = REPO_ROOT / "cache" / "dashboard.html"
PET_SPRITE_FILE = REPO_ROOT / "bin" / "assets" / "pet" / "cat-walk.png"


def _pet_data_url() -> str:
    """Encode the walking-cat spritesheet as a data: URL so it ships
    inline with the HTML (works in both static and server mode). See
    bin/assets/pet/README.md for asset provenance and license."""
    import base64
    try:
        b = PET_SPRITE_FILE.read_bytes()
        return "data:image/png;base64," + base64.b64encode(b).decode("ascii")
    except OSError:
        # If the asset is missing, return empty — CSS will gracefully
        # show no pet rather than a broken image.
        return ""


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
        "tier_cards_label": "工作卡片",
        "tier_chips_label": "小项",
        "thread_members_label": "包含",
        "thread_no_members": "无附属卡片",
        "chip_pending_tasks": "{} 项待办",
        "tasks_meta": "{} 个任务 · {} 已完成 · {} 已取消",
        "sessions_meta": "{} 个会话",
        "task_status_done": "已完成",
        "task_status_cancelled": "已取消",
        "task_cancel_action": "标记为已取消",
        "task_uncancel_action": "重新激活",
        "task_terminal_fold_show": "▶ 显示 {}",
        "task_terminal_fold_hide": "▼ 收起",
        "confirm_cancel_task": "将 \"{}\" 标记为已取消?\n该任务从待办列表移走,可以随时重新激活。",
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
        "confirm_delete_artifact": "从这张卡里移除 \"{}\" ?\n该 artifact 进入隐藏列表；即使 AI 在新 session 里再次提到也不会回来，除非你手动清理 user_overrides.json。",
        "btn_artifact_del": "从卡片移除",
        "btn_consolidate": "合并重复",
        "consolidate_progress": "正在分析重复项…",
        "consolidate_no_dups": "未发现明确的语义重复，任务列表已经干净。",
        "consolidate_preview_title": "合并预览",
        "consolidate_preview_hint": "确认后，这些任务将被标记为 cancelled（带 evidence 指向保留项）。整个动作走 user_overrides，不会触发 AI 重跑，随时可在 dashboard 上恢复。",
        "consolidate_keep_label": "保留",
        "consolidate_cancel_label": "标记 cancelled",
        "consolidate_apply": "应用合并",
        "consolidate_dismiss": "取消",
        "consolidate_error": "合并请求失败：{}",
        "consolidate_evidence_prefix": "duplicate of",
        "dlg_ok": "确定",
        "dlg_cancel": "取消",
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
        "lifecycle_paused": "Pipeline 已暂停 — 后台 AI 不再运行",
        "lifecycle_paused_reason_prefix": "原因:",
        "lifecycle_resume": "恢复",
        "lifecycle_resume_confirm": "恢复后,Stop hook 将再次触发 AI 流水线。继续?",
        "lifecycle_resumed_toast": "Pipeline 已恢复",
        "update_available": "claude-stray 有新版本",
        "update_versions_fmt": "{local} → {remote}",
        "update_now": "立刻升级",
        "update_dismiss": "今天先不",
        "update_in_progress": "正在升级…",
        "update_success_toast": "已升级到 {after}，重启 stray --serve 生效",
        "update_failed_toast": "升级失败：{err}",
        "archive_bucket_this_week": "本周归档",
        "archive_bucket_last_week": "上周归档",
        "archive_bucket_two_weeks_ago": "2 周前归档",
        "archive_bucket_older": "更早归档",
        "weekly_label": "本周回顾",
        "weekly_open_btn": "查看周报 ({})",
        "weekly_loading": "加载中…",
        "weekly_empty": "尚未生成,运行 mindmap --weekly-report 生成",
        "weekly_modal_title": "周报 — {}",
        "next_steps_label": "建议关注",
        "next_steps_empty": "暂无建议",
        "tip_label": "今日 tip",
        "tip_ticker_hint": "点一下听下一句",
        "tip_kind_work": "工作",
        "tip_kind_wisdom": "感悟",
        "tip_kind_rest": "休息",
        "tip_kind_curiosity": "知识",
        "tip_emoji_work": "🧑‍💻",
        "tip_emoji_wisdom": "🤔",
        "tip_emoji_rest": "☕",
        "tip_emoji_curiosity": "💡",
        "tip_lead_work": "嘿,顺手说一句:",
        "tip_lead_wisdom": "嗯…",
        "tip_lead_rest": "歇会儿?",
        "tip_lead_curiosity": "你知道吗:",
        "wellness_toast_prefix": "🌱 ",
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
        "tier_cards_label": "Cards",
        "tier_chips_label": "Quick items",
        "thread_members_label": "Contains",
        "thread_no_members": "No member cards",
        "chip_pending_tasks": "{} pending",
        "tasks_meta": "{} tasks · {} done · {} cancelled",
        "sessions_meta": "{} sessions",
        "task_status_done": "done",
        "task_status_cancelled": "cancelled",
        "task_cancel_action": "Mark cancelled",
        "task_uncancel_action": "Reactivate",
        "task_terminal_fold_show": "▶ Show {}",
        "task_terminal_fold_hide": "▼ Hide",
        "confirm_cancel_task": "Mark \"{}\" cancelled?\nMoves it out of the active list. You can reactivate it any time.",
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
        "confirm_delete_artifact": "Remove \"{}\" from this card?\nAdded to the hidden list; AI cannot resurrect it from future sessions until you clear user_overrides.json.",
        "btn_artifact_del": "Remove from card",
        "btn_consolidate": "Consolidate duplicates",
        "consolidate_progress": "Scanning for duplicates…",
        "consolidate_no_dups": "No clear semantic duplicates — the task list is already clean.",
        "consolidate_preview_title": "Consolidation preview",
        "consolidate_preview_hint": "On confirm, the listed tasks get marked cancelled (with evidence pointing at the survivor). Goes through user_overrides — no AI rerun, fully reversible from the dashboard.",
        "consolidate_keep_label": "Keep",
        "consolidate_cancel_label": "Cancel as duplicate",
        "consolidate_apply": "Apply consolidation",
        "consolidate_dismiss": "Cancel",
        "consolidate_error": "Consolidation failed: {}",
        "consolidate_evidence_prefix": "duplicate of",
        "dlg_ok": "OK",
        "dlg_cancel": "Cancel",
        "sync_idle": "not synced",
        "sync_local": "{} pending changes",
        "sync_disk": "saved to cache/",
        "sync_server": "auto-syncing via server",
        "sync_connect": "🔌 Grant cache/ access",
        "sync_connected": "✓ connected",
        "sync_download": "📥 Download patch",
        "sync_unsupported": "Browser lacks File System Access — using download fallback",
        "helper_offline": "Helper offline (run `stray --serve` for jump)",
        "helper_online": "✓ helper :{}",
        "data_stale_banner": "↻ Server has new data — click to load",
        "manual_refresh": "🔄 Run AI refresh",
        "lifecycle_paused": "Pipeline paused — background AI is off",
        "lifecycle_paused_reason_prefix": "Reason:",
        "lifecycle_resume": "Resume",
        "update_available": "claude-stray update available",
        "update_versions_fmt": "{local} → {remote}",
        "update_now": "Update now",
        "update_dismiss": "Not today",
        "update_in_progress": "Updating…",
        "update_success_toast": "Updated to {after} — restart `stray --serve` to load",
        "update_failed_toast": "Update failed: {err}",
        "lifecycle_resume_confirm": "Resume the pipeline? Stop hooks will start firing AI work again.",
        "lifecycle_resumed_toast": "Pipeline resumed",
        "archive_bucket_this_week": "Archived this week",
        "archive_bucket_last_week": "Archived last week",
        "archive_bucket_two_weeks_ago": "Archived 2 weeks ago",
        "archive_bucket_older": "Archived earlier",
        "weekly_label": "This week's recap",
        "weekly_open_btn": "Open weekly report ({})",
        "weekly_loading": "Loading…",
        "weekly_empty": "Not generated yet — run `stray --weekly-report`",
        "weekly_modal_title": "Weekly report — {}",
        "next_steps_label": "Suggested focus",
        "next_steps_empty": "No suggestions yet",
        "tip_label": "Tip of the day",
        "tip_ticker_hint": "Tap for the next one",
        "tip_kind_work": "Work",
        "tip_kind_wisdom": "Wisdom",
        "tip_kind_rest": "Rest",
        "tip_kind_curiosity": "Did you know",
        "tip_emoji_work": "🧑‍💻",
        "tip_emoji_wisdom": "🤔",
        "tip_emoji_rest": "☕",
        "tip_emoji_curiosity": "💡",
        "tip_lead_work": "Hey, quick one —",
        "tip_lead_wisdom": "Hmm…",
        "tip_lead_rest": "Psst, break?",
        "tip_lead_curiosity": "Did you know:",
        "wellness_toast_prefix": "🌱 ",
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

    These were physically removed from dashboard.json by the classifier but
    the full initiative payload is preserved on disk. The HTML needs them
    so the archive zone keeps showing items even after the AI refresh
    that consumed them.

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
/* DD-006 tips bubble — floats in the top-right of the cards area as
   a compact speech bubble. Emoji is the "speaker", balloon is the
   bubble body with a tail pointing back at the emoji. Click to cycle. */
.tips-bubble {
  /* Top-right empty band, fixed. Sits in the negative space between
     the toolbar (filter chips + search) and the first row of cards —
     a natural transition strip on-axis with the user's first glance
     when the page loads (top of Z-pattern). Doesn't overlap any
     existing chrome or card content. */
  position: fixed;
  top: 150px;
  right: 100px;
  z-index: 6;
  width: 320px;
  display: flex; align-items: flex-end; gap: 4px;
  padding: 0;
  cursor: pointer; user-select: none;
  background: transparent;
}
.tips-bubble[hidden] { display: none; }
.tips-bubble { cursor: grab; }
.tips-bubble.dragging { cursor: grabbing; }
.tips-bubble.dragging .tt-balloon { box-shadow: 0 6px 20px rgba(0,0,0,0.18); }
.tips-bubble .tt-source {
  display: inline-block; margin-left: 6px;
  text-decoration: none; font-size: 13px;
  color: var(--text-mute); opacity: 0.7;
  border-radius: 6px; padding: 0 4px;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}
.tips-bubble .tt-source[hidden] { display: none; }
.tips-bubble .tt-source:hover {
  opacity: 1; background: rgba(0,0,0,0.06);
  color: var(--text);
}
/* Pixel-art walking-cat companion. Sprite is a 432×60 sheet of 6
   frames (72×60 each), shipped inline as a data: URL — see
   bin/assets/pet/README.md for provenance. CSS `steps()` flips
   through frames for the walk cycle; `image-rendering: pixelated`
   keeps the art crisp at any zoom. */
.tips-bubble .tt-pet {
  flex-shrink: 0;
  width: 72px; height: 60px;
  background-image: url("__PET_DATA_URL__");
  background-repeat: no-repeat;
  background-position: 0 0;
  background-size: 432px 60px;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  animation: pet-walk 0.9s steps(6) infinite;
  transform-origin: bottom center;
  transition: transform 0.15s ease;
}
@keyframes pet-walk {
  from { background-position:    0 0; }
  to   { background-position: -432px 0; }
}
.tips-bubble:hover .tt-pet { transform: scale(1.1); }
.tips-bubble.cycling .tt-pet {
  /* Pause walk briefly + do a little hop when a new tip arrives. */
  animation: pet-hop 0.55s cubic-bezier(0.34, 1.56, 0.64, 1),
             pet-walk 0.9s steps(6) infinite 0.55s;
}
@keyframes pet-hop {
  0%   { transform: translateY(0)    scale(1); }
  40%  { transform: translateY(-10px) scale(1.05); }
  70%  { transform: translateY(0)    scale(1, 0.95); }
  100% { transform: translateY(0)    scale(1); }
}
.tips-bubble .tt-balloon {
  position: relative;
  flex: 1; min-width: 0;
  padding: 10px 14px;
  background: white;
  border-radius: 16px 16px 16px 4px;   /* asymmetric — tail-side flat */
  box-shadow: 0 4px 14px rgba(0,0,0,0.10), 0 1px 3px rgba(0,0,0,0.05);
  font-size: 13px; line-height: 1.5;
  color: var(--text);
  word-break: break-word;
}
/* Tail pointing down-left toward the emoji avatar. */
.tips-bubble .tt-balloon::before {
  content: "";
  position: absolute;
  bottom: 0; left: -8px;
  width: 0; height: 0;
  border-style: solid;
  border-width: 0 0 12px 12px;
  border-color: transparent transparent white transparent;
  filter: drop-shadow(-1px 1px 1px rgba(0,0,0,0.04));
}
.tips-bubble .tt-lead {
  display: block; margin-bottom: 2px;
  font-weight: 600; color: var(--text-dim);
  font-size: 12px; letter-spacing: 0.02em;
}
.tips-bubble .tt-text { display: block; }
/* Per-kind tint — same color used on balloon body and tail. */
.tips-bubble[data-kind="work"]      .tt-balloon,
.tips-bubble[data-kind="work"]      .tt-balloon::before { background: #eef2ff; }
.tips-bubble[data-kind="work"]      .tt-balloon::before { border-bottom-color: #eef2ff; }
.tips-bubble[data-kind="work"]      .tt-lead { color: #4338ca; }
.tips-bubble[data-kind="wisdom"]    .tt-balloon,
.tips-bubble[data-kind="wisdom"]    .tt-balloon::before { background: #fef9e0; }
.tips-bubble[data-kind="wisdom"]    .tt-balloon::before { border-bottom-color: #fef9e0; }
.tips-bubble[data-kind="wisdom"]    .tt-lead { color: #92400e; }
.tips-bubble[data-kind="rest"]      .tt-balloon,
.tips-bubble[data-kind="rest"]      .tt-balloon::before { background: #e6f9ee; }
.tips-bubble[data-kind="rest"]      .tt-balloon::before { border-bottom-color: #e6f9ee; }
.tips-bubble[data-kind="rest"]      .tt-lead { color: #065f46; }
.tips-bubble[data-kind="curiosity"] .tt-balloon,
.tips-bubble[data-kind="curiosity"] .tt-balloon::before { background: #fdeef5; }
.tips-bubble[data-kind="curiosity"] .tt-balloon::before { border-bottom-color: #fdeef5; }
.tips-bubble[data-kind="curiosity"] .tt-lead { color: #9d174d; }
.tips-bubble.cycling .tt-balloon { animation: tipPop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1); }
@keyframes tipPop {
  0%   { opacity: 0.4; transform: scale(0.94); }
  100% { opacity: 1;   transform: scale(1); }
}
/* On narrow viewports, shrink so it doesn't cover too much content. */
@media (max-width: 900px) {
  .tips-bubble { width: 240px; right: 14px; top: 96px; }
}
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
  align-items: start;
}

/* Archive zone weekly buckets — one section per week-relative group. */
section.archive-zone .archive-bucket { margin-top: 12px; }
section.archive-zone .archive-bucket:first-of-type { margin-top: 0; }
section.archive-zone .archive-bucket-head {
  display: flex; align-items: baseline; gap: 8px;
  margin: 4px 0 8px;
  font-size: 12px; color: var(--text-mute);
  cursor: pointer; user-select: none;
}
section.archive-zone .archive-bucket-head:hover .bucket-label { color: var(--text); }
section.archive-zone .archive-bucket-head .bucket-toggle {
  font-size: 10px; line-height: 1; transition: transform 0.12s;
  display: inline-block; width: 10px; color: var(--text-mute);
}
section.archive-zone .archive-bucket.collapsed .bucket-toggle { transform: rotate(-90deg); }
section.archive-zone .archive-bucket.collapsed .archive-body { display: none; }
section.archive-zone .archive-bucket-head .bucket-label {
  font-weight: 500;
}
section.archive-zone .archive-bucket-head .bucket-count {
  background: var(--bg-mute, rgba(0,0,0,0.05));
  padding: 0 8px; border-radius: 999px; font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.archive-zone .from-ws .archive-when {
  color: var(--text-mute); font-variant-numeric: tabular-nums;
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

/* DD-014: ws-body is now a vertical stack of three tiers.
   - tier-threads: poker-deck visualization for thread initiatives
   - tier-cards:   the existing card grid for card initiatives
   - tier-chips:   compact horizontal-flow chips for chip initiatives
   Empty tiers are omitted from the DOM entirely, so single-tier
   workspaces look identical to the pre-DD-014 layout. */
div.ws-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.tier {
  position: relative;
}
.tier-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 14px;
  align-items: start;
}

/* ---------- Threads (poker decks) ---------- */
.tier-threads {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 14px;
  align-items: start;
}
.thread-deck {
  position: relative;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 18px 14px;
  box-shadow: var(--shadow);
  transition: transform 0.25s cubic-bezier(.2,.7,.3,1.3),
              box-shadow 0.25s, border-color 0.2s;
  cursor: pointer;
  isolation: isolate;
}
.thread-deck::before,
.thread-deck::after {
  /* The two stacked-paper backplates that give the "deck of cards"
     illusion. Both sit behind the deck and offset down-right. On hover
     they fan out further so the deck "spreads." */
  content: "";
  position: absolute;
  inset: 0;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  z-index: -1;
  transition: transform 0.25s cubic-bezier(.2,.7,.3,1.3),
              box-shadow 0.25s;
  box-shadow: var(--shadow);
}
.thread-deck::before { transform: translate(6px, 6px) rotate(1.2deg); opacity: 0.85; }
.thread-deck::after  { transform: translate(12px, 12px) rotate(2.4deg); opacity: 0.7; }
.thread-deck:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
  border-color: var(--border-hover);
}
.thread-deck:hover::before { transform: translate(8px, 8px) rotate(1.6deg); }
.thread-deck:hover::after  { transform: translate(16px, 16px) rotate(3.2deg); }
.thread-deck.expanded::before,
.thread-deck.expanded::after { display: none; }
.thread-deck-head {
  display: flex; align-items: flex-start; gap: 8px;
}
.thread-deck-head .thread-icon {
  font-size: 13px; line-height: 1.5;
}
.thread-deck-head h3 {
  font-size: 15px; font-weight: 600; margin: 0; flex: 1;
  line-height: 1.4; word-break: break-word;
}
.thread-deck-summary {
  margin: 8px 0 0; color: var(--text-dim);
  font-size: 13px; line-height: 1.55;
}
.thread-deck-members {
  margin-top: 12px;
  display: flex; flex-wrap: wrap; gap: 6px;
  font-size: 12px; color: var(--text-mute);
}
.thread-deck-member-pill {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 10px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.thread-deck-member-pill:hover {
  background: var(--card-bg);
  border-color: var(--border-hover);
  color: var(--text);
}
.thread-deck-member-pill .pill-dot {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; margin-right: 5px; vertical-align: middle;
}
.thread-deck-foot {
  margin-top: 12px;
  display: flex; gap: 10px; font-size: 11px;
  color: var(--text-mute);
}
.thread-deck-foot .deck-stat {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 8px;
}
.thread-deck.expanded {
  /* expanded mode: deck flattens into its own column. The members
     pills become a clickable list. */
  transform: translateY(0);
  box-shadow: var(--shadow-hover);
  border-color: var(--accent);
}
.thread-deck.expanded .thread-deck-foot .deck-stat.deck-toggle::after {
  content: " ▴";
}
.thread-deck-foot .deck-stat.deck-toggle::after { content: " ▾"; }

/* ---------- Chips (compact tags for tiny initiatives) ---------- */
.tier-chips {
  display: flex; flex-wrap: wrap;
  gap: 6px;
  /* A subtle "ground line" under the chips to mark them as the
     low-emphasis tier without resorting to a heavy section divider. */
  padding-top: 2px;
}
.tier-chips .tier-chips-label {
  flex-basis: 100%;
  font-size: 11px; color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 2px;
}
.chip-card {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px 4px 10px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--text);
  cursor: pointer;
  max-width: 320px;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
.chip-card:hover {
  background: var(--card-bg);
  border-color: var(--border-hover);
  transform: translateY(-1px);
}
.chip-card.hidden { display: none; }
.chip-card .chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
.chip-card .chip-dot.active { background: var(--green); }
.chip-card .chip-dot.paused { background: var(--amber); }
.chip-card .chip-dot.done   { background: var(--slate); }
.chip-card .chip-dot.archived { background: var(--text-mute); }
.chip-card .chip-name {
  font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.chip-card .chip-meta {
  font-size: 10px; color: var(--text-mute);
  display: inline-flex; gap: 4px; align-items: center;
}
.chip-card .chip-task-badge {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0 6px;
  font-size: 10px;
  color: var(--text-dim);
}
.chip-card .chip-blocker {
  color: var(--red); font-size: 11px;
}
.chip-card.has-pending {
  border-color: var(--accent);
  background: linear-gradient(to right, rgba(59,130,246,0.06), transparent);
}

/* Tier label (only shown when tier-cards is below tier-threads or
   above tier-chips, to clarify the visual hierarchy). */
.tier-divider {
  font-size: 11px; color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 4px;
  display: flex; align-items: center; gap: 8px;
}
.tier-divider::after {
  content: ""; flex: 1; height: 1px; background: var(--border);
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
/* DD-006 derived sidebar widgets — server-mode only (payloads come
   from cache/derived/, fetched via /api/derived). */
.derived-widgets { margin-top: 16px; display: flex; flex-direction: column; gap: 10px; }
.derived-widget {
  background: white; border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 12px;
  font-size: 12px;
}
.derived-widget .dw-head {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 6px;
  font-weight: 500; color: var(--text);
}
.derived-widget .dw-label { font-size: 12px; }
.derived-widget .dw-body { color: var(--text-dim); line-height: 1.55; }
.derived-widget .dw-link {
  background: var(--bg, #f7f8fa); border: none;
  color: var(--accent, #2563eb); cursor: pointer;
  font-size: 12px; padding: 4px 0; text-align: left; width: 100%;
}
.derived-widget .dw-link:hover { text-decoration: underline; }
.derived-widget ul.dw-list { list-style: none; margin: 0; padding: 0; }
.derived-widget ul.dw-list li {
  padding: 6px 0; border-top: 1px dashed var(--border);
  cursor: pointer;
}
.derived-widget ul.dw-list li:first-child { border-top: 0; }
.derived-widget ul.dw-list li:hover .dw-init { color: var(--accent, #2563eb); }
.derived-widget .dw-init { font-weight: 500; color: var(--text); }
.derived-widget .dw-init-ws { font-size: 11px; color: var(--text-mute); }
.derived-widget .dw-reason { color: var(--text-dim); font-size: 11px; margin-top: 2px; }

/* Weekly report rendered modal */
.weekly-modal { max-width: 860px; }
.weekly-modal .weekly-md {
  font-size: 14px; line-height: 1.75; color: var(--text);
}
.weekly-modal .weekly-md > h2,
.weekly-modal .weekly-md > h3 {
  margin: 24px 0 8px; padding-top: 16px;
  border-top: 1px solid var(--border);
  font-weight: 600;
}
.weekly-modal .weekly-md > h2:first-child,
.weekly-modal .weekly-md > h3:first-child {
  border-top: 0; padding-top: 0; margin-top: 0;
}
.weekly-modal .weekly-md h2 { font-size: 16px; }
.weekly-modal .weekly-md h3 { font-size: 14px; color: var(--text); }
.weekly-modal .weekly-md p { margin: 8px 0; }
.weekly-modal .weekly-md ul {
  padding-left: 22px; margin: 8px 0;
}
.weekly-modal .weekly-md li { margin: 4px 0; }
.weekly-modal .weekly-md strong { font-weight: 600; color: var(--text); }
.weekly-modal .weekly-md code {
  background: var(--bg, #f4f5f7); padding: 1px 6px;
  border-radius: 4px; font-size: 12.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.weekly-modal .weekly-md a {
  color: var(--accent, #2563eb); text-decoration: none;
}
.weekly-modal .weekly-md a:hover { text-decoration: underline; }

/* Lifecycle pause banner (DD-005). Stays at top of viewport when
   pipeline is paused; resume button is only wired in server mode. */
.lifecycle-banner {
  position: sticky; top: 0; z-index: 900;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 24px;
  background: var(--red-bg, #fef2f2);
  border-bottom: 2px solid var(--red, #dc2626);
  color: var(--red, #b91c1c);
  font-size: 13px;
}
.lifecycle-banner[hidden] { display: none; }
.lifecycle-banner .lb-icon { font-size: 16px; }
.lifecycle-banner .lb-text { display: flex; flex-direction: column; gap: 2px; }
.lifecycle-banner .lb-title { font-weight: 600; }
.lifecycle-banner .lb-reason { font-size: 12px; color: var(--text-dim); }
.lifecycle-banner .lb-reason:empty { display: none; }
.lifecycle-banner .lb-grow { flex: 1; }
.lifecycle-banner .lb-resume {
  background: var(--red, #dc2626); color: white;
  border: none; padding: 6px 16px; border-radius: 6px;
  font-size: 13px; cursor: pointer; font-weight: 500;
}
.lifecycle-banner .lb-resume:hover { filter: brightness(1.07); }

/* Update-available banner — same shape as lifecycle banner but green */
.update-banner {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px;
  background: var(--green-bg); color: var(--green);
  border-bottom: 1px solid var(--green);
  font-size: 13px;
}
.update-banner[hidden] { display: none; }
.update-banner .ub-icon { font-size: 16px; }
.update-banner .ub-text { display: flex; flex-direction: column; gap: 2px; }
.update-banner .ub-title { font-weight: 600; }
.update-banner .ub-versions {
  font-size: 12px; color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.update-banner .ub-versions:empty { display: none; }
.update-banner .ub-grow { flex: 1; }
.update-banner .ub-apply {
  background: var(--green); color: white;
  border: none; padding: 6px 12px; border-radius: 4px;
  font-size: 12px; font-weight: 600; cursor: pointer;
}
.update-banner .ub-apply:hover { filter: brightness(1.07); }
.update-banner .ub-apply:disabled { opacity: 0.6; cursor: wait; }
.update-banner .ub-dismiss {
  background: transparent; border: 1px solid transparent;
  color: var(--text-mute); font-size: 14px; line-height: 1;
  padding: 4px 8px; border-radius: 3px; cursor: pointer;
}
.update-banner .ub-dismiss:hover { color: var(--text); }
.lifecycle-banner .lb-resume[disabled] { opacity: 0.5; cursor: wait; }

.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: flex-start; justify-content: center;
  z-index: 1000;
  padding: 8vh 16px;
}
/* Custom confirm dialog — used in place of window.confirm() so the
   browser's per-origin "block dialogs" setting can't make our buttons
   look broken. */
.confirm-overlay { align-items: center; padding: 16px; z-index: 1100; }
.confirm-box {
  background: white; border-radius: 10px; padding: 22px 24px 18px;
  max-width: 460px; width: 100%;
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
}
.confirm-box .confirm-msg {
  white-space: pre-wrap; font-size: 14px; line-height: 1.55;
  color: var(--text); margin-bottom: 18px;
}
.confirm-box .confirm-actions {
  display: flex; gap: 10px; justify-content: flex-end;
}
.confirm-box .confirm-actions button {
  background: var(--bg); border: 1px solid var(--border, #ddd);
  padding: 7px 18px; border-radius: 6px; cursor: pointer;
  font-size: 13px; color: var(--text);
}
.confirm-box .confirm-actions button:hover { background: var(--bg-mute, #f3f3f3); }
.confirm-box .confirm-actions button.confirm-ok {
  border-color: transparent; background: var(--accent, #2563eb); color: white;
}
.confirm-box .confirm-actions button.confirm-ok.danger {
  background: var(--red, #dc2626);
}
.confirm-box .confirm-actions button.confirm-ok:hover { filter: brightness(1.07); }
.confirm-box .confirm-actions button:focus { outline: 2px solid var(--accent, #2563eb); outline-offset: 1px; }
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
.modal-section ul.modal-artifacts-list li button.art-del {
  background: transparent; border: 1px solid transparent; color: var(--text-mute);
  font-size: 13px; line-height: 1; padding: 2px 6px; border-radius: 3px;
  cursor: pointer; opacity: 0; transition: opacity 0.12s, color 0.12s, border-color 0.12s;
}
.modal-section ul.modal-artifacts-list li:hover button.art-del { opacity: 1; }
.modal-section ul.modal-artifacts-list li button.art-del:hover {
  color: var(--red); border-color: var(--red);
}
.modal-section p.modal-empty { margin: 0; color: var(--text-mute); font-size: 12px; }

/* Consolidate-duplicates preview ----------------------------------- */
.modal.consolidate-modal { max-width: 720px; }
.modal.consolidate-modal .consolidate-hint {
  margin: 0 0 16px; padding: 10px 12px;
  background: var(--bg-mute, rgba(0,0,0,0.04));
  border-radius: 4px;
  font-size: 12px; line-height: 1.5; color: var(--text-dim);
}
.consolidate-group {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px; margin-bottom: 10px;
}
.consolidate-keep {
  display: flex; gap: 8px; align-items: baseline;
  margin-bottom: 6px; padding-bottom: 6px;
  border-bottom: 1px dashed var(--border);
}
.consolidate-keep .cg-label {
  font-size: 10px; color: var(--green);
  background: var(--green-bg);
  padding: 2px 6px; border-radius: 3px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
}
.consolidate-keep .cg-title { font-weight: 500; flex: 1; }
ul.consolidate-cancels {
  list-style: none; margin: 0; padding: 0;
}
ul.consolidate-cancels li {
  display: flex; gap: 8px; align-items: baseline;
  padding: 4px 0; font-size: 13px;
}
ul.consolidate-cancels li .cc-mark { color: var(--red); width: 14px; }
ul.consolidate-cancels li .cc-title {
  flex: 1; text-decoration: line-through; color: var(--text-dim);
}
ul.consolidate-cancels li .cc-reason {
  font-size: 11px; color: var(--text-mute);
  background: var(--bg-mute, rgba(0,0,0,0.04));
  padding: 1px 6px; border-radius: 3px;
}
.consolidate-actions {
  display: flex; gap: 8px; justify-content: flex-end;
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--border);
}
.consolidate-actions button {
  font-family: inherit; font-size: 13px;
  padding: 6px 14px; border-radius: 4px;
  border: 1px solid var(--border); background: transparent;
  color: var(--text); cursor: pointer;
}
.consolidate-actions button:hover { background: var(--bg); }
.consolidate-actions button.primary {
  background: var(--accent); color: white; border-color: var(--accent);
}
.consolidate-actions button.primary:hover { filter: brightness(0.95); }

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
ul.tasks-list li.task[data-status="done"] .task-title,
ul.tasks-list li.task[data-status="cancelled"] .task-title {
  text-decoration: line-through; color: var(--text-mute);
}
ul.tasks-list li.task .task-status-icon {
  width: 16px; flex-shrink: 0; text-align: center;
  font-weight: 600; line-height: 1.45; margin-top: 1px;
}
ul.tasks-list li.task[data-status="done"] .task-status-icon { color: var(--green, #1f7a3b); }
ul.tasks-list li.task[data-status="cancelled"] .task-status-icon { color: var(--text-mute); }
ul.tasks-list li.task .task-del,
ul.tasks-list li.task .task-cancel,
ul.tasks-list li.task .task-reactivate {
  background: none; border: none; cursor: pointer; padding: 0 6px;
  color: var(--text-mute); opacity: 0; font-size: 13px; line-height: 1;
}
ul.tasks-list li.task:hover .task-del,
ul.tasks-list li.task:hover .task-cancel,
ul.tasks-list li.task:hover .task-reactivate { opacity: 1; }
ul.tasks-list li.task .task-del:hover { color: var(--red); }
ul.tasks-list li.task .task-cancel:hover,
ul.tasks-list li.task .task-reactivate:hover { color: var(--accent); }
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

<!-- Pipeline lifecycle banner (DD-005). Hidden by default; JS shows it
     when DATA.lifecycle.paused is true. Visible to both static and
     server modes; the resume button is server-mode only. -->
<div class="lifecycle-banner" id="lifecycle-banner" hidden>
  <span class="lb-icon">⏸</span>
  <span class="lb-text">
    <strong class="lb-title">__LIFECYCLE_PAUSED__</strong>
    <span class="lb-reason" id="lb-reason"></span>
  </span>
  <span class="lb-grow"></span>
  <button class="lb-resume" id="lb-resume" type="button">__LIFECYCLE_RESUME__</button>
</div>

<!-- Update-available banner. Polled from /api/version on a 24h cadence
     (matches the server-side check). Hidden until JS sees `behind: true`. -->
<div class="update-banner" id="update-banner" hidden>
  <span class="ub-icon">✨</span>
  <span class="ub-text">
    <strong class="ub-title">__UPDATE_AVAILABLE__</strong>
    <span class="ub-versions" id="ub-versions"></span>
  </span>
  <span class="ub-grow"></span>
  <button class="ub-apply" id="ub-apply" type="button">__UPDATE_NOW__</button>
  <button class="ub-dismiss" id="ub-dismiss" type="button" title="__UPDATE_DISMISS__">✕</button>
</div>

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

<!-- DD-006 tips bubble — playful speech-bubble. Click to cycle, drag to move.
     Populated by loadDerived(); hidden until at least one tip arrives.
     #tips-ticker id retained because JS references it.
     The walking pixel cat (CC0, see bin/assets/pet/README.md) sits to
     the left of the balloon — its emoji role is decorative; per-kind
     variation lives in the bubble color + lead text. -->
<div class="tips-bubble" id="tips-ticker" hidden title="__TIP_TICKER_HINT__">
  <div class="tt-pet" id="tt-kind" aria-hidden="true"></div>
  <div class="tt-balloon">
    <span class="tt-lead" id="tt-lead"></span>
    <span class="tt-text" id="tt-text"></span>
    <a class="tt-source" id="tt-source" target="_blank" rel="noopener noreferrer"
       hidden title="查看来源 · open source link">↗</a>
  </div>
</div>

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
    <!-- DD-006 derived widgets — only shown in server mode (the
         payloads are fetched from cache/derived/). -->
    <div class="derived-widgets" id="derived-widgets" hidden>
      <div class="derived-widget" id="dw-weekly" hidden>
        <div class="dw-head">📋 <span class="dw-label">__WEEKLY_LABEL__</span></div>
        <button class="dw-link" id="dw-weekly-btn" type="button"></button>
      </div>
      <div class="derived-widget" id="dw-next" hidden>
        <div class="dw-head">🎯 <span class="dw-label">__NEXT_STEPS_LABEL__</span></div>
        <ul class="dw-list" id="dw-next-list"></ul>
      </div>
    </div>
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
  // dashboard.json but we keep them visible in the archive zone here.
  let ARCHIVED_PERSISTED = JSON.parse(document.getElementById('archived-data').textContent);
  // Lifecycle state (DD-005). Embedded at render time so static mode
  // reflects pause state on first paint; server mode updates it on
  // every /api/data poll.
  let LIFECYCLE = DATA.lifecycle || { paused: false };
  const STORAGE_KEY = 'claude-code-worktree:overrides:v1';
  const COLLAPSE_KEY = 'claude-code-worktree:ws-collapsed:v1';
  const FILTER_KEY = 'claude-code-worktree:filter:v1';
  const HELPER_PORTS = [9876, 9877, 9878];

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
    // hidden_artifacts: [{init_id, key, at}]. Persistent suppression list
    // — keeps a user-deleted MR/PR/etc. off the card across refreshes
    // even when Layer 1 keeps re-emitting it from session frontmatter.
    return { task_toggles: [], archived: [], deleted: [], deleted_tasks: [],
             hidden_artifacts: [] };
  }
  // Keep in sync with Python's artifact_key() in bin/classify.py.
  // Precedence: url → (type, ref_id) → (type, title).
  function artifactKey(a) {
    if (!a || typeof a !== 'object') return null;
    const url = (a.url || '').trim();
    if (url.startsWith('http://') || url.startsWith('https://')) {
      return 'url::' + url;
    }
    const typ = (a.type || '').trim().toLowerCase();
    const ref = String(a.ref_id == null ? '' : a.ref_id).trim();
    if (typ && ref) return 'tid::' + typ + '::' + ref;
    const title = (a.title || '').trim();
    if (typ && title) return 'ttl::' + typ + '::' + title;
    return null;
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

  // Per-bucket collapse state for the archive zone. Defaults so that
  // 本周 (bucket idx 0) is expanded and 上周 / 2 周前 / 更早 are
  // collapsed — the user only cares about recent archive activity by
  // default but can drill into older weeks on demand.
  const ARCHIVE_BUCKET_KEY = 'claude-code-worktree:archive-buckets:v1';
  function loadArchiveBuckets() {
    try { return new Set(JSON.parse(localStorage.getItem(ARCHIVE_BUCKET_KEY) || 'null')); }
    catch (e) { return null; }
  }
  function saveArchiveBuckets() {
    localStorage.setItem(ARCHIVE_BUCKET_KEY,
                          JSON.stringify([...collapsedArchiveBuckets]));
  }
  // Keys: 'b0', 'b1', 'b2', 'b3' (matching bucket index).
  // null on first load means "use defaults" — collapse everything
  // except 本周.
  const _persisted = loadArchiveBuckets();
  const collapsedArchiveBuckets = _persisted !== null
    ? _persisted
    : new Set(['b1', 'b2', 'b3']);

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
        archived_at: entry.archived_at || null,   // for weekly grouping
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
      if (!t) continue;
      // DD-011: prefer `status`. Pre-DD-011 toggles use `done: bool`.
      if (tt.status === 'pending' || tt.status === 'done' || tt.status === 'cancelled') {
        t.status = tt.status;
      } else if ('done' in tt) {
        t.status = tt.done ? 'done' : 'pending';
      }
      // Keep legacy `done` aligned for any older code reading it.
      t.done = (t.status === 'done');
    }
    init.tasks = (init.tasks || []).filter(t => !overrides.deleted_tasks.some(dt => dt.init_id === initId && dt.task_title === t.title));
    // Filter artifacts hidden by the user. classify.py applies the same
    // filter server-side on the next refresh; we apply it here so the UI
    // reflects the delete instantly without waiting for an AI round-trip.
    if (Array.isArray(init.artifacts) && overrides.hidden_artifacts.length) {
      const hiddenKeys = new Set(
        overrides.hidden_artifacts
          .filter(h => h && h.init_id === initId)
          .map(h => h.key)
      );
      if (hiddenKeys.size) {
        init.artifacts = init.artifacts.filter(a => {
          const k = artifactKey(a);
          return !(k && hiddenKeys.has(k));
        });
      }
    }
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

  // Archive zone weekly bucketing (DD-006-anchor for weekly report too).
  // Group archived entries by ISO week relative to "this week":
  //   0 → 本周, 1 → 上周, 2 → 2 周前, ≥3 → 更早.
  // "This week" starts Monday in the user's local time. Entries with no
  // archived_at fall into 更早 (oldest bucket).
  function _mondayOfWeek(d) {
    const date = new Date(d);
    const day = date.getDay();   // 0=Sun, 1=Mon, ..., 6=Sat
    const diff = day === 0 ? -6 : (1 - day);
    date.setDate(date.getDate() + diff);
    date.setHours(0, 0, 0, 0);
    return date;
  }

  function _weekBucketIndex(archivedAt, now) {
    if (!archivedAt) return 3;
    const ad = new Date(archivedAt);
    if (isNaN(ad.getTime())) return 3;
    const weeksAgo = Math.round(
      (_mondayOfWeek(now) - _mondayOfWeek(ad)) / (7 * 86400000)
    );
    if (weeksAgo <= 0) return 0;
    if (weeksAgo === 1) return 1;
    if (weeksAgo === 2) return 2;
    return 3;
  }

  function groupArchivedByWeekBucket(list) {
    const now = new Date();
    const buckets = [
      { label: I18N.archive_bucket_this_week,     entries: [] },
      { label: I18N.archive_bucket_last_week,     entries: [] },
      { label: I18N.archive_bucket_two_weeks_ago, entries: [] },
      { label: I18N.archive_bucket_older,         entries: [] },
    ];
    for (const e of list) {
      buckets[_weekBucketIndex(e.archived_at, now)].entries.push(e);
    }
    for (const b of buckets) {
      b.entries.sort((a, b) =>
        (b.archived_at || '').localeCompare(a.archived_at || ''));
    }
    return buckets;
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
    const archivedList = []; // [{ws_name, ws_idx, init, archived_at}]
    const seenInArchive = new Set();

    // Lookup table from ARCHIVED_PERSISTED so the live-dashboard loop
    // can use the *actual* archive timestamp (when the user clicked
    // archive, or when classify swept the card) instead of falling back
    // to last_activity_at — which buckets a card archived today but
    // last touched 2 weeks ago into "2 weeks ago", confusing everyone.
    const archivedAtById = {};
    for (const entry of (ARCHIVED_PERSISTED || [])) {
      if (entry && entry.init && entry.init.id) {
        archivedAtById[entry.init.id] = entry.archived_at || '';
      }
    }

    workspaces.forEach((ws, wsIdx) => {
      // Split: archived inits get peeled off into archivedList
      const liveInits = [];
      for (const init of (ws.initiatives || [])) {
        if (isDeleted(init.id)) continue;
        if (effectiveStatus(init.id) === 'archived') {
          // Prefer the persisted archived_at (correct user/sweep
          // timestamp). Fall back to last_activity_at only when no
          // persisted record exists — that case still happens for
          // AI-status=archived items that haven't been swept to disk.
          archivedList.push({
            ws_name: ws.name, ws_idx: wsIdx, init: init,
            archived_at: archivedAtById[init.id] || init.last_activity_at || ''
          });
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

      // DD-014: split live initiatives into thread / card / chip tiers.
      // Cards/chips whose `parent_thread_id` matches a thread in this
      // workspace are folded INTO that thread's deck as member pills;
      // they don't also appear in the standalone card/chip tier. Orphan
      // cards/chips (no parent or parent missing) render as standalone.
      const threads = [];
      const cards = [];
      const chips = [];
      for (const init of liveInits) {
        const lvl = init.level || 'card';
        if (lvl === 'thread') threads.push(init);
        else if (lvl === 'chip') chips.push(init);
        else cards.push(init);
      }
      const threadById = {};
      for (const t of threads) threadById[t.id] = t;

      const orphanCards = [];
      const orphanChips = [];
      const childrenByThread = {};
      const pushChild = (init) => {
        const p = init.parent_thread_id;
        if (p && threadById[p]) {
          (childrenByThread[p] = childrenByThread[p] || []).push(init);
        } else {
          ((init.level || 'card') === 'chip' ? orphanChips : orphanCards).push(init);
        }
      };
      for (const c of cards) pushChild(c);
      for (const c of chips) pushChild(c);

      // Tier 1: threads (always first when present).
      if (threads.length) {
        const tier = document.createElement('div');
        tier.className = 'tier tier-threads';
        for (const t of threads) {
          tier.appendChild(renderThreadDeck(t, childrenByThread[t.id] || []));
        }
        wsBody.appendChild(tier);
      }

      // Tier 2: standalone cards. If both threads and cards exist, add a
      // visual divider so the eye knows it's a different tier.
      if (orphanCards.length) {
        if (threads.length) {
          const divider = document.createElement('div');
          divider.className = 'tier-divider';
          divider.textContent = I18N.tier_cards_label || 'Cards';
          wsBody.appendChild(divider);
        }
        const tier = document.createElement('div');
        tier.className = 'tier tier-cards';
        for (const c of orphanCards) tier.appendChild(renderCard(c.id));
        wsBody.appendChild(tier);
      }

      // Tier 3: chips. Always last; tiny visual label so first-time
      // users understand the chip row isn't a list of broken cards.
      if (orphanChips.length) {
        const tier = document.createElement('div');
        tier.className = 'tier tier-chips';
        const lbl = document.createElement('div');
        lbl.className = 'tier-chips-label';
        lbl.textContent = (I18N.tier_chips_label || 'Quick items') +
          ' · ' + orphanChips.length;
        tier.appendChild(lbl);
        for (const c of orphanChips) tier.appendChild(renderChip(c));
        wsBody.appendChild(tier);
      }

      wsSec.appendChild(wsBody);
      board.appendChild(wsSec);
    });

    // Also pull in items persisted to cache/archive/ (already swept from
    // dashboard.json by the classifier). They are in initById tagged as `persisted`.
    // Persisted (user-archived to disk) entries already carry
    // entry.archived_at from cache/archive/<ws>/<id>.json. Merge them
    // into archivedList here, preserving that timestamp for grouping.
    for (const id in initById) {
      if (seenInArchive.has(id) || isDeleted(id)) continue;
      const rec = initById[id];
      if (rec.persisted) {
        archivedList.push({
          ws_name: rec.ws_name, ws_idx: -1, init: rec.init,
          archived_at: rec.archived_at || rec.init.last_activity_at || ''
        });
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

      // Group archived entries by ISO-week bucket relative to current
      // week: 本周 / 上周 / 2 周前 / 更早. Each bucket renders as its
      // own .archive-bucket section so users can scan a timeline of
      // what got shelved when. archived_at is preferred; fall back to
      // last_activity_at for AI-archived entries.
      const buckets = groupArchivedByWeekBucket(archivedList);
      buckets.forEach((bucket, bIdx) => {
        if (!bucket.entries.length) return;
        const bucketKey = 'b' + bIdx;
        const bCollapsed = collapsedArchiveBuckets.has(bucketKey);
        const bSec = document.createElement('div');
        bSec.className = 'archive-bucket' + (bCollapsed ? ' collapsed' : '');
        const bHead = document.createElement('div');
        bHead.className = 'archive-bucket-head';
        bHead.innerHTML =
          '<span class="bucket-toggle">▾</span>' +
          '<span class="bucket-label">' + esc(bucket.label) + '</span>' +
          '<span class="bucket-count">' + bucket.entries.length + '</span>';
        bHead.addEventListener('click', () => {
          if (collapsedArchiveBuckets.has(bucketKey)) {
            collapsedArchiveBuckets.delete(bucketKey);
          } else {
            collapsedArchiveBuckets.add(bucketKey);
          }
          saveArchiveBuckets();
          bSec.classList.toggle('collapsed');
        });
        bSec.appendChild(bHead);
        const bBody = document.createElement('div');
        bBody.className = 'archive-body';
        for (const entry of bucket.entries) {
          const card = renderCard(entry.init.id);
          const fromTag = document.createElement('div');
          fromTag.className = 'from-ws';
          fromTag.innerHTML = esc(I18N.from_workspace) + ' <code>' +
            esc(entry.ws_name) + '</code>' +
            (entry.archived_at
              ? '<span class="archive-when"> · ' +
                esc(entry.archived_at.substring(0, 10)) + '</span>'
              : '');
          const meta = card.querySelector('.card-meta');
          if (meta) meta.parentNode.insertBefore(fromTag, meta);
          else card.insertBefore(fromTag, card.firstChild);
          bBody.appendChild(card);
        }
        bSec.appendChild(bBody);
        arcSec.appendChild(bSec);
      });
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

    // Tasks (DD-011: tri-state, single store, inline fold for terminal)
    const tasks = (init.tasks || []).map(taskStatus);
    if (tasks.length) {
      const doneCount = tasks.filter(t => t._status === 'done').length;
      const cancelledCount = tasks.filter(t => t._status === 'cancelled').length;
      const labelMeta = I18N.tasks_meta
        .replace('{}', tasks.length)
        .replace('{}', doneCount)
        .replace('{}', cancelledCount);
      const taskSection = document.createElement('div');
      taskSection.className = 'card-section tasks-section';
      taskSection.innerHTML = '<div class="label">' + esc(I18N.tasks) +
        ' <span class="label-meta">' + esc(labelMeta) + '</span></div>';
      const ul = document.createElement('ul');
      ul.className = 'tasks-list';
      const pendings = tasks.filter(t => t._status === 'pending');
      const terminals = tasks.filter(t => t._status !== 'pending');
      for (const t of pendings) ul.appendChild(buildTaskLi(initId, t, false));
      for (const t of terminals) ul.appendChild(buildTaskLi(initId, t, true));
      taskSection.appendChild(ul);

      if (terminals.length) {
        const fold = document.createElement('button');
        fold.className = 'expand-toggle';
        fold.setAttribute('data-state', 'collapsed');
        fold.textContent = I18N.task_terminal_fold_show.replace('{}', terminals.length);
        fold.addEventListener('click', () => {
          const collapsed = fold.getAttribute('data-state') === 'collapsed';
          ul.querySelectorAll('li.task-terminal').forEach(li => {
            li.classList.toggle('hidden-done', !collapsed);
          });
          if (collapsed) {
            fold.setAttribute('data-state', 'expanded');
            fold.textContent = I18N.task_terminal_fold_hide;
          } else {
            fold.setAttribute('data-state', 'collapsed');
            fold.textContent = I18N.task_terminal_fold_show.replace('{}', terminals.length);
          }
        });
        taskSection.appendChild(fold);
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
      ab.addEventListener('click', async () => {
        if (!(await confirmDialog(I18N.confirm_archive.replace('{}', init.name)))) return;
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
    // Consolidate-duplicates button: appears when the card has piled
    // up ≥ 8 pending tasks AND we have a server to call. DD-012's
    // forward fix (Layer 1 sees PRIOR titles) prevents future bloat;
    // this is the manual escape valve for cards already in the bad
    // state — one AI round, preview, user confirms, applied via the
    // existing task_toggles override path.
    const pendingCount = (init.tasks || []).filter(
      t => (t.status || 'pending') === 'pending').length;
    if (SERVER_MODE && !isArchived && pendingCount >= 8) {
      const cb = document.createElement('button');
      cb.innerHTML = '✨ ' + esc(I18N.btn_consolidate);
      cb.addEventListener('click', async () => {
        cb.disabled = true;
        const originalLabel = cb.innerHTML;
        cb.innerHTML = '⏳ ' + esc(I18N.consolidate_progress);
        try {
          const r = await fetch(SERVER_ORIGIN + '/api/consolidate-tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_id: initId }),
          });
          const payload = await r.json().catch(() => ({}));
          if (!r.ok) {
            toast(I18N.consolidate_error.replace('{}',
              payload.error || ('HTTP ' + r.status)));
            return;
          }
          const groups = payload.groups || [];
          if (!groups.length) {
            toast(I18N.consolidate_no_dups);
            return;
          }
          openConsolidatePreview(initId, init.name, groups);
        } catch (e) {
          toast(I18N.consolidate_error.replace('{}', e.message));
        } finally {
          cb.disabled = false;
          cb.innerHTML = originalLabel;
        }
      });
      foot.appendChild(cb);
    }

    const db = document.createElement('button');
    db.className = 'danger';
    db.innerHTML = '🗑️ ' + esc(I18N.btn_delete);
    db.addEventListener('click', async () => {
      if (!(await confirmDialog(I18N.confirm_delete.replace('{}', init.name), { danger: true }))) return;
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

  // -- Custom confirm dialog ---------------------------------------------
  // Replaces window.confirm() because Chrome (and others) lets users
  // suppress browser dialogs per-origin after a few prompts; once
  // suppressed, confirm() silently returns false and the calling handler
  // returns early — looks exactly like "the button does nothing", which
  // is what users reported. A custom in-page modal is also more
  // consistent with the dashboard's visual style.
  //
  // Returns a Promise<boolean>.
  function confirmDialog(message, opts) {
    return new Promise(resolve => {
      const o = opts || {};
      const okText = o.okText || I18N.dlg_ok;
      const cancelText = o.cancelText || I18N.dlg_cancel;
      const danger = !!o.danger;

      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay confirm-overlay';
      const box = document.createElement('div');
      box.className = 'confirm-box' + (danger ? ' danger' : '');
      box.innerHTML =
        '<div class="confirm-msg"></div>' +
        '<div class="confirm-actions">' +
          '<button class="confirm-cancel" type="button"></button>' +
          '<button class="confirm-ok ' + (danger ? 'danger' : '') + '" type="button"></button>' +
        '</div>';
      box.querySelector('.confirm-msg').textContent = message;
      box.querySelector('.confirm-cancel').textContent = cancelText;
      box.querySelector('.confirm-ok').textContent = okText;
      overlay.appendChild(box);

      const close = (result) => {
        document.removeEventListener('keydown', onKey, true);
        overlay.remove();
        resolve(result);
      };
      const onKey = (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); close(false); }
        else if (ev.key === 'Enter') { ev.preventDefault(); close(true); }
      };
      overlay.addEventListener('click', (ev) => { if (ev.target === overlay) close(false); });
      box.querySelector('.confirm-cancel').addEventListener('click', () => close(false));
      box.querySelector('.confirm-ok').addEventListener('click', () => close(true));

      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey, true);
      // Focus the OK button for keyboard users
      requestAnimationFrame(() => box.querySelector('.confirm-ok').focus());
    });
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
        const key = artifactKey(a);
        const safeKey = key ? key.replace(/"/g, '&quot;') : '';
        aHtml +=
          '<li>' +
            '<span class="art-type">' + esc(a.type || '?') + '</span>' +
            '<span class="art-status ' + esc(statusCls) + '">' + esc(statusLabel) + '</span>' +
            '<span class="art-title">' + esc(title) + '</span>' +
            (a.url ? '<a class="art-link" target="_blank" rel="noopener" href="' + safeUrl + '">' + esc(I18N.modal_open_external) + ' ↗</a>' : '') +
            (key
              ? '<button class="art-del" type="button" title="' + esc(I18N.btn_artifact_del) + '" data-art-key="' + safeKey + '" data-art-title="' + esc(title).replace(/"/g, '&quot;') + '">✕</button>'
              : '') +
          '</li>';
      }
      aHtml += '</ul>';
    } else {
      aHtml += '<p class="modal-empty">' + esc(I18N.modal_no_artifacts) + '</p>';
    }
    aSec.innerHTML = aHtml;
    // Wire delete buttons — overrides.hidden_artifacts is persistent
    // (classify.py keeps it across runs; never auto-cleared).
    aSec.querySelectorAll('button.art-del').forEach(btn => {
      btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const key = btn.getAttribute('data-art-key');
        const title = btn.getAttribute('data-art-title') || key;
        if (!key) return;
        if (!(await confirmDialog(I18N.confirm_delete_artifact.replace('{}', title), { danger: true }))) return;
        // Idempotent: don't push duplicates for the same (init, key).
        if (!overrides.hidden_artifacts.some(h => h.init_id === initId && h.key === key)) {
          overrides.hidden_artifacts.push({ init_id: initId, key: key, at: new Date().toISOString() });
        }
        saveOverrides();
        closeDetailModal();
        replaceCard(initId);
      });
    });
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

  // Consolidate-tasks preview overlay. Shown after a successful
  // /api/consolidate-tasks call so the user can eyeball the AI's
  // dedup plan before any cancellations land. On apply, each cancel
  // becomes a task_toggles override; the existing apply path picks
  // them up on the next classify, and effective() reflects them
  // instantly via replaceCard.
  function openConsolidatePreview(initId, initName, groups) {
    closeDetailModal();
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) closeConsolidatePreview();
    });
    const modal = document.createElement('div');
    modal.className = 'modal consolidate-modal';
    overlay.appendChild(modal);

    const head = document.createElement('div');
    head.className = 'modal-head';
    head.innerHTML =
      '<h2>' + esc(I18N.consolidate_preview_title) + ' — ' + esc(initName) + '</h2>' +
      '<button class="modal-close" title="' + esc(I18N.modal_close) + '">✕</button>';
    head.querySelector('.modal-close').addEventListener('click', closeConsolidatePreview);
    modal.appendChild(head);

    const hint = document.createElement('p');
    hint.className = 'consolidate-hint';
    hint.textContent = I18N.consolidate_preview_hint;
    modal.appendChild(hint);

    const list = document.createElement('div');
    list.className = 'consolidate-groups';
    let cancelTotal = 0;
    for (const g of groups) {
      const gSec = document.createElement('div');
      gSec.className = 'consolidate-group';
      const keep = document.createElement('div');
      keep.className = 'consolidate-keep';
      keep.innerHTML =
        '<span class="cg-label">' + esc(I18N.consolidate_keep_label) + '</span> ' +
        '<span class="cg-title">' + esc(g.keep) + '</span>';
      gSec.appendChild(keep);
      const ul = document.createElement('ul');
      ul.className = 'consolidate-cancels';
      for (const c of g.cancel) {
        cancelTotal += 1;
        const li = document.createElement('li');
        li.innerHTML =
          '<span class="cc-mark">✕</span>' +
          '<span class="cc-title">' + esc(c.title) + '</span>' +
          (c.reason ? '<span class="cc-reason">' + esc(c.reason) + '</span>' : '');
        ul.appendChild(li);
      }
      gSec.appendChild(ul);
      list.appendChild(gSec);
    }
    modal.appendChild(list);

    const foot = document.createElement('div');
    foot.className = 'consolidate-actions';
    const dismiss = document.createElement('button');
    dismiss.textContent = I18N.consolidate_dismiss;
    dismiss.addEventListener('click', closeConsolidatePreview);
    const apply = document.createElement('button');
    apply.className = 'primary';
    apply.textContent = I18N.consolidate_apply + ' (' + cancelTotal + ')';
    apply.addEventListener('click', () => {
      const now = new Date().toISOString();
      for (const g of groups) {
        for (const c of g.cancel) {
          // Drop any older toggle entry for this exact task — last
          // write wins, same as the existing postStatusToggle path.
          overrides.task_toggles = overrides.task_toggles.filter(
            tt => !(tt.init_id === initId && tt.task_title === c.title));
          overrides.task_toggles.push({
            init_id: initId,
            task_title: c.title,
            status: 'cancelled',
            evidence: (I18N.consolidate_evidence_prefix + ' "' + g.keep + '"').slice(0, 80),
            at: now,
          });
        }
      }
      saveOverrides();
      closeConsolidatePreview();
      replaceCard(initId);
    });
    foot.appendChild(dismiss);
    foot.appendChild(apply);
    modal.appendChild(foot);

    document.body.appendChild(overlay);
    document.addEventListener('keydown', consolidateKeyHandler);
  }

  function closeConsolidatePreview() {
    document.querySelectorAll('.modal-overlay').forEach(o => o.remove());
    document.removeEventListener('keydown', consolidateKeyHandler);
  }

  function consolidateKeyHandler(ev) {
    if (ev.key === 'Escape') closeConsolidatePreview();
  }

  // DD-014: renderChip — compact tag-shaped element for `level: chip`
  // initiatives. Clicking opens the same detail view as a card (we
  // reuse renderCard's modal target by routing through scrollToCard
  // when the user expands inline).
  function renderChip(init) {
    const eff = effective(init.id);
    const data = eff ? eff.init : init;
    const isArchived = overrides.archived.indexOf(init.id) !== -1;
    const status = isArchived ? 'archived' : data.status;
    const chip = document.createElement('span');
    chip.className = 'chip-card';
    chip.setAttribute('data-init-id', init.id);
    chip.setAttribute('data-status', status);

    const tasks = (data.tasks || []).map(taskStatus);
    const pending = tasks.filter(t => t._status === 'pending').length;
    const hasBlocker = Array.isArray(data.blockers) && data.blockers.length > 0;
    if (pending > 0) chip.classList.add('has-pending');

    const dot = document.createElement('span');
    dot.className = 'chip-dot ' + status;
    chip.appendChild(dot);

    const name = document.createElement('span');
    name.className = 'chip-name';
    name.title = data.name || '';
    name.textContent = data.name || '';
    chip.appendChild(name);

    const meta = document.createElement('span');
    meta.className = 'chip-meta';
    meta.textContent = humanizeAge(data.last_activity_at);
    chip.appendChild(meta);

    if (pending > 0) {
      const badge = document.createElement('span');
      badge.className = 'chip-task-badge';
      badge.textContent = I18N.chip_pending_tasks.replace('{}', pending);
      chip.appendChild(badge);
    }
    if (hasBlocker) {
      const b = document.createElement('span');
      b.className = 'chip-blocker';
      b.textContent = '⚠';
      b.title = data.blockers[0] || '';
      chip.appendChild(b);
    }

    chip.addEventListener('click', (ev) => {
      ev.stopPropagation();
      // Promote to a card view: scroll to it (if there's a hidden full
      // card somewhere), otherwise expand inline as a tiny popover.
      promoteChipToInspect(init.id);
    });
    return chip;
  }

  // Inline "open the chip's full card" — we render the card into a
  // floating popover anchored where the chip sits. This avoids the
  // dashboard's "I clicked something small and the whole world
  // changed" feel.
  function promoteChipToInspect(initId) {
    // Remove any previous popover first.
    document.querySelectorAll('.chip-popover').forEach(p => p.remove());
    const card = renderCard(initId);
    if (!card) return;
    const popover = document.createElement('div');
    popover.className = 'modal-overlay chip-popover';
    popover.innerHTML = '<div class="modal-card" style="max-width: 580px;"></div>';
    const modalCard = popover.querySelector('.modal-card');
    modalCard.appendChild(card);
    popover.addEventListener('click', (ev) => {
      if (ev.target === popover) popover.remove();
    });
    document.addEventListener('keydown', function onEsc(ev) {
      if (ev.key === 'Escape') {
        popover.remove();
        document.removeEventListener('keydown', onEsc);
      }
    });
    document.body.appendChild(popover);
  }

  // DD-014: renderThreadDeck — the poker-deck visualization for a
  // `level: thread` initiative. The deck head shows the thread's title,
  // status, summary; below it sits a row of "member pills" linking out
  // to each member card/chip. Clicking the deck toggles `.expanded`,
  // which fans the backplates away and emphasises the deck contents.
  function renderThreadDeck(thread, members) {
    const eff = effective(thread.id);
    const data = eff ? eff.init : thread;
    const isArchived = overrides.archived.indexOf(thread.id) !== -1;
    const status = isArchived ? 'archived' : data.status;

    const deck = document.createElement('div');
    deck.className = 'thread-deck';
    deck.setAttribute('data-init-id', thread.id);
    deck.setAttribute('data-status', status);

    const head = document.createElement('div');
    head.className = 'thread-deck-head';
    head.innerHTML =
      '<span class="status-dot ' + status + '"></span>' +
      '<span class="thread-icon">📚</span>' +
      '<h3>' + esc(data.name || '') + '</h3>' +
      '<span class="status-badge ' + status + '">' +
        esc(I18N['status_' + status] || status) + '</span>' +
      '<span class="status-badge">' + esc(humanizeAge(data.last_activity_at)) + '</span>';
    deck.appendChild(head);

    if (data.summary) {
      const sum = document.createElement('p');
      sum.className = 'thread-deck-summary';
      sum.textContent = data.summary;
      deck.appendChild(sum);
    }

    if (members && members.length) {
      const memWrap = document.createElement('div');
      memWrap.className = 'thread-deck-members';
      const mlbl = document.createElement('span');
      mlbl.style.cssText = 'color: var(--text-mute); font-size: 11px; align-self: center;';
      mlbl.textContent = (I18N.thread_members_label || 'Contains') + ':';
      memWrap.appendChild(mlbl);
      for (const m of members) {
        const mEff = effective(m.id);
        const mData = mEff ? mEff.init : m;
        const mStatus = (overrides.archived.indexOf(m.id) !== -1) ? 'archived' : mData.status;
        const pill = document.createElement('span');
        pill.className = 'thread-deck-member-pill';
        pill.setAttribute('data-init-id', m.id);
        pill.innerHTML =
          '<span class="pill-dot ' + 'status-dot ' + mStatus +
            '" style="background: var(--' +
            (mStatus === 'active' ? 'green' :
             mStatus === 'paused' ? 'amber' :
             mStatus === 'done' ? 'slate' : 'text-mute') + ');"></span>' +
          esc(mData.name || '');
        pill.addEventListener('click', (ev) => {
          ev.stopPropagation();
          promoteChipToInspect(m.id);
        });
        memWrap.appendChild(pill);
      }
      deck.appendChild(memWrap);
    }

    const foot = document.createElement('div');
    foot.className = 'thread-deck-foot';
    const memCount = members ? members.length : 0;
    foot.innerHTML =
      '<span class="deck-stat">' + memCount + ' ' +
        (memCount === 1 ? (I18N.initiative || 'item')
                        : (I18N.initiative || 'items')) + '</span>' +
      '<span class="deck-stat deck-toggle">' +
        esc(I18N.thread_members_label || 'Details') + '</span>';
    deck.appendChild(foot);

    deck.addEventListener('click', (ev) => {
      if (ev.target.closest('.thread-deck-member-pill')) return;
      // Clicking the deck itself opens the thread's own full card
      // (using the chip popover route — reuses the same modal stack).
      promoteChipToInspect(thread.id);
    });

    return deck;
  }

  function buildSection(label, innerHtml) {
    const d = document.createElement('div');
    d.className = 'card-section';
    d.innerHTML = '<div class="label">' + esc(label) + '</div>' + innerHtml;
    return d;
  }

  function taskStatus(t) {
    // DD-011: prefer `status`; fall back to legacy `done: bool` for any
    // dashboard.json snapshot written before the migration ran.
    let s = t.status;
    if (s !== 'pending' && s !== 'done' && s !== 'cancelled') {
      s = t.done ? 'done' : 'pending';
    }
    return Object.assign({}, t, { _status: s });
  }

  function postStatusToggle(initId, task, nextStatus) {
    overrides.task_toggles = overrides.task_toggles.filter(
      tt => !(tt.init_id === initId && tt.task_title === task.title));
    overrides.task_toggles.push({
      init_id: initId, task_title: task.title,
      status: nextStatus, at: new Date().toISOString(),
    });
    saveOverrides();
    replaceCard(initId);
  }

  function buildTaskLi(initId, task, foldHidden) {
    const li = document.createElement('li');
    const s = task._status || 'pending';
    const isTerminal = (s !== 'pending');
    li.className = 'task task-status-' + s + (isTerminal ? ' task-terminal' : '')
      + (foldHidden && isTerminal ? ' hidden-done' : '');
    li.setAttribute('data-task-title', task.title);
    li.setAttribute('data-status', s);

    // Evidence marker (✨ for done, ✕ for cancelled with reason)
    const evidence = task.evidence || task.done_evidence;
    const evidenceHtml = (isTerminal && evidence)
      ? ' <span class="task-evidence" title="' + esc(evidence) + '">✨</span>'
      : '';

    // Pending → checkbox. Terminal → status icon + reactivate menu.
    const head = (s === 'pending')
      ? '<input type="checkbox">'
      : '<span class="task-status-icon" title="'
        + esc(s === 'done' ? I18N.task_status_done : I18N.task_status_cancelled)
        + '">' + (s === 'done' ? '✓' : '✕') + '</span>';

    const actions = (s === 'pending')
      ? '<button class="task-cancel" title="' + esc(I18N.task_cancel_action) + '">⊘</button>'
        + '<button class="task-del" title="' + esc(I18N.btn_delete) + '">✕</button>'
      : '<button class="task-reactivate" title="' + esc(I18N.task_uncancel_action) + '">↺</button>'
        + '<button class="task-del" title="' + esc(I18N.btn_delete) + '">✕</button>';

    li.innerHTML = head
      + '<span class="task-title">' + esc(task.title) + '</span>'
      + evidenceHtml
      + actions;

    const checkbox = li.querySelector('input[type="checkbox"]');
    if (checkbox) {
      checkbox.addEventListener('change', (e) => {
        postStatusToggle(initId, task, e.target.checked ? 'done' : 'pending');
      });
    }
    const cancelBtn = li.querySelector('.task-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', async () => {
        if (!(await confirmDialog(I18N.confirm_cancel_task.replace('{}', task.title)))) return;
        postStatusToggle(initId, task, 'cancelled');
      });
    }
    const reactivateBtn = li.querySelector('.task-reactivate');
    if (reactivateBtn) {
      reactivateBtn.addEventListener('click', () => {
        postStatusToggle(initId, task, 'pending');
      });
    }
    li.querySelector('.task-del').addEventListener('click', async () => {
      if (!(await confirmDialog(I18N.confirm_delete_task.replace('{}', task.title), { danger: true }))) return;
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
    const resumeCmd = (resumeCwd ? 'cd ' + resumeCwd + ' && ' : '')
      + 'claude --dangerously-skip-permissions --resume ' + sid;

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
            if (await confirmDialog(I18N.toast_pane_gone.replace('{}', loc.zellij_pane_id) + ' — 在新 pane 中 resume?')) {
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
      hidden_artifacts: overrides.hidden_artifacts,
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
      const ov = { version: 1, task_toggles: overrides.task_toggles, deleted_tasks: overrides.deleted_tasks, hidden_artifacts: overrides.hidden_artifacts, updated_at: new Date().toISOString() };
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
          if (j && j.service === 'claude-stray') {
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
  // When the pipeline runs in the background, dashboard.json changes. We poll
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
      // Lifecycle + cost-alarm change independently of mindmap content
      // (e.g. user pauses but no new classify ran). Update those first
      // every poll, regardless of the freshness check below.
      if (j.lifecycle) {
        const changed = JSON.stringify(j.lifecycle) !== JSON.stringify(LIFECYCLE);
        if (changed) {
          LIFECYCLE = j.lifecycle;
          updateLifecycleBanner();
        }
      }
      const srvGen = j?.mindmap?.generated_at || '';
      if (!srvGen) return;
      // Detect mindmap or archive changes
      const newArcCount = (j.archived || []).length;
      const oldArcCount = (ARCHIVED_PERSISTED || []).length;
      if (srvGen === lastGeneratedAt && newArcCount === oldArcCount) {
        return;  // nothing new in the mindmap itself
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
    if (payload.lifecycle) LIFECYCLE = payload.lifecycle;
    lastGeneratedAt = DATA.generated_at || lastGeneratedAt;
    rebuildIndex();
    render();
    updateLifecycleBanner();
    // Preserve scroll
    window.scrollTo({ top: scrollY, behavior: 'instant' });
    // Subtle toast so user knows data refreshed (skip on first apply at boot)
    if (window.__ccwBooted) toast('数据已更新');
    window.__ccwBooted = true;
  }

  // ---------- Lifecycle banner (DD-005) -----------------------------------
  const $lifecycleBanner = document.getElementById('lifecycle-banner');
  const $lbReason = document.getElementById('lb-reason');
  const $lbResume = document.getElementById('lb-resume');

  function updateLifecycleBanner() {
    if (!$lifecycleBanner) return;
    if (!LIFECYCLE || !LIFECYCLE.paused) {
      $lifecycleBanner.hidden = true;
      return;
    }
    $lifecycleBanner.hidden = false;
    const reason = (LIFECYCLE.reason || '').trim();
    if ($lbReason) {
      $lbReason.textContent = reason
        ? `${I18N.lifecycle_paused_reason_prefix} ${reason}`
        : '';
    }
    // Resume button is only meaningful in server mode (writes a file
    // on the host). In file:// mode show the banner but disable the
    // button, so users at least see the state.
    if ($lbResume) {
      $lbResume.disabled = !SERVER_MODE;
      $lbResume.title = SERVER_MODE ? '' : 'Run `stray --resume` in your terminal';
    }
  }

  if ($lbResume) {
    $lbResume.addEventListener('click', async () => {
      if (!SERVER_MODE) return;
      const okText = I18N.lifecycle_resume || 'Resume';
      const okayed = await confirmDialog(I18N.lifecycle_resume_confirm, { okText });
      if (!okayed) return;
      $lbResume.disabled = true;
      try {
        const r = await fetch(SERVER_ORIGIN + '/api/lifecycle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'resume' }),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok) {
          LIFECYCLE = j && typeof j.paused !== 'undefined' ? j : { paused: false };
          updateLifecycleBanner();
          toast(I18N.lifecycle_resumed_toast);
        } else {
          toast('resume failed: HTTP ' + r.status);
        }
      } catch (e) {
        toast('resume failed: ' + (e.message || e));
      } finally {
        $lbResume.disabled = false;
      }
    });
  }

  // Initial paint
  updateLifecycleBanner();

  // ---------- Update-available banner -----------------------------------
  // Poll /api/version (the server-side state file; updated by the
  // background thread every 24h and on serve startup). When `behind`
  // flips to true, show the banner with the "Update now" button.
  const $updateBanner = document.getElementById('update-banner');
  const $ubVersions = document.getElementById('ub-versions');
  const $ubApply = document.getElementById('ub-apply');
  const $ubDismiss = document.getElementById('ub-dismiss');
  const UPDATE_DISMISS_KEY = 'claude-code-worktree:update-dismissed-remote';
  let _updateSnapshot = null;
  let _updateBannerDismissedRemote = null;

  function fmtVersions(local, remote) {
    return (I18N.update_versions_fmt || '{local} → {remote}')
      .replace('{local}', local || '?')
      .replace('{remote}', remote || '?');
  }

  function updateUpdateBanner() {
    if (!$updateBanner) return;
    const s = _updateSnapshot;
    if (!s || !s.behind) { $updateBanner.hidden = true; return; }
    // User-dismissed THIS remote version stays hidden until a newer
    // remote shows up. Per-session, localStorage-scoped.
    if (_updateBannerDismissedRemote === s.remote) {
      $updateBanner.hidden = true;
      return;
    }
    $updateBanner.hidden = false;
    if ($ubVersions) $ubVersions.textContent = fmtVersions(s.local, s.remote);
  }

  async function fetchVersion() {
    if (!SERVER_MODE) return;
    try {
      const r = await fetch(SERVER_ORIGIN + '/api/version');
      if (!r.ok) return;
      _updateSnapshot = await r.json();
      updateUpdateBanner();
    } catch (_) { /* offline — keep last snapshot */ }
  }

  if ($ubDismiss) {
    $ubDismiss.addEventListener('click', () => {
      if (_updateSnapshot && _updateSnapshot.remote) {
        _updateBannerDismissedRemote = _updateSnapshot.remote;
        try { localStorage.setItem(UPDATE_DISMISS_KEY,
                                    _updateBannerDismissedRemote); } catch (_) {}
      }
      $updateBanner.hidden = true;
    });
  }

  if ($ubApply) {
    $ubApply.addEventListener('click', async () => {
      if (!SERVER_MODE) return;
      $ubApply.disabled = true;
      const originalLabel = $ubApply.textContent;
      $ubApply.textContent = I18N.update_in_progress;
      try {
        const r = await fetch(SERVER_ORIGIN + '/api/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.ok) {
          toast((I18N.update_success_toast || 'Updated to {after}')
            .replace('{after}', j.after || '?'));
          // Refresh the snapshot — server side has already cleared `behind`.
          await fetchVersion();
        } else {
          const err = (j && j.error) || ('HTTP ' + r.status);
          toast((I18N.update_failed_toast || 'Update failed: {err}')
            .replace('{err}', err));
        }
      } catch (e) {
        toast((I18N.update_failed_toast || 'Update failed: {err}')
          .replace('{err}', e.message || e));
      } finally {
        $ubApply.disabled = false;
        $ubApply.textContent = originalLabel;
      }
    });
  }

  // Restore the last dismissed remote (if any) so a reload doesn't
  // re-show the banner for the same version.
  try {
    _updateBannerDismissedRemote = localStorage.getItem(UPDATE_DISMISS_KEY);
  } catch (_) {}

  if (SERVER_MODE) {
    // Initial fetch + 24h poll. Cheap (single JSON read on the server).
    fetchVersion();
    setInterval(fetchVersion, 24 * 3600 * 1000);
  }

  // ---------- Derived widgets (DD-006) ----------------------------------
  // Sidebar widgets for weekly report / next-steps / tips. Wellness is
  // emitted as a top toast on dashboard load if a fresh nudge exists.
  // Server-mode only — the payloads live under cache/derived/ and
  // require /api/derived.
  const $widgets = document.getElementById('derived-widgets');
  const $dwNext = document.getElementById('dw-next');
  const $dwNextList = document.getElementById('dw-next-list');
  const $dwWeekly = document.getElementById('dw-weekly');
  const $dwWeeklyBtn = document.getElementById('dw-weekly-btn');
  // DD-006 tips speech-bubble (playful redesign). The "mascot" slot
  // (#tt-kind) is now a pixel-art walking cat rendered entirely via
  // CSS; JS only updates the bubble color (data-kind) and the lead
  // text. See bin/assets/pet/README.md for the sprite asset.
  const $tipsTicker = document.getElementById('tips-ticker');
  const $ttLead = document.getElementById('tt-lead');
  const $ttText = document.getElementById('tt-text');
  const $ttSource = document.getElementById('tt-source');
  let _tipsPool = [];   // [{kind, text, pattern?, source_url?}], shuffled
  let _tipsIdx = 0;
  let _tipsTimer = null;
  const TIP_LEAD = {
    work:      I18N.tip_lead_work,
    wisdom:    I18N.tip_lead_wisdom,
    rest:      I18N.tip_lead_rest,
    curiosity: I18N.tip_lead_curiosity,
  };
  // Fisher-Yates shuffle in place. After a full sequential walk over a
  // shuffled pool, every tip plays exactly once before any repeat —
  // better than pure random (which can show the same tip back-to-back)
  // and far better than sequential (which clusters by kind: 8 curiosity
  // in a row, then 6 wisdom, etc).
  function shuffleTipsPool(prevKind) {
    for (let i = _tipsPool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [_tipsPool[i], _tipsPool[j]] = [_tipsPool[j], _tipsPool[i]];
    }
    // Avoid two same-kind tips touching across a wrap boundary: if the
    // new head matches the previous tail's kind, swap head with the
    // next non-matching position.
    if (prevKind && _tipsPool.length > 1
        && _tipsPool[0].kind === prevKind) {
      for (let i = 1; i < _tipsPool.length; i++) {
        if (_tipsPool[i].kind !== prevKind) {
          [_tipsPool[0], _tipsPool[i]] = [_tipsPool[i], _tipsPool[0]];
          break;
        }
      }
    }
  }
  function renderTipAt(i) {
    if (!_tipsPool.length) return;
    const wrap = i >= _tipsPool.length;
    if (wrap) shuffleTipsPool(_tipsPool[_tipsIdx]?.kind);
    _tipsIdx = ((i % _tipsPool.length) + _tipsPool.length) % _tipsPool.length;
    const t = _tipsPool[_tipsIdx];
    const kind = t.kind || 'wisdom';
    $tipsTicker.setAttribute('data-kind', kind);
    const lead = TIP_LEAD[kind] || '';
    $ttLead.textContent = lead;
    $ttLead.style.display = lead ? 'block' : 'none';
    $ttText.textContent = t.text || '';
    if ($ttSource) {
      const url = t.source_url || '';
      if (url && /^https?:\/\//i.test(url)) {
        $ttSource.href = url;
        $ttSource.hidden = false;
      } else {
        $ttSource.removeAttribute('href');
        $ttSource.hidden = true;
      }
    }
    $tipsTicker.title = (t.text || '') + '  ·  ' + (I18N.tip_ticker_hint || '');
    // pet hops on every cycle
    $tipsTicker.classList.remove('cycling');
    void $tipsTicker.offsetWidth;
    $tipsTicker.classList.add('cycling');
  }
  function scheduleTipsRotation() {
    if (_tipsTimer) clearInterval(_tipsTimer);
    if (_tipsPool.length < 2) return;
    _tipsTimer = setInterval(() => renderTipAt(_tipsIdx + 1), 25 * 1000);
  }

  // ---- Drag-to-position + click-to-cycle ----
  // Click vs drag distinction: only consider it a drag once the mouse
  // moves > DRAG_THRESHOLD pixels from the mousedown point. Smaller
  // movements (or no movement at all) → it's a click; cycle the tip.
  // Position is persisted to localStorage so reloads remember it.
  // Default position is the CSS top/right anchor; user-positioned
  // bubbles use left/top with right/bottom cleared.
  const TIPS_POS_KEY = 'tips-bubble-pos';
  const DRAG_THRESHOLD = 4;
  function clampToViewport(left, top) {
    const rect = $tipsTicker.getBoundingClientRect();
    const maxLeft = Math.max(0, window.innerWidth  - rect.width  - 4);
    const maxTop  = Math.max(0, window.innerHeight - rect.height - 4);
    return {
      left: Math.min(Math.max(0, left), maxLeft),
      top:  Math.min(Math.max(0, top),  maxTop),
    };
  }
  function applyAbsolutePosition(left, top) {
    const c = clampToViewport(left, top);
    // Translate transforms break getBoundingClientRect math, so we
    // switch the bubble from "right/transform" anchor to pure left/top
    // when the user starts positioning it manually.
    $tipsTicker.style.left = c.left + 'px';
    $tipsTicker.style.top = c.top + 'px';
    $tipsTicker.style.right = 'auto';
    $tipsTicker.style.bottom = 'auto';
    $tipsTicker.style.transform = 'none';
  }
  // Restore saved position (after the bubble is laid out at least once)
  try {
    const saved = JSON.parse(localStorage.getItem(TIPS_POS_KEY) || 'null');
    if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
      // Defer one frame so the bubble has its computed size when we clamp
      requestAnimationFrame(() => applyAbsolutePosition(saved.left, saved.top));
    }
  } catch (e) { /* ignore corrupt localStorage */ }

  let _drag = null;     // active drag state
  let _suppressClick = false;
  if ($tipsTicker) {
    $tipsTicker.addEventListener('mousedown', (ev) => {
      // Clicking the source-link should NOT start a drag.
      if (ev.target.closest('.tt-source')) return;
      if (ev.button !== 0) return;
      const rect = $tipsTicker.getBoundingClientRect();
      _drag = {
        startX: ev.clientX, startY: ev.clientY,
        origLeft: rect.left, origTop: rect.top,
        moved: false,
      };
      ev.preventDefault();
    });
    document.addEventListener('mousemove', (ev) => {
      if (!_drag) return;
      const dx = ev.clientX - _drag.startX;
      const dy = ev.clientY - _drag.startY;
      if (!_drag.moved
          && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
        _drag.moved = true;
        $tipsTicker.classList.add('dragging');
      }
      if (_drag.moved) {
        applyAbsolutePosition(_drag.origLeft + dx, _drag.origTop + dy);
      }
    });
    document.addEventListener('mouseup', () => {
      if (!_drag) return;
      if (_drag.moved) {
        $tipsTicker.classList.remove('dragging');
        try {
          const rect = $tipsTicker.getBoundingClientRect();
          localStorage.setItem(TIPS_POS_KEY,
            JSON.stringify({ left: rect.left, top: rect.top }));
        } catch (e) { /* ignore quota errors */ }
        _suppressClick = true;
        // The synthetic click event fires AFTER mouseup; clear the
        // flag on the next tick so it suppresses exactly one click.
        setTimeout(() => { _suppressClick = false; }, 0);
      }
      _drag = null;
    });
    // Click cycles, but not when we just finished a drag and not when
    // the click bubbled up from the source link.
    $tipsTicker.addEventListener('click', (ev) => {
      if (_suppressClick) return;
      if (ev.target.closest('.tt-source')) return;
      if (!_tipsPool.length) return;
      renderTipAt(_tipsIdx + 1);
      scheduleTipsRotation();
    });
    // After window resize, re-clamp the user position so the bubble
    // doesn't end up off-screen.
    window.addEventListener('resize', () => {
      if (!$tipsTicker.style.left) return;  // still at default anchor
      const left = parseFloat($tipsTicker.style.left);
      const top  = parseFloat($tipsTicker.style.top);
      if (Number.isFinite(left) && Number.isFinite(top)) {
        applyAbsolutePosition(left, top);
      }
    });
  }

  async function loadDerived() {
    if (!SERVER_MODE) return;
    try {
      const r = await fetch(SERVER_ORIGIN + '/api/derived');
      if (!r.ok) return;
      const d = await r.json();
      let any = false;

      // next-steps
      if (d.suggestions && d.suggestions.items && d.suggestions.items.length) {
        $dwNextList.innerHTML = '';
        for (const it of d.suggestions.items) {
          const li = document.createElement('li');
          li.innerHTML =
            '<div class="dw-init">' + esc(it.init_name || it.init_id) + '</div>' +
            '<div class="dw-init-ws">' + esc(it.ws_name || '') + '</div>' +
            '<div class="dw-reason">' + esc(it.reason || '') + '</div>';
          li.addEventListener('click', () => {
            const target = document.querySelector(
              'article.card[data-init-id="' + CSS.escape(it.init_id) + '"]');
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          });
          $dwNextList.appendChild(li);
        }
        $dwNext.hidden = false;
        any = true;
      }

      // tips: header ticker, multi-category rotation
      if (d.tips && Array.isArray(d.tips.tips) && d.tips.tips.length) {
        _tipsPool = d.tips.tips.slice();
        shuffleTipsPool();   // randomize order so categories don't cluster
        _tipsIdx = 0;
        renderTipAt(0);
        scheduleTipsRotation();
        $tipsTicker.hidden = false;
      } else if (d.tips && d.tips.tip) {
        // Backward-compat with v1 schema (single-tip), in case an old
        // tips/latest.json is still on disk.
        _tipsPool = [{ kind: d.tips.pattern ? 'work' : 'wisdom',
                       text: d.tips.tip }];
        renderTipAt(0);
        $tipsTicker.hidden = false;
      }

      // weekly
      if (d.weekly && d.weekly.latest && d.weekly.latest.week) {
        $dwWeeklyBtn.textContent =
          I18N.weekly_open_btn.replace('{}', d.weekly.latest.week);
        $dwWeeklyBtn.onclick = () => openWeeklyReport(d.weekly.latest.week);
        $dwWeekly.hidden = false;
        any = true;
      }

      $widgets.hidden = !any;

      // Wellness — emit as one-time toast per generated_at
      if (d.wellness && d.wellness.message) {
        const seenKey = 'ccw-wellness-seen-' + (d.wellness.generated_at || '');
        if (!localStorage.getItem(seenKey)) {
          toast((I18N.wellness_toast_prefix || '') + d.wellness.message);
          localStorage.setItem(seenKey, '1');
        }
      }
    } catch (e) { /* server gone or transient */ }
  }

  async function openWeeklyReport(week) {
    if (!SERVER_MODE) return;
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) overlay.remove();
    });
    const modal = document.createElement('div');
    modal.className = 'modal weekly-modal';
    modal.innerHTML =
      '<div class="modal-head">' +
        '<h2>' + esc(I18N.weekly_modal_title.replace('{}', week)) + '</h2>' +
        '<button class="modal-close" type="button">×</button>' +
      '</div>' +
      '<div class="modal-section weekly-md">' + esc(I18N.weekly_loading) + '</div>';
    overlay.appendChild(modal);
    modal.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);

    try {
      const r = await fetch(
        SERVER_ORIGIN + '/api/weekly-report?week=' + encodeURIComponent(week));
      if (!r.ok) {
        modal.querySelector('.weekly-md').textContent = 'HTTP ' + r.status;
        return;
      }
      const j = await r.json();
      // Minimal markdown renderer: headings + lists + links + paragraphs.
      modal.querySelector('.weekly-md').innerHTML = renderSimpleMarkdown(j.markdown || '');
    } catch (e) {
      modal.querySelector('.weekly-md').textContent = 'load failed: ' + (e.message || e);
    }
  }

  // Tiny markdown → HTML. Handles the subset our weekly report uses:
  // headings (# / ## / ###), bullet lists (- / *), [text](url),
  // **bold**, `code`, paragraphs, HTML comments (stripped).
  // Not a full markdown parser — bringing in marked.js would be
  // overkill for one feature. Keeps escaping correct (esc first, then
  // re-inject the allowed HTML for inline formatters).
  function renderSimpleMarkdown(md) {
    md = md.replace(/<!--[\s\S]*?-->/g, '').trim();
    const inlineFmt = (s) => {
      let out = esc(s);
      // Links: [text](url)
      out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
                        '<a href="$2" target="_blank" rel="noopener">$1</a>');
      // Bold: **text** (not *text* because the report uses ** consistently
      // and single-star can conflict with list bullets)
      out = out.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
      // Inline code: `text` (avoid matching ``` fences which are
      // pre-stripped by Haiku's output; this is a line-level regex)
      out = out.replace(/`([^`]+?)`/g, '<code>$1</code>');
      return out;
    };
    const lines = md.split('\n');
    const out = [];
    let inList = false;
    const closeList = () => { if (inList) { out.push('</ul>'); inList = false; } };
    for (let raw of lines) {
      const line = raw.replace(/\s+$/, '');
      if (!line.trim()) { closeList(); continue; }
      const h = /^(#{1,3})\s+(.+)/.exec(line);
      if (h) {
        closeList();
        // # → h2, ## → h3, ### → h3 (h1 is reserved for modal title)
        const lvl = Math.min(3, h[1].length + 1);
        out.push('<h' + lvl + '>' + inlineFmt(h[2]) + '</h' + lvl + '>');
        continue;
      }
      const b = /^[-*]\s+(.+)/.exec(line);
      if (b) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push('<li>' + inlineFmt(b[1]) + '</li>');
        continue;
      }
      closeList();
      out.push('<p>' + inlineFmt(line) + '</p>');
    }
    closeList();
    return out.join('\n');
  }

  if (SERVER_MODE) loadDerived();

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
      // Re-enable after a beat (pipeline takes ~30-120s)
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
                # DD-014: pass level / parent_thread_id through so the
                # client can do 3-tier layout. v2 data without these
                # fields renders as `card` (the JS layer enforces that
                # default to keep the dashboard alive during migration).
                "level": i.get("level") or "card",
                "parent_thread_id": i.get("parent_thread_id"),
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
    # Embed lifecycle state so static (file://) mode also shows the
    # pause banner on first paint. Server mode subsequently refreshes
    # this via /api/data polling.
    try:
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from _lifecycle import status as _lifecycle_status
        lifecycle = _lifecycle_status()
    except Exception:
        lifecycle = {"paused": False}

    slim = {
        "schema_version": data.get("schema_version", 3),
        "generated_at": data.get("generated_at"),
        "workspaces": workspaces,
        "lifecycle": lifecycle,
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
    out = out.replace("__LIFECYCLE_PAUSED__", html_lib.escape(L["lifecycle_paused"]))
    out = out.replace("__LIFECYCLE_RESUME__", html_lib.escape(L["lifecycle_resume"]))
    out = out.replace("__UPDATE_AVAILABLE__", html_lib.escape(L["update_available"]))
    out = out.replace("__UPDATE_NOW__", html_lib.escape(L["update_now"]))
    out = out.replace("__UPDATE_DISMISS__", html_lib.escape(L["update_dismiss"]))
    out = out.replace("__WEEKLY_LABEL__", html_lib.escape(L["weekly_label"]))
    out = out.replace("__NEXT_STEPS_LABEL__", html_lib.escape(L["next_steps_label"]))
    out = out.replace("__TIP_LABEL__", html_lib.escape(L["tip_label"]))
    out = out.replace("__TIP_TICKER_HINT__", html_lib.escape(L["tip_ticker_hint"]))
    out = out.replace("__PET_DATA_URL__", _pet_data_url())
    out = out.replace("__DATA_JSON__", json_for_script(slim))
    out = out.replace("__I18N_JSON__", json_for_script(i18n_for_js))
    out = out.replace("__LOCATIONS_JSON__", json_for_script(locations))
    out = out.replace("__ARCHIVED_JSON__", json_for_script(archived_items))
    return out


def main() -> int:
    if not DASHBOARD_FILE.exists():
        print(f"No mindmap cache found at {DASHBOARD_FILE}", file=sys.stderr)
        print("Run: mindmap --refresh", file=sys.stderr)
        return 1
    data = json.loads(DASHBOARD_FILE.read_text())
    lang = get_lang()
    L = LOCALE[lang]
    html = render_html(data, L, lang)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# DD-028 — 会话状态不更新的根治:hook 写错了 worktree 的 cache

**一句话结论:** 卡片状态卡死的根因不是 hook 漏发,而是 hook 脚本各自用「自己所在文件位置」算
`cache/` 路径——一旦 `install.sh` 从某个 worktree 里跑过(开发 DD-022 时常发生),全局 hook
就被注册成 `bash .../.claude/worktrees/<x>/bin/refresh-bg.sh`,于是每次 live 写入都落进那个
worktree 的 `cache/live/`,而 serve 只读主 checkout 的 `cache/live/`,卡片便永远停在主 checkout
最后看到的那个事件上;修复是把所有写方/读方/安装器统一解析到**主 worktree**(`bin/_repo-root.sh`
/ `bin/_repo_root.py`,经 `git rev-parse --git-common-dir`),并让 `install.sh` 始终把 hook 注册到
主 checkout。

## 症状
活跃会话的 jsonl 很新鲜(秒级),但其 `cache/live/<sid>.json` 停在几小时前的 `UserPromptSubmit`,
卡片永远「进行中」下不来。曾试过 `e78a8d3` 用 transcript-mtime 当 ground-truth 兜底,旋即在
`d0b6890` 撤回(「回到 hook 改状态」)——本次按要求做根因修复,不再加 transcript 兜底。

## 诊断
1. 直接喂事件给脚本,hook 链本身正确(`UserPromptSubmit→running`、`Stop→done_unread`)——脚本逻辑没坏。
2. 实证:用**worktree 里的** `live-state.py` 处理一个事件,写入落到了 `worktree/cache/live/`,主
   checkout 的 `cache/live/` 里**没有**该文件——serve 自然读到旧值。
3. 根因:`live-state.py` / `record-location.py` / `live-hook.sh` / `refresh-bg.sh` / `install.sh`
   都用 `Path(__file__).parent.parent` 或 `dirname $0/..` 推 `cache/`。`install.sh` 同样如此——从
   worktree 跑安装,就把全局 hook 命令指向了 worktree 的 `bin/`,导致全系统的 live 写入跑偏。
   (排除项:全局 `~/.claude/settings.json` 当前指向主 checkout;`6cf80f5` 的 kill-switch 早退也
   已修。两者都不是本次根因。)

## 修复
- 新增 `bin/_repo-root.sh`(shell,sourced)与 `bin/_repo_root.py`(python):统一把根解析到
  **主 worktree**。解析顺序:`STRAY_REPO_ROOT` 环境变量(shell 入口设一次,python 子进程免 git 调用)
  → `git rev-parse --git-common-dir` 的父目录(共享 `.git` 在主 checkout)→ 朴素回退。永不抛错。
- 五个写方(`refresh-bg.sh`、`live-hook.sh`、`live-state.py`、`record-location.py` 经入口脚本)与
  管线(`pipeline-run.sh`、`layer2-trigger.sh`)、读方 `serve.py` 全部改用该解析器。
- `install.sh` 在注册前先归一化 `REPO_ROOT` 到主 checkout——即便从 worktree 跑安装,hook 与
  `stray` 软链也始终指向主 checkout。
- 容错:helper 缺失时(部分部署)`. _repo-root.sh 2>/dev/null || true` + `${STRAY_REPO_ROOT:-朴素}`
  回退,hook 绝不因此中断。

## 验证
从 worktree 路径跑 `live-hook.sh`(UserPromptSubmit)与 `refresh-bg.sh`(Stop):写入均落到**主**
`cache/live/`、worktree 无泄漏、状态正确翻转;无 `STRAY_REPO_ROOT` 时 git 回退同样解析到主 checkout;
helper 缺失时 hook 退出码 0 不中断。

## 备注(非本次根因,已被既有机制兜住)
管线自身的 `claude --no-session-persistence -p` 子调用会触发全局 hook,留下 `jsonl=NONE` 的
phantom「running」记录;`a242672`(serve 端 running 静默 300s 自动降级 idle)已把它们收口为 idle,
不再显形。若日后要彻底消噪,可给嵌套 `claude` 调用加 `STRAY_HOOK_SKIP=1` 环境标记并在 hook 入口早退。

# 贡献指南

本仓库改动的约定。写给未来的自己看，不是给陌生人。

英文原版：[../CONTRIBUTING.md](../CONTRIBUTING.md)

## 文档规范

| 文档类型 | 位置 | 何时新增 |
|---|---|---|
| 用户向安装/使用 | `README.md`（根）+ `docs/README.zh-CN.md` | 任何用户可见的 flag、命令或工作流变更 |
| 系统怎么跑 | `docs/ARCHITECTURE.md` + `docs/zh-CN/ARCHITECTURE.md` | 新增 pipeline 阶段、新 cache 文件、新组件 |
| 运维手册 | `docs/TROUBLESHOOTING.md` + 中文镜像 | 新的故障模式或新诊断能力 |
| 未来计划 | `docs/ROADMAP.md` + 中文镜像 | 决定延后；写明原由 |
| 非琐碎设计 | `docs/design/DD-NNN-slug.md` + 中文镜像 | 影响多文件、改 data 形状、或改外部 contract（hook、prompt、API） |
| 发布 / 分支 | `docs/RELEASE.md` + 中文镜像 | 改了分支模型、版本规则、或 release 流程本身 |
| 每个 release 的用户可见变更 | `CHANGELOG.md`（根目录） | 边改边记 — 加到 `[Unreleased]` 段，不要等发布前一次性补 |

**精炼优先**。每份文档要过"60 秒可扫读"测试。如果一份文档能帮 5
位未来读者但会让 7 位非读者不爽，宁可在 TROUBLESHOOTING 里加一条
可 `grep` 的条目，也不开新文档。

## 设计文档（DD-NNN）

写代码*之前*先写 DD，前提是：

- 改动跨越 3+ 文件
- 改动了 AI prompt 或 cache JSON schema
- 引入了新 IPC 面（hook、HTTP endpoint、CLI subcommand）
- 发现了根因需要解释的 bug（"事后 DD"——对非显然的坑很有用）

模板见 [design/README.md](design/README.md)。编号单调递增：下一个可用
编号是 `ls design/DD-*.md | tail -1 | sed 's/DD-\([0-9]*\).*/\1/'` + 1。

## Commit 消息

参考现有风格——`git log --oneline`。简单说：

- 主题行：祈使句、小写动词开头、不带句号、**控制在 72 字符内**
  - 好：`Fix stale card content and truncated session_ids`
  - 差：`Fixed the bug where cards weren't updating properly.`
- 正文 72 字符断行。讲 WHY，不讲 WHAT（diff 已经显示 what 了）。
- 多用途 commit 优先拆分。若不得不绑一起，正文要解释为什么绑。
- 不带 `Co-Authored-By: Claude` trailer——保持 log 干净。署名跨多
  commit 会很噪音。

## 何时 commit

默认是**每个逻辑工作单元完成时 commit**，不是几小时 session 完成
后一锅端。如果你发现自己已经改了 5+ 文件横跨 3 个特性，那你应该
已经至少 commit 两次了。

例外：和用户明确说好"统一回顾后一起 commit"。即便如此，commit
时优先拆分（`git add -p`），不要塞 mega commit。

## 给 `bin/mindmap` 加 flag

dispatcher 前面先把 flag 解析为 `DO_*` boolean，再按固定优先级分发。
套路：

1. 在 `for arg in "$@"; do case "$arg" in ...` 里加 case
2. 更新 `-h|--help` 分支的帮助文本
3. 如果 flag 委托给 Python，在解析循环之后用
   `exec python3 "$REPO_ROOT/bin/<script>.py"` 调用
4. 冒烟测试：`bash bin/mindmap --你的flag` 和 `bash bin/mindmap --help`

## 给 `serve.py` 加 endpoint

1. 决定 GET vs POST。GET 用于读/静态，POST 用于写/动作
2. 在 `Handler` 类里加 `_handle_<名字>` 方法
3. 在 `do_GET` 或 `do_POST` 里挂路由
4. CORS 已在 `_cors()` 设好——在 `end_headers()` 之前调用即可
5. 用 `self._reply(code, dict)` 返回 JSON
6. 在 `ARCHITECTURE.md` 文档化（cache 文件表或 server 段落）

## 改 AI prompt

`prompts/classify.md` 是分类器唯一的真相源。两个失败模式要防：

- **漂移**：prompt 累积膨胀直到自相矛盾。加新段前先从头到尾通读
- **输出欠规范**：AI 返回短 id、漏字段、用错语言。给任何你关心的
  不变量加上自检段落 **和** `refresh.sh` 里的后处理修复（双保险）

prompt 改动后 force 一次真实 refresh 看 DIFF 输出
（`mindmap --refresh && tail Library/Logs/claude-stray.log`）。
如果 `DIFF vs prior` 显示 initiative `id` 被改名或 `done` 反弹回
`false`，说明 prompt 改动破坏了连续性。

## Cache 文件变更

cache 是 gitignore 的——schema 变更外部不感知。迁移是贡献者的责任：

- 升 `mindmap.json.schema_version` 需要 `render.py` 和 `render-html.py`
  里有至少一个版本的 fallback 路径
- 新字段：优先可选，代码默认为安全值，不要强制全量迁移
- 删字段：先废弃（继续写但不消费），几周后再真删

## 测试

没有单元测试。判断"东西没坏"的信号层级：

1. `python3 bin/render.py` 对当前 `cache/mindmap.json` 跑不报错
2. `bash bin/refresh.sh` 干净退出（force 或 hash-skip 都行）
3. `mindmap --diagnose` 对活跃 session 报全绿
4. `mindmap --serve` 起得来，能服务 `/`，能接受 `/api/save`，能
   Ctrl-C 干净退出
5. Playwright 冒烟测试打 `http://127.0.0.1:9876/`
   （`/tmp/playwright-test-*.js`）

重构前后跑齐这五项。

# DD-026 — 外部资源模块:URL 解析(已做)+ 优化待办(后做)

> 状态:**URL 解析已落地**(commit eb00ae0)。其余优化轴**记账待办**,当前焦点不在此,
> 先把**子卡(DD-025)做好做完**再回来。

## 背景

外部资源 = 一条 session 衍生的、可在浏览器打开的后续落点(MR/PR/CR/ISSUE/deployment/doc)
+ 代码位置(branch/tag/worktree/dir)。这是对标 Agent View 的**护城河**之一:它只认
GitHub PR,内网 Aone 的 CR/MR/需求它进不来,我们能。

## 已做:机械 URL 解析(根治「url-less 灰条」)

**问题**:AI(summarize Rule 10)常采到 `ref_id` 却采不到 `url`——完整链接只出现在
**更早轮次**或 **bash 输出(tool_result)**里,都在 summarize 的「最近 12 轮 + 砍 tool_result」
窗口之外。于是真实 MR 在面板里成了**不可点灰条**。

**解法**(`bin/_resources.py`,纯函数 + 单测;`serve._attach_resource_urls` 渲染期接线):
1. **回填(精确)**:扫整条 session jsonl,把 `codereview/<id>` `bug/<id>` `req/<id>`
   `issue/<id>` 链接按尾号建 `ref_id→url`,补到缺 url 的 artifact 上。最近一次提及为准。
2. **重建(兜底)**:url 全程没出现时,从 session repo 的 `git remote get-url origin`
   + ref_id 重建 `<web_base>/codereview/<id>`(仅 mr/cr/pr;aone issue 需 project id,跳过)。
   注意:跨仓 MR 重建可能 404 → 精确回填永远优先,重建仅兜底,并打 `url_source`
   (`harvested` / `reconstructed`)以便区分。

只有「含 url-less ref 的卡」才读 jsonl;jsonl 按 mtime 缓存、remote 按 cwd 缓存,渲染期零 AI、
对所有现存卡立即生效。

## 待办(记账,后做 —— 当前专注子卡)

按用户 2026-06-08 选定的优先轴:

### 1. 采集可靠性(harvest)
AI 的 12 轮窗口会**漏**(本轮 27724957 就是)。加一道**机械 harvest**:扫全 jsonl 的
codereview/aone 链接,去重后**作为候选 artifact 补进来**(不只是给已采集的补 url)。
- 张力:DD-021 的初衷是**减噪**(别把每个路过的 CR 都收)。所以 harvest 不能无脑全收。
- 候选边界:只收**用户/AI 实际操作过**的(出现在 `a1 repo mr` 命令、push 输出、评论创建里),
  排除「只是浏览/引用」的链接。需要一个轻判据(命令动词 / 出现频次 / 是否本仓)。
- 形态:harvest 出的候选可标 `source: harvested` 与 AI 采的并存,UI 上可弱化展示。

### 2. 排序与主次
当前一视同仁平铺。应:**当前卡的「主 MR」置顶**(最近操作 / 本仓 / pending 优先),
其余按最近提及降序。可能需要一个 `primary` 标记或排序键(last_mentioned_at + 状态权重)。

### 3. 视觉 / 交互
灰条、悬浮列、hover 展开那套再打磨:配色(按 type/状态)、密度、点击行为(打开 / 复制 /
预览)。注意用户此前在面板 UI 上已迭代很多次,**别推倒重来**,只做增量。

### 4. 状态语义更厚(用户想做,但**明确押后**)
MR 显示评审态(待评审/已合并/已关闭)配色、CI/发布状态、谁在等评审——让一眼看出资源处于
哪个阶段。**当前不做**,先记着。

## 关键文件
- `bin/_resources.py`(URL 解析,已做)、`bin/serve.py::_attach_resource_urls`(接线)
- `bin/cockpit.html`(渲染:`isExternal` / `chip` / `renderTermRes` / `extArts`)
- `prompts/summarize-session.md` Rule 10(源头采集原则,DD-021)

## 验证(已做部分)
`tests/test_resources.py` 7/7;真会话:`27724957`(runtime-sar)、`27821892`(ops-portal)
经 `harvested` 补齐为可点链接。

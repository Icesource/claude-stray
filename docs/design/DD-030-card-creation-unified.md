# DD-030: 创建卡 / 子卡 —— 统一身份、就地丰富、消灭交接

**Status**: Accepted (grilled to convergence with user, 2026-06-10)
**Author**: Claude (with user)
**Date**: 2026-06-10
**Predecessors**: DD-025(并行子卡)、DD-027(即时公民)、项目转向「card = one session」、
本轮已提交修复(id 稳定 `aee4583`、删除按 session 墓碑 `fba8a0a`、subcards 文件锁 `7a14f55`、
tab 同步 `1fcdd9a`、live 新鲜窗口 `f655ef6`)
**Supersedes**: DD-027 的「pending 占位卡 + 真卡交接」机制(bug 源,退役)

## 为什么(病根)

「手动建主卡 / 建子卡」这个本该简单的功能产出了无数 bug。根因:**一张卡有两个身份,
中间靠一次脆弱的交接**:

1. 创建时拿到占位卡 id=`pending-<token>`(锚 token),存 `pending-cards.json`,显示准备中。
2. classify 另铸真卡 id=`subcard::<sid>` 或 AI slug(锚 sid)。
3. `merge_into_mindmap` 在真卡出现后丢掉占位卡。

身份中途变了,且交接**依赖 AI 管线成功**。于是:
- summarize/classify 没跑(hook 漏)→ 占位卡永远等不到「被代表」→ **永久卡准备中**。
- 真卡用新 slug → 钉旧 id 的墓碑/focus/终端全错位 → **消失/改名/重复**。
- 两个注册表(pending + subcards)要互相对上 → 竞态 → **浮顶/丢子卡**。
- 为塞 pending 特例,band 逻辑被污染 → **「之前没问题的状态转换」被搞乱**。

## 北极星不变量

**一条 session = 一张 `card::<sid>` 卡。** 创建动作只是「让卡瞬间出现 + 绑 sid/父/worktree」,
之后管线**就地丰富**它,身份永不变。没有第二张卡,没有交接。

## 设计决策(Q1–Q9 收敛)

### 1. 身份与存储
- 卡 id = **`card::<sid>`**(锚 session_id)。约 10 秒前奏期(还没 sid)临时用创建 token 显示,
  捕获 sid 后定型,再不变。
- **唯一缓冲** `cache/created-cards.json`(取代 `pending-cards.json` + `subcards.json`):
  `{token → {sid, name, cwd, worktree, parent, initial_task, created_at}}`,单文件单锁(fcntl)。
  它只是「classify 还没吸收这张卡」的几十秒过渡;卡进 dashboard 后,**父链接拷到卡身上
  (carry-forward 永久保留)**,缓冲条目丢弃 → 稳态缓冲为空,**无「在册/不在册」之分**。

### 2. 认领(保证只有一张卡)
- classify 对每个「已捕获 sid 的缓冲条目」**强制把该 session 收进 `card::<sid>`**,
  从任何 AI 卡剥离;AI 的好名字/进展**拷过来**填充。`dedup_by_session` 兜底。
  (= 把现有 `mint_subcard_initiatives` 证明可行的机制,推广成主卡也走。)
- **纯命令行起的会话照旧自动发现**(AI slug + id 稳定),**同样能认父、被建子卡**
  —— 父只认 sid,不认注册表成员;所以「给自动发现卡建子卡」和「给创建卡建子卡」同一条路。

### 3. 准备中 / 可打开 / 状态(正交三件事)
- **准备中徽章** = `cache/summaries/<sid>.md` 不存在。一有 summary 立刻摘,转正常卡。
- **可打开** = sid 已捕获(不等 summary)→ 准备中也能开终端/注入,修掉「打不开关联会话」。
- **band** = 永远走规范 live→classify 逻辑;准备中只是叠加徽章,**删除 `bandFor` 里
  `if(init._pending) return running` 这种特例**(这是「状态转换一团糟」的根)。
- 准备中期间卡名 = 初始任务文本(截断),没有则「准备中…」。

### 4. 触发(单机制)
- **单 hook 机制**;**根治 tmux-spawn**,让子卡会话像常规会话一样持续触发 Stop hook。
  **不加 serve 对账循环**(避免双份复杂度)。证据:常规新会话(ops-portal 主卡)hook 正常触发并被总结;
  仅 detached-tmux spawn 的子卡只触发一次 → 是 spawn substrate 的问题,不是 hook 本身。

### 5. 子卡
- = 带独立 worktree 的会话 + 父链接(认父 sid)。入口 = 主卡终端视图里「+子卡」,父隐式 = 当前卡。
- 价值 = 并行支线 + 合并回主干(对 Agent View 的差异点)。

### 6. 消失规则
- **空卡(0 轮)/失败 launch → TTL(15 分钟)自动清**;**有内容(≥1 轮)永不自动消失**,只手动删。
- 删除 = 清缓冲条目 + session 墓碑(防复活,DD-029)+ 子卡删 worktree+分支。永远只由用户触发。

### 7. 复用地基(不推倒重来)
- id 稳定、删除按 session 墓碑、文件锁、tab 同步、live 新鲜窗口 —— 全保留,是新模型地基。
- 退役的只有「pending + subcards 双表 + 占位卡交接」那套 bug 源。

## 范围边界(本次 = 甲)
- 本次只统一「创建/子卡」这条线。**全盘机械化(每张卡都 `card::<sid>`、classify 退化为纯机械装配、
  不再 AI 聚类)= 乙,留作单独一步**(动整个看板,风险大)。自动发现卡保持 AI slug,但功能不分裂。

## 交付分片(每片带测试)
1. 缓冲层 `created-cards.json` + 锁 + token→sid 捕获(替换 `_pending`/`_subcards` 读写口)。
2. classify 认领:`mint_subcard` 推广为「所有创建卡认领进 `card::<sid>` + 父链接上卡 + carry-forward」。
3. 准备中/可打开/band 解耦:cockpit `bandFor` 删 pending 特例;准备中降级徽章;可打开看 sid。
4. **tmux-spawn hook 根治**(先给根因再动手)。
5. 消失规则:TTL 空卡清 + 删除墓碑 + 子卡 worktree 清,统一一处。
6. 迁移:旧双表活条目迁入新缓冲(尊重墓碑),退役旧文件。
7. 端到端测试:新建主卡→准备中→说话→正常;建子卡→嵌父→合并→关闭;命令行会话仍自动成卡;
   删除不复活;全程状态准确。

## 验证基线(交付即「无明显 bug」)
- 新建主卡:点创建后**立刻**出现准备中卡;说一句话后 ≤60s 转正常卡(同一张,id 不变)。
- 建子卡:主卡视图点 +子卡 → 立刻嵌在父卡下的准备中子卡;有独立 worktree;可开终端。
- 状态:准备中卡也能正确显示 等你/进行中;正常卡状态转换不被污染。
- 删除:删掉的卡两次 classify 都不复活。
- 命令行会话:不走平台,照样自动成卡、可被建子卡。

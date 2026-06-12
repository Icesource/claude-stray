---
name: stray-subcard
description: >
  One-shot delegation: spin the CURRENT conversation's small task off into a
  single stray sub-card (own worktree + session + card), seeded with enough
  context to run independently — freeing this main session immediately.
  Activate on /stray-subcard <task>, or phrases like "拆个子卡去修这个,别占
  主卡" / "这个小问题开张子卡去搞" / "delegate this to a sub-card". The
  EXPLICIT invocation with a task IS the user's confirmation — spawn at once,
  no extra confirm round (unlike stray-subcards, which drafts a multi-item
  split and waits for approval). Do NOT use the built-in Task tool / background
  agents as a substitute — those are invisible to the stray dashboard.
---

# stray-subcard — 把当前对话里的一件事,一次性委派给一张子卡

## 核心差异(vs `stray-subcards`)

| | stray-subcard(本 skill) | stray-subcards |
|---|---|---|
| 场景 | 对话中冒出的**单件**小活,主卡不想久占 | 梳理出 **N 件**独立事项,fan out 并行 |
| 确认 | **调用即确认**(用户敲命令带任务 = 明确意图) | 先列切法,等用户点头才 spawn |
| 产出 | 1 张子卡,立刻回到主线 | N 张子卡 |

## 工作流(快进快出,目标是 30 秒内还给主卡)

1. **写种子任务(这是本 skill 的全部价值)** —— 子卡看不到本对话,种子必须自包含:
   - 一两句背景:这是什么系统/仓库,问题出现在哪;
   - 问题陈述:症状原话、报错原文(有就带上)、复现方式;
   - 指路:相关文件路径、函数名、相关的近期提交/设计文档;
   - 已知信息:本对话里已经排查到/排除了什么(别让子卡重走弯路);
   - 验收标准:什么算修好(测试绿、行为 X);
   - 收尾要求:**把工作 commit 掉**(未提交的改动无法走合并闭环),如适用跑全套测试。
2. **spawn 一张**(Bash 工具,在工作所属 repo 目录下):
   `stray spawn "<种子任务>" --name <短slug>`
   (它用 `$CLAUDE_CODE_SESSION_ID` 当父卡;一次调用只开一张。)
3. **报告并退出**:告诉用户卡名 + 已开跑,然后**立刻回到主线话题**。不轮询、
   不跟进 —— 用户从驾驶舱(http://127.0.0.1:9876/)看进展、按需 `stray subtasks` 拉摘要。
4. 子卡干完后的合并/落地在驾驶舱点按钮完成,不在本对话操作。

## 规则

- args 为空 → 问一句「要委派哪件事?」,不要猜。
- 一次调用 = 一张卡。用户一句话里有多件事 → 建议改用 /stray-subcards 拆分流程。
- 种子里**不要**塞整段对话原文 —— 提炼成上面的结构化要点(子卡上下文宝贵)。
- spawn 失败(serve 没起 / 不在 git 仓库 / 无 tmux)→ 把错误和修复提示带给用户。
- 绝不用内置 Task 工具 / `claude agents` 代替 —— 那些对 stray 不可见,不是子卡。

---
name: stray-progress
description: >
  Pull ALL sub-cards' progress into the CURRENT (parent) conversation in one
  shot and summarize it for action. Activate on /stray-progress, or phrases
  like "子卡们怎么样了" / "同步一下子卡进展" / "孩子们干完了吗" / "how are my
  sub-cards doing". One-shot pull (`stray subtasks`), never a polling loop.
---

# stray-progress — 一把拉齐所有子卡进展

## 做什么

1. **拉数据**(Bash 工具,本会话内):`stray subtasks`
   —— 低 token 摘要 JSON:本会话每张子卡的 名字 / session_id / 状态 /
   进展首行 / 卡点 / 下一步 / worktree / 分支。
2. **按可行动性汇总**(不是罗列,是分诊),输出三段:
   - **要你管的**:卡在等用户(needs_you / blockers 非空 / 停在 trust 确认)
     —— 每张一行:卡名 + 卡在哪 + 建议动作(去它终端答一句 / 点合并 / 落地);
   - **在跑的**:正常推进中 —— 卡名 + 进展一句话,不展开;
   - **干完的**:状态 done/已合并 —— 提示「可在驾驶舱点合并→落地收口」。
3. 结尾给一行总账:`N 张子卡:X 等你 / Y 在跑 / Z 完成`。

## 规则

- **一次性拉取,绝不自主轮询**(单驾驶员原则;用户要更新就再说一次)。
- 子卡为空 → 一句话说明,别空表格。
- `stray subtasks` 报错「无 $CLAUDE_CODE_SESSION_ID」→ 必须经 Bash 工具在
  Claude Code 会话内跑;报「serve 没在跑」→ 提示 `stray --serve`。
- 想深入某一张时:引导用户开它的终端(驾驶舱/会话族侧栏),或用
  `stray send <session_id> "<一句话>"` 转一条消息进去 —— 不要替它干活。
- 这是「父拉子」的按需同步;被动同步已有惰性 hook(子卡动态会自动作为上下文
  附在你每轮输入里),本 skill 用于你想要**完整一览**的时刻。

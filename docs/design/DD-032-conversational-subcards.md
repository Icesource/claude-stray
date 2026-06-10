# DD-032: 对话创建子卡 —— stray-subcards 独立 SKILL

**Status**: Accepted (grilled with user, 2026-06-11 夜)
**Author**: Claude (with user)
**Predecessors**: DD-025(并行子卡)、DD-030(创建卡统一)、DD-031(合并闭环)
**补齐的空白**: 黄金场景「主卡梳理 → fan out → 并行 → 合并收口」的**开头**。
spawn/subtasks/send 三原语早已在 `stray` CLI 里,但「主会话懂得用它们」此前
只活在用户私人的 `~/.claude/CLAUDE.md` 指令块里,不是产品的一部分。

## 决策(Q1–Q3 收敛)

### Q1 分发形态 = 新建独立 skill `stray-subcards`
- 不扩展现有 stray SKILL(它的定位是「管理动作」,且 description 明确声明
  不做 agent 工作 —— 塞进去语义自相矛盾、触发变胖)。
- 不走安装时注入用户 CLAUDE.md(永驻上下文吃 token、侵入性最强)。
- 仓库内放 `skills/stray-subcards/SKILL.md`;`bin/install-skill.sh` 两个一起装
  (`~/.claude/skills/stray/` + `~/.claude/skills/stray-subcards/`),
  uninstall 同步移除。

### Q2 触发与自主边界 = 显式触发 + 可提议,拆分须确认
- 用户说「子卡/拆出去/并行跑/fan out」才动手。
- Claude 看到对话里出现明显可并行的独立事项,**可以提议一句**,但绝不
  自动 spawn。
- 拆分方案(几张卡、每张的任务 prompt)必须先列出来等用户点头再执行 ——
  「用户决定拆分」是 DD-025 以来的不变量。
- 子卡任务 prompt 必须自包含(子会话看不到父对话),并要求 commit
  (未提交的工作合并不回来,呼应 DD-031 pre-check ②)。

### Q3 合并入口 = 今晚不开对话入口,引导去驾驶舱
- skill 只覆盖 spawn / subtasks / send;子卡做完后提醒用户去驾驶舱点
  「合并」(DD-031 的按钮路径)。
- 理由:DD-031 刚落地,先让按钮路径经受真实使用;对话触发合并是个小 DD,
  验证后再补。「落地人类一闸」原则不被稀释。

## 不变量(继承自产品哲学)
- 子卡 = `stray spawn` 一种创建方式;内置 Task 工具/后台 agent 不是子卡,
  skill 里明文禁止替代。
- 单驾驶员:不许对子卡跑自主协调循环;`stray subtasks` 只在用户问时拉。

## 交付
1. `skills/stray-subcards/SKILL.md`(触发词、三原语、六步工作流、反模式)。
2. `bin/install-skill.sh` 装两个 skill;`bin/uninstall.sh` 移除两个。
3. 本机安装生效;用户私人 CLAUDE.md 的旧指令块由用户在验证后自行删除
  (两者语义一致,共存无冲突)。

## 验证基线
- 新会话里说「把 X/Y 拆成子卡」→ skill 激活 → 列出拆分方案 → 确认后
  逐条 `stray spawn` → 驾驶舱出现嵌套子卡。
- 「子卡们咋样了」→ `stray subtasks` 摘要。
- 子卡 done → Claude 引导去驾驶舱合并,而不是自己 git merge。

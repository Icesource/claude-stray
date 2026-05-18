# 设计文档

非琐碎改动在代码落地**之前**先写一份编号 DD 放这里。何时写见
[../CONTRIBUTING.md](../CONTRIBUTING.md#设计文档dd-nnn)。

英文原版：[../../design/README.md](../../design/README.md)

## 索引

| ID | 标题 | 状态 |
|---|---|---|
| [DD-001](DD-001-two-pass-classification.md) | 两段式分类：用每 session AI 摘要替代硬压缩 | Superseded by DD-002 |
| [DD-002](DD-002-ai-pipeline-redesign.md) | AI Pipeline 重设计（三层 + 冷热 + dirty tracking + coalesce） | 已实施（P14）|
| [DD-003](DD-003-card-detail-and-artifacts.md) | 卡片详情 modal：artifact 提取（CR/issue/branch）+ 卡点追踪 | 已实施（P15）|
| [DD-004](../../design/DD-004-circuit-breaker-and-alarm.md) | 成本熔断器 + 异常告警（日预算、速率监控、面板 banner） | **Proposed** |
| [DD-005](../../design/DD-005-lifecycle.md) | 生命周期 / opt-in 运行模式（pause/resume、serve-only） | **Proposed** |
| [DD-006](../../design/DD-006-card-derived-ai-features.md) | 基于卡片的 AI 派生功能（周报、下一步建议、tips、暖心提醒） | **Proposed** |
| [DD-007](../../design/DD-007-agent-auto-runner.md) | 卡片驱动的 AI 代理自动推进 | **Idea-stage，需要 POC** |
| [DD-008](../../design/DD-008-task-aggregation-and-archive.md) | Task 聚合、按 slug 去重、cap + 归档 | 被 DD-011 取代 |
| [DD-009](../../design/DD-009-task-ownership-and-completion.md) | Task 绑定 session 所有权 + 语义去重 + AI 辅助完成态推断 | 被 DD-011 取代 |
| [DD-010](../../design/DD-010-tasks-additive-only.md) | Task 是 AI-additive-only / 用户才能删除(2026-05-18 数据丢失事故后) | 被 DD-011 取代 |
| [DD-011](../../design/DD-011-task-model-final.md) | Task 模型最终版：三态 status(pending/done/cancelled)、删除归档目录、AI 可以基于证据取消任务 | Accepted |

## 模板

复制以下骨架到 `DD-NNN-<slug>.md` 填充：

```markdown
# DD-NNN: <标题>

**Status**: Proposed | Accepted | Implemented | Rejected | Superseded by DD-MMM
**Author**: <名字>
**Date**: YYYY-MM-DD

## 问题

今天哪里不对。用具体证据：一个失败案例、一个指标、一句用户原话。
不要写"要是 X 就好了"。

## 目标 / 非目标

成功的样子。bullet 列表。明确什么不做。

## 方案

实际设计。欢迎用图（纯文本 ASCII 框）。逐组件描述。指明具体文件路径、
函数名、schema 字段。

## 按组件列改动

表格或列表，每个被动到的文件配一行总结。让 review 可行。

## 迁移

如果改了 schema 或不变量，已有装置怎么从旧到新。

## 成本 / 风险

token 成本、延迟、失败模式。诚实写明可能出什么问题。

## 拒绝的方案

考虑过但拒绝的，每个写明为什么。未来的自己会感谢现在的自己。
```

## 约定

- **编号单调**。拒绝的 DD 不要回收编号
- **状态向前推进**。DD 落地后改 Status 为 `Implemented`，加一行
  `commit: <sha>`。不要删除
- **被拒绝的 DD 留着**。它是"为什么我们没做 X"的机构记忆
- **长度是 smell**。比实现还长的 DD 通常想多了。目标 ≤ 500 行

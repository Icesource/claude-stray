# claude-stray 文档（中文）

内部开发文档。用户向的安装/使用说明在根目录的 [`README.md`](../../README.md)；
对应中文版是 [`docs/README.zh-CN.md`](../README.zh-CN.md)。

英文原版索引：[`docs/README.md`](../README.md)。

| 文档 | 用途 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统是怎么跑起来的：pipeline 各阶段、cache 文件清单、并发情况、关键不变量 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | commit/PR 规范、文档规范、何时该写设计文档 |
| [RELEASE.md](RELEASE.md) | 分支模型（`main` / `stable` / topic）、SemVer 规则、release 检查清单、hotfix 流程 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | "卡片没更新"、"hook 没触发"、"AI 输出错"等问题的决策树，配合 `mindmap --diagnose` 使用 |
| [ROADMAP.md](ROADMAP.md) | 已规划但还没落地的功能 + 设计原由 |
| [design/](design/) | 设计文档（DD-NNN），非琐碎改动先写文档。模板见 [design/README.md](design/README.md) |
| [../../CHANGELOG.md](../../CHANGELOG.md) | 按 release 维度的用户可见变更摘要，Keep-a-Changelog 格式 |
| [../../PLAN.md](../../PLAN.md) | 历史设计笔记（已冻结，v1 之前的思考） |

## 阅读顺序

- 新贡献者 → ARCHITECTURE.md → CONTRIBUTING.md → DD-001
- 排查卡住的卡片 → TROUBLESHOOTING.md
- 加新功能 → ROADMAP.md → design/README.md（非琐碎改动写 DD）

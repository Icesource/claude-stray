# DD-033: Layer-2 机械化 —— classify 从「作者」降为「装订工」

**Status**: Implemented 2026-06-11(切片 1-5 全部完成;生产 cache 迁移在合并入 main 时执行 `bin/_migrate_card_ids.py`)
**Author**: Claude (with user)
**Predecessors**: 北极星转向 2026-06-04(卡=单 session)、DD-013/014/020(status/level/attention
已机械化)、DD-011/021(tasks/artifacts 机械聚合)、DD-029/030(id 钉死、创建卡机械铸造)

## Why

北极星(2026-06-04)已裁定:工作单元 = 一条 session,卡 id = session id,跨会话聚类是推测
复杂度。这判了 Layer-2 AI 的死刑,但一直未执行。现状是一个奇观:classify 调一次 AI,然后跑
**九道机械工序推翻它的输出**——

| 防御工序 | 对抗的 AI 行为 |
|---|---|
| `stabilize_card_ids_against_prior` (DD-029) | 每轮乱换卡 id |
| `enforce_carry_forward_initiatives` | 丢上一轮的卡 |
| `enforce_cold_and_terminal_monotone` | 乱改冷卡/已完结任务 |
| `enforce_hot_initiative_status` (DD-013) | status 不可靠,机械重算 |
| `enforce_level_ceiling` (DD-014) | level 不可靠,**AI 输出直接忽略** |
| `aggregate_tasks` / `aggregate_artifacts` (DD-011/021) | 丢任务/丢资源,从源头机械重建 |
| `dedup_by_session` (DD-016) | 一件工作铸两张卡 |
| `mint_subcard_initiatives` (DD-025/030) | 丢用户刚建的子卡 |
| 写入前 race-guard 重扫墓碑 | AI 跑得慢(分钟级),期间用户的删除被写回 |

AI 被实际采纳的产出只剩**给卡起名字**(聚类在卡=session 后无意义)。为一个起名功能,养着
一条分钟级延迟、每轮花钱、需要九道工序看管的管线。卡消失/改名/重复/复活整族 bug
(DD-029 及 2026-06 连环修)的根因——「AI 每轮重新生成全局 + 跑得慢产生时序窗口」——仍在。

## 决议(2026-06-11 grill 记录)

1. **理念**:Layer-2 作为管线阶段保留(必须有人把 N 份每会话摘要装订成一份全局
   dashboard),作为 AI 决策者退役。**全局层零 AI;AI 全部退到 Layer-1**(每会话视角,
   北极星点名的差异化)。将来若需跨会话智能(合并建议、日报),做只提建议、不碰
   dashboard 的旁路。
2. **卡名下沉 Layer-1**:summarize frontmatter 新增 `title:`(≤24 字语义名)。防抖沿用
   prior 回喂模式(同 prior_tasks/prior_sealed_segments):上一轮 title 注入 prompt,
   不重译不改名,除非工作目标实质变化。用户改名(override)永远最高优先。
3. **存量卡名零空窗**:25 张活跃卡全有名(生产数据核实),装配器从上一版 dashboard 继承
   `name`,无需批量补跑。`title` 只服务新 session。
4. **老卡 id 一次性统一迁移**为 `card::<sid>`(生产 23 张 slug 卡),同步改写
   deleted_ids.json / user_overrides.json / archive 目录引用;迁移前整份 cache 备份,可回滚。
   此后全系统单一 id 形态,零特例。
5. **切换节奏:短对照一步切**。真实 cache 快照上新旧两版各跑一遍(`--output`)diff 对照 +
   隔离环境(STRAY_*)集成测试,验收即切默认、跑迁移、同一 PR 拆 AI 路径。回滚 = cache
   备份 + git revert。
6. **thread 级移除**(北极星点名;生产仅 5 张,降为 card,纯视觉变化)。chip(封存片)保留。
7. **手动合并卡退役**:`initiative_links.json` 不再读取(生产核实:唯一一组合并对应的卡
   已不在活跃 dashboard,损失为零)。文件留档不删。
8. **范围**:本 worktree 先机械化,再做外部资源模块打磨(资源模型下沉因地基干净而变薄)。

## 方案:机械装配器 `bin/_assemble.py`

### 输入

`cache/summaries/*.md`(全部)、上一版 dashboard.json(名字/单调不变量的继承源)、
created-cards.json + subcards.json(创建卡注册表)、墓碑(archive 目录 + deleted_ids.json,
id 级 + session 级时间窗)、user_overrides.json(task_toggles / deleted_tasks /
hidden_artifacts)。

### 装配规则(每条合格 session → 一张卡)

合格 = 有 summary 且未被 session 墓碑压住,且(user_turns ≥ MIN_TURNS 或 created 注册
或 prior 已有其卡)。

| 字段 | 来源(机械,零 AI) |
|---|---|
| `id` | `card::<sid>`(迁移后全局唯一形态) |
| `name` | prior.name → fm.title → `# 目标` 首句 → workspace 名 |
| `status` | status_guess 映射:done→done;paused/abandoned→paused;else active(即 DD-013 规则在单 session 下的退化形) |
| `summary` / `progress` | body `# 目标` / `# 当前状态` 节(DD-020 同源) |
| `next_step` / `awaiting_user` | frontmatter 同名字段 |
| `tasks` | prior 单调并集 + summary frontmatter(DD-011 不变量与 shrink 守卫保留) |
| `artifacts` | prior 单调并集 + summary frontmatter + hidden_artifacts 过滤(DD-021 不变量保留) |
| `blockers` | frontmatter `blockers:` 列表 |
| `level` | sealed→card;≤1 task 且无 artifacts/blockers→chip;else card(thread 移除) |
| `sessions`/`linked_cwds`/`last_activity_at` | `[sid]` / `[cwd]` / fm |
| workspace 归属 | `_ws_name_for_cwd(cwd)`(worktree 归主仓) |

封存片照 `mint_sealed_initiatives` 原逻辑铸造(`sealed::` id、空 sessions、从活卡剥离
已封存 artifacts/tasks)。父子链接不入 dashboard(serve `_subcards.link` 渲染期附加,不变)。
user overrides 的 task 改动直接烘焙(逻辑迁自 `apply_user_overrides_inplace`)。

### 拆除(随切换删除)

`build_prompt` / `slim_prior` / `call_claude` / `parse_ai_output` /
`prompts/classify-cross-session.md`;九道防御工序全部(职责被「直接构造」吸收);
MAX_HOT 截断(无 prompt 体积约束);race-guard(亚秒级构建,墓碑在写入时即时读取)。
`classify.py` 保留为 CLI 入口壳(`layer2-trigger.sh` / `pipeline-run.sh` 零改动),
内部委托 `_assemble.py`。

### 验收等价定义(新旧 diff 对照)

按 session 对齐两份 dashboard 后:卡集合一致(±墓碑时序)、名字一致(继承)、状态一致、
workspace 分组一致、artifacts/tasks 不丢(单调不变量保持)。允许的差异:id 形态
(slug→card::<sid>,经映射等价)、thread→card 降级、字段顺序。

## 收益 / 风险

**收益**:classify 分钟级+每轮 Haiku 成本 → 亚秒+零成本;「准备中」窗口缩到秒级;
卡消失/改名/复活整族时序 bug 根除;classify.py 约砍半;后续功能免写「防 AI」层。
**风险**:新 session 卡名质量依赖 Layer-1(title 防抖规则缓解);迁移脚本一次性
(备份回滚兜底);dashboard 形状下游(serve/cockpit/render/测试)回归(diff 对照 +
隔离环境验收兜底)。

## 切片

1. ✅ 本文档
2. Layer-1 `title:` 字段(prompt 规则 + prior 回喂)——纯增量先合
3. `_assemble.py` + 单测 + `classify.py --mech` 开关
4. 真实 cache 快照 diff 对照 + 9877 隔离 serve 目检
5. 切默认 + `_migrate_card_ids.py` 迁移 + 拆 AI 路径 + cockpit 去 thread + 文档对齐
6. (后续)外部资源模块五切片(DD-021/026 路线)

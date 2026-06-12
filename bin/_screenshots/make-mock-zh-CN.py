#!/usr/bin/env python3
"""Generate fake-but-plausible mock data for the claude-stray dashboard,
suitable for marketing screenshots. Writes into the current repo's cache/.
"""
import json, pathlib, datetime

now = datetime.datetime.now(datetime.timezone.utc)
def iso(delta_h=0):
    return (now - datetime.timedelta(hours=delta_h)).strftime("%Y-%m-%dT%H:%M:%SZ")

# session uuids that look real
SID = {
    "applepay":  "a1b2c3d4-1111-2222-3333-444455556666",
    "applepay2": "a1b2c3d4-1111-2222-3333-444455556677",
    "a11y":      "b2c3d4e5-2222-3333-4444-555566667777",
    "fees":      "c3d4e5f6-3333-4444-5555-666677778888",
    "fees2":     "c3d4e5f6-3333-4444-5555-666677778899",
    "refund":    "d4e5f6a7-4444-5555-6666-777788889999",
    "fraud":     "e5f6a7b8-5555-6666-7777-88889999aaaa",
    "ml":        "f6a7b8c9-6666-7777-8888-9999aaaabbbb",
    "k8s":       "a7b8c9d0-7777-8888-9999-aaaabbbbcccc",
    "k8s2":      "a7b8c9d0-7777-8888-9999-aaaabbbbcccd",
    "cost":      "b8c9d0e1-8888-9999-aaaa-bbbbccccdddd",
}

# ---- mock dashboard.json ----
mm = {
  "schema_version": 2,
  "generated_at": iso(0),
  "workspaces": [
    {
      "name": "checkout-frontend",
      "cwd": "~/code/checkout-frontend",
      "last_activity_at": iso(2),
      "initiatives": [
        {
          "id": "checkout-applepay-integration",
          "name": "结账页 Apple Pay 集成",
          "status": "active",
          "summary": "在 web 结账流程接入 Apple Pay,iOS Safari 用户跳过手填卡步骤直接 Face ID 完成支付。",
          "progress": "merchant cert 已签发,后端 /payment/applepay/session 接口跑通。前端 PaymentRequest API 集成中,iOS 17 + 模拟交易已成功。等待 Stripe 后端测试环境放行后跑端到端。",
          "last_activity_at": iso(2),
          "sessions": [SID["applepay"], SID["applepay2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "obtain-merchant-cert", "title": "申请并下载 Apple Pay merchant certificate",
             "status": "done", "evidence": "merchant cert 已签发 + 上传至 prod",
             "terminal_at": iso(72)},
            {"id": "backend-session-endpoint", "title": "实现 /payment/applepay/session 后端端点",
             "status": "done", "evidence": "MR 27512348 已合并",
             "terminal_at": iso(48)},
            {"id": "frontend-paymentrequest", "title": "前端用 PaymentRequest API 接入",
             "status": "pending"},
            {"id": "e2e-staging", "title": "在 staging 跑端到端真实卡测试", "status": "pending"},
            {"id": "fraud-rule-tuning", "title": "Apple Pay 通道的 fraud rule 单独调阈值",
             "status": "cancelled", "evidence": "合并到「异常交易告警去重」",
             "terminal_at": iso(24)},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(checkout): Apple Pay session endpoint", "ref_id": "27512348",
             "url": "https://code.example.com/payments/checkout-frontend/codereview/27512348",
             "status": "merged", "last_mentioned_at": iso(48)},
            {"type": "mr", "title": "feat(checkout): wire up PaymentRequest API for Apple Pay",
             "ref_id": "27514102",
             "url": "https://code.example.com/payments/checkout-frontend/codereview/27514102",
             "status": "pending", "last_mentioned_at": iso(2)},
            {"type": "issue", "title": "Stripe staging env open up Apple Pay", "ref_id": "OPS-4471",
             "url": "https://aone.example.com/issue/OPS-4471",
             "status": "open", "last_mentioned_at": iso(6)},
          ],
          "blockers": [
            "等 Stripe 后端开通 staging Apple Pay 通道(OPS-4471 工单已提)",
            "等 iOS App Store Connect 上的 merchant ID 审核",
          ],
        },
        {
          "id": "card-input-a11y",
          "name": "卡输入字段无障碍优化",
          "status": "paused",
          "summary": "重做 CardInput 组件让 screen reader 能正确朗读字段类型和错误,符合 WCAG 2.2 AA。",
          "progress": "调研完毕,确定用 ARIA live region 报错。等设计组出新的视觉稿(用更高对比度的错误态颜色)。",
          "last_activity_at": iso(96),
          "sessions": [SID["a11y"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "wcag-audit", "title": "用 axe-core 跑一遍现有 CardInput 组件",
             "status": "done", "evidence": "audit 报告: 14 个 violations 已落 issue",
             "terminal_at": iso(120)},
            {"id": "aria-live-pattern", "title": "确定 ARIA live region 报错模式", "status": "done",
             "evidence": "POC 完成,3 种 screen reader 测试通过",
             "terminal_at": iso(108)},
            {"id": "new-design", "title": "等设计组新的高对比度错误态视觉", "status": "pending"},
            {"id": "impl", "title": "实现新组件 + 旧组件 fallback", "status": "pending"},
          ],
          "blockers": ["等设计组 Sarah 出高对比度错误态视觉(预计本周末)"],
        },
      ],
    },
    {
      "name": "payment-service",
      "cwd": "~/code/payment-service",
      "last_activity_at": iso(4),
      "initiatives": [
        {
          "id": "fee-calc-refactor",
          "name": "费率计算引擎重构",
          "status": "active",
          "summary": "把交易费率计算从 if-else 链子换成规则表 + DSL,新增费率不用改代码。",
          "progress": "DSL 已定义,parser 实现完毕。现有 11 种费率规则全部迁移完成,unit test 覆盖率 94%。本周做 shadow run 跟旧引擎对账,差异 0 才上线。",
          "last_activity_at": iso(4),
          "sessions": [SID["fees"], SID["fees2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "dsl-spec", "title": "定义费率 DSL 语法", "status": "done",
             "evidence": "spec 已 review 通过", "terminal_at": iso(168)},
            {"id": "parser-impl", "title": "实现 DSL parser + AST", "status": "done",
             "evidence": "MR 27498012 已合并,coverage 96%", "terminal_at": iso(120)},
            {"id": "migrate-rules", "title": "把 11 种现有规则迁移到 DSL 表达",
             "status": "done", "evidence": "11/11 完成,所有 unit test 通过",
             "terminal_at": iso(48)},
            {"id": "shadow-run", "title": "灰度环境跑 shadow 对账,差异分析",
             "status": "pending"},
            {"id": "rollout-plan", "title": "拉一份 rollout 方案 + rollback 演练", "status": "pending"},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(fees): DSL parser implementation", "ref_id": "27498012",
             "url": "https://code.example.com/payments/payment-service/codereview/27498012",
             "status": "merged", "last_mentioned_at": iso(120)},
            {"type": "doc", "title": "费率 DSL spec v1.0",
             "url": "https://yuque.com/payments/fee-dsl-spec",
             "status": "unknown", "last_mentioned_at": iso(168)},
          ],
        },
        {
          "id": "refund-api-rate-limit",
          "name": "退款 API 限流",
          "status": "done",
          "summary": "给 /refund 接口加 token bucket 限流,防止脚本误调引发故障。",
          "progress": "已上线,限流规则:每商户 100 req/min,burst 50。生产观察 7 天,无误伤。",
          "last_activity_at": iso(180),
          "sessions": [SID["refund"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "design", "title": "选 token bucket 还是 leaky bucket", "status": "done",
             "evidence": "decision: token bucket(突发容忍)", "terminal_at": iso(240)},
            {"id": "impl", "title": "接入 Sentinel 实现限流", "status": "done",
             "evidence": "MR 27465901 已合并 + 灰度", "terminal_at": iso(200)},
            {"id": "monitor", "title": "上线后 7 天监控,确认无误伤", "status": "done",
             "evidence": "7 天 0 限流告警", "terminal_at": iso(180)},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(refund): Sentinel rate limit", "ref_id": "27465901",
             "url": "https://code.example.com/payments/payment-service/codereview/27465901",
             "status": "merged", "last_mentioned_at": iso(200)},
          ],
        },
      ],
    },
    {
      "name": "fraud-detector",
      "cwd": "~/code/fraud-detector",
      "last_activity_at": iso(8),
      "initiatives": [
        {
          "id": "anomaly-alert-dedup",
          "name": "异常交易告警去重",
          "status": "active",
          "summary": "同一笔异常被多个规则同时命中时,只对 oncall 发一条告警(带所有命中规则),不再 5 条狂轰滥炸。",
          "progress": "聚合窗口逻辑实现完毕(60s 窗口 + transaction_id 维度去重)。集成测试通过,等 reviewer 评审。",
          "last_activity_at": iso(8),
          "sessions": [SID["fraud"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "design-window", "title": "决定聚合窗口大小 + 去重维度",
             "status": "done", "evidence": "60s 窗口 + (txn_id, merchant_id) 双维度",
             "terminal_at": iso(72)},
            {"id": "impl-aggregator", "title": "实现聚合器", "status": "done",
             "evidence": "MR 27510445 已开,待评审", "terminal_at": iso(24)},
            {"id": "review-pass", "title": "等 reviewer 评审通过", "status": "pending"},
            {"id": "shadow-1day", "title": "shadow 跑 1 天观察去重比例", "status": "pending"},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(alert): 60s window + dedup by txn+merchant",
             "ref_id": "27510445",
             "url": "https://code.example.com/payments/fraud-detector/codereview/27510445",
             "status": "pending", "last_mentioned_at": iso(8)},
          ],
          "blockers": ["等 @zhao 评审(已 ping 2 次,等明天 standup)"],
        },
        {
          "id": "ml-model-v3-eval",
          "name": "欺诈模型 v3 评估",
          "status": "paused",
          "summary": "评估新模型 v3 跟 v2 的误报率 / 召回率,决定是否上线。",
          "progress": "数据科学组训练好 v3,在历史数据上 recall +2.1%、误报 -0.4%。但生产 shadow 还没跑(等算法侧准备 inference server)。",
          "last_activity_at": iso(216),
          "sessions": [SID["ml"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "offline-eval", "title": "历史数据上对比 v2 vs v3", "status": "done",
             "evidence": "v3 recall +2.1% / 误报 -0.4%", "terminal_at": iso(240)},
            {"id": "shadow-infra", "title": "搭 shadow inference server", "status": "pending"},
            {"id": "shadow-run-2w", "title": "shadow 跑 2 周对比", "status": "pending"},
            {"id": "rollout-decision", "title": "出推荐 / rollback 决策报告", "status": "pending"},
          ],
          "blockers": ["等算法组 @li 准备 v3 inference server(估计下周)"],
        },
      ],
    },
    {
      "name": "infra",
      "cwd": "~/code/infra",
      "last_activity_at": iso(12),
      "initiatives": [
        {
          "id": "k8s-upgrade-1-30",
          "name": "K8s 集群升级到 1.30",
          "status": "active",
          "summary": "把 prod / staging / dev 三套集群从 1.27 升到 1.30(跳两个版本,Anthos 不支持单跨)。",
          "progress": "dev 集群已升完,跑了 3 天无异常。staging 升级计划本周末执行。prod 等 staging 跑稳一周再动。",
          "last_activity_at": iso(12),
          "sessions": [SID["k8s"], SID["k8s2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "compat-audit", "title": "审计 deprecated API 用法 (1.27→1.30)",
             "status": "done", "evidence": "3 处 PSP 改 PSA,已修",
             "terminal_at": iso(168)},
            {"id": "dev-upgrade", "title": "dev 集群升级", "status": "done",
             "evidence": "dev 已升至 1.30,3 天运行正常",
             "terminal_at": iso(72)},
            {"id": "staging-upgrade", "title": "staging 集群升级(本周末)", "status": "pending"},
            {"id": "staging-soak", "title": "staging soak 1 周", "status": "pending"},
            {"id": "prod-upgrade", "title": "prod 集群升级", "status": "pending"},
            {"id": "rollback-plan", "title": "走通 rollback 演练", "status": "pending"},
          ],
        },
        {
          "id": "cost-dashboard",
          "name": "云成本看板搭建",
          "status": "archived",
          "summary": "本来要搭一个内部 Grafana 看 AWS / 阿里云分项成本。已合并到「FinOps 中心化平台」项目,不再独立推进。",
          "progress": "原计划暂停。后续走 FinOps 平台。",
          "last_activity_at": iso(720),
          "sessions": [SID["cost"]],
          "linked_cwds": [],
        },
      ],
    },
  ],
}

# ---- mock tips ----
tips = {
  "generated_at": iso(0),
  "tips": [
    {"kind": "curiosity", "text": "Git 首个版本由 Linus Torvalds 用 C 在 2 周内完成,他给自己起的项目代号是 \"the stupid content tracker\"。",
     "source_url": "https://en.wikipedia.org/wiki/Git"},
    {"kind": "curiosity", "text": "Markdown 是 2004 年 John Gruber + Aaron Swartz 一起设计的,目标是\"读起来像纯文本\"。",
     "source_url": "https://daringfireball.net/projects/markdown/"},
    {"kind": "curiosity", "text": "JavaScript 最初叫 Mocha,后来改 LiveScript,最终为了蹭 Java 热度才用现在的名字。",
     "source_url": "https://en.wikipedia.org/wiki/JavaScript"},
    {"kind": "curiosity", "text": "Python 名字取自喜剧团体《蒙提·派森》,创始人 Guido 是粉丝。从来不是来自蛇。",
     "source_url": "https://docs.python.org/3/faq/general.html#why-is-it-called-python"},
    {"kind": "curiosity", "text": "Debug 一词来自 1947 年,工程师从 Harvard Mark II 计算机继电器里捉出一只真实的飞蛾,贴在日志本上。",
     "source_url": "https://en.wikipedia.org/wiki/Software_bug#Etymology"},
    {"kind": "curiosity", "text": "Unicode 里的 'zero-width joiner' 是个隐形字符,用途是让阿拉伯/印度某些字母在显示时连写。",
     "source_url": "https://en.wikipedia.org/wiki/Zero-width_joiner"},
    {"kind": "curiosity", "text": "'OK' 这个词源自 1839 年波士顿一份报纸刊登的玩笑缩写 \"oll korrect\"。",
     "source_url": "https://en.wikipedia.org/wiki/OK"},
    {"kind": "curiosity", "text": "HTTP 的 418 状态码 \"I'm a teapot\" 来自 1998 年愚人节 RFC 2324,至今仍是正式协议。",
     "source_url": "https://en.wikipedia.org/wiki/Hyper_Text_Coffee_Pot_Control_Protocol"},
    {"kind": "wisdom", "text": "采菊东篱下,悠然见南山。— 陶渊明《饮酒·其五》",
     "source_url": "https://zh.wikipedia.org/wiki/%E9%99%B6%E6%B7%B5%E6%98%8E"},
    {"kind": "wisdom", "text": "明月松间照,清泉石上流。— 王维《山居秋暝》",
     "source_url": "https://zh.wikipedia.org/wiki/%E7%8E%8B%E7%B6%AD"},
    {"kind": "wisdom", "text": "竹外桃花三两枝,春江水暖鸭先知。— 苏轼《惠崇春江晚景》",
     "source_url": "https://zh.wikipedia.org/wiki/%E8%98%87%E8%BB%BE"},
    {"kind": "wisdom", "text": "山光悦鸟性,潭影空人心。— 常建《题破山寺后禅院》",
     "source_url": "https://zh.wikipedia.org/wiki/%E5%B8%B8%E5%BB%BA"},
    {"kind": "wisdom", "text": "稻花香里说丰年,听取蛙声一片。— 辛弃疾《西江月·夜行黄沙道中》",
     "source_url": "https://zh.wikipedia.org/wiki/%E8%BE%9B%E5%BC%83%E7%96%BE"},
    {"kind": "wisdom", "text": "春眠不觉晓,处处闻啼鸟。夜来风雨声,花落知多少。— 孟浩然《春晓》",
     "source_url": "https://zh.wikipedia.org/wiki/%E5%AD%9F%E6%B5%A9%E7%84%B6"},
    {"kind": "rest", "text": "屏幕看久了眼睛会涩。起身倒杯水,看 20 秒远处再回来。"},
    {"kind": "rest", "text": "肩膀紧张是码代码的职业病。转转脖子、拉拉肩,比贴膏药管用。"},
    {"kind": "rest", "text": "下午困别硬撑。5 分钟短睡比咖啡有效得多。"},
    {"kind": "work", "text": "anomaly-alert-dedup 已 ping reviewer 2 次,等了 8h。明天 standup 当面催效率会更高。",
     "pattern": "paused_with_blockers"},
    {"kind": "work", "text": "k8s-upgrade-1-30 staging 升级安排在本周末。提前 push 一下 rollback 演练 task。",
     "pattern": "active_with_milestone"},
    {"kind": "work", "text": "card-input-a11y 已经卡在「等设计」第 4 天。是不是先用旧设计稿做个 POC 自测?",
     "pattern": "paused_long"},
  ],
  "history": [],
}

# ---- mock suggestions (next-steps) ----
suggestions = {
  "generated_at": iso(0),
  "items": [
    {"init_id": "anomaly-alert-dedup",
     "init_name": "异常交易告警去重",
     "reason": "MR 已开 8 小时等评审,你 ping 过 2 次。是这周离上线最近的 initiative,推一下 reviewer。"},
    {"init_id": "checkout-applepay-integration",
     "init_name": "结账页 Apple Pay 集成",
     "reason": "Stripe staging 工单 OPS-4471 是关键路径。今天追一下进展,顺手推前端 PaymentRequest 集成。"},
    {"init_id": "k8s-upgrade-1-30",
     "init_name": "K8s 集群升级到 1.30",
     "reason": "本周末要升 staging。rollback 演练这条 task 还没动,周五前必须走完。"},
  ],
}

# ---- mock weekly report ----
week_label = "2026-W21"
report_md = """# 周报 · 2026-W21（2026-05-18 至 2026-05-24）

## Highlights

- **退款 API 限流** 完成上线,7 天 0 误伤(MR 27465901)。
- **费率引擎重构** 11/11 规则迁移完毕,本周做 shadow 对账。这是 Q2 最大的重构项,看着稳。
- **K8s 1.30 升级**:dev 集群已升,3 天稳定。staging 周末执行。
- **异常告警去重** MR 已开,等 @zhao 评审。

## Active initiatives

- **payment-service / 费率计算引擎重构** [active] — 11/11 规则迁移完成,本周 shadow 对账。
- **checkout-frontend / 结账页 Apple Pay 集成** [active] — 后端跑通,前端 PaymentRequest 集成中,等 Stripe 工单。
- **fraud-detector / 异常交易告警去重** [active] — MR 已开等评审,8 小时无回复。
- **infra / K8s 升级到 1.30** [active] — dev 已升,staging 周末。

## Shipped / Closed

- 退款 API 限流(已上线 + 7 天观测无异常)
- /payment/applepay/session 后端端点(MR 27512348 已合并)
- 费率 DSL parser(MR 27498012 已合并)

## Scope changes

- Apple Pay 通道单独调阈值 → 合并到「异常交易告警去重」。

## Notable artifacts

- [feat(checkout): wire up PaymentRequest API for Apple Pay](https://code.example.com/payments/checkout-frontend/codereview/27514102) — pending review
- [feat(alert): 60s window + dedup by txn+merchant](https://code.example.com/payments/fraud-detector/codereview/27510445) — pending review
- [OPS-4471 Stripe staging Apple Pay](https://aone.example.com/issue/OPS-4471) — open

## Sessions touched

11 sessions across 4 workspaces.
"""

# ---- write everything ----
import os
repo = pathlib.Path(os.environ.get("REPO_ROOT", "/Users/bby/Code/claude-stray"))
cache = repo / "cache"
assert cache.is_dir(), f"cache dir not found: {cache}"
(cache / "dashboard.json").write_text(json.dumps(mm, indent=2, ensure_ascii=False))

tips_dir = cache / "derived/tips"
tips_dir.mkdir(parents=True, exist_ok=True)
(tips_dir / "latest.json").write_text(json.dumps(tips, indent=2, ensure_ascii=False))

sug_dir = cache / "derived/suggestions"
sug_dir.mkdir(parents=True, exist_ok=True)
(sug_dir / "latest.json").write_text(json.dumps(suggestions, indent=2, ensure_ascii=False))

reports_dir = cache / "derived/reports"
reports_dir.mkdir(parents=True, exist_ok=True)
(reports_dir / f"{week_label}.md").write_text(report_md)
(reports_dir / f"{week_label}.json").write_text(json.dumps({
    "week_label": week_label,
    "week_start": "2026-05-18",
    "hot_sessions": [{"sid": SID["fees"], "cwd": "~/code/payment-service"}],
    "active_initiatives": [],
    "archived_this_week": [],
    "tasks_done_this_week": [],
    "tasks_cancelled_this_week": [],
    "new_artifacts_this_week": [],
}, indent=2, ensure_ascii=False))

print("mock data written to", cache)

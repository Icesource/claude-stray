#!/usr/bin/env python3
"""English-language mock for promo screenshots."""
import json, pathlib, datetime, os

now = datetime.datetime.now(datetime.timezone.utc)
def iso(delta_h=0):
    return (now - datetime.timedelta(hours=delta_h)).strftime("%Y-%m-%dT%H:%M:%SZ")

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
    "cost":     "b8c9d0e1-8888-9999-aaaa-bbbbccccdddd",
}

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
          "name": "Apple Pay integration on web checkout",
          "status": "active",
          "summary": "Wire Apple Pay into the web checkout flow so iOS Safari users skip the card form and pay with Face ID.",
          "progress": "Merchant cert issued, backend /payment/applepay/session endpoint live. Frontend PaymentRequest integration in progress; iOS 17 + sandbox transaction succeeded. Waiting on Stripe staging unblock before running end-to-end.",
          "last_activity_at": iso(2),
          "sessions": [SID["applepay"], SID["applepay2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "obtain-merchant-cert", "title": "Apply for and download Apple Pay merchant certificate",
             "status": "done", "evidence": "merchant cert issued + uploaded to prod",
             "terminal_at": iso(72)},
            {"id": "backend-session-endpoint", "title": "Implement /payment/applepay/session backend endpoint",
             "status": "done", "evidence": "MR 27512348 merged",
             "terminal_at": iso(48)},
            {"id": "frontend-paymentrequest", "title": "Wire PaymentRequest API in the frontend",
             "status": "pending"},
            {"id": "e2e-staging", "title": "Run end-to-end real-card test on staging", "status": "pending"},
            {"id": "fraud-rule-tuning", "title": "Tune fraud rule threshold for the Apple Pay channel separately",
             "status": "cancelled", "evidence": "rolled into the anomaly-alert-dedup initiative",
             "terminal_at": iso(24)},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(checkout): Apple Pay session endpoint", "ref_id": "27512348",
             "url": "https://github.com/example/checkout-frontend/pull/27512348",
             "status": "merged", "last_mentioned_at": iso(48)},
            {"type": "mr", "title": "feat(checkout): wire up PaymentRequest API for Apple Pay",
             "ref_id": "27514102",
             "url": "https://github.com/example/checkout-frontend/pull/27514102",
             "status": "pending", "last_mentioned_at": iso(2)},
            {"type": "issue", "title": "Stripe staging — open up Apple Pay channel", "ref_id": "OPS-4471",
             "url": "https://example.atlassian.net/browse/OPS-4471",
             "status": "open", "last_mentioned_at": iso(6)},
          ],
          "blockers": [
            "Waiting on Stripe to open up the staging Apple Pay channel (ticket OPS-4471 filed)",
            "Waiting on App Store Connect merchant ID review",
          ],
        },
        {
          "id": "card-input-a11y",
          "name": "Card input accessibility pass",
          "status": "paused",
          "summary": "Rebuild the CardInput component so screen readers correctly announce field type and errors. Targets WCAG 2.2 AA.",
          "progress": "Audit done, ARIA live region pattern decided. Waiting on design to ship the new high-contrast error visuals before rebuilding the component.",
          "last_activity_at": iso(96),
          "sessions": [SID["a11y"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "wcag-audit", "title": "Run axe-core on current CardInput",
             "status": "done", "evidence": "14 violations filed as issues",
             "terminal_at": iso(120)},
            {"id": "aria-live-pattern", "title": "Decide ARIA live region pattern for error announcements", "status": "done",
             "evidence": "POC verified with 3 screen readers", "terminal_at": iso(108)},
            {"id": "new-design", "title": "Wait for design org's new high-contrast error visuals", "status": "pending"},
            {"id": "impl", "title": "Build the new component + old-component fallback", "status": "pending"},
          ],
          "blockers": ["Waiting on Sarah (design) for high-contrast error visuals — expected this weekend"],
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
          "name": "Fee calculation engine refactor",
          "status": "active",
          "summary": "Replace the if-else chain with a rule table + DSL so new fee rules ship without code changes.",
          "progress": "DSL spec settled, parser implemented. All 11 existing fee rules migrated; unit-test coverage at 94%. Shadow-running against the old engine this week — zero divergence is the gate to rollout.",
          "last_activity_at": iso(4),
          "sessions": [SID["fees"], SID["fees2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "dsl-spec", "title": "Define the fee DSL grammar", "status": "done",
             "evidence": "spec reviewed and merged", "terminal_at": iso(168)},
            {"id": "parser-impl", "title": "Implement DSL parser + AST", "status": "done",
             "evidence": "MR 27498012 merged, 96% coverage", "terminal_at": iso(120)},
            {"id": "migrate-rules", "title": "Port all 11 current fee rules to the DSL",
             "status": "done", "evidence": "11/11 done, all unit tests green",
             "terminal_at": iso(48)},
            {"id": "shadow-run", "title": "Run shadow reconciliation against the old engine",
             "status": "pending"},
            {"id": "rollout-plan", "title": "Write the rollout + rollback runbook", "status": "pending"},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(fees): DSL parser implementation", "ref_id": "27498012",
             "url": "https://github.com/example/payment-service/pull/27498012",
             "status": "merged", "last_mentioned_at": iso(120)},
            {"type": "doc", "title": "Fee DSL spec v1.0",
             "url": "https://notion.so/example/fee-dsl-spec",
             "status": "unknown", "last_mentioned_at": iso(168)},
          ],
        },
        {
          "id": "refund-api-rate-limit",
          "name": "Refund API rate limit",
          "status": "done",
          "summary": "Add token-bucket rate limiting to /refund so script misfires can't cause an incident.",
          "progress": "Shipped. Limit: 100 req/min per merchant, burst 50. Seven days in prod with zero false positives.",
          "last_activity_at": iso(180),
          "sessions": [SID["refund"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "design", "title": "Decide token bucket vs leaky bucket", "status": "done",
             "evidence": "chose token bucket (burst tolerance)", "terminal_at": iso(240)},
            {"id": "impl", "title": "Plumb the limit through the existing Sentinel integration", "status": "done",
             "evidence": "MR 27465901 merged + canaried", "terminal_at": iso(200)},
            {"id": "monitor", "title": "Monitor for 7 days, confirm no false trips", "status": "done",
             "evidence": "7 days, 0 false-positive alerts", "terminal_at": iso(180)},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(refund): Sentinel rate limit", "ref_id": "27465901",
             "url": "https://github.com/example/payment-service/pull/27465901",
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
          "name": "De-duplicate anomaly alerts",
          "status": "active",
          "summary": "When a transaction trips multiple rules simultaneously, send one consolidated alert to oncall instead of five separate pages.",
          "progress": "Aggregation window implemented (60s window, dedupe by (txn_id, merchant_id)). Integration tests pass. MR open, waiting on review.",
          "last_activity_at": iso(8),
          "sessions": [SID["fraud"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "design-window", "title": "Decide aggregation window size + dedupe key",
             "status": "done", "evidence": "60s window, (txn_id, merchant_id) key",
             "terminal_at": iso(72)},
            {"id": "impl-aggregator", "title": "Build the aggregator", "status": "done",
             "evidence": "MR 27510445 open, waiting on review", "terminal_at": iso(24)},
            {"id": "review-pass", "title": "Get reviewer sign-off", "status": "pending"},
            {"id": "shadow-1day", "title": "Shadow-run for 1 day, measure dedup ratio", "status": "pending"},
          ],
          "artifacts": [
            {"type": "mr", "title": "feat(alert): 60s window + dedup by txn+merchant",
             "ref_id": "27510445",
             "url": "https://github.com/example/fraud-detector/pull/27510445",
             "status": "pending", "last_mentioned_at": iso(8)},
          ],
          "blockers": ["Waiting on @zhao to review (pinged 2× already, will catch them at standup tomorrow)"],
        },
        {
          "id": "ml-model-v3-eval",
          "name": "Fraud model v3 evaluation",
          "status": "paused",
          "summary": "Decide whether to ship v3 by comparing recall and false-positive rate against v2.",
          "progress": "Offline eval shows v3 recall +2.1%, false positives -0.4%. Shadow infrastructure not yet up (blocked on ML team's inference server).",
          "last_activity_at": iso(216),
          "sessions": [SID["ml"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "offline-eval", "title": "Compare v2 vs v3 on historical data", "status": "done",
             "evidence": "v3 recall +2.1% / FP -0.4%", "terminal_at": iso(240)},
            {"id": "shadow-infra", "title": "Stand up the shadow inference server", "status": "pending"},
            {"id": "shadow-run-2w", "title": "Run shadow for 2 weeks against v2", "status": "pending"},
            {"id": "rollout-decision", "title": "Write rollout / rollback decision memo", "status": "pending"},
          ],
          "blockers": ["Waiting on ML team (@li) to prep v3 inference server — ETA next week"],
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
          "name": "Upgrade Kubernetes clusters to 1.30",
          "status": "active",
          "summary": "Take prod / staging / dev from 1.27 to 1.30 (two-step jump; Anthos won't do single-version).",
          "progress": "dev cluster upgraded, 3 days clean. staging upgrade scheduled for this weekend. prod waits for staging to soak.",
          "last_activity_at": iso(12),
          "sessions": [SID["k8s"], SID["k8s2"]],
          "linked_cwds": [],
          "tasks": [
            {"id": "compat-audit", "title": "Audit deprecated API usage (1.27 → 1.30)",
             "status": "done", "evidence": "3 PSP usages migrated to PSA",
             "terminal_at": iso(168)},
            {"id": "dev-upgrade", "title": "Upgrade dev cluster", "status": "done",
             "evidence": "dev on 1.30, clean for 3 days",
             "terminal_at": iso(72)},
            {"id": "staging-upgrade", "title": "Upgrade staging cluster (this weekend)", "status": "pending"},
            {"id": "staging-soak", "title": "Soak staging for 1 week", "status": "pending"},
            {"id": "prod-upgrade", "title": "Upgrade prod cluster", "status": "pending"},
            {"id": "rollback-plan", "title": "Walk through the rollback drill end-to-end", "status": "pending"},
          ],
        },
        {
          "id": "cost-dashboard",
          "name": "Cloud cost dashboard",
          "status": "archived",
          "summary": "Planned standalone Grafana for AWS + Aliyun spend. Rolled into the company-wide FinOps platform — no longer a separate effort.",
          "progress": "Paused. Carry-on work moves under the FinOps platform.",
          "last_activity_at": iso(720),
          "sessions": [SID["cost"]],
          "linked_cwds": [],
        },
      ],
    },
  ],
}

# English tips
tips = {
  "generated_at": iso(0),
  "tips": [
    {"kind": "curiosity", "text": "Linus Torvalds wrote the first version of Git in C over two weeks. His project codename was \"the stupid content tracker\".",
     "source_url": "https://en.wikipedia.org/wiki/Git"},
    {"kind": "curiosity", "text": "Markdown was designed in 2004 by John Gruber with Aaron Swartz — the goal was \"reads like plain text\".",
     "source_url": "https://daringfireball.net/projects/markdown/"},
    {"kind": "curiosity", "text": "JavaScript was originally called Mocha, then LiveScript, finally renamed to ride on Java's marketing wave.",
     "source_url": "https://en.wikipedia.org/wiki/JavaScript"},
    {"kind": "curiosity", "text": "Python is named after Monty Python, not the snake. Guido van Rossum was a fan when he started the project.",
     "source_url": "https://docs.python.org/3/faq/general.html#why-is-it-called-python"},
    {"kind": "curiosity", "text": "The word \"debug\" entered computing in 1947 when engineers literally pulled a moth out of Harvard Mark II's relays.",
     "source_url": "https://en.wikipedia.org/wiki/Software_bug#Etymology"},
    {"kind": "curiosity", "text": "Unicode has a \"zero-width joiner\" — an invisible character whose job is to glue Arabic and Indic letters together when rendered.",
     "source_url": "https://en.wikipedia.org/wiki/Zero-width_joiner"},
    {"kind": "curiosity", "text": "\"OK\" comes from an 1839 Boston newspaper joke abbreviation: \"oll korrect.\"",
     "source_url": "https://en.wikipedia.org/wiki/OK"},
    {"kind": "curiosity", "text": "HTTP status 418 \"I'm a teapot\" came from a 1998 April Fool's RFC and is still a formally defined protocol code.",
     "source_url": "https://en.wikipedia.org/wiki/Hyper_Text_Coffee_Pot_Control_Protocol"},
    {"kind": "wisdom", "text": "\"I went to the woods because I wished to live deliberately, to front only the essential facts of life.\" — Thoreau, Walden",
     "source_url": "https://en.wikipedia.org/wiki/Walden"},
    {"kind": "wisdom", "text": "\"You do not have to be good. You do not have to walk on your knees for a hundred miles through the desert repenting.\" — Mary Oliver, Wild Geese",
     "source_url": "https://en.wikipedia.org/wiki/Mary_Oliver"},
    {"kind": "wisdom", "text": "\"Two roads diverged in a wood, and I — I took the one less traveled by, and that has made all the difference.\" — Robert Frost",
     "source_url": "https://en.wikipedia.org/wiki/The_Road_Not_Taken"},
    {"kind": "wisdom", "text": "\"The woods are lovely, dark, and deep. But I have promises to keep, and miles to go before I sleep.\" — Robert Frost",
     "source_url": "https://en.wikipedia.org/wiki/Stopping_by_Woods_on_a_Snowy_Evening"},
    {"kind": "wisdom", "text": "\"Beauty is truth, truth beauty — that is all ye know on earth, and all ye need to know.\" — John Keats, Ode on a Grecian Urn",
     "source_url": "https://en.wikipedia.org/wiki/Ode_on_a_Grecian_Urn"},
    {"kind": "wisdom", "text": "\"How we spend our days is, of course, how we spend our lives.\" — Annie Dillard",
     "source_url": "https://en.wikipedia.org/wiki/Annie_Dillard"},
    {"kind": "rest", "text": "Eyes get dry after a long screen session. Stand up, top up your water, and look 20 seconds at something far before coming back."},
    {"kind": "rest", "text": "Shoulder tension is the coder's occupational hazard. Roll your neck, stretch your shoulders — beats a heat patch."},
    {"kind": "rest", "text": "Afternoon slump — don't muscle through. A 5-minute power nap actually beats coffee for short-horizon recovery."},
    {"kind": "work", "text": "anomaly-alert-dedup has been waiting on reviewer for 8 hours and you've pinged twice. Tomorrow's standup is the right place to escalate face-to-face.",
     "pattern": "paused_with_blockers"},
    {"kind": "work", "text": "k8s-upgrade-1-30 staging upgrade is on the calendar this weekend. Push the rollback-drill task forward before then.",
     "pattern": "active_with_milestone"},
    {"kind": "work", "text": "card-input-a11y has been stuck on \"waiting on design\" for 4 days. Could you POC against the old design while waiting?",
     "pattern": "paused_long"},
  ],
  "history": [],
}

suggestions = {
  "generated_at": iso(0),
  "items": [
    {"init_id": "anomaly-alert-dedup",
     "init_name": "De-duplicate anomaly alerts",
     "reason": "MR has been open 8 hours awaiting review and you've pinged twice. Closest to shipping of any active item — push the reviewer."},
    {"init_id": "checkout-applepay-integration",
     "init_name": "Apple Pay integration on web checkout",
     "reason": "Stripe staging ticket OPS-4471 is on the critical path. Chase it today, then push the frontend PaymentRequest work in parallel."},
    {"init_id": "k8s-upgrade-1-30",
     "init_name": "Upgrade Kubernetes clusters to 1.30",
     "reason": "Staging upgrade is this weekend. The rollback-drill task hasn't been touched — must close it by Friday."},
  ],
}

week_label = "2026-W21"
report_md = """# Weekly · 2026-W21 (May 18 — May 24)

## Highlights

- **Refund API rate limit** shipped. Seven days in prod, zero false positives (MR 27465901).
- **Fee engine refactor**: 11/11 rules migrated, shadow reconciliation runs this week. Biggest Q2 refactor — looking stable.
- **K8s 1.30 upgrade**: dev cluster on 1.30 for 3 days clean. staging scheduled for the weekend.
- **Anomaly alert dedup**: MR open, awaiting @zhao for review.

## Active initiatives

- **payment-service / Fee calculation engine refactor** [active] — all 11 rules migrated, shadow this week.
- **checkout-frontend / Apple Pay integration on web checkout** [active] — backend live, frontend PaymentRequest in progress, blocked on Stripe staging.
- **fraud-detector / De-duplicate anomaly alerts** [active] — MR open, 8h with no review.
- **infra / Upgrade Kubernetes clusters to 1.30** [active] — dev done, staging this weekend.

## Shipped / Closed

- Refund API rate limit (shipped + 7-day soak, zero false positives)
- /payment/applepay/session backend endpoint (MR 27512348 merged)
- Fee DSL parser (MR 27498012 merged)

## Scope changes

- Apple Pay fraud-rule threshold tuning → rolled into the anomaly-alert-dedup initiative.

## Notable artifacts

- [feat(checkout): wire up PaymentRequest API for Apple Pay](https://github.com/example/checkout-frontend/pull/27514102) — pending review
- [feat(alert): 60s window + dedup by txn+merchant](https://github.com/example/fraud-detector/pull/27510445) — pending review
- [OPS-4471 Stripe staging Apple Pay](https://example.atlassian.net/browse/OPS-4471) — open

## Sessions touched

11 sessions across 4 workspaces.
"""

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

# flip UI lang to en
config_p = cache / "config.json"
cfg = json.loads(config_p.read_text())
cfg["lang"] = "en"
config_p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

print("EN mock data written + config.lang=en")

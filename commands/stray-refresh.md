---
description: Force refresh the dashboard cache then show it
allowed-tools: Bash(bash:*), Bash(python3:*)
---

Output the text below verbatim inside a fenced code block (```text ... ```). Write nothing else — no greeting, no summary, no explanation, just the code block.

!`bash __REPO__/bin/pipeline-run.sh --all-dirty --force-classify >/dev/null 2>&1 && python3 __REPO__/bin/render.py`

---
name: lakebase-move-lab-preflight
description: Checks that this Databricks workspace is ready for the Lakebase Move Lab before a workshop, and says what to fix. Use when the user asks to validate, preflight, or readiness-check the Lakebase Move Lab. Do not use to install, import, or run the lab (README Start here), to explain how the lab works or why a lab step failed (use lakebase-move-lab-expert), or for general Lakebase questions. If they already have Summary or job output, do not run the cell; explain that output.
---

<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab preflight

Use `lakebase_move_lab_preflight` to check readiness, then explain its actual results. It creates and deletes throwaway projects, including one in the other workspace if selected. Don't claim readiness without its Summary or returned report.

## Steps

1. If the notebook is already in their Git folder, have them attach Serverless and click Run all. Use the job cell only if they agree and the notebook isn't already open. Tell them it takes about 3 minutes and deletes its throwaway projects. Use their lab catalog, or `main` if none was named. Use the other workspace's URL only if the new home goes there. A job can't answer the hidden token prompt; have them run **Choose your setup** interactively first if credentials aren't stored.
2. If you use the job cell, add ONE Python cell with exactly the code in "The cell" below, changing only `CATALOG` and `OTHER_WORKSPACE_URL`, and run it. Don't split, shorten, or rewrite it. It waits for the job to finish, so it runs for a few minutes.
3. If they already have output, don't run anything. Lead with its verdict: ✅ Ready, ⚠️ Ready with notes, or ❌ Not ready. Show a short table of non-passing checks, their consequences, and the fixes from the output. Include the job run link if present. Match errors in [troubleshooting](../lakebase-move-lab-expert/troubleshooting.md#the-preflight-and-its-genie-code-cell).
4. If leftovers failed, don't resubmit the same job. Follow [preflight results](../lakebase-move-lab-expert/lab-walkthrough.md#preflight-results). Don't change workspace settings or permissions yourself.

## The cell

```python
# Lakebase Move Lab preflight: runs the check as a one-time serverless job, then prints what to fix.
import json
import time

from databricks.sdk import WorkspaceClient

CATALOG = "main"  # the catalog you'll use for the lab's synced table
OTHER_WORKSPACE_URL = ""  # the other workspace's URL, if the lab's new home goes there
REPO = "https://github.com/ryancicak/lakebase-move-lab"
NOTEBOOK = "lakebase_move_lab_preflight"

w = WorkspaceClient()
params = {"catalog": CATALOG, "other_url": OTHER_WORKSPACE_URL,
          "where": "Another workspace" if OTHER_WORKSPACE_URL else "This workspace"}
task = {"task_key": "preflight", "timeout_seconds": 1800,
        "notebook_task": {"notebook_path": NOTEBOOK, "source": "GIT", "base_parameters": params}}
spec = {"run_name": "Lakebase Move Lab preflight", "tasks": [task],
        "git_source": {"git_url": REPO, "git_provider": "gitHub", "git_branch": "main"}}
source = f"{REPO} (main)"
try:  # prefer a copy next to this notebook, for example in the lab's Git folder
    here = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    local = f"{here.rsplit('/', 1)[0]}/{NOTEBOOK}"
    w.workspace.get_status(local)
    task["notebook_task"].update(notebook_path=local, source="WORKSPACE")
    spec.pop("git_source")
    source = local
except Exception:
    pass

run_id = w.api_client.do("POST", "/api/2.1/jobs/runs/submit", body=spec)["run_id"]
print(f"Running the preflight from {source}. This takes about 3 minutes...")
while True:
    run = w.api_client.do("GET", "/api/2.1/jobs/runs/get", query={"run_id": run_id})
    if run["state"]["life_cycle_state"] in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
        break
    time.sleep(10)
print("Job run:", run["run_page_url"], "\n")

output = w.api_client.do("GET", "/api/2.1/jobs/runs/get-output", query={"run_id": run["tasks"][0]["run_id"]})
result = (output.get("notebook_output") or {}).get("result")
if not result:
    print("❌ The preflight stopped before it finished:", output.get("error") or run["state"].get("state_message"))
else:
    report = json.loads(result)
    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️"}
    for r in report["results"]:
        print(f"{icon[r['status']]} {r['check']}: {r['detail']}")
        if r["fix"]:
            print(f"     Fix: {r['fix']}")
    print({"ready": "\n✅ Ready for the lab.",
           "ready with notes": "\n⚠️ Ready for the lab, with the notes above.",
           "not ready": "\n❌ Not ready: fix the items marked ❌, then run this check again."}[report["verdict"]])
```

## If the cell itself fails

Use the [preflight error reference](../lakebase-move-lab-expert/troubleshooting.md#the-preflight-and-its-genie-code-cell). If the job returns no report, say it stopped; don't turn the job's status into a readiness verdict.

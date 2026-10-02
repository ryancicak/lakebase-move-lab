---
name: lakebase-move-lab-preflight
description: Checks that this Databricks workspace is ready for the Lakebase Move Lab before anyone runs it, and says what to fix. Use when the user asks to validate, preflight, or readiness-check the Lakebase Move Lab, to make sure the lab will work here, or why the lab's setup cells fail. Do not use to run the lab itself or for general Lakebase questions.
---

<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab preflight

The Lakebase Move Lab is a notebook that promotes and moves a Lakebase environment between projects. Its preflight notebook, `lakebase_move_lab_preflight`, tries everything the lab needs (downloads, sign-in, a bundle deploy, Postgres connections, a second database, roles and grants, `pg_dump` and `pg_restore`, branches, snapshots, a synced table) on one throwaway project, deletes it, and reports each check as ✅ pass, ⚠️ warning, ❌ fail, or ⏭️ skipped, with a fix.

This skill runs that notebook as a one-time serverless job and explains the results.

## Steps

1. Tell the user in one or two sentences what will happen: a one-time serverless job that takes about 3 minutes and uses one throwaway Lakebase project, named `lb-move-pre-...`, which it deletes at the end. If the user named a catalog for the lab, use it; otherwise use `main`.
2. Add ONE Python cell with exactly the code in "The cell" below, changing only `CATALOG`, and run it. Don't split, shorten, or rewrite it. It waits for the job to finish, so it runs for a few minutes.
3. When the cell finishes, answer from its output:
   - First line: the verdict, one of ✅ Ready, ⚠️ Ready with notes, or ❌ Not ready.
   - Then a short table of every check that isn't ✅: the check, what it means for the lab, and the fix. Use the fix from the output; the troubleshooting table below adds context.
   - Then the job run link from the output, for the full details.
4. If anything failed, offer to help with the fix, and to run the check again afterward. Don't change workspace settings or permissions yourself.

## The cell

```python
# Lakebase Move Lab preflight: runs the check as a one-time serverless job, then prints what to fix.
import json
import time

from databricks.sdk import WorkspaceClient

CATALOG = "main"  # the catalog you'll use for the lab's synced table
REPO = "https://github.com/ryancicak/lakebase-move-lab"
NOTEBOOK = "lakebase_move_lab_preflight"

w = WorkspaceClient()
task = {"task_key": "preflight", "timeout_seconds": 1800,
        "notebook_task": {"notebook_path": NOTEBOOK, "source": "GIT", "base_parameters": {"catalog": CATALOG}}}
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

## Troubleshooting

| Check | What a problem means for the lab | Fix |
|---|---|---|
| Serverless compute (warning) | The lab was tested on serverless only | Attach serverless compute |
| Python packages (PyPI) | The lab's first cell fails | Allow serverless compute to reach PyPI, or a PyPI mirror |
| PostgreSQL client tools (apt.postgresql.org) | No `pg_dump` or `pg_restore`, so no move | Allow serverless compute to reach apt.postgresql.org over HTTPS |
| psycopg on the downloaded libpq | The lab can't connect to Postgres | Send the error to the lab's owner |
| Databricks SDK and the Lakebase API | Nothing in the lab works | Lakebase must be available in the workspace's region, with permission to use it |
| Databricks CLI (github.com) | No bundle steps | Allow serverless compute to reach github.com over HTTPS |
| CLI signs in as you | No bundle steps | Send the error to the lab's owner |
| No leftovers from an earlier lab run | The lab trips over old projects instead of starting clean | Run the lab's Module 7, or run the preflight notebook with `CLEAN_LEFTOVERS = True` |
| Bundle deploys a Lakebase project | The lab can't build its new home | Permission to create Lakebase projects, and a writable home folder (bundles keep state in `~/.bundle`) |
| Connect with a login token | No Postgres access | A timeout points at the serverless network policy; anything else goes to the lab's owner |
| Create a second database, Roles, ownership, and grants, pg_dump and a filtered pg_restore, Child branch and its compute, Point-in-time branch | That step of the lab fails | Send the error to the lab's owner |
| Snapshots (warning) | The lab skips its snapshot demo | Nothing to do |
| Schema and Delta table in the catalog (warning) | The lab skips its synced-table steps | Use a catalog where the user can create schemas, or ask for `CREATE SCHEMA` on it |
| Synced table into Lakebase (warning) | The lab skips its synced-table steps | Read the error in the detail |
| prevent_destroy guards the bundle, Cleanup | The lab's cleanup may not work | Delete what the detail lists, and send it to the lab's owner |

⏭️ skipped means a check it depends on failed; fix that one first.

## If the cell itself fails

- Permission denied on `runs/submit`, or serverless jobs aren't enabled: ask the user to open the `lakebase_move_lab_preflight` notebook (from the lab's Git folder, or import it from the repo) and click Run all. Its last cell prints the same summary.
- The job can't reach GitHub as a Git source: import `lakebase_move_lab_preflight.py` from the repo into the same folder as the current notebook, then run the cell again. It uses a copy next to the notebook first.

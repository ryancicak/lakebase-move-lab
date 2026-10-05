<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab

**Start with one workspace.** The notebook releases a coupon change, then moves the app's databases between two Lakebase projects. Lakebase is managed Postgres in Databricks.

The app is simulated with SQL. The projects and database operations are real. There's no separate app or automated CI/CD pipeline to install.

## Start here

You need:

- **Serverless** in the notebook's compute dropdown, with internet access. A SQL warehouse is a different kind of compute.
- **Lakebase Postgres** in the grid menu at the top right, plus permission to create projects. If it isn't there, ask your workspace admin before starting.
- A workspace where you're allowed to create lab resources.

1. **Open it in Databricks.** Go to **Workspace**, then **Create**, then **Git folder**. Paste `https://github.com/ryancicak/lakebase-move-lab`, choose GitHub, and create the folder on branch `main`. Open `lakebase_move_lab`. Databricks recognizes this `.py` file as a notebook.
2. **Choose Serverless.** Run the first code cell, **Choose your setup**, and leave its defaults for this first run.
3. **Go cell by cell.** Use **Shift+Enter** to run a cell and move to the next. Read the short text above it; you can skim the helper code. When the first project appears, open its **See it in Lakebase Postgres** link in another tab. Then come back and continue through cleanup.

**Run all includes cleanup.** It takes a few minutes and deletes the lab resources at the end. Your notebook and Git folder stay.

Only need the notebook? In a workspace folder, use **Import** and select `lakebase_move_lab.py`, not a ZIP of the repo. The Git folder also includes the optional preflight and Genie Code skills.

**If a cell fails, use Module 7: Clean up before trying again.** Its instructions cover a Python restart too. Do not click Run all to recover a stopped run. Run only one copy at a time as the same user.

## Optional: use a real second workspace

Finish the first run and cleanup. Then **import `lakebase_move_lab.py` as a new notebook** in the original workspace. Don't reuse the completed notebook. Only the new home goes to the other workspace.

You don't need to edit code or install a CLI on your laptop:

1. In the other workspace, create a short-lived **personal access token** under **Settings**, **Developer**, **Access tokens**. You'll need permission to create Lakebase projects there too.
2. In the fresh lab notebook, run **Choose your setup** once. Put the other workspace's URL in **box 2 first**, then pick **Another workspace** in box 1. This avoids asking the setup cell to sign in before it has an address.
3. The setup cell asks for the token in a hidden input **below the cell**. Paste it there, not into the notebook's code or a widget. Once it says you're signed in to the other workspace, continue. Changing a box may run the setup cell automatically; otherwise, run it yourself.

The token goes into your secret scope, readable by you and workspace admins, not into the notebook. You need permission to create that scope here. Module 7 deletes it; revoke the token in the other workspace when you're done.

If the hidden box won't accept your token, use the CLI fallback in [credential setup](skills/lakebase-move-lab-expert/lab-walkthrough.md#jobs-and-service-principals), then run setup again. That section also covers jobs and service principals. The [test record](TESTING.md#limits) describes the browser check and its limits.

If the workspaces have separate metastores, the lab skips the new home's synced table. Its source lakehouse table isn't there. The database move still runs.

`[REDACTED]` is expected for the saved workspace URL. If the connection fails, run preflight with the same setup and check the [error reference](skills/lakebase-move-lab-expert/troubleshooting.md).

For Ryan's AWS-to-Azure pair, use the addresses in [Where we ran it](TESTING.md#where-we-ran-it). Other learners use workspaces they can access.

## Optional: check a workspace before a workshop

Before a group session, or if the lab is blocked, open `lakebase_move_lab_preflight`. Choose Serverless, run **Choose your setup** with the lab's answers, then click **Run all**. It takes about 3 minutes and deletes its throwaway projects. Don't run it while your lab is active.

Read **Summary**, not just the job status. If a check fails, follow its fix before starting the lab.

## Optional: ask Genie Code

1. Use the Git folder from the install above. Importing just the lab notebook doesn't include the skills.
2. Open the Genie Code pane, then its **⋮** menu, then **Customizations**, then **Skills**.
3. If you've never added a skill, click **Create skills folder** first.
4. Click **Add skill**, paste the **workspace** Git folder's `skills` path, then click **Add folder**. For example: `/Users/you@company.com/lakebase-move-lab/skills`. Use the path from the workspace tree, not your laptop.

Start a new chat after adding or changing skills. Ask *"Why is the new development branch empty after the restore?"* for the expert, or *"Check that this workspace is ready for the Lakebase Move Lab"* for preflight. The expert answers questions; preflight can run checks. Genie Code asks before running code unless you've enabled auto-approval.

These UI steps were tested on October 2, 2026.

## Reference

- If you're moving a real app, use the [production playbook](skills/lakebase-move-lab-expert/playbook.md).
- If a cell stops, match its message in [troubleshooting](skills/lakebase-move-lab-expert/troubleshooting.md).
- For runtime settings and reruns, use the [notebook reference](skills/lakebase-move-lab-expert/lab-walkthrough.md).
- For limits and source labels, see [facts](skills/lakebase-move-lab-expert/facts.md). The actual run results and untested cases are in [TESTING.md](TESTING.md).

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

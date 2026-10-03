<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab

One notebook that walks you through promoting and moving a Lakebase environment, one cell at a time, on real Lakebase projects. It's the hands-on companion to the *Promote Lakebase across workspaces* deck: the deck explains the why, and this notebook lets you actually do it. It also works on its own: each step explains what it's doing and why.

**The short version:** you can't move a Lakebase branch. So you rebuild the environment in the new place: a bundle creates the project and branches, `pg_dump` and `pg_restore` copy the data when it has to come along, and migrations carry schema changes, as in any release. This lab takes you through all of it, start to finish.

## Quick start

1. **Get the notebook** into your workspace. Clone this repo as a Git folder, or download `lakebase_move_lab.py` and import it (Workspace, then Import). Attach serverless compute.
2. **Run Choose your setup.** Leave the boxes at the defaults so both homes stay in this workspace. Change the catalog only if you need a different one for the synced-table steps.
3. **Go through it.** Cell by cell with Shift+Enter is best for learning; **Run all** works as a demo. A full run is about 4 minutes, and the last module deletes everything it made.

Running it with a group? The [preflight](#before-the-lab-run-the-preflight) checks the workspace first, in about 3 minutes, and tells you what to fix.

If a run stops partway, scroll to **Module 7** and run its two cells: they clean up whatever the lab made. (If the notebook has restarted or detached since, first run the cells from the top through **Module 0**.)

Stuck, or curious why something works the way it does? Ask the [lab expert](#ask-the-lab-expert) in Genie Code.

## What's in here

```
lakebase-move-lab/
├── lakebase_move_lab.py             # the whole lab: one Databricks notebook (Modules 0 to 7)
├── lakebase_move_lab_preflight.py   # the pre-lab check: run it first, about 3 minutes
├── skills/
│   ├── lakebase-move-lab-preflight/
│   │   └── SKILL.md                 # a Genie Code skill that runs the pre-lab check and explains the results
│   └── lakebase-move-lab-expert/
│       ├── SKILL.md                 # a Genie Code skill that answers questions about the lab and the playbook behind it
│       ├── lab-walkthrough.md       # every module and cell, and the output to expect
│       ├── playbook.md              # promoting and moving for real, across workspaces
│       ├── troubleshooting.md       # errors, their causes, and fixes
│       └── facts.md                 # limits, numbers, and test results, each with its source
├── LICENSE                          # Apache License 2.0
└── README.md
```

To run the lab, you only need `lakebase_move_lab.py`. The preflight and the Genie Code skills are optional.

## What you'll do

0. **Set up:** install `psycopg`, the PostgreSQL 17 client tools, and the Databricks CLI, right in the notebook.
1. **Build the old home:** production with two databases (`databricks_postgres` and `reporting`), access roles, a dev branch with unreleased work, and a synced table fed from a Delta table.
2. **Promote** a change the everyday way: a migration, no data.
3. **Build the new home with a real `databricks bundle deploy`**, then try to branch across projects and see the error that explains everything.
4. **Move production's data:** pause writes, dump and restore each database, and prove the copy matches. Recreate the synced table, rebuild access, pass a final check, and switch the app; you'll see how long writes were paused. Then rebuild the dev branch (delete, redeploy, migrate) and bring back its own work.
5. **See what stays behind:** point-in-time history and snapshots.
6. **Doing it for real:** a checklist for a real move.
7. **Clean up:** watch `prevent_destroy` refuse a `bundle destroy`, then remove the guard and delete everything.

You only need one workspace. Two projects in it play old home and new home, because a branch can't leave its project. A second workspace is optional.

## Optional: use a real second workspace

By default, both homes live in the workspace you run the lab in. To put the new home in another workspace, you don't need the CLI or any code changes:

1. In the other workspace, create a personal access token (**Settings**, **Developer**, **Access tokens**).
2. In the lab, run **Choose your setup**, pick **Another workspace** in the first box, and put its URL in the second.
3. Run the cell again. It asks for the token in a hidden box, keeps it in a secret scope of your own (`lb-move-lab-<you>-<your user id>`, which only you and workspace admins can read), and signs in to check it works. Then go through the lab.

The token is never shown or saved in the notebook. Module 7 deletes the scope when you clean up; the token itself keeps working until it expires, so revoke it in the other workspace when you're done. In a job, nobody can answer the hidden box, so store the token first: run the cell interactively once, or use `databricks secrets put-secret lb-move-lab-<you>-<your user id> token`. A service principal works too: put `client-id` and `client-secret` in that scope instead of `token`.

Everything else runs the same, with two differences:

- **The lab may need the other workspace's public address.** In our test, from serverless in an AWS workspace to an Azure workspace, Lakebase hostnames resolved to a Databricks proxy that refused the other workspace's computes. So the lab tries the normal route first, and if it's refused that way, it looks up the compute's public address in public DNS (dns.google, or cloudflare-dns.com as a fallback) and connects to that. Other pairs of workspaces weren't tested; the preflight shows which route yours needs.
- **With separate metastores, the synced table stays behind.** Its Delta source would have to be copied to the other workspace first, which is its own job, so the lab skips that step and says so.

Databricks hides anything that matches a secret, so the other workspace's URL shows up as `[REDACTED]` in the output. To check it all first, run the preflight with the same answers.

## Before the lab: run the preflight

The preflight, `lakebase_move_lab_preflight`, tries everything the lab needs, the same way the lab does it, and tells you what to fix before anyone starts. It checks:

- downloads from PyPI, apt.postgresql.org, and GitHub;
- sign-in for the SDK and the CLI;
- a bundle deploy and a Postgres connection;
- a second database, roles and grants, and `pg_dump` with a filtered `pg_restore`;
- point-in-time branches, snapshots, and a synced table;
- `prevent_destroy` and cleanup;
- leftovers from an earlier run;
- optionally, a second workspace: sign-in, a bundle deploy, a connection from here, and a restore of this workspace's dump into it.

It takes about 3 minutes, uses one throwaway project, `lb-move-pre-<you>-<id>-<timestamp>` (one in each workspace, if you use two), and deletes it. There are three ways to run it:

1. **Run the notebook.** Open `lakebase_move_lab_preflight`, attach serverless compute, run its first cell, **Choose your setup**, with the answers you'll give the lab, and click Run all. The **Summary** cell at the end says ✅ ready, ⚠️ ready with notes, or ❌ not ready, with a fix for each problem.
2. **Ask Genie Code.** Add the skills once (below), open Genie Code in any notebook, and ask: *"Check that this workspace is ready for the Lakebase Move Lab."* Genie Code adds one cell that runs the preflight as a one-time serverless job, then explains the results and the fixes. It asks before running code, unless you've set Genie Code to auto-approve.
3. **Paste one cell.** The cell in [`skills/lakebase-move-lab-preflight/SKILL.md`](skills/lakebase-move-lab-preflight/SKILL.md) runs the preflight from any notebook and prints the results. It uses a copy of the preflight next to your notebook if there is one, and otherwise runs it straight from this repo.

### Add the Genie Code skills

1. Clone this repo as a Git folder (Workspace, then Create, then Git folder).
2. Open the Genie Code pane, then its **⋮** menu, then **Customizations**, then **Skills**.
3. If you've never added a skill, click **Create skills folder** first.
4. Click **Add skill**, paste the Git folder's `skills` path, for example `/Users/<you>/lakebase-move-lab/skills`, and click **Add folder**.

You'll see two skills, switched on: `lakebase-move-lab-preflight` and `lakebase-move-lab-expert`. Start a new chat after adding or changing skills. Genie Code picks the right one from your question, or you can mention one directly, like `@lakebase-move-lab-expert`. These steps were tested in the Genie Code UI on October 2, 2026. The Databricks docs also describe copying the skill folders into your own skills folder, `/Users/<you>/.assistant/skills/`, or a workspace admin putting them in `Workspace/.assistant/skills/` for everyone; we haven't tested those.

## Ask the lab expert

The expert is a Genie Code skill that knows this lab and the playbook behind it: what every cell does and what its output should look like, why each step works the way it does, what an error means and how to fix it, and how to do a real move between workspaces. Every point in an answer says where it comes from: tested in the lab, tested in the runs behind it, the Databricks docs, or not tested.

Add it with the preflight skill (above), start a new chat, and ask away. A few to try:

- *Why does the lab restore with `--no-owner --no-acl` and a filtered list instead of the documented `pg_restore` command?*
- *Won't `pg_restore` rebuild the child branches for me?*
- *How long will writes be paused when we move production, and how do we keep that short?*
- *Our app signs in with OAuth instead of a password. What changes when we move it?*
- In the lab notebook, after a run: *How long were writes paused in this run, and why?*

It answers questions, and it won't create or change anything unless you ask. Readiness questions go to the preflight skill. It doesn't cover disaster recovery (a standby in another region for failover), which is a different job.

## Requirements

- **Serverless compute with internet access.** The notebook downloads the PostgreSQL 17 client tools (`pg_dump`, `pg_restore`, and `libpq`, which psycopg also uses) from [apt.postgresql.org](https://apt.postgresql.org) and the Databricks CLI from [GitHub](https://github.com/databricks/cli/releases), and unpacks them locally. No admin rights needed. We haven't tested a classic cluster.
- **Permission to create Lakebase projects.**
- **For the optional synced-table steps:** `CREATE SCHEMA` on a Unity Catalog catalog (default `main`). Pick another one in **Choose your setup**. Without it, the lab skips those steps and says why.
- **For another workspace:** a personal access token from it (or a service principal), and permission to create a secret scope here, which every user has by default.

## What it creates, and deletes

- Projects `lb-move-old-<you>-<id>` (created with the SDK) and `lb-move-new-<you>-<id>` (created by the bundle), each with `production` and `development` branches. Production holds two databases.
- The bundle's deployment folder, `/Workspace/Users/<you>/.bundle/lb-move-lab`.
- Optional: schema `<catalog>.lb_move_<you>_<your user id>` with a 50-row Delta table and a synced table.
- For another workspace: secret scope `lb-move-lab-<you>-<your user id>` with its URL and your token.

Your numeric user id is in every name, so two learners whose user names start alike can't collide. The projects also carry name tags (`Lakebase move lab: old home` and `Lakebase move lab: new home`). The lab only reuses a project it made in the same session; it stops on a leftover from an earlier run, or on a same-named project it didn't make, instead of reusing it.
- Dump files and the downloaded tools, in temporary folders on the compute.

Module 7 deletes all of it, including after a run that stopped partway, and it only deletes projects with the lab's tag. The bundle sets `purge_on_delete`, and the old project is deleted with `purge=True`, so the project names are free right away.

The preflight creates the project `lb-move-pre-<you>-<id>-<timestamp>`, the schema `<catalog>.lb_move_pre_<you>_<timestamp>`, and the bundle folder `~/.bundle/lb-move-lab-preflight-<timestamp>`, and deletes them before it finishes. Every run gets its own names, so two runs at once don't collide. Preflight leftovers older than 30 minutes get deleted by the next preflight. If an earlier lab run left its projects, schema, or bundle folder behind, the preflight tells you. Set `CLEAN_LEFTOVERS = True` in its settings cell to delete them.

## Key Lakebase facts the lab shows

- **A branch can't leave its project.** Creating a branch from another project's branch is rejected. Moving to another workspace means rebuilding there: a bundle for the project and branches, migrations for the schema, and `pg_dump` only when the data has to come along.
- **One dump and restore per database.** A branch can hold several databases, and `pg_dump` and `pg_restore` each work on one. Any database besides `databricks_postgres` has to exist on the new side before its restore.
- **A Lakebase dump includes Lakebase's own platform objects.** Restoring them into another project fails, so the lab filters them out of each dump first.
- **Synced tables don't travel through `pg_dump`.** Leave them out of the dump and recreate them on the new side. The create call returns before the rows land, so wait for them.
- **Access doesn't come along.** Roles belong to the branch; ownership and grants belong to each database. After a restore with `--no-owner --no-acl`, rebuild them before you rebuild the child branches.
- **A child branch created before the restore stays empty.** Delete it and run `bundle deploy` again, and the bundle recreates it from the restored production. Then bring back its own work.
- **`prevent_destroy` blocks `bundle destroy`** until someone takes the guard out of the file.
- **Point-in-time history and snapshots stay with their project.** The new project's history starts at the move, and a snapshot can't be restored into another project.

## Tested

October 1 and 2, 2026, in an AWS us-west-2 workspace:

- **The lab:**
  - full runs as serverless jobs on environment versions 1 through 5, which covers Python 3.10 to 3.12, x86 and ARM machines, and Ubuntu 22.04 and 24.04;
  - a run with a catalog that doesn't exist, where the synced-table steps skip cleanly;
  - a run with 19 cells run twice in a row, where each one takes its safe path;
  - an interactive **Run all** by a workspace user, in a notebook freshly imported from this repo's URL.

  Each run took about 4 minutes, every check passed, and the teardown left nothing behind.
- **The lab with a real second workspace,** from an AWS workspace to an Azure workspace, as a serverless job and interactively: every cell passed, both databases restored with exit code 0 across clouds, the last checklist passed 7 of 7, writes were paused for 44 to 57 seconds (tiny synthetic data, not an estimate), and the teardown cleaned up both workspaces. The synced-table step skipped, as designed, because the two workspaces have separate metastores. The first try failed at the first Postgres connection: serverless sent the Azure compute's hostname to a Databricks proxy, which answered `FATAL: External authorization failed`. Connecting to the compute's public address worked, so the lab falls back to it when the normal route is refused.
- **Choose your setup:**
  - interactively, as a workspace user: picking **Another workspace** re-ran the cell on its own and asked for the URL; entering it brought up the hidden token box; a wrong token got "That token didn't work" and a second box; with a working token, the cell signed in, and **Run all** moved everything to the Azure workspace, using the catalog from box 3, then deleted the scope;
  - as jobs: the default answers ran the one-workspace lab; **Another workspace** with no token stored stopped in about a minute with the CLI command to store one, instead of hanging; with a token stored, the whole lab ran.
- **The preflight:**
  - ✅ on environment versions 1 through 5;
  - ⚠️ with a catalog that doesn't exist, and for a user without `CREATE SCHEMA` on `main`;
  - ❌ with an earlier lab run's project left over, which `CLEAN_LEFTOVERS = True` then deleted;
  - ✅ for two runs at once, with stale preflight leftovers planted, which they deleted.
- **Genie Code, the preflight skill:** a workspace user added the skill from the Git folder and asked, *"Check that this workspace is ready for the Lakebase Move Lab."* Genie Code ran the preflight and reported ⚠️ (no `CREATE SCHEMA` on `main`) with the fix. Told to use a catalog the user owns, it re-ran the check and reported ✅.
- **Genie Code, the expert skill:** ten questions about the lab and real moves, each in a new chat, asked with the skill switched off and then on.
  - Off, Genie Code answered from general Lakebase guidance. Five of the ten answers had something wrong or misleading, like a project having only one root branch, roles coming along in a dump, or a dump dropping when its login token expires, and most missed the tested specifics.
  - On, after tuning the skill's description so questions that don't mention the lab still reach it, every answer covered the tested key points, with a source for each point.
  - In a lab notebook after a run, it answered from the notebook's real outputs: writes paused for 66 seconds, 44 of them for the synced-table swap.
  - Readiness questions still went to the preflight skill, and an unrelated Lakebase question went to Genie Code's general guidance.
- **After a review, October 2:**
  - the lab as jobs, in one workspace and with a second workspace: every cell passed; both databases' app schemas matched; the open-session check found no other session; with the second workspace, the normal route to its computes was refused, and the lab switched to their public address on its own;
  - a planted project with the lab's name and tag, and one with the lab's name but not its tag: the lab stopped at its first project cell with the matching message, and touched neither;
  - a run stopped on purpose right after Module 3's deploy, interactively as a workspace user: Module 7's two cells deleted both projects, the synced table, the schema, and the bundle folder, once in the same session and once after re-running the cells from the top through Module 0;
  - the preflight: ✅ 20 of 20 in one workspace, and ⚠️ with a second workspace (25 passed, plus the separate-metastore note), reporting that the new home needed its public address;
  - Genie Code, after narrowing the expert skill's description: a Postgres upgrade question and a question about restoring a dump into a second root branch still loaded it, and questions about autoscaling sizes and service-principal OAuth access went to Genie Code's built-in Lakebase guidance instead.
- **After a second review, October 2,** with the final notebook and the pinned packages (databricks-sdk 0.146.0, psycopg 3.3.6), as jobs in two AWS workspaces:
  - the lab with the default answers, as a service principal with the synced table and as a workspace user without `CREATE SCHEMA` on `main`: every cell passed, the last checklist passed 7 of 7, and the teardown left nothing behind;
  - the lab twice in one Python session: Module 7, then Modules 1 to 7 again, then Module 7 a third time. The second pass made new projects and a new synced table, and its point-in-time branch was empty. A branch at the first pass's restore time was rejected, because that new home didn't exist yet. The third cleanup found nothing, deployed nothing, and left nothing behind;
  - the preflight: ✅ 20 of 20 for the service principal, and ⚠️ for the workspace user (no `CREATE SCHEMA` on `main`).
- **As a first-time user, October 3:** a workspace user imported the notebook into a new folder and ran it in the notebook UI, following only the README and the notebook's own text:
  - Run all with the default answers: every cell passed. The user had only `USE CATALOG` on `main`, so the synced-table steps were skipped with a clear note;
  - with a catalog the user owns in box 3, Run all passed with the synced table, in about 3 minutes;
  - cell by cell: after the skip, the user put that catalog in box 3 and ran Step 6 again, which synced the table mid-lab. A second change to box 3 was refused with a clear note, changing it back was accepted, and the rest of the lab passed and cleaned up;
  - one attempt stopped in Module 0 when the CLI download from GitHub dropped partway, so the lab now retries its downloads. The same checks then passed as jobs, and the two-passes-in-one-session test passed again;
  - the final notebook, freshly imported, and again from a new Git folder cloned from this repo after the push: one uninterrupted Run all with the default answers passed all 38 code cells and cleaned up. As jobs, it also passed on environment versions 1 through 4 with the pinned packages, with the synced table on 1 and 2;
  - the preflight, run in the notebook UI: its Summary cell used to show only a raw JSON line, because returning the results replaced that cell's output. The results now come back from their own last cell, so the Summary shows the table and the verdict. As a job, it still returns the JSON that Genie Code reads.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

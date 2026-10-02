<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab

One Databricks notebook that walks through promoting and moving a Lakebase environment, cell by cell, on real Lakebase projects. It's the companion to the *Promote Lakebase across workspaces* deck: the deck explains the why, and this notebook lets you do it. It also stands on its own, because every step explains what it does and why.

> **License:** Apache-2.0

## Contents

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

The lab lives in one notebook on purpose. There are no helper modules or SQL files to keep next to it, so you can import the single file and run it. The preflight is a separate, optional notebook because it runs before the lab.

## Before the lab: run the preflight

`lakebase_move_lab_preflight` tries everything the lab needs, the same way the lab does it, and says what to fix before anyone starts:

- downloads from PyPI, apt.postgresql.org, and GitHub;
- sign-in for both the SDK and the CLI;
- a bundle deploy and a Postgres connection;
- a second database, roles and grants, and `pg_dump` with a filtered `pg_restore`;
- point-in-time branches, snapshots, and a synced table;
- `prevent_destroy` and cleanup;
- leftovers from an earlier run.

It takes about 3 minutes and uses one throwaway project, `lb-move-pre-<you>-<id>-<timestamp>`, which it deletes. There are three ways to run it:

1. **Run the notebook.** Open `lakebase_move_lab_preflight`, set the **catalog** widget to the catalog you'll use in the lab, attach serverless compute, and click Run all. The last cell prints ✅ ready, ⚠️ ready with notes, or ❌ not ready, with a fix for each problem.
2. **Ask Genie Code.** Add the skills once (below), then open Genie Code in any notebook and ask: *"Check that this workspace is ready for the Lakebase Move Lab."* Genie Code adds one cell that runs the preflight as a one-time serverless job, then explains the results and the fixes. It asks before running code, unless you've set Genie Code to auto-approve.
3. **Paste one cell.** The cell in [`skills/lakebase-move-lab-preflight/SKILL.md`](skills/lakebase-move-lab-preflight/SKILL.md) runs the preflight as a one-time job from any notebook and prints the results. It uses a copy of the preflight next to your notebook if there is one; otherwise it runs it straight from this repo.

### Add the Genie Code skills

1. Clone this repo as a Git folder (Workspace, then Create, then Git folder).
2. Open the Genie Code pane, then its **⋮** menu, then **Customizations**, then **Skills**.
3. If you've never added a skill, click **Create skills folder** first.
4. Click **Add skill**, paste the Git folder's `skills` path, for example `/Users/<you>/lakebase-move-lab/skills`, and click **Add folder**.

Two skills show up, switched on: `lakebase-move-lab-preflight` and `lakebase-move-lab-expert`. Start a new chat after adding or changing skills. Genie Code picks the right one from your question, or you can mention one directly, like `@lakebase-move-lab-expert`. You can also put copies of the skill folders in your own skills folder, `/Users/<you>/.assistant/skills/`, or a workspace admin can put them in `Workspace/.assistant/skills/` for everyone.

## Ask the lab expert

`lakebase-move-lab-expert` is a Genie Code skill that knows the lab and the playbook behind it: what every cell does and the output to expect, why the lab does each step its way, what an error means and how to fix it, and how to promote or move a Lakebase environment for real, across workspaces. Each point in an answer says where it comes from: tested in the lab, tested in the runs behind it, the Databricks docs, or not tested. Add it with the preflight skill (above), start a new chat, and ask. For example:

- *Why does the lab restore with `--no-owner --no-acl` and a filtered list instead of the documented `pg_restore` command?*
- *Won't `pg_restore` rebuild the child branches for me?*
- *How long will writes be paused when we move production, and how do we keep that short?*
- *Our app signs in with OAuth instead of a password. What changes when we move it?*
- In the lab notebook, after a run: *How long were writes paused in this run, and why?*

It answers questions and doesn't create or change anything unless you ask. Questions about whether a workspace is ready go to the preflight skill. It doesn't cover disaster recovery, a standby in another region for failover, which is a different job.

## What you'll do

0. **Set up:** install `psycopg`, the PostgreSQL 17 client tools, and the Databricks CLI, right in the notebook.
1. **Build an old home:** a production branch with two databases (`databricks_postgres` and `reporting`), access roles, a dev branch with unreleased work, and a synced table fed from a Delta table.
2. **Promote** a change the everyday way: a migration, no data.
3. **Build the new home with a real `databricks bundle deploy`**, then try to branch across projects and see the error that explains everything.
4. **Move** production's data: a write pause and watermark, one `pg_dump` and filtered `pg_restore` per database, an exact-copy check, the synced table recreated, access rebuilt, a verification gate, and the switch, with a readout of how long writes were paused. Then rebuild the child branch the deck's way ("delete, redeploy, then migrate") and carry its own work.
5. **See what stays behind:** point-in-time history and snapshots.
6. **Doing it for real:** a checklist for a real move.
7. **Clean up:** watch `prevent_destroy` refuse a `bundle destroy`, remove the guard, and delete everything.

Two projects in one workspace stand in for two workspaces. A branch can't leave its project even inside one workspace, so the mechanics are the same.

## Run it

1. Get the notebook into your workspace. Either clone this repo as a Git folder, or download `lakebase_move_lab.py` and import it (Workspace, then Import).
2. Attach **serverless** compute. The notebook asks for serverless environment version 5.
3. Optional: in the Module 0 helpers cell, set `CATALOG` to a catalog where you can create a schema, or set `DO_SYNCED_TABLES = False` to skip the synced-table steps.
4. Run the cells in order. A full run takes about 5 minutes.

## Requirements

- Serverless compute with internet access. The notebook downloads the PostgreSQL 17 client tools (`pg_dump`, `pg_restore`, and the `libpq` library psycopg also uses) from [apt.postgresql.org](https://apt.postgresql.org) and the Databricks CLI from [GitHub](https://github.com/databricks/cli/releases), and unpacks them locally; no admin rights needed. A classic cluster with internet access should also work, but we haven't tested one.
- Permission to create Lakebase projects.
- For the optional synced-table steps: `CREATE SCHEMA` on a Unity Catalog catalog (default `main`).

## What it creates, and deletes

- Projects `lb-move-old-<you>-<id>` (created with the SDK) and `lb-move-new-<you>-<id>` (created by the bundle), each with `production` and `development` branches. Production holds two databases.
- The bundle's deployment folder, `/Workspace/Users/<you>/.bundle/lb-move-lab`.
- Optional: schema `<catalog>.lb_move_<you>` with a 50-row Delta table and a synced table.
- Dump files and the downloaded tools, in temporary folders on the compute.

Module 7 deletes all of it. The bundle sets `purge_on_delete`, and the old project is deleted with `purge=True`, so the project names are free right away.

The preflight creates the project `lb-move-pre-<you>-<id>-<timestamp>`, the schema `<catalog>.lb_move_pre_<you>_<timestamp>`, and the bundle folder `~/.bundle/lb-move-lab-preflight-<timestamp>`, and deletes them before it finishes. Each run has its own names, so two runs at once don't collide, and a run deletes anything an earlier one left behind once it's over 30 minutes old. If an earlier lab run left its projects, schema, or bundle folder behind, the preflight says so; set `CLEAN_LEFTOVERS = True` in its settings cell to delete them.

## Key Lakebase facts the lab shows

- **A branch can't leave its project.** Creating a branch from another project's branch is rejected. Moving to another workspace means rebuilding there: a bundle for the project and branches, migrations for the schema, and `pg_dump` only when the data has to come along.
- **One dump and restore per database.** A branch can hold several databases, and `pg_dump` and `pg_restore` each work on one. Any database besides `databricks_postgres` has to be created on the new side before its restore.
- **A Lakebase dump includes Lakebase's own platform objects.** Restoring them into another project fails, so the lab comments them out of each dump's table of contents first.
- **Synced tables don't travel through `pg_dump`.** Exclude them from the dump and recreate them on the new side. The create call returns before the rows land, so wait for them.
- **Access doesn't come along.** Roles belong to the branch; ownership and grants belong to each database. After a restore with `--no-owner --no-acl`, rebuild them before you rebuild child branches.
- **A child branch created before the restore stays empty.** Delete it and run `bundle deploy` again: the bundle recreates it from the restored production. Then carry its own work across.
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
- **The preflight:**
  - ✅ on environment versions 1 through 5;
  - ⚠️ with a catalog that doesn't exist, and for a user without `CREATE SCHEMA` on `main`;
  - ❌ with an earlier lab run's project left over, which `CLEAN_LEFTOVERS = True` then deleted;
  - ✅ for two runs at once, with stale preflight leftovers planted, which they deleted.
- **Genie Code, the preflight skill:** a workspace user added the skill from the Git folder and asked, *"Check that this workspace is ready for the Lakebase Move Lab."* Genie Code ran the preflight and reported ⚠️ (no `CREATE SCHEMA` on `main`) with the fix. Told to use a catalog the user owns, it re-ran the check and reported ✅.
- **Genie Code, the expert skill:** ten questions about the lab and real moves, each in a new chat, asked with the skill switched off and then on.
  - Off, Genie Code answered from general Lakebase guidance. Five of the ten answers included something wrong or misleading, like a project having only one root branch, roles coming along in a dump, or a dump dropping when its login token expires, and most missed the tested specifics.
  - On, after tuning the skill's description so questions that don't mention the lab still reach it, every answer covered the tested key points, with a source for each point.
  - In a lab notebook after a run, it answered from the notebook's real outputs: writes paused for 66 seconds, 44 of them for the synced-table swap.
  - Readiness questions still went to the preflight skill, and an unrelated Lakebase question went to Genie Code's general guidance.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

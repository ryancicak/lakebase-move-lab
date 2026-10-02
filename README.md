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
├── lakebase_move_lab.py   # the whole lab: one Databricks notebook (Modules 0 to 7)
├── LICENSE                # Apache License 2.0
└── README.md
```

Everything lives in the one notebook on purpose. There are no helper modules or SQL files to keep next to it, so you can import the single file and run it.

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

October 1, 2026: full runs as serverless jobs in an AWS us-west-2 workspace on serverless environment versions 1 through 5, which covers Python 3.10 to 3.12, x86 and ARM machines, and Ubuntu 22.04 and 24.04. Each took about 4 minutes. Every check passed and the teardown left nothing behind.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase move lab

A hands-on Databricks notebook that walks through promoting and moving a Lakebase environment, one cell at a time, on real Lakebase projects. It's the companion to the *Promote Lakebase across workspaces* deck: the deck explains the why, and this notebook lets you do it. It also stands on its own, because every step explains what it does and why.

> **License:** Apache-2.0

## Contents

```
lakebase-move-lab/
├── lakebase_move_lab.py   # the Databricks notebook (Modules 0 to 6)
├── LICENSE                # Apache License 2.0
└── README.md
```

## What you'll do

1. **Build an old home:** a project with production data, access roles, a dev branch with unreleased work, and an optional synced table fed from a Delta table.
2. **Try to move a branch** and see the error that explains everything.
3. **Promote** a change the everyday way: a migration, no data.
4. **Move** production to a new home in the deck's five steps: write pause and watermark, one `pg_dump` per database, the filtered `pg_restore`, an exact-copy check, the synced table recreated, access rebuilt, a verification gate, and the switch.
5. **Rebuild the child branch** after the restore, then carry its own work: replay its migration, load its dev-only table, and reconcile its changes to shared tables. An optional cell shows why a full data-only dump of the branch fails.
6. **See what stays behind:** point-in-time history and snapshots.
7. **Clean up** everything it created.

Two projects in one workspace stand in for two workspaces. A branch can't leave its project even inside one workspace, so the mechanics are the same.

## Run it

1. Get the notebook into your workspace. Either clone this repo as a Git folder, or download `lakebase_move_lab.py` and import it (Workspace, then Import). It's self-contained, so either way works.
2. Attach **serverless** compute. The notebook asks for serverless environment version 5.
3. Optional: in the Module 0 helpers cell, set `CATALOG` to a catalog where you can create a schema, or set `DO_SYNCED_TABLES = False` to skip the synced-table steps.
4. Run the cells in order. A full run takes about 5 minutes.

## Requirements

- Serverless compute. The notebook downloads the PostgreSQL 17 client tools (`pg_dump`, `pg_restore`, and the `libpq` library psycopg also uses) from [apt.postgresql.org](https://apt.postgresql.org) and unpacks them locally; no admin rights needed. A classic cluster with internet access should also work, but we haven't tested one.
- Permission to create Lakebase projects.
- For the optional synced-table steps: `CREATE SCHEMA` on a Unity Catalog catalog (default `main`).

## What it creates, and deletes

- Projects `lb-move-old-<you>-<id>` and `lb-move-new-<you>-<id>`, each with `production` and `development` branches.
- Optional: schema `<catalog>.lb_move_<you>` with a 50-row Delta table and a synced table.
- Dump files in a temporary folder on the compute.

Module 6 deletes all of it, using `purge=True` so the project names are free right away.

## Key Lakebase facts the lab shows

- **A branch can't leave its project.** Creating a branch from another project's branch is rejected. Moving to another workspace means rebuilding there: a bundle for the project and branches, migrations for the schema, and `pg_dump` only when the data has to come along.
- **A Lakebase dump includes Lakebase's own platform objects.** Restoring them into another project fails, so the lab comments them out of the dump's table of contents first.
- **Synced tables don't travel through `pg_dump`.** Exclude them from the dump and recreate them on the new side. The create call returns before the rows land, so wait for them.
- **Access doesn't come along.** After a restore with `--no-owner --no-acl`, rebuild roles, ownership, grants, and default privileges, before you rebuild child branches.
- **A child branch created before the restore stays empty.** Recreate it from the restored production, then carry its own work across.
- **Point-in-time history and snapshots stay with their project.** The new project's history starts at the move, and a snapshot can't be restored into another project.

## Tested

October 1, 2026: full runs as serverless jobs in an AWS us-west-2 workspace on serverless environment versions 1 through 5, which covers Python 3.10 to 3.12, x86 and ARM machines, and Ubuntu 22.04 and 24.04. Each took about 4 minutes. Every check passed and the teardown left nothing behind.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

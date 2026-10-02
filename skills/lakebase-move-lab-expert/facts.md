# Facts, numbers, and where they come from

Tags: **[lab]** tested in the lab (October 1 and 2, 2026); **[runs]** tested in the runs behind the lab, five moves from an AWS workspace to an Azure workspace (September 28 to 30, 2026, PostgreSQL 17.11, Databricks CLI 1.17.0); **[docs]** from the Databricks docs, not tested; **[not tested]**.

## Branches, projects, and limits

- A branch's parent must be in the same project. Cross-project and cross-workspace branch creation both fail with `source_branch field must point to the branch from the same Project`. [runs] [lab]
- No API method exports, imports, copies, moves, clones, promotes, or merges a branch or project. [runs]
- "Reset from parent" has no API or CLI command; it's in the UI only, and it's blocked while the branch has children. [runs]
- A child branch never sees its parent's later writes, and the parent never sees the child's. [runs] [lab]
- A project can have 3 root branches and 500 branches in total, plus one protected branch, and any branch can be the default. Root branches beyond `production` come only from a point-in-time or snapshot restore, and a branch created without a parent becomes a child of the default branch. So there's no empty second root to restore a dump into: a dump goes into the new project's production, or into a project of its own. [docs]
- A branch can hold up to 500 databases, all served by the branch's one compute host. A connection sees one database; the database name in the connection picks it. [docs]
- A project runs at most 20 computes at once besides the default branch. [docs]
- Creating a project creates `production` and its compute; creating a branch through the API creates its compute. [runs]
- A soft-deleted project ID can't be reused for 7 days; purging frees it right away. Redeploying after a soft-deleted branch still recreated it under the same ID. [docs] [runs]
- Snapshots restore only inside their own project: `source_snapshot field must point to a snapshot from the same Project`. Inside a project, creating a snapshot and restoring a branch from it took a few seconds each. [runs] [lab]
- The restore window (point-in-time history) is 2 to 30 days, 7 by default, and belongs to the project. [docs] The new project's history starts at the move: a point-in-time branch from just before the restore was empty. [lab]
- `CREATE PUBLICATION` and `CREATE SUBSCRIPTION` are disabled, so there's no logical replication between projects. [runs]
- There's no in-place major version upgrade. [docs] Bumping `pg_version` on a deployed bundle plans a delete and recreate of the project. [runs]

## Dump and restore

- The documented `pg_dump -Fc` and `pg_restore` restored every row but exited 1: 18 errors into another workspace, 11 into a fresh project in the same workspace with the same identity. [runs]
- `--no-owner --no-acl` took it from 18 errors to 7; the 7 left were all Lakebase platform objects. Adding the filtered list (`-L`) gave exit 0. Both are required; `--single-transaction --exit-on-error` doesn't change a clean run, but rolls back a failed one. [runs]
- In the original test dump, the filter commented out 10 platform entries. In the lab, it commented out 33 of 81 entries in `databricks_postgres` (the synced table adds internal entries) and 8 of 31 in `reporting`. The filter reflects what Lakebase put in dumps on Postgres 17.11 in September 2026. [runs] [lab]
- Full restore into an empty database: 8.7 seconds in the first test, versus 16.6 seconds for a data-only load into tables that migrations had created. Four re-runs were all slower for the data-only load, by varying amounts. [runs]
- The deck's move commands ran as a script with exit 0 into fresh projects on both clouds, in 22.8 seconds and 41.7 seconds, with identical schema, rows, and sequences. [runs]
- `pg_dump` against a grandchild branch captured everything that branch sees: what it inherited plus its own changes. [runs]
- A 20-level branch chain, built empty on the new side and filled with one dump and restore per branch: all 21 branches matched exactly, down to an md5 of every table and view. At that tiny size, each branch took about 7.5 seconds to dump and 3.5 seconds to restore. [runs]
- A pattern in `--exclude-table` that matches nothing isn't an error, even with `--strict-names`. A view that reads an excluded synced table is still dumped, and the restore fails. (Checked on a local PostgreSQL 17.10.) [runs]
- In the lab, each database's dump took under a second and each restore about 0.2 to 0.3 seconds. [lab]

## Synced tables

- A synced table through `pg_dump` fails on restore with `[Databricks SyncedTable] Consider using the databricks_synced_table_add_manager ...`. Stripping its label gives an empty partitioned table that blocks recreating the sync. Excluding it and recreating the sync works. [runs]
- The sync filled about 33 seconds after the create call reported done, for 1,000 rows in the runs and 50 rows in the lab. [runs] [lab]
- `get-synced-table` doesn't return the sync's spec, so keep it in Git. [runs]
- In the lab, the swap (delete the old sync, create the new one, wait for the rows) took about 40 to 45 seconds. [lab]

## Bundles

- A bundle deploy created a project, four branches, and four computes in 23.8 to 25 seconds, with zero tables on every branch. [runs] In the lab, a deploy of the project, two branches, and one compute took about 15 seconds. [lab]
- `bundle validate` passes without `no_expiry`; `bundle deploy` then fails with `Expiration must be specified`. [runs]
- `lifecycle.prevent_destroy` refused `bundle destroy` and a `pg_version` bump, with CLI 1.17.0. [runs] [lab]
- `bundle generate` has no Lakebase option. `bundle deployment bind` needs full resource names. [runs]
- Bundle resource types listed for Lakebase: projects, branches, endpoints, databases, roles, catalogs, synced tables, and snapshot schedules. Only projects, branches, and endpoints were tested. [docs] [runs]
- Lakebase support in bundles is labeled Beta. [docs]

## Access, identities, and tokens

- After `--no-owner --no-acl`, every restored object belongs to whoever ran `pg_restore`. [runs] [lab]
- `pg_restore --role=<owner role>` failed on the first `CREATE SCHEMA` with `permission denied for database`. [runs]
- Every Databricks identity role, CI's included, had the `REPLICATION` attribute in our runs; password roles didn't. Not documented that we found. [runs]
- Password logins need `enable_pg_native_login` on the project; turning it on took about 2 seconds. [runs]
- An OAuth database token lasts an hour and is checked only at connect. A 318-second query that spanned expiry finished, and an idle session kept working; a new connection with the expired token was refused. The minimum credential lifetime is 300 seconds. [runs]
- A four-way parallel `pg_dump -Fd -j 4` on a fresh service principal OAuth token ran clean in 15.6 seconds. [runs]
- Apps that sign in with OAuth need a Postgres role in the new project and the Workspace access entitlement to generate credentials. [docs]

## The live-app runs

- Two runs moved a live app (an order every second) with password logins, group roles, a synced catalog, a second database, unreleased work on child branches, and CI. [runs]
- Both passed all 27 independent checks against the source, with zero lost orders: 53,299 orders in the first and 57,411 in the second. [runs]
- Write pause: 25 min 49 s in the first (7 min 50 s of work, then 17 min 59 s waiting on a sign-off with the app ready on the new side), 5 min 48 s in the second (only production's steps while paused). [runs]
- In the lab, writes were paused about 60 to 70 seconds, about 40 to 45 of them for the synced-table swap. [lab]

## The lab itself

- Runs on serverless environment version 5 (pinned), and passed on versions 1 through 4: Python 3.10 to 3.12, x86 and ARM, Ubuntu 22.04 and 24.04. A full run takes about 4 to 5 minutes. [lab]
- Passed as a service principal in jobs and as a workspace user in an interactive Run all. [lab]
- Expected data: 1,000 customers, 5,000 orders plus 25 before the pause (watermark 5025), 3 migrations on production, 200 rows in `reporting`, 50 synced rows; new orders 5026 to 5030 after the switch. [lab]

## Not tested

- Large volumes (the runs moved about 200,000 rows, 2.3 MB compressed) and parallel restore.
- Writes during the dump; every run paused writes first.
- Classic clusters for the lab.
- Disaster recovery (Private Preview).
- The bundle resources for databases, roles, catalogs, synced tables, and snapshot schedules.
- Registering a Lakebase database in Unity Catalog, protected branches, HA and read replicas, and the Data API.
- Secretless GitHub sign-in for CI.
- An app that signs in with OAuth through a move (the live-app runs used a password role).

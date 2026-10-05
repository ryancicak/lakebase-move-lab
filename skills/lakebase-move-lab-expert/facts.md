# Limits and test sources

Product limits and the earlier experiments are recorded here. Current notebook results, timings, source hashes, and cleanup evidence belong in [TESTING.md](../../TESTING.md). The measured databases were small and synthetic, not sizing benchmarks.

Tags: **[lab]** tested in the lab (dates noted below; current walkthrough in [TESTING.md](../../TESTING.md)); **[runs]** tested in the runs behind the lab, five moves from an AWS workspace to an Azure workspace (September 28 to 30, 2026, PostgreSQL 17.11, Databricks CLI 1.17.0); **[docs]** from the Databricks docs, not tested; **[not tested]**.

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
- The restore window (point-in-time history) is 2 to 30 days, 7 by default, and belongs to the project. [docs] The new project records its own history from its creation; it doesn't inherit the old project's past. A point-in-time branch from just before the restore was empty. [lab]
- `CREATE PUBLICATION` and `CREATE SUBSCRIPTION` are disabled, so there's no logical replication between projects. [runs]
- There's no in-place major version upgrade. [docs] Bumping `pg_version` on a deployed bundle plans a delete and recreate of the project. [runs]

## Dump and restore

- The documented `pg_dump -Fc` and `pg_restore` restored every row but exited 1: 18 errors into another workspace, 11 into a fresh project in the same workspace with the same identity. [runs]
- `--no-owner --no-acl` took it from 18 errors to 7; the 7 left were all Lakebase platform objects. Adding the filtered list (`-L`) gave exit 0. Both are required; `--single-transaction --exit-on-error` doesn't change a clean run, but rolls back a failed one. [runs]
- In the original test dump, the filter commented out 10 platform entries. In the lab, it commented out 33 of 81 entries in `databricks_postgres` (the synced table adds internal entries) and 8 of 31 in `reporting`. The filter reflects what Lakebase put in dumps on Postgres 17.11 in September 2026. [runs] [lab]
- Full restore into an empty database: 8.7 seconds in the first test, versus 16.6 seconds for a data-only load into tables that migrations had created. Four re-runs were all slower for the data-only load, by varying amounts. [runs]
- The move commands ran as a script with exit 0 into fresh projects on both clouds, in 22.8 seconds and 41.7 seconds, with identical schema, rows, and sequences. [runs]
- `pg_dump` against a grandchild branch captured everything that branch sees: what it inherited plus its own changes. [runs]
- A 20-level branch chain, built empty on the new side and filled with one dump and restore per branch: all 21 branches matched exactly, down to an md5 of every table and view. At that tiny size, each branch took about 7.5 seconds to dump and 3.5 seconds to restore. [runs]
- A pattern in `--exclude-table` that matches nothing isn't an error, even with `--strict-names`. A view that reads an excluded synced table is still dumped, and the restore fails. (Checked on a local PostgreSQL 17.10.) [runs]

## Synced tables

- A synced table through `pg_dump` fails on restore with `[Databricks SyncedTable] Consider using the databricks_synced_table_add_manager ...`. Stripping its label gives an empty partitioned table that blocks recreating the sync. Excluding it and recreating the sync works. [runs]
- The sync filled about 33 seconds after the create call reported done, for 1,000 rows in the runs and 50 rows in the lab. [runs] [lab]
- `get-synced-table` doesn't return the sync's spec, so keep it in Git. [runs]
- In the lab, the swap (delete the old sync, create the new one, wait for the rows) took about 40 to 45 seconds. [lab]
- In one workspace (one metastore), a synced table's name can point at only one project: creating it on the new project had to wait until the old sync was deleted and the name was released. [lab] Creating the new sync before the pause when the metastores are separate follows from that, but wasn't tested; the two live-app runs created their syncs during the pause. [not tested]

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

## The lab itself

- Runs on serverless environment version 5 (pinned), and passed on versions 1 through 4: Python 3.10 to 3.12, x86 and ARM, Ubuntu 22.04 and 24.04. [lab]
- The lab pins databricks-sdk 0.146.0, psycopg 3.3.6, protobuf below 6, and Databricks CLI 1.17.0. The package-change notice after installation is expected. [lab]
- In an interactive run, `dbutils.notebook.exit` replaces its cell's output with `Notebook exited: <value>`. That hid the preflight's summary table and verdict until the exit moved to a cell of its own (October 3). [lab]
- The lab ran twice in one Python session: Module 7, then Modules 1 to 7 again. The second pass made new projects and a new restore time, and running Module 7 a third time found nothing and deployed nothing. [lab]
- A point-in-time branch can't start before its project existed: `The provided timestamp is before your project was created, try a more recent timestamp.` [lab]
- With default answers and no `CREATE SCHEMA` on `main`, the optional sync skipped and the lab passed. With a usable catalog, the sync ran. A learner going cell by cell can fix box 3 and rerun Step 6 after a skip. [lab]
- Setup changes are guarded once resources exist. After a session restart, run from the top before changing a box so the helper state exists. [lab]
- Creating a project took 5 to 6 seconds in every run. Once, the CLI's 18 MB download from GitHub dropped after 64 KB (`IncompleteRead`), so the lab now tries each download three times. [lab]
- Passed as a service principal in jobs and as a workspace user in an interactive Run all. [lab]
- Names: projects `lb-move-old-<slug>-<user id>` and `lb-move-new-<slug>-<user id>`, schema `<catalog>.lb_move_<slug>_<user id>`, secret scope `lb-move-lab-<slug>-<user id>`. The user id keeps two learners whose user names start alike from sharing a schema or scope. [lab]
- The lab tags its projects `Lakebase move lab: old home` and `Lakebase move lab: new home`. The project link uses the API's UID because a URL with the project name returns `project not found`. [lab]
- The lab only reuses a project it made in the same session. A same-named project with the lab's tag stops it as a leftover from an earlier run; one without the tag stops it as someone else's. Cleanup deletes only tagged projects. [lab]
- The copy check compares each database's app schema definitions (a schema-only `pg_dump` of `app`, without owners, grants, and the dump's own header lines) and every app table's row count and checksum, plus the watermark and migration history. It doesn't cover access, which is rebuilt later, or anything outside the `app` schema. [lab]
- Fresh installs use `sslrootcert=system` for psycopg and `PGSSLROOTCERT=system` for the Postgres tools, with hostname and certificate verification still on. The earlier default-root-certificate failure and corrected reruns are in `TESTING.md`. [lab]
- Both setup cells refuse to replace a saved destination with a different workspace. Later sign-in checks compare the saved host with box 2 before using its credentials. Connection retries give a route change its own attempt, even on the last retry, and exhausted retries raise rather than returning `None`. Covered in local helper tests; the rare last-retry and conflicting-scope cases were mocked, not forced in a live workspace. [lab]
- Module 7 cleaned up runs stopped after the bundle deploy and after the synced-table move, both in the same session and after Python restarted. [lab]
- The project's creator was a member of `pg_read_all_stats`, so `pg_stat_activity` showed every session's state, including another session `idle in transaction`. Lakebase's own `cloud_admin` sessions sat idle in the `postgres` database. The lab's pause check counts other client sessions in the app databases that are `active` or `idle in transaction`. [lab]

## Two workspaces (the lab's optional mode)

- From AWS serverless, the tested Azure computes needed their public IP through libpq `hostaddr` after the proxy either refused authorization or presented a certificate for the wrong hostname. Both routes keep the original hostname, `verify-full`, and system trust. Only those two signatures enable fallback. Other workspace pairs weren't tested. [lab] [not tested]
- Across workspaces, the cross-project branch and the cross-project snapshot were rejected with the same errors as inside one workspace. [lab]
- The notebook's bundle deploy, redeploy, and destroy ran against the other workspace, with the CLI signed in through the secret scope's token. [lab]
- The two workspaces had separate metastores, so the lab skipped the synced table on the new side. Moving a synced table between two workspaces that share a metastore wasn't tested. [lab] [not tested]
- **Choose your setup** (the first code cell) puts three widgets at the top. In an interactive notebook, Databricks re-ran it on its own when the dropdown or the URL box changed. [lab]
- On serverless, Python's `getpass` shows a masked input box under the cell in an interactive notebook, and what you type isn't echoed. In a job, it raises `StdinNotImplementedError` at once, so the lab stops with the CLI command to store the token instead of hanging. [lab]
- A wrong token got the "That token didn't work in the other workspace" prompt; with a working token stored, the cell signed in and printed the user name there. [lab]
- An empty token input is rejected with `The token box was empty` before setup saves a token. The current helper tests cover this in both notebooks. A token already stored in the scope uses the same sign-in check without showing the hidden input again. [lab]

## Not tested

- Large volumes (the runs moved about 200,000 rows, 2.3 MB compressed) and parallel restore.
- Writes during the dump; every run paused writes first.
- Classic clusters for the lab.
- The bundle resources for databases, roles, catalogs, synced tables, and snapshot schedules.
- Registering a Lakebase database in Unity Catalog, protected branches, HA and read replicas, and the Data API.
- Secretless GitHub sign-in for CI.
- An app that signs in with OAuth through a move (the live-app runs used a password role).
- Disaster recovery is a separate regional-standby workflow, not a one-time move. It is Private Preview and wasn't tested here. [docs]
- Lakebase Change Data Feed streams row changes into Delta tables, not into another Lakebase branch. It is Public Preview and wasn't tested here. [docs]

# Facts, numbers, and where they come from

This is the canonical list. When another reference file disagrees with it on a fact or a number, this file wins. To change a fact, change it here first, then the files that repeat it: `SKILL.md`, `lab-walkthrough.md`, `playbook.md`, and `troubleshooting.md`. Times and counts here come from small synthetic databases in a few specific setups, not estimates for a real move.

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
- In the lab, writes were paused about 60 to 70 seconds, about 40 to 45 of them for the synced-table swap. The lab's pause is simulated (its pretend app just stops), and its database is tiny. [lab]

## The lab itself

- Runs on serverless environment version 5 (pinned), and passed on versions 1 through 4: Python 3.10 to 3.12, x86 and ARM, Ubuntu 22.04 and 24.04. A full run takes about 4 to 5 minutes. [lab]
- The lab pins its packages: databricks-sdk 0.146.0, psycopg 3.3.6, and the Databricks CLI 1.17.0. The final October 2 runs used those, with protobuf 5.29.6 and the PostgreSQL 17.9 client tools. With the pins, the lab passed again on environment versions 1 through 4 on October 3, and once more on the final notebook, with each run printing its runtime: `client.1.13` (Python 3.10.12), `client.2.5` (3.11.10), `client.3.6` and `client.4.10` (3.12.3). Version 1 (Ubuntu 22.04) printed pip's red note that `googleapis-common-protos` wants protobuf below 5. In the notebook UI, version 5 shows an orange `Core Python package version(s) changed` box after the install (`databricks-sdk: 0.67.0 -> 0.146.0`). Both are harmless, and the lab says to expect them. [lab]
- In an interactive run, `dbutils.notebook.exit` replaces its cell's output with `Notebook exited: <value>`. That hid the preflight's summary table and verdict until the exit moved to a cell of its own (October 3). [lab]
- The lab ran twice in one Python session: Module 7, then Modules 1 to 7 again. The second pass made new projects and a new restore time, and running Module 7 a third time found nothing and deployed nothing. [lab]
- A point-in-time branch can't start before its project existed: `The provided timestamp is before your project was created, try a more recent timestamp.` [lab]
- First-time-user runs on October 3, interactively, as a workspace user, in a freshly imported notebook. Run all with the default answers, and only `USE CATALOG` on `main`, skipped the synced-table steps and took about 2.3 minutes of cell time. With a catalog the user owned, it took about 3.2 minutes. Cell by cell, after the skip, putting that catalog in box 3 and running Step 6 again synced the table mid-lab. A second box change after that was refused, and the lab finished and cleaned up. [lab]
- The widgets' default setting is Run Accessed Commands. With the notebook idle, a changed box re-ran **Choose your setup** and the helpers cell on their own; during a Run all, it re-ran neither, then or after. After the session detached, a changed box re-ran both too, and the helpers cell failed with `NameError: name 'os' is not defined`, because the cells between them hadn't run in the new session. Now it stops first with a message to click Run all, and Run all then passed (October 3). [lab]
- Creating a project took 5 to 6 seconds in every run. Once, the CLI's 18 MB download from GitHub dropped after 64 KB (`IncompleteRead`), so the lab now tries each download three times. [lab]
- Passed as a service principal in jobs and as a workspace user in an interactive Run all. [lab]
- Expected data: 1,000 customers, 5,000 orders plus 25 before the pause (watermark 5025), 3 migrations on production, 200 rows in `reporting`, 50 synced rows; new orders 5026 to 5030 after the switch. [lab]
- Names: projects `lb-move-old-<slug>-<user id>` and `lb-move-new-<slug>-<user id>`, schema `<catalog>.lb_move_<slug>_<user id>`, secret scope `lb-move-lab-<slug>-<user id>`. The user id keeps two learners whose user names start alike from sharing a schema or scope. [lab]
- The lab tags its projects with display names, `Lakebase move lab: old home` and `Lakebase move lab: new home` (the bundle sets `display_name`; CLI 1.17.0's `bundle validate` warns on unknown fields and didn't on this one). A project's display name comes back in `status.display_name`. [lab]
- The lab only reuses a project it made in the same session. A same-named project with the lab's tag stops it as a leftover from an earlier run; one without the tag stops it as someone else's. Cleanup deletes only tagged projects. [lab]
- The copy check compares each database's app schema definitions (a schema-only `pg_dump` of `app`, without owners, grants, and the dump's own header lines) and every app table's row count and checksum, plus the watermark and migration history. It doesn't cover access, which is rebuilt later, or anything outside the `app` schema. [lab]
- Module 7 cleaned up a run stopped on purpose right after Module 3's deploy: both projects, the synced table, the schema, and the bundle folder. It worked in the same session, and after re-running the cells from the top through Module 0 (which restarts Python), when it deleted the new home directly because the session had no bundle. A run stopped right after Module 4's synced-table move was cleaned up too: Step 1's destroy was refused, and Step 2 deleted the synced table, both projects, and the schema (October 3). [lab]
- The project's creator was a member of `pg_read_all_stats`, so `pg_stat_activity` showed every session's state, including another session `idle in transaction`. Lakebase's own `cloud_admin` sessions sat idle in the `postgres` database. The lab's pause check counts other client sessions in the app databases that are `active` or `idle in transaction`. [lab]

## Two workspaces (the lab's optional mode)

- From an AWS workspace (us-west-2) to an Azure workspace (eastus2), as serverless jobs and interactively on environment version 5, October 2, 2026: every cell passed. The restores exited 0 in about 5 seconds across clouds, every app table matched, the last checklist passed 7 of 7, writes were paused 44 to 57 seconds (no synced-table swap, tiny data; 57 once the copy check also compared schemas, which took about 18 seconds across clouds), and the teardown cleaned up both workspaces. [lab]
- In that setup, from serverless in the AWS workspace, Lakebase hostnames resolved to one private Databricks proxy address, for that workspace's computes and the Azure workspace's. The proxy refused the Azure compute: `FATAL: External authorization failed`. Connecting to that compute's public IP from public DNS (libpq `hostaddr`) worked. With the fallback, the lab printed that it switched, and the preflight's connect check reported the public address. [lab] The live-app runs never hit this, because they ran `pg_dump` and `pg_restore` outside Databricks. [runs] Other pairs, like two workspaces in the same cloud or region, weren't tested, so the lab tries the normal route first and switches a compute to its public address only on that error. [not tested]
- Across workspaces, the cross-project branch and the cross-project snapshot were rejected with the same errors as inside one workspace. [lab]
- The notebook's bundle deploy, redeploy, and destroy ran against the other workspace, with the CLI signed in through the secret scope's token. [lab]
- The two workspaces had separate metastores, so the lab skipped the synced table on the new side. Moving a synced table between two workspaces that share a metastore wasn't tested. [lab] [not tested]
- The preflight with a second workspace: 25 checks passed and 1 warning (separate metastores), and its cleanup ran in both workspaces. [lab]
- **Choose your setup** (the first code cell) puts three widgets at the top. In an interactive notebook, Databricks re-ran it on its own when the dropdown or the URL box changed. [lab]
- On serverless, Python's `getpass` shows a masked input box under the cell in an interactive notebook, and what you type isn't echoed. In a job, it raises `StdinNotImplementedError` at once, so the lab stops with the CLI command to store the token instead of hanging. [lab]
- A wrong token got the "That token didn't work in the other workspace" prompt; with a working token stored, the cell signed in and printed the user name there. [lab]

## Not tested

- Large volumes (the runs moved about 200,000 rows, 2.3 MB compressed) and parallel restore.
- Writes during the dump; every run paused writes first.
- Classic clusters for the lab.
- Disaster recovery (Private Preview).
- The bundle resources for databases, roles, catalogs, synced tables, and snapshot schedules.
- Registering a Lakebase database in Unity Catalog, protected branches, HA and read replicas, and the Data API.
- Secretless GitHub sign-in for CI.
- An app that signs in with OAuth through a move (the live-app runs used a password role).

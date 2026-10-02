# The lab, cell by cell

`lakebase_move_lab` is one Databricks notebook. It runs on serverless compute, and its first line pins serverless environment version 5 (versions 1 through 4 also passed; classic clusters weren't tested). A full Run all takes about 5 minutes. The expected outputs below come from tested runs on October 1 and 2, 2026, including an interactive Run all by a workspace user. Your hosts, IDs, and timings will differ.

Two projects in one workspace stand in for two workspaces. A branch can't leave its project even inside one workspace, so moving between two projects is the same job as moving between workspaces. The lab says where a real cross-workspace move differs.

## Settings a learner can change

All in Module 0's helpers cell, **Connect, name the two projects, and define helpers**. They're settings in the code, not widgets:

- `CATALOG` (default `main`): the Unity Catalog catalog for the synced-table steps. The learner needs `CREATE SCHEMA` on it. If they don't have it, the lab skips the synced-table steps and says why; it doesn't fail.
- `DO_SYNCED_TABLES` (default `True`): set to `False` to skip the synced-table steps on purpose.
- Names: the projects are `lb-move-old-<slug>-<user id>` and `lb-move-new-<slug>-<user id>`, where the slug is the part of the user name before `@`, lowercased, with anything else turned into hyphens, cut to 16 characters. The schema is `<catalog>.lb_move_<slug with underscores>`. The bundle is named `lb-move-lab` and keeps its state in `/Workspace/Users/<user>/.bundle/lb-move-lab`.

## Before Module 0

- The `%pip` cell installs `databricks-sdk>=0.81.0` (the first version with the Lakebase API, `w.postgres`), plain `psycopg>=3.1`, and `protobuf<6`. On older serverless versions pip may print a red dependency-conflict note about `protobuf` from a preinstalled package; it's harmless. The next cell restarts Python.

## Module 0: Set up your tools

- **Download and unpack the PostgreSQL 17 client tools**: reads the machine's Ubuntu release and CPU type, downloads `postgresql-client-17` and `libpq5` from apt.postgresql.org, and unpacks them with `dpkg-deb -x` (serverless has no `apt-get`, and no admin rights are needed). Prints the `pg_dump` and `pg_restore` versions, for example `pg_dump (PostgreSQL) 17.9`. The client must be the same as or newer than the database's Postgres version, and the lab's projects are Postgres 17.
- **Download the Databricks CLI**: downloads the pinned CLI release (1.17.0) for the machine's CPU type from GitHub into a temp folder. Prints `Databricks CLI v1.17.0`. The bundle steps run real `databricks bundle` commands with it.
- **Connect, name the two projects, and define helpers**: creates the `WorkspaceClient`, loads psycopg, picks the names, and defines the helpers. Prints `Signed in as`, `Old home`, and `New home`.
  - psycopg runs in its pure-Python mode on the `libpq` the first cell downloaded. The `psycopg[binary]` package bundles its own OpenSSL, which fails a FIPS self-test and kills the Python kernel on some serverless machines (seen on environment versions 3 to 5). The downloaded `libpq` uses the machine's own OpenSSL. psycopg finds libpq by asking `ctypes.util.find_library("pq")`, so the cell answers that one lookup with the downloaded file while psycopg imports.
  - Every connection gets a fresh one-hour login token, so nothing expires mid-lab. In Lakebase, the Databricks identity is the Postgres user.
  - `cli()` runs the CLI with a token from the notebook's own sign-in, passed in its environment and never printed.
  - `fingerprint()` counts each table's rows and takes an md5 over every row in a fixed order. Two copies are identical when every table's count and md5 match.
  - The app's migrations, V1 to V4, are defined here. `migrate()` applies the ones a branch hasn't had and records them in `app.schema_migrations`, the way Flyway or Liquibase would. Once the `app_owner` role exists, it runs `SET ROLE app_owner` first, so new objects belong to that role and pick up its default privileges.

## Module 1: Build the old home

- **Step 1, Create the old home's project**: `Created project lb-move-old-... (Postgres 17)` and the production compute's host. Reuses the project if it exists.
- **Step 2, Migrate production to V2 and load data**: `applied V1: customers`, `applied V2: orders`, then 1,000 customers and 5,000 orders. Loads data only if the tables are empty.
- **Step 3, Create the reporting database on production and load it**: `Created database reporting ...`; the databases are `databricks_postgres`, `postgres`, and `reporting`; 200 rows in `reporting`'s `app.stock`. This is there to show that `pg_dump` and `pg_restore` work one database at a time.
- **Step 4, Create roles, hand ownership to app_owner, grant read access, in both databases**: creates `app_owner` and `app_reader` (both `NOLOGIN`) once, because roles belong to the branch, then sets ownership, grants, and default privileges in each database, because those belong to each database. Shows 4 tables, all owned by `app_owner` and readable by `app_reader`.
- **Step 5, Branch production into development and make dev-only changes**: creates `development` from production, applies V3 and V4 there (V4, feature flags, is unreleased), adds the coupon `DEV-TEST-50` to orders 11, 22, and 33, and adds two feature flags. Development shows V1 to V4; production still shows V1 and V2.
- **Step 6 (optional), Create a Delta table and sync it into old production**: creates the schema and a 50-row Delta table (Change Data Feed on), then a Snapshot-mode synced table into old production. The create call returns before the rows land, so it waits: `Synced: 50 rows in Postgres, state ...ONLINE..., after 33 s`. If the catalog can't be used, it prints `Skipping the synced-table steps: <reason>` and sets `DO_SYNCED_TABLES = False`. Re-running reuses an existing synced table.

## Module 2: Promote a change the everyday way

- **Run V3 on production, then use the new table**: `applied V3: coupons`; production gets the real coupon `FALL10`. Production has `FALL10` only, and development has `DEV-TEST-50` only. Promotion moves schema, not data, and a branch never picks up its parent's later changes.
- **The new table picked up the default grants**: `coupons` belongs to `app_owner` and `app_reader` can read it, because V3 ran as `app_owner`.

## Module 3: The old home is going away: build the new home

The deck's five steps for a move: put it all in Git; deploy the bundle and leave production un-migrated; restore production from a full dump, one database at a time; recreate synced tables and let them fill; recreate the child branches. Module 3 does steps 1 and 2.

- **Step 1: write the bundle file (it would live in Git)**: prints `databricks.yml` for the new home:
  - `postgres_projects.app` with `pg_version: 17`, `history_retention_duration: 604800s` (the restore window, 7 days; it's a setting, so you set it again on the new side), `purge_on_delete: true` (lab only, so the name is free right after deletion), and `lifecycle: { prevent_destroy: true }`.
  - `postgres_branches.production` with `replace_existing: true`, because Lakebase creates production with the project and the bundle adopts it, plus `prevent_destroy`.
  - `postgres_branches.development` with `source_branch` set to production and `no_expiry: true`, because every branch you add needs an expiry setting.
  - `postgres_endpoints.development_primary` with `replace_existing: true`.
- **Step 2: databricks bundle validate, then deploy**: `Validation OK!`, then `Created postgres_projects.app`, `Created postgres_branches.production`, `Created postgres_branches.development`, `Created postgres_endpoints.development_primary`, and `Resources: 4 created`. About 15 seconds.
- **What the bundle built**: both computes' hosts, and new production has only `databricks_postgres` and `postgres`, with no app tables. It stays empty and un-migrated on purpose, because the restore brings the schema, the data, and the migration history together, and a restore into tables that already exist fails.
- **Try to branch the new home from the old home's production**: `Rejected, as expected: source_branch field must point to the branch from the same Project`. That's the core lesson.

## Module 4: Move the data

- **The app places a few orders, then writes pause and we take a watermark**: inserts 25 orders, then `Writes paused. Watermark: newest order_id 5025, 5025 orders.` and the count of other active sessions (0). It also starts the pause timer.
- **Which databases does old production have?**: lists them and moves every database except the built-in, empty `postgres`: `databricks_postgres` and `reporting`.
- **pg_dump each database on old production**: one `pg_dump -Fc` per database. In `databricks_postgres` it adds `--exclude-table=<schema>.product_catalog_synced`. Prints `databricks_postgres: pg_dump exit code 0` (about 72 KB) and `reporting: pg_dump exit code 0` (about 10 KB), then `Synced table entries left in the dumps: 0`, which catches a mistyped exclude.
- **Comment out Lakebase's own platform entries, in each dump**: lists each dump with `pg_restore -l` and puts a `;` in front of lines matching ` (cloud_admin|databricks_control_plane)$|__db_system`. Prints `databricks_postgres: 81 entries in the dump, 33 commented out` (the synced table adds internal `__db_system` entries) and `reporting: 31 entries in the dump, 8 commented out`.
- **Create the extra databases on new production**: `Created database reporting ...`. Every new project starts with `databricks_postgres`, but `pg_restore` restores into an existing database.
- **pg_restore each database into new production**: `--no-owner --no-acl --single-transaction --exit-on-error -L <filtered list> -d <database>`, once per database. Prints `pg_restore exit code 0` for each. It notes the time first (Module 5 uses it). It skips any database that already has app tables, so re-running is safe.
  - Why not the documented restore: in our runs it restored every row but exited 1, with 18 errors into another workspace and 11 even into a fresh project in the same workspace. They come from two places: owners and grants from the old side, and Lakebase's own platform entries, which every database already has. `--no-owner --no-acl` took it from 18 errors to 7, and the filtered list took it to 0. Both are required. `--single-transaction --exit-on-error` rolls a failed restore back instead of leaving it half done.
- **Compare old and new production, database by database**: 5 tables, all identical (`coupons` 1, `customers` 1,000, `orders` 5,025, `schema_migrations` 3, `stock` 200), the watermark matches (5025), and the migration history is [1, 2, 3]. Then `New production is an exact copy of old production, in every database.` If someone re-ran earlier cells after the restore, this assert fails; run Module 7 and start over.
- **Step 4 (optional), Replace the sync: old project out, new project in**: deletes the old project's sync, creates the same synced table name on new production (retrying while the name is released), waits for 50 rows (about 33 seconds), and proves it's current: the Delta version it last synced equals the newest version in `DESCRIBE HISTORY`. In one workspace (one metastore), a synced table's name can point at only one project, so the old sync goes first, during the pause. Why during the pause: the app runs on the old side until the switch, so its sync stays in place until writes stop, and reusing the name keeps the Postgres table name the same for the app. The sync copies from the Delta table, so the app's writes don't change what it copies. With separate metastores, you could create the new sync before the pause (not tested).
- **Access on new production right after the restore**: no `app_owner` or `app_reader` role exists, and every table, in both databases, belongs to whoever ran the restore.
- **Recreate roles, ownership, and grants on new production**: the same access SQL, run on production before the children are rebuilt, so they inherit it. All tables owned by `app_owner` and readable by `app_reader`.
- **Check everything before the switch**: seven checks, all ✅: every database identical; watermark matches; sequences carried over; migration history carried over; `app_reader` can read every table; synced table current (or not used); and an app smoke test. The smoke test inserts order `-1` and reads it back inside a transaction that always rolls back, so it doesn't use a sequence value.
- **Point the app at the new home and place new orders**: the old and new hosts, new orders `[5026, 5027, 5028, 5029, 5030]` right after the watermark (the dump carried the sequence values), and the old home's newest order still 5025. It prints how long writes were paused, about 60 to 70 seconds in tested runs, and how much of that was the synced-table swap (about 40 to 45 seconds). If the learner stopped to read, that time is included.
- **Step 5, The child branch the bundle created before the restore**: `has_app_tables` is false. A branch is a copy as of when it was created, and the bundle created `development` while production was empty.
- **Delete development, then redeploy the bundle to recreate it**: deletes the branch (purge), runs `bundle deploy` again, and the bundle recreates the branch and its compute from the restored production: `Resources: 2 created, 0 changed, 0 deleted, 2 unchanged`. Development then has 5,030 orders, migrated to V3, `app_reader` can read, and `reporting` has 200 rows. This is the deck's "delete, redeploy, then migrate."
- **Replay V4, carry dev-only tables, reconcile shared rows**: applies V4 on the new development, copies the dev-only `feature_flags` rows with a data-only dump of just that table, then reconciles dev's own changes to shared tables: `Reconciled 1 dev-only coupon(s) and 3 order update(s)`. Development ends with coupons `DEV-TEST-50, FALL10`, 2 feature flags, 3 orders on the dev coupon, and `app_reader` can read the flags. Re-running skips the copy if the flags are already there.
- **(Optional) The shortcut that fails: a full data-only dump of dev**: `pg_restore exit code: 1` with `duplicate key value violates unique constraint "coupons_pkey"`. A data-only dump of a whole child includes production's rows too. Because of `--single-transaction`, nothing changes: development still has 1,000 customers.

## Module 5: What doesn't come along

- **Branch the new home's production from before the move**: a point-in-time branch at the moment just before the restore has no app tables. The new project's history starts at the move. The branch is deleted again.
- **Snapshot old production, then try to restore it in the new home**: `Created snapshot: ...`, then `Rejected, as expected: source_snapshot field must point to a snapshot from the same Project`. Snapshot creation retries up to 3 times; if it still fails, the cell prints `Couldn't create a snapshot here, so skipping this demo` and the lab continues.

## Module 6: Doing it for real

No code. A checklist for a real move: before the day, on the day, and after. See `playbook.md`.

## Module 7: Clean up

- **Step 1: try bundle destroy with the guard in place**: writes the bundle with `prevent_destroy`, runs `databricks bundle destroy --auto-approve`, and gets exit code 1: `resources.postgres_branches.production has lifecycle.prevent_destroy set, but the plan calls for this resource to be recreated or destroyed`, and the same for the project. `The new home still exists: True`.
- **Step 2: remove the guard, destroy the new home, and delete everything else**: guarded by `CONFIRM_TEARDOWN = True`. Deletes the synced table, rewrites the bundle without the guard, redeploys (4 unchanged), and destroys (`Destroy: 4 deleted`, a hard delete because of `purge_on_delete`). Then deletes the old project with `purge=True`, drops the lab's schema, deletes the bundle folder, and removes local files. Ends with `Done.`

## Re-running and starting over

- Safe to re-run: project, migration, database, access, branch, synced-table, promotion, bundle, dump, filter, restore (skips), compare, access rebuild, gate, and dev-work cells.
- Not meant to be re-run: the watermark cell (adds 25 orders and restarts the pause timer), the switch cell (adds 5 orders), the synced-table swap (recreates the sync), and the redeploy cell (deletes development again, including the dev work carried in after it).
- To start over, run Module 7, then Run all.
- Don't run two copies of the lab at once as the same user: they share project and bundle names and collide.

## The preflight notebook

`lakebase_move_lab_preflight` runs before the lab, in about 2.5 minutes, as the same user and on the same compute the lab will use. It records 20 checks as ✅ pass, ⚠️ warning (the lab still runs, minus a step), ❌ fail (fix before the lab), or ⏭️ skipped (a check it depends on failed), each with a fix:

1. Serverless compute; Python packages (PyPI); PostgreSQL client tools (apt.postgresql.org); psycopg on the downloaded libpq; Databricks SDK and the Lakebase API; Databricks CLI (github.com); CLI signs in as you.
2. No leftovers from an earlier lab run: the lab's projects, schema, or bundle folder. `CLEAN_LEFTOVERS = True` in its settings cell deletes them.
3. On a throwaway project, `lb-move-pre-<slug>-<user id>-<timestamp>`, deployed with the lab's bundle shape: bundle deploys a Lakebase project; connect with a login token; create a second database; roles, ownership, and grants; pg_dump and a filtered pg_restore; child branch and its compute; point-in-time branch; snapshots (warning only).
4. Schema and Delta table in the catalog, and synced table into Lakebase (both warnings only; set the **catalog** widget to the catalog the lab will use).
5. prevent_destroy guards the bundle; cleanup.

Each run has its own names, so two preflights at once don't collide, and a run deletes preflight leftovers older than 30 minutes. The last cell prints the verdict (ready, ready with notes, or not ready) and returns the results as JSON for Genie Code or a job. The `lakebase-move-lab-preflight` skill runs it as a one-time serverless job, from a copy next to the current notebook if there is one, otherwise straight from the GitHub repo.

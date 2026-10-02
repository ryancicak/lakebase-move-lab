# Troubleshooting

Match the error text or symptom, then give the cause and the fix. Everything here was seen in testing unless marked otherwise.

## Lab and preflight setup

| Error or symptom | Cause | Fix |
|---|---|---|
| `Fatal error: The Python kernel is unresponsive` right after psycopg is imported, and later cells show `Command skipped`. A job run can still report SUCCESS. | The `psycopg[binary]` package bundles its own OpenSSL, which fails a FIPS self-test and aborts Python on some serverless machines (seen on environment versions 3 to 5). In a separate process it shows `crypto/fips/fips.c:154: OpenSSL internal error: FATAL FIPS SELFTEST FAILURE`. | Use the lab's install as written: plain `psycopg` in the `%pip` cell, plus the `libpq` the first Module 0 cell downloads. Don't change the install back to `psycopg[binary]`. |
| A red pip note: `ERROR: pip's dependency resolver ...` about `protobuf` | A preinstalled package asks for an older `protobuf`. | Harmless; the lab runs fine with it. It doesn't appear on environment versions 3 to 5. |
| The `%pip` cell fails | Serverless can't reach PyPI. | A workspace admin allows PyPI, or a PyPI mirror, for serverless compute. |
| The PostgreSQL client cell fails with a connection error or timeout | Serverless can't reach apt.postgresql.org. | Allow HTTPS to apt.postgresql.org in the serverless network policy. |
| `Couldn't find [...] for <release>/<cpu> at https://apt.postgresql.org/...` | The PostgreSQL package repository has no client packages for that Ubuntu release and CPU type. | Not seen in testing. Send it to the lab's owner with the release and CPU type. |
| The CLI download cell fails | Serverless can't reach github.com. | Allow HTTPS to github.com. |
| `'WorkspaceClient' object has no attribute 'postgres'`, or the preflight says the SDK is older than 0.81 | An older Databricks SDK is loaded. | Run the `%pip` cell, then the restart cell, before the rest. |
| `Couldn't get a token for the CLI from this notebook's sign-in` | The notebook's sign-in didn't hand over a bearer token. | Run the notebook as yourself on serverless compute. Not seen in testing. |

## Lab steps

| Error or symptom | Cause | Fix |
|---|---|---|
| `Skipping the synced-table steps: ... PERMISSION_DENIED: User does not have CREATE SCHEMA on Catalog 'main'` | The user can't create schemas in the catalog. Seen for a workspace user who had only `USE CATALOG` on `main`. | Set `CATALOG` in Module 0's helpers cell to a catalog where the user can create schemas, or ask for `CREATE SCHEMA` on it. Then run Module 7 and Run all, so the synced-table steps run from the start. The rest of the lab works either way. |
| `[NO_SUCH_CATALOG_EXCEPTION] Catalog '<name>' was not found` in the synced-table step | `CATALOG` names a catalog that doesn't exist. | Fix the name in the helpers cell. The lab skips the synced-table steps until then. |
| `name still being released, retrying` in the synced-table swap | The old sync's name takes a moment to free up after it's deleted. | Normal; the cell retries up to 10 times. |
| `TimeoutError: synced_tables/...: state ..., N rows` | The synced table didn't come online with all rows within 15 minutes. | Check the synced table's state in Catalog Explorer. Not seen in testing; it took about 33 seconds. |
| `TimeoutError: No compute with a host on projects/...` | A branch's compute didn't get a host within 5 minutes. | Re-run the cell. Check the project in the Lakebase UI. |
| `pg_dump of <database> failed: ...` or `pg_restore of <database> failed: ...` | The tool's error follows the colon. | Match it in "Real moves" below. |
| `New production already has every database's tables. Skipping the restore` | The restore already ran. | Expected on a re-run. |
| `AssertionError: The copy doesn't match. If you re-ran earlier cells after the restore...` | Something changed old production after the restore, usually a re-run of the watermark cell. | Run Module 7, then Run all. |
| `AssertionError: Don't switch: a check failed` | The gate found a mismatch. | Look at the row marked ❌ in the table above it. |
| `AssertionError: The synced table is behind its source` | The new sync's Delta version is older than the source's newest. | The source table changed during the swap. Re-run the swap cell. Not seen in testing. |
| `Run the restore cell in Module 4 first` | The point-in-time cell needs the time recorded just before the restore. | Run Module 4's restore cell in this session first. |
| `Couldn't create a snapshot here, so skipping this demo`, or `INTERNAL_ERROR: Failed to create snapshot` | Seen once as a one-off platform error; the next tries succeeded. | The lab retries 3 times. If it still skips, the rest of the lab is fine. |
| `Failed to acquire deployment lock: deploy lock acquired by <user>` | Another deploy or destroy of the same bundle is running, usually two copies of the lab at once as the same user. | Run one copy at a time per user. Wait for the other to finish. |
| Module 3's deploy fails because the new project already exists, or the lab reuses an old project | Leftovers from an earlier run that didn't reach Module 7. | Run Module 7 in a session with the same names, or run the preflight with `CLEAN_LEFTOVERS = True`. |
| `pg_restore exit code: 1` with `duplicate key value violates unique constraint "coupons_pkey"` in the optional cell | Expected. A data-only dump of the whole dev branch includes production's rows too. | Nothing; that's the lesson. Nothing changed, thanks to `--single-transaction`. |
| Module 7, Step 1: `exit code 1` with `has lifecycle.prevent_destroy set` | Expected. The guard refuses the destroy. | Step 2 removes the guard and destroys for real. |

## The preflight and its Genie Code cell

| Error or symptom | Cause | Fix |
|---|---|---|
| ❌ `No leftovers from an earlier lab run: found project lb-move-old-...` | An earlier, or still running, lab run's projects, schema, or bundle folder. | Run the lab's Module 7, or set `CLEAN_LEFTOVERS = True` in the preflight's settings cell and run it again. Don't run the preflight while a lab run is in progress. |
| ⚠️ `Schema and Delta table in <catalog>` | No `CREATE SCHEMA` on the catalog, or no such catalog. | Pick a catalog where the user can create schemas: set it in the preflight's catalog widget and in the lab's `CATALOG` setting. |
| ⏭️ `skipped: needs ...` | A check it depends on failed. | Fix that check first. |
| ❌ `Bundle deploys a Lakebase project` | No permission to create Lakebase projects, or the home folder isn't writable (bundles keep state in `~/.bundle`). | The error names the permission; ask a workspace admin. |
| ❌ `Connect with a login token` | A timeout points at the serverless network policy; an authentication error is something else. | Network policy: ask the admin. Otherwise send the error to the lab's owner. |
| `The preflight stopped before it finished: ...` from the Genie Code cell | The preflight job failed before its last cell, usually at the `%pip` cell. | Open the job run link it prints. |
| The Genie Code cell fails on `runs/submit` with a permission error | The user can't submit one-time job runs, or serverless jobs aren't enabled. | Open `lakebase_move_lab_preflight` and click Run all instead. |
| The Genie Code cell's job can't fetch the notebook from GitHub | The workspace blocks GitHub as a Git source. | Put `lakebase_move_lab_preflight` in the same folder as the notebook you're asking from; the cell uses a copy next to it first. |

## Real moves

| Error or symptom | Cause | Fix |
|---|---|---|
| The documented `pg_restore` exits 1: 18 errors across workspaces, 11 even in the same workspace. Errors like `role "..." does not exist`, `already exists`, `permission denied to change default privileges`, `Permission denied to execute a function owned by a superuser role`, `grant options cannot be granted back to your own grantor` | Two sources: owners and grants from the old side, and Lakebase's own platform objects, which every database already has (the `__db_system` schema and its ACL, three `grant_*` event-trigger functions owned by `cloud_admin`, two default ACL entries, and three event triggers). | Restore with `--no-owner --no-acl` and a filtered list: `pg_restore -l dump \| sed -E '/ (cloud_admin\|databricks_control_plane)$\|__db_system/ s/^/;/' > toc`, then `-L toc`. Both fixes are required; in the same workspace with the same identity, `--no-owner` can go but `--no-acl` can't. |
| `[Databricks SyncedTable] Consider using the databricks_synced_table_add_manager ...` on restore, and nothing lands | A synced table went through `pg_dump`. | Exclude each synced table with `--exclude-table`, and recreate the sync on the new side. |
| A restored table is an empty partitioned shell: `no partition of relation "..." found for row`, and recreating the sync fails with `Destination table ... already exists` | Someone stripped the synced table's security label to force it through. | Don't. Drop that table on the new side, then recreate the sync. |
| `relation "..." does not exist` on restore, with nothing landing | A view reads a synced table that was excluded. | Exclude the view too (`-T` matches views), and recreate it once the sync is online. |
| `type "public.<type>" does not exist` restoring a single-table dump | A `pg_dump -t` file doesn't include the types or tables it references. | Use a full dump into an empty database. A single-table, data-only dump works only into a database that already has the schema, an empty table, and the rows it points to. |
| The synced table is still in the dump after `--exclude-table` | A pattern that matches nothing isn't an error, even with `--strict-names`. | Check `pg_restore -l dump \| grep <table>` before restoring. |
| `source_branch field must point to the branch from the same Project` | A branch's parent must be in the same project, even in the same workspace. | Rebuild on the new side instead: bundle, migrations, and a dump when data has to move. |
| `source_snapshot field must point to a snapshot from the same Project` | Snapshots restore only inside their own project. | Keep the old project for pre-move restores. |
| `CREATE PUBLICATION is not enabled on this Lakebase instance` or `CREATE SUBSCRIPTION ...` | Logical replication is disabled. | There's no live sync; pause writes and move. |
| `Expiration must be specified when creating a branch` | A branch in the bundle has no expiry setting. | Add `no_expiry: true` or a `ttl`. `bundle validate` doesn't catch it. |
| `read_write endpoint already exists` or `branch already exists; branch_name:"production"` | Lakebase already created that branch or compute. | Add `replace_existing: true`. |
| `has lifecycle.prevent_destroy set, but the plan calls for this resource to be recreated or destroyed` | The guard blocked a destroy, or a change that recreates the project, like bumping `pg_version`. | Don't bump `pg_version`; upgrade with a move. To delete for real, remove the guard in a reviewed change first. |
| `No API found for 'GET /postgres/<id>'` when binding a project to a bundle | Bind needs the full resource name. | Use `projects/<id>`. |
| Flyway: `Found non-empty schema(s) "public" but no schema history table` | Lakebase's own functions live in `public`. | `-baselineOnMigrate=true -baselineVersion=0`. |
| Flyway: `relation "customers" does not exist` at V2 | It baselined at 1 and skipped V1. | Baseline at 0, never the default of 1. |
| `native postgres login is disabled for this endpoint` | Password logins are off for the project. | Turn on `enable_pg_native_login` with `databricks postgres update-project`. |
| `OAuth: User is not authorized` on a new connection | The token expired. Open sessions keep working; new connections don't. | Generate a fresh token, or use a password role for anything that reconnects later. |
| `permission denied for schema public` while handing ownership to an owner role | A table can only move to an owner that can create in its schema. | Grant `CREATE ON SCHEMA public` to the owner role for that transaction, then revoke it. |
| `permission denied for database` restoring with `pg_restore --role=<owner role>` | The whole restore runs as that role. | Restore as yourself, then hand ownership to the owner role. |
| `create-role` fails when the role ID is a client ID | `--role-id` must match `^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$`. | Use a role ID that starts with a lowercase letter, like `ci-deployer`, and pass the client ID as `postgres_role`. |
| `Source IP address ... is blocked by Databricks IP ACL` for CI | GitHub-hosted runners aren't on the workspace's IP access list. | Use a self-hosted runner inside the network, or allow the runners' addresses. |
| Child branches are empty after the restore | They were created before production was restored. | Delete them, youngest first, then redeploy the bundle and migrate them. |
| Child branches don't have the synced tables | They were created before the syncs. | Recreate them after the syncs are online. |
| Duplicate keys loading a child's data-only dump into the rebuilt child | The dump includes production's rows too. | Load only the branch's own tables, and script its edits to shared rows. |
| A data-only load doubled every row in a table without a primary key | The target table already had rows. | Data-only loads work only into empty tables; truncate them first, all in one `TRUNCATE`. |
| A project ID can't be reused after deleting the project | A soft-deleted project ID is held for 7 days (docs). | Delete with purge, or use `purge_on_delete: true` in the bundle. |

## Genie Code skills

| Symptom | Fix |
|---|---|
| The skills panel shows only "Create skills folder" | Click it first. Then **Add skill**, paste the path of a folder that contains skill folders (for example, the Git folder's `skills`), and click **Add folder**. |
| A skill doesn't show up, or acts like an old version | Start a new chat; edits don't apply to an open one. If it still looks stale, hard-refresh the browser tab. |
| Genie Code ran code without asking | Its approval mode is set to auto-approve: Genie Code's menu, then Genie Code Settings, then Actions. |

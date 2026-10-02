# The playbook: promoting and moving a Lakebase environment

What the lab teaches, as you'd do it for real between two workspaces. Sources: the lab, five end-to-end moves from an AWS workspace to an Azure workspace in September 2026 (two with a live app writing until the pause, with independent checks), and the Databricks docs where marked. It's synthetic data on Postgres 17: a tested pattern, not a sizing benchmark or a complete production runbook.

## The model: each layer has its own tool

| Layer | Rebuilt on the new side by | Carries |
|---|---|---|
| Project, branch tree, computes | A bundle (Declarative Automation Bundle, formerly Databricks Asset Bundle), one target per workspace | Definitions only. A deploy created a four-branch tree in 24 seconds with zero tables (tested). |
| Schema | Your migration tool (Flyway, Liquibase, Alembic, and so on), run against each branch | Tables, columns, indexes, and data fixes written into migrations |
| Data, only when needed | `pg_dump` and `pg_restore` | A full logical copy of one database on one branch. Not its point-in-time history, snapshots, access, or synced tables. |

## The decision: does the data have to move?

Ask it per project, then per branch, then per database (a branch can hold more than one).

- **No: it's a promotion.** Dev, staging, and prod in their own workspaces. Bundle plus migrations; no data crosses workspaces. Production makes its own data, and dev's is test data you'd never ship.
- **Yes: it's a move.** The environment relocates (new workspace, cloud, or region), or it needs a newer Postgres major version, because Lakebase doesn't upgrade a project's major version in place (docs). Add `pg_dump` and `pg_restore`.
- **Want production data to test with?** Branch it. A child branch has production's data in seconds, and nothing done there touches production. Copying production into another workspace with a dump works too, but that's a real copy of production data, so treat it like one.
- Inside a project, usually only production's data moves, and the children get rebuilt from it.

## Promoting: three steps, every release

1. Put the bundle, the migrations, and the app code in Git.
2. `databricks bundle validate -t <target>`, then `databricks bundle deploy -t <target>`.
3. Run your migration tool against each target branch, lowest environment first, with tests and approvals in between. Use a tool that records applied versions in the database, so a replay applies exactly what's missing. Flyway on a brand-new Lakebase database needs `-baselineOnMigrate=true -baselineVersion=0`, because Lakebase's own functions live in `public`, so Flyway sees a non-empty schema with no history. The default baseline of 1 then skips V1 and breaks (tested).

Never merge child data upward. Refresh a child from its parent instead: reset it in the UI, or delete and recreate it.

## Moving: five steps, once, in order

**1. Put it all in Git.**

**2. Deploy the bundle, and leave the new production un-migrated.** `pg_restore` can't create a project, branches, or computes. Don't run migrations on the new production: the full dump brings the schema, the data, and the migration history together, and a restore into existing tables fails. For a one-off nobody will manage with a bundle, skip it: create the project in the UI or CLI, restore, create the syncs, then create the branches, which inherit everything instantly.

Bundle details that aren't obvious (all tested):

- `replace_existing: true` on the production branch and on any compute you declare that already exists. Lakebase creates production and its compute with the project, and a compute with every branch created through the API. Without it: `read_write endpoint already exists`, `branch already exists`, or `Expiration must be specified`.
- `no_expiry: true` or a `ttl` on every branch you add. `bundle validate` passes without it; `bundle deploy` fails with `Expiration must be specified when creating a branch`.
- For production, `lifecycle: { prevent_destroy: true }` on the project and the production branch. Then `bundle destroy`, or a deploy that would recreate them (like bumping `pg_version`), fails instead of deleting them. It doesn't protect a resource someone deletes from the file.
- `databricks bundle generate` has no Lakebase option; write the YAML. To adopt an existing project, `bundle deployment bind` needs the full name, `projects/<id>`.
- `purge_on_delete: true` makes `bundle destroy` a hard delete. Fine for labs; leave it off production.
- Bundle support for Lakebase is labeled Beta.

**3. Restore production from a full dump, one database at a time.** Pause writes first (see the cutover). For each database on the source branch (list them with `SELECT datname FROM pg_database WHERE NOT datistemplate`, skipping the empty built-in `postgres`):

```bash
pg_dump -Fc --exclude-table=<each synced table> -f prod.dump          # against the old production
pg_restore -l prod.dump | sed -E '/ (cloud_admin|databricks_control_plane)$|__db_system/ s/^/;/' > prod.toc
pg_restore --no-owner --no-acl --single-transaction --exit-on-error -L prod.toc -d <database> prod.dump   # against the new production
```

- Create every database besides `databricks_postgres` on the new production first, for example `CREATE DATABASE reporting;`. The live-app runs moved a second database this way.
- `--no-owner --no-acl` and the filtered list are both required for exit code 0. `--single-transaction --exit-on-error` is the safety net: a failure rolls back instead of leaving a half-restored database. See `troubleshooting.md` for why the documented restore exits 1.
- Check `pg_restore -l` on your own dump before trusting the filter.
- Variant: if the new side's schema already came from migrations and its tables are empty, dump data only and exclude the migration history's rows: `pg_dump -Fc --data-only --exclude-table-data=public.schema_migrations` (Flyway: `public.flyway_schema_history`). It only works into empty tables, and it was slower every time than a full restore into an empty database.

**4. Recreate the synced tables on the new production, and let them fill,** before the child branches.

- Synced tables can't travel through `pg_dump` (tested). Exclude each with `--exclude-table` (once per table), or `--exclude-schema` if they have a schema to themselves. A typo matches nothing and isn't an error, so confirm with `pg_restore -l` that none is left. Exclude any view that reads a synced table too (`-T` matches views), and recreate it once the sync is online. (The typo and view behaviors were checked on a local PostgreSQL 17, not in the moves.)
- Create the sync in the UI, the API, or `databricks postgres create-synced-table <catalog.schema.table> --json @sync.json`, where `sync.json` is `{"spec": {"source_table_full_name": ..., "branch": "projects/<id>/branches/production", "primary_key_columns": [...], "scheduling_policy": "SNAPSHOT", "postgres_database": "databricks_postgres", "create_database_objects_if_missing": true}}`.
- The create call returns before the rows land. Ours filled about 33 seconds after it reported done. Wait for the state to be online and count the rows.
- Prove it's current: `status.last_sync.delta_table_sync_info.delta_commit_version` from `get-synced-table` should equal the newest version in `DESCRIBE HISTORY` on the source.
- Keep each sync's spec in Git: `get-synced-table` doesn't return the spec, so you can't read the scheduling policy back later. Snapshot and Triggered syncs only refresh when triggered; Continuous keeps itself current (docs).
- The source Delta table has to exist on the new side too, and getting it there is a separate job. One run exported Parquet to a volume and loaded it with `COPY INTO`; that worked but wasn't measured at scale.
- Two workspaces in the same region usually share a metastore, so a synced table's name can point at only one project (tested only in the lab, which uses one workspace; the runs crossed clouds, so their metastores were separate and the name never collided): delete the old sync first, during the pause, and create the new one with the same name. It waits for the pause because the app runs on the old side until the switch, and deleting its sync is the one step that changes the old side. The same name keeps the Postgres table name the same for the app. With separate metastores (across regions or clouds), you can create the new sync before the pause (not tested; the two live-app runs created theirs during the pause).
- A Unity Catalog registration of a Lakebase database points at one branch's database, so register it again on the new side.

**5. Rebuild the child branches from the restored production.** A child starts from its parent at the moment it's created and never sees the parent's later writes (tested both ways). The bundle created the children while production was empty, so delete them, youngest first, then redeploy, then migrate them:

```bash
databricks postgres delete-branch projects/<new-project>/branches/<child> --purge -p <new-side profile>
databricks bundle deploy -t <target>      # recreates the children from the restored production
```

- "Reset from parent" does the same, but only in the UI (no API or CLI), and it's blocked while the branch has children of its own.
- Only delete brand-new branches on the new side like this. Check the profile and the project ID first: deleting a branch deletes whatever is on it.
- Migrating the rebuilt children puts back schema changes production didn't have yet.
- A child's own data: only production's data moves. Load branch-only tables with a data-only dump of just those tables, after the child's migrations. Script any edits the child made to rows production also has; one live-app run carried 515 `orders.coupon_code` values per child that way. A data-only dump of the whole child includes production's rows too, so loading it into the rebuilt child fails on duplicate keys.
- `pg_restore` fills only the branch you point it at. `pg_dump` can read any branch: a grandchild's dump had everything it sees, what it inherited plus its own changes (tested). If a branch several levels down is the one the app depends on, restore its dump as the new production and rebuild the branches you still need under it.
- To keep every branch exactly as it was, build the whole tree on the new side while production is still empty, then dump each old branch and restore it into its match. Tested 20 levels deep: all 21 branches matched exactly. The costs: each branch becomes a full copy instead of sharing storage with its parent, access has to be set up on every branch, and a project runs at most 20 computes at once besides the default branch (docs).

## The cutover

- There's no live replication: `CREATE PUBLICATION` and `CREATE SUBSCRIPTION` are disabled (tested). Writes pause before the final dump, and anything written to the source after the dump doesn't make it across.
- Stop every writer, not just the app: jobs, scripts, and apps on child branches. Check `pg_stat_activity` for open write transactions, and record a watermark, such as the newest ID in your busiest tables.
- While writes are paused, do only what production needs: the dump and restore, the syncs, and access. Then switch the app and resume writes. Rebuild the children afterward; the app only talks to production. With one shared metastore, the old sync has to go first, during the pause; with separate metastores, you can create the new syncs before it (step 4).
- Get sign-offs before you pause. In the two live-app runs, the first paused writes for 25 min 49 s: 7 min 50 s of work, including rebuilding the children, then 17 min 59 s waiting on a sign-off with the app ready on the new side. The second did only production's steps and resumed at 5 min 48 s. Both were small databases, so time your own dump and restore before promising a number. In the lab, the pause is about a minute, mostly the synced-table swap.
- Don't switch until the new side passes a gate: every database restored with exit 0; row counts and the watermark match; sequences are at or past the source's; synced tables are current; roles, grants, and default privileges match; and an app smoke test reads and writes.
- Switching changes the host. For an app that signs in with OAuth, its workspace URL and endpoint name change too.
- Backing out: nothing in the playbook changes the source, except deleting the old sync when both sides share a metastore, so before the switch, backing out is just resuming writes on the old side. If you deleted a sync, recreate it there first, from the spec in Git (not tested). After the first write on the new side, the old side is stale, and going back means a reverse move or reconciling those writes by hand. Decide abort criteria before you pause.
- The two live-app runs lost zero orders and passed all 27 independent checks.

## Access and identities

None of this comes with the dump. Set it up on the new production after the restore and before rebuilding the children, so they inherit it.

- After `--no-owner --no-acl`, every restored object belongs to whoever ran `pg_restore`. Restore as yourself; `pg_restore --role=<owner role>` failed on the first `CREATE SCHEMA` with `permission denied for database` (tested).
- Recreate the old side's Postgres roles, memberships, grants, and default privileges, read from the source (`pg_roles`, `pg_auth_members`, `information_schema.role_table_grants`, schema and sequence privileges, `pg_default_acl`, and the grants inside every database). Roles belong to the branch; ownership and grants belong to each database.
- Don't recreate the old side's Databricks identities or Lakebase's system roles. Workspaces in one account can share users, groups, and service principals; another account always means different ones. Either way, create their Postgres roles in the new project, because even the same identity needs a new role there. Granting to group roles keeps the mapping short: a Databricks group's Postgres role is named after the group.
- Passwords don't come across. Password logins need native login turned on first: `databricks postgres update-project projects/<id> spec.enable_pg_native_login --json '{"spec": {"enable_pg_native_login": true}}'`. Reuse passwords you have (like the app's), set new ones for the rest.
- Hand the app's objects to an owner role that you and CI both belong to. A table can only move to an owner that can create in its schema, so grant `CREATE ON SCHEMA public` to that role for the transaction, then revoke it. Put the default privileges on the owner role.
- In our runs, every Databricks identity role, CI's included, had the `REPLICATION` attribute, and password roles didn't. It isn't documented that we found, and only a superuser can remove it. Flag it for security review.

**Apps that sign in with OAuth** (from the docs; the live-app runs used a password role for the app): give the service principal the app will use on the new side a Postgres role in the new project, add it to the app's group role, and make sure it has the Workspace access entitlement, which credential generation requires. Then the app's workspace URL, endpoint name (`projects/<id>/branches/<branch>/endpoints/<endpoint>`), and host change. Across accounts it's a different service principal, so its client ID, secret, and Postgres user name change too, and its tokens have to come from the new workspace.

**CI** (tested): `CAN_MANAGE` on the project (it runs `bundle deploy`); a Postgres role created with `databricks postgres create-role`, whose `--role-id` must start with a lowercase letter, so a client ID that starts with a digit can't be used as the ID; and bundle state where only CI and admins can write, like CI's own home folder (`workspace.root_path`), not `/Workspace/Shared`, which gives all users Can Manage. Make CI migrate as the owner role, for example `flyway -initSql="SET ROLE app_owner" migrate` (Flyway 13.4 warns `initSql` is deprecated but runs it). Secretless GitHub sign-in needs an account admin for the federation policy, and a workspace IP access list blocked GitHub-hosted runners, so the runs used a self-hosted runner.

## Tokens and long dumps

- A Lakebase OAuth token is good for an hour, and it's checked only when a connection opens. An open session kept working after its token expired; a new connection with the expired token was refused (tested). The minimum credential lifetime is 300 seconds.
- So a single-connection `pg_dump` or `pg_restore` that starts with a fresh token finishes even if it runs longer. Anything that reconnects after expiry, like a retry or a later step, needs a fresh token or a native Postgres password role.
- Parallel `-j` workers connect when the parallel phase starts. A four-way `pg_dump -Fd -j 4` on a fresh OAuth token ran clean (tested). Parallel jobs can't combine with `--single-transaction`.
- Large databases: prefer the full-restore variant, run the tools from a VM or cluster near the databases, and use directory format with `-j`. Not tested at scale.

## Major versions

There's no in-place major version upgrade (docs). Bumping `pg_version` on a deployed bundle plans a delete and recreate of the whole project, data included, and `prevent_destroy` blocks it (tested). Upgrade with a move: create a new project on the newer version and dump and restore into it. The `pg_dump` client must be the same as or newer than the source's Postgres version.

## After the move

- Keep the old project for at least one restore window. Point-in-time history and snapshots belong to a project: the new project's history starts at the move, and a snapshot can't be restored into another project (tested). The window is 2 to 30 days, 7 by default (docs).
- Set the restore window and the snapshot schedule again on the new project; they're settings. A bundle can set the window with `history_retention_duration` (tested) and a snapshot schedule with `postgres_snapshot_schedules` (not tested).
- For a pre-move restore point that outlasts the window, take a manual snapshot of the old production while writes are paused, with `no_expiry` or a TTL, and keep that project (docs; manual snapshots are billed as full snapshots).
- From then on, promotions go to the new side only.
- Check extension parity across clouds with `pg_available_extensions` on both sides.

## What this isn't

- **Disaster recovery** keeps a standby of a whole project in a workspace in another region for manual failover. It's a different job, it's Private Preview and not for production, and it wasn't tested or covered here (docs). A one-time move dump isn't a standby; scheduled dumps are a documented backup method but don't give regional failover.
- **Lakebase Change Data Feed** (Public Preview) streams row changes into Delta tables in Unity Catalog. It's a change history for the lakehouse, not a way to move or sync a branch (docs).

## Connecting from a shell (tested)

```bash
lb_env() {  # usage: lb_env <cli-profile> <project-id> <branch-id>
  local ep="projects/$2/branches/$3/endpoints/primary"
  export PGHOST=$(databricks postgres get-endpoint "$ep" -p "$1" -o json | jq -r .status.hosts.host)
  export PGUSER=$(databricks current-user me -p "$1" -o json | jq -r .userName)
  export PGPASSWORD=$(databricks postgres generate-database-credential "$ep" -p "$1" -o json | jq -r .token)
  export PGDATABASE=databricks_postgres PGSSLMODE=require
}
```

`databricks auth login` sets up one CLI profile per workspace. Flyway doesn't read the `PG*` variables: use `FLYWAY_URL=jdbc:postgresql://$PGHOST:5432/$PGDATABASE?sslmode=require` with the same user and token.

# Release or move a Lakebase environment

If production only needs a feature or schema change, deploy the bundle and run the tested migrations. If its existing data has to move, use the cutover procedure below.

This is the real-app reference for [the lab](../../lakebase_move_lab.py), not a complete production runbook. The tests used small synthetic databases. [Facts](facts.md) defines the source labels below; [TESTING.md](../../TESTING.md) records the current notebook runs and their limits.

| Tool | What it does |
|---|---|
| Bundle | Creates projects, branches, and computes, not app tables or rows |
| Migration tool | Applies versioned SQL changes for a release, or unreleased changes on rebuilt child branches |
| `pg_dump` / `pg_restore` | Copies one database's schema, rows, and migration history for a move |

## Release a change

1. Keep the bundle, migrations, and app settings in Git.
2. Run `databricks bundle validate -t <target>`, then `databricks bundle deploy -t <target>`.
3. Run your migration tool against each target branch, lowest environment first, with tests and approvals between environments.

Use a migration tool that records applied versions. On a new Lakebase database, Flyway needs `-baselineOnMigrate=true -baselineVersion=0`: Lakebase's functions in `public` make the database look non-empty. The default baseline of 1 skips V1. [runs]

Don't merge dev's rows into production. To refresh dev, reset it from its parent or recreate it.

## Before the pause

- Decide which branches' data must survive. Usually production moves and children are rebuilt. If you need a different result, see [child branches](#rebuild-child-branches).
- List every database with `SELECT datname FROM pg_database WHERE NOT datistemplate`. Skip the empty built-in `postgres`. Create extra databases on new production first, for example `CREATE DATABASE reporting;`.
- Save access rules and synced-table specs. Check that each source Delta table exists in the destination metastore; copying it there is a separate job.
- Check Postgres versions and `pg_available_extensions` on both sides. The `pg_dump` client must be the same major version as the source or newer. A major-version upgrade requires a new project, not a version change on the existing bundle. [docs] [runs]
- Agree on sign-off and abort criteria before stopping writes. Time a practice dump and restore of your own data.

Deploy the new home, but **don't migrate new production**. The full restore brings its schema and migration history with the rows; pre-creating those tables makes it fail. For a one-off you won't manage with a bundle, creating the project in the UI or CLI also works.

### Bundle settings

These were tested with the CLI version recorded in [facts](facts.md#bundles). Lakebase bundle support is labeled Beta. [docs]

- Use `replace_existing: true` for production and any already-created compute you declare. Lakebase creates them automatically; the bundle must adopt them.
- Give each added branch `no_expiry: true` or a `ttl`. Validation can pass without it, but deployment fails.
- Put `lifecycle: { prevent_destroy: true }` on the project and production. It blocks destroy and changes that would recreate them. It doesn't protect a resource removed from the file.
- Leave `purge_on_delete` off production. It's a hard delete, used in the lab so names are immediately reusable.

Write the YAML yourself: `bundle generate` has no Lakebase option. To bind an existing project, give `bundle deployment bind` its full name, `projects/<id>`. [runs]

## Cutover

### Stop and keep every writer stopped

Stop the app, schedules, scripts, and writers on child branches. The tested move has no live replication; an order written on the old side after the dump won't arrive on the new one. [runs]

Enforce the pause so clients can't resume or reconnect and write. Removing write grants from the actual writer roles is one option; ending sessions with `pg_terminate_backend` alone doesn't prevent reconnects. Account for ownership and inherited grants too. These enforcement methods weren't tested in the lab.

Check `pg_stat_activity` for other client sessions that are `active` or `idle in transaction` in the app databases. Then record a watermark, such as the newest order ID and total count, and verify it stays put. The lab tested the session check, not enforcement of a real app's pause. [lab]

### Dump and restore each database

Use the [shell credential helper](#shell-credentials) below, or equivalent connection settings. Substitute your CLI profiles and project IDs in this `reporting` example:

```bash
lb_env old-profile old-project production
export PGDATABASE=reporting
pg_dump -Fc -f reporting.dump
pg_restore -l reporting.dump | sed -E '/ (cloud_admin|databricks_control_plane)$|__db_system/ s/^/;/' > reporting.toc

lb_env new-profile new-project production
export PGDATABASE=reporting
pg_restore --no-owner --no-acl --single-transaction --exit-on-error -L reporting.toc -d "$PGDATABASE" reporting.dump
```

Inspect your dump's list before using that filter. It skips Lakebase's platform objects, which the destination already has. `--no-owner --no-acl` skips old ownership and grants. Both are needed for exit code 0 in the tested restores. `--single-transaction --exit-on-error` rolls back a failed restore instead of leaving part of it behind. [runs]

If a database has synced tables, exclude each with `--exclude-table=<schema.table>`, or exclude their dedicated schema. Exclude views that read them too. Confirm with `pg_restore -l` that none remain: a misspelled exclusion isn't an error. The view and typo cases were checked on local PostgreSQL, not in the cloud moves. [runs]

If migrations already created the schema and **all target tables are empty**, a data-only dump is an alternative. Exclude migration-history rows with `--exclude-table-data=public.schema_migrations` (Flyway: `public.flyway_schema_history`). It was slower than a full restore in the measured runs. [runs]

### Recreate synced tables

Create each sync on new production and let it fill before rebuilding children. Use the UI, API, or `databricks postgres create-synced-table <catalog.schema.table> --json @sync.json`. The spec needs the source table, target branch and database, primary keys, scheduling policy, and `create_database_objects_if_missing`. Keep it in Git; `get-synced-table` didn't return it in testing. [runs]

Wait for ONLINE and the expected row count. Compare `status.last_sync.delta_table_sync_info.delta_commit_version` from `get-synced-table` with the newest version in `DESCRIBE HISTORY` on the source Delta table. A completed create call doesn't mean the rows have arrived. [runs] [lab]

If both workspaces share a metastore, the sync's name can point at only one project. Delete the old sync during the pause, then create the new one with the same name. This keeps the Postgres table name unchanged for the app. The name collision was tested in one workspace, not across workspaces. With separate metastores, preparing the new sync before the pause hasn't been tested here.

Snapshot and Triggered syncs need a trigger to refresh; Continuous refreshes itself. A Unity Catalog registration of a Lakebase database also needs to be recreated for the new branch's database. [docs]

### Rebuild access

Follow [access and identities](#access-and-identities) on new production now, before child branches are rebuilt. The dump didn't bring those rules.

### Check, switch, and resume

Don't switch until:

- Every database restored with exit code 0.
- App schema definitions, row counts, checksums, watermark, and migration history match. Sequences are at or past the source's values.
- Synced tables are current, or the app doesn't use them.
- Roles, ownership, grants, and default privileges are correct in each database.
- An app smoke test can read and write. Roll test writes back while the old side is still authoritative.

Change the app's host, then resume writes on the new side. OAuth apps also need the [workspace and credential changes](#access-and-identities) below. Rebuild children afterward if the app only uses production.

**If you abort before the first new write,** resume on the old side. If you removed its sync, recreate it from the saved spec first; that rollback wasn't tested. **After the first new write,** the old side is stale. Returning means a reverse move or reconciling those writes, not just pointing the app back.

## Rebuild child branches

Children created before the restore are still empty. Once production's sync and access are ready, delete those brand-new children, youngest first, then redeploy. Check the destination profile and project ID first: deletion removes everything on that branch.

```bash
databricks postgres delete-branch projects/<new-project>/branches/<child> --purge -p <new-side-profile>
databricks bundle deploy -t <target>
```

The replacement starts from production as it is now. Run its unreleased migrations, then load only branch-only tables with a data-only dump of those tables. Script the child's edits to shared rows separately. Dumping all of dev's data collides with production's rows already in the rebuilt branch. [runs] [lab]

UI **Reset from parent** is another option, but has no API or CLI command and is blocked while the branch has children. [runs]

If the app depends on a branch farther down the tree, you can restore that branch's full dump as the new production. If every branch must keep its exact state, instead build an empty destination tree and restore one full dump per branch into its match. That pattern was tested; it makes each branch a full copy, and you must rebuild access on each. Check the [compute limits](facts.md#branches-projects-and-limits) before choosing it.

## Access and identities

Restore as yourself, then assign ownership. `pg_restore --role=<owner role>` failed on `CREATE SCHEMA` in testing. Roles belong to a branch; ownership and grants must be set in every database. [runs]

- Read source roles and memberships from `pg_roles` and `pg_auth_members`, and grants from `information_schema.role_table_grants`, schema and sequence privileges, and `pg_default_acl`.
- Recreate app roles, not Lakebase system roles. Databricks identities can be shared within an account; another account uses different identities. Even a shared identity needs its Postgres role in the new project. Group roles can simplify the mapping.
- Passwords aren't exported. Supply them securely or issue new ones. Password roles require native login: `databricks postgres update-project projects/<id> spec.enable_pg_native_login --json '{"spec": {"enable_pg_native_login": true}}'`. [runs]
- Use an owner role shared by you and CI. When transferring a table, that role needs CREATE in its schema. Grant it for the transaction, then revoke it, and put default privileges on the owner role. [runs]

**OAuth apps:** give the app's service principal a Postgres role and group membership in the new project, plus the Workspace access entitlement needed to generate credentials. Change its workspace URL, endpoint name (`projects/<id>/branches/<branch>/endpoints/<endpoint>`), and host. Across accounts, client ID, secret, and Postgres user name change too. Tokens must come from the new workspace. This comes from docs; the live-app moves used password roles.

**CI:** it needs `CAN_MANAGE` on the project and a Postgres role. The `create-role` ID must start with a lowercase letter, so use an ID such as `ci-deployer`, not a client ID that starts with a digit. Keep bundle state writable only by CI and admins, for example in CI's home via `workspace.root_path`, not a broadly writable Shared folder. Migrate as the owner role, for example `flyway -initSql="SET ROLE app_owner" migrate`; the tested Flyway version warned that `initSql` was deprecated but ran it. [runs]

Secretless GitHub sign-in needs an account admin to configure federation and wasn't tested. The tested CI used a self-hosted runner because the workspace's IP access list blocked GitHub-hosted runners.

Databricks identity roles had `REPLICATION` in the measured runs, unlike password roles. We didn't find documentation for it; only a superuser could remove it. Include that in security review. [runs]

## Shell credentials

Run the tools where they can reach both computes and sign in to both workspaces. A laptop and CI runners were tested. For serverless routing problems, use [preflight](../../README.md#optional-check-a-workspace-before-a-workshop) and [troubleshooting](troubleshooting.md); other workspace pairs weren't tested.

Set up one CLI profile per workspace with `databricks auth login`. This wrapper uses full certificate verification, as tested in the notebooks. **The wrapper itself wasn't rerun with these certificate settings.**

```bash
lb_env() {  # usage: lb_env <cli-profile> <project-id> <branch-id>
  local ep="projects/$2/branches/$3/endpoints/primary"
  export PGHOST=$(databricks postgres get-endpoint "$ep" -p "$1" -o json | jq -r .status.hosts.host)
  export PGUSER=$(databricks current-user me -p "$1" -o json | jq -r .userName)
  export PGPASSWORD=$(databricks postgres generate-database-credential "$ep" -p "$1" -o json | jq -r .token)
  export PGDATABASE=databricks_postgres PGSSLMODE=verify-full PGSSLROOTCERT=system
}
```

Flyway doesn't read `PG*` variables. Set its user and token separately. For JDBC, use Java's truststore rather than libpq's `sslrootcert=system`:

```bash
export FLYWAY_USER="$PGUSER"
export FLYWAY_PASSWORD="$PGPASSWORD"
export FLYWAY_URL="jdbc:postgresql://$PGHOST:5432/$PGDATABASE?sslmode=verify-full&sslfactory=org.postgresql.ssl.DefaultJavaSSLFactory"
```

The Java truststore must trust the certificate's issuer. This configuration follows [pgJDBC's SSL documentation](https://jdbc.postgresql.org/documentation/ssl/) and wasn't tested in the lab.

### Tokens and larger databases

OAuth tokens are checked when a connection opens. An open session kept working past expiry; a new connection with an expired token failed. Generate a fresh token before each tool invocation, and again for any reconnect or retry after expiry. [runs]

Four-way `pg_dump -Fd -j 4` was tested. Large databases and parallel restore weren't. For those, practice near the databases and measure first. Parallel restore can't use `--single-transaction`; dropping that option also drops the all-or-nothing protection.

## Keep recovery available

Keep the old project for at least one restore window, or longer if your recovery plan requires it. Its history and snapshots don't transfer. The [retention limits](facts.md#branches-projects-and-limits) give the current default and range.

Set `history_retention_duration` and the snapshot schedule on the new project. The bundle's retention setting was tested; `postgres_snapshot_schedules` wasn't. For a pre-move restore point beyond the history window, take a manual snapshot while writes are paused, with `no_expiry` or an appropriate TTL, and retain the old project. Manual snapshots are billed as full snapshots. [docs]

After the move, release changes to the new side only.

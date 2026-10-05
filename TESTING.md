<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# First-run check

Reran the revised checkout on October 5, 2026, in Chicago and UTC.

Three fresh lab notebooks passed all 39 code cells and all 7 final checks: AWS with default answers, AWS with synced product data, then AWS-to-Azure. The revised two-workspace preflight passed 25 checks with one expected separate-metastore warning. Independent API checks confirmed cleanup after each run.

The hidden token input also worked with automated browser entry this time. That closes the earlier automation gap, not the need for a new learner to try it.

The earlier tests ran October 4 in Chicago, October 5 in UTC. The original install failed at its first connection. Those failures and fixes stay in this record.

## Where we ran it

| Role | Workspace |
|---|---|
| Run the notebook and keep the old home here, AWS us-west-2 | `https://dbc-7bae415f-6ff0.cloud.databricks.com/` |
| Put the new home here on the second run, Azure eastus2 | `https://adb-984752964297111.11.azuredatabricks.net/` |

The notebook ran on serverless, with environment version 5 requested. The rerun preflight reported environment 5 (`client.5.12`), Python 3.12.3, aarch64, and Ubuntu 24.04.4 LTS. It confirmed Databricks SDK 0.146.0, psycopg 3.3.6, protobuf 5.29.6, Databricks CLI 1.17.0, PostgreSQL client tools 17.9, libpq 18.3, and Lakebase Postgres 17.11.

For the default AWS run, Ryan couldn't create a schema in `main`. The product-data exercise skipped and the rest finished. For the full exercise and the Azure run, we used `cicaktest_catalog`, where Ryan can create a schema.

## Results

These are the October 5 reruns of the current source, not the earlier wording versions.

| Run | Result | Final Checks | Runtime | Simulated Write Pause |
|---|---|---|---|---|
| Fresh AWS, default answers | 39 of 39 code cells; both restores exited 0; optional sync skipped | 7 of 7 | 132.6 seconds | 20 seconds |
| Fresh AWS, with product data | 39 of 39; 50 rows synced in each project; synced and latest Delta versions matched at 1 | 7 of 7 | 217.5 seconds | 64 seconds, including a 39-second sync swap |
| Fresh AWS-to-Azure | 39 of 39; both databases restored into Azure; new-side sync skipped | 7 of 7 | 246.3 seconds | 59 seconds |
| Revised two-workspace preflight | 25 passes, 1 expected separate-metastore warning; no failures or skips | Ready with notes | 188.809 seconds | Not an app move |

These times are for tiny, made-up databases. They're not estimates for a real app.

Each lab started in a new notebook with no saved widgets, outputs, or execution timestamps. Databricks exports unused execution counts as `0`; we checked the other fields too. The source still matched this checkout after each completed run.

### Azure checks

The Azure rerun took about 4 minutes. `databricks_postgres` restored with exit code 0 in 5.0 seconds; `reporting` did the same in 2.7 seconds.

The copy check found matching app schemas and matching contents in every app table: 1,000 customers, 5,025 orders, one production coupon, three migration records, and 200 stock rows. The watermark was 5025 on both sides.

After rebuilding access, all 7 checks passed. The simulated app then placed orders 5026 through 5030 on Azure. The old home stayed at 5025.

We also checked that development was empty before rebuilding, then got migrations V1 through V4, two feature flags, both coupons, and the three dev-only order edits. The data-only shortcut failed on duplicate keys without changing the database. The point-in-time branch from before the restore was empty. Cross-project branching and snapshot restore were rejected as expected. The delete guard refused the first destroy; the last cell removed the guard and cleaned up.

**The Azure sync was deliberately skipped.** These workspaces have different metastores, so the source Delta table isn't in Azure. The 7-check table counts that sync as "not used"; a green result does not mean we moved it across clouds. The source sync stayed running until cleanup.

## What broke

### First connection, even in AWS

The Git-folder install at commit `751f0a4` stopped at its first Postgres connection. It asked for full certificate verification but had no default `~/.postgresql/root.crt`.

Both notebooks now use the system's trusted certificates: `sslrootcert="system"` for psycopg and `PGSSLROOTCERT=system` for the Postgres tools. Hostname and certificate verification stay on.

### First Azure connection

The next fresh Azure attempt stopped in **What the bundle built**. The AWS proxy presented a certificate for `*.database.cloud.databricks.com`, which didn't match the Azure compute's hostname. The old fallback only recognized `External authorization failed`, so it never got to the public route.

Both notebooks now recognize those two specific proxy errors and retry the Azure compute's public address. They keep the hostname and `verify-full` on that connection too. Same-workspace connections and generic certificate failures don't enable this fallback.

The failed run was cleaned up through Module 7 before the retry. Both later fresh Azure runs passed.

### Settings reset during an upload

Uploading revised source reset an earlier notebook's setup boxes. That attempt ran in AWS only. It passed and cleaned up, but **it is not counted as an Azure test**.

After that, we exported each fresh notebook before setup, then checked the three boxes and the Azure sign-in message before Run all. The untouched exports had no widgets, outputs, or executed cells.

### Two edges found in local tests

A route refusal on the last connection retry could return `None` without trying the public address. Changing routes now gets its own attempt; exhausted retries raise.

The preflight could also replace the lab's shared destination secret. Both setup cells now refuse a conflicting saved host, and later sign-in checks require it to match box 2 before using the credentials.

These edge cases were reproduced with mocks, not forced against live databases.

### Preflight cleanup after Python restart

The two-workspace preflight passed its connection and cross-cloud restore, then reported `NameError: name 'scope' is not defined` in cleanup. The deletes had completed, and separate API checks confirmed that both projects, their bundle folders, and the source schema and sync were gone.

The final message used a variable from before Python's restart. It now uses `NEW_SCOPE`, which is defined afterward. Two new tests run cleanup without the old setup variables. The Postgres-tool helper also keeps the source identity when its source client is passed explicitly.

That earlier cleanup-fix preflight rerun passed all 25 checks in 177.837 seconds. Its only warning was the expected separate-metastore note. The source matched before and after execution, and separate API checks confirmed cleanup in both workspaces. The test scope was deleted and the short-lived token revoked.

## Cleanup

After each fresh lab rerun, separate SDK checks found these exact resources absent:

- Both lab project names in both workspaces.
- The lab's bundle folder in both workspaces.
- The source schema, Delta table, and synced table.
- The source secret scope used for Azure sign-in.

The hidden-input test PAT was revoked after the Azure lab. Preflight used a separate one-hour PAT, which was revoked after its run. No unrelated projects were deleted. The notebooks and their output records remain.

The default `main.lb_move_ryan_cicak_8379170564079364` schema was also absent after each rerun. The revised preflight has its own independent cleanup record: projects and bundle folders in both workspaces, plus the source schema and sync. Its test secret scope was deleted.

## Ready-to-run copy

A separate, untouched copy is installed in AWS:

`/Users/ryan.cicak@databricks.com/lakebase-move-ready-20261005/lakebase_move_lab`

Notebook ID: `465045170785742`. Its exported source matches the local lab after normalizing the exporter's final newline. It has no saved widgets, outputs, or execution timestamps, and none of its 39 code cells has run. This is the starting copy, not one of the completed tests. Its preflight is unused too.

The folder also includes the README, preflight, and skills. Local scratch files, sync state, and credentials were excluded from the upload.

## Limits

- **Fresh notebooks, existing accounts.** We used Ryan's authenticated workspace accounts, not newly provisioned users. Both accounts had admin membership. This does not prove an ordinary new account's permissions are sufficient.
- **The hidden token input passed automated browser entry.** The helper checked that the field was an `input` of type `password`, submitted a one-hour PAT, and verified that the secret scope held that exact value. The setup cell then confirmed Azure sign-in. The helper didn't put the token value in code, output, or local test files. This was automation, not a human learner manually pasting.
- **No separate live app or release pipeline.** SQL simulates orders and the write pause. Real projects, bundle commands, dump/restore, roles, and cleanup were exercised.
- **Small data and one workspace pair.** We did not test large databases, other network policies, other cloud pairs, classic clusters, or a cross-workspace synced-table move.
- **Mocks have limits.** The helper tests check options, guards, and retries; they don't prove certificate enforcement on a hostile endpoint. The live runs used full TLS verification without disabling it.

Before a workshop, have someone with ordinary, non-admin permissions try the setup and token entry.

## Evidence

The raw exports and API reports are retained locally under `.tmp/`, which is ignored by Git:

| Evidence | File Or Notebook ID |
|---|---|
| Original first-connection failure | `.tmp/aws-baseline.ipynb` |
| AWS default run | `.tmp/aws-default-final.ipynb`, notebook `465045170784467` |
| AWS with synced product data | `.tmp/aws-sync-final.ipynb`, notebook `465045170784519` |
| Fresh AWS after runtime fixes, untouched before setup and completed after | `.tmp/aws-verified-before.ipynb`, `.tmp/aws-verified-final.ipynb`, notebook `465045170785692` |
| First Azure connection failure and its cleanup | `.tmp/aws-azure-first-connection-failed.ipynb`, `.tmp/aws-azure-abort-cleaned.ipynb` |
| Successful fresh Azure retry | `.tmp/aws-azure-final.ipynb`, notebook `465045170785638` |
| Final fresh Azure, untouched before setup and completed after | `.tmp/aws-azure-verified-before.ipynb`, `.tmp/aws-azure-verified-final.ipynb`, notebook `465045170785655` |
| Independent final Azure cleanup | `.tmp/aws-azure-verified-cleanup.json` |
| Independent cleanup after the last AWS rerun | `.tmp/aws-azure-cleanup.json` |
| AWS preflight, 20 of 20 | `.tmp/aws_preflight_patched_465045170784471/summary.json`, run `556770938732573` |
| Two-workspace preflight cleanup-message failure, with independent cleanup | `.tmp/preflight-aws-azure-cleanup-failed/`, run `1052727523054822` |
| Final two-workspace preflight, 25 passes and 1 expected warning | `.tmp/preflight-aws-azure-verified/`, run `602297631072876` |
| Current AWS default, untouched before setup and completed after | `.tmp/rerun-aws-default-before.ipynb`, `.tmp/rerun-aws-default-final.ipynb`, notebook `1949836290777222` |
| Current AWS product-data run, untouched before setup and completed after | `.tmp/rerun-aws-sync-before.ipynb`, `.tmp/rerun-aws-sync-final.ipynb`, notebook `1949836290777231` |
| Current AWS-to-Azure, untouched before setup and completed after | `.tmp/rerun-aws-azure-before.ipynb`, `.tmp/rerun-aws-azure-final.ipynb`, notebook `1949836290777257` |
| Hidden input and verified Azure setup before Run all | `.tmp/rerun-aws-azure-token-ui.txt`, `.tmp/rerun-aws-azure-signed-in-ui.txt`, `.tmp/rerun-aws-azure-configured.ipynb`; local driver `.tmp/browser_bridge.py` |
| Independent cleanup after each current lab run | `.tmp/rerun-aws-default-cleanup.json`, `.tmp/rerun-aws-sync-cleanup.json`, `.tmp/rerun-aws-azure-cleanup.json` |
| Revised preflight, untouched source and completed job | `.tmp/rerun-preflight-aws-azure-before.ipynb`, `.tmp/preflight-rerun-aws-azure-20261005/`, run `762433169041907`, task run `703176829605757` |
| Current unused AWS starting copy | `.tmp/rerun-ready-main-unused.ipynb`, `.tmp/rerun-ready-main-source.py`, notebook `465045170785742` |
| Current unused AWS preflight | `.tmp/rerun-ready-preflight-unused.ipynb`, `.tmp/rerun-ready-preflight-source.py` |

The earlier cloud runs used main source SHA-256 `2d7a166bd0b4fe3761465ce42deb952d8ade464a05780b36c497a9865cb14777`. Their source exports matched it, apart from the CLI omitting the final newline.

The earlier cleanup-fix preflight used source SHA-256 `65ec16d1a900c0c4477da88e06835d5045fb3d250878bc0e832abf7911e11160`.

### Current checkout

All three fresh lab reruns used the current main source. The revised preflight also matched its local source before and after execution. The source-only exports are retained beside the completed notebook exports.

**Both current notebook sources have now run end-to-end in the cloud.** The shell wrapper and JDBC example in the playbook remain untested.

Current local SHA-256:

- Main: `c3b8ea4612591038fa02005a490ce829a7b653bf97886e1f43885194db9b63b1`.
- Preflight: `52d91620e0484e4980aa2f5a8078bab3331dbaaf01f4a02b71c460ef24827a6b`.

Local verification:

```sh
uv run --no-env-file --no-project python -B -m unittest discover -s tests -v
git diff --check
```

All 31 helper tests passed; both notebooks' Python cells parsed with Python 3.10 syntax rules. All 44 local file and section links resolved. The notebook's playbook link opened the correct workspace file in Databricks. The cloud-run checks included Jupyter errors and Databricks' `baseError` metadata.

---
name: lakebase-move-lab-expert
description: Tested answers on moving or promoting a Lakebase environment to another project or workspace, and on the Lakebase Move Lab that teaches it. Covers restoring pg_dump into Lakebase, root and child branches after a move, synced tables, multiple databases, roles, grants, and OAuth apps on the new side, point-in-time restore and snapshots across projects, major version upgrades (pg_version), and the cutover and write pause. Use when a question is about moving, promoting, restoring into, or upgrading a Lakebase project or branch, or about the lab, even if it doesn't name the lab. Load it alongside general Lakebase guidance for those questions. Do not use for general Lakebase setup, connections, sizing, or features unrelated to a move, or to check whether a workspace is ready for the lab (use lakebase-move-lab-preflight).
---

<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Move Lab expert

You're the expert on the Lakebase Move Lab and the playbook behind it. The lab is one notebook, `lakebase_move_lab`, that builds an "old home" Lakebase project, promotes a change with a migration, builds a "new home" with a bundle, moves production's data with one `pg_dump` and filtered `pg_restore` per database, rebuilds a child branch, shows what doesn't come along, and cleans up. By default, two projects in one workspace teach the same core rebuild pattern as a move between workspaces; advanced users can pick **Another workspace** in its first code cell, **Choose your setup (defaults are fine)**, to put the new home in a real second workspace. Its companion, `lakebase_move_lab_preflight`, optionally checks a workshop or restricted workspace before the lab.

Sources: the lab; the runs behind it (five moves from an AWS workspace to an Azure workspace, two with a live app); and the Databricks docs. **`facts.md` is the canonical list:** it tags every fact with its source, and when another file disagrees with it on a fact or a number, `facts.md` wins. `lab-walkthrough.md` is the lab, and `playbook.md` and `troubleshooting.md` mark what comes from the docs or wasn't tested. Don't add the runs to a fact from the lab, or the lab to a fact from the runs.

## How to answer

1. Read the reference file for the topic before you answer. Don't answer lab-specific questions from memory, don't stretch a tip beyond the case the file gives it for, and don't fill in details the files don't give.
2. If the user is in the lab notebook, look at the cell and the output they mean, and answer from what it actually shows. When they say "this notebook" or "this run", read its outputs and quote its numbers, not the typical ones in the reference files. Refer to cells by their titles and modules (for example, "Module 4, Step 3, the pg_restore cell").
3. Lead with the direct answer in a sentence or two. Then the why, then what to do about it. Include the practical next step from the reference file even if the user didn't ask, like keeping the old project for a restore window after a move.
4. Put the source in parentheses right after each point: (tested in the lab), (tested in our runs), (docs), or (not tested). Don't sum up the sources in one line for the whole answer, because most answers mix them; OAuth apps, for example, come from the docs. If the reference files don't cover something, say so plainly and point to the Databricks docs instead of guessing.
5. Times and counts from the lab and the runs come from small synthetic databases in a few specific setups. Never present them as an estimate for someone's move; tell them to time a practice dump and restore of their own data.
6. For "why did this fail?", match the error text to `troubleshooting.md` and give its fix. You may offer read-only checks, like listing projects or a catalog's grants. Don't create, change, or delete anything without asking, and never print a token or a password.
7. If the user wants to know whether their workspace is ready for the lab, use the `lakebase-move-lab-preflight` skill instead.

A calibrated answer looks like this:

> **Q:** Do our snapshots come along when we move to a new project?
>
> **A:** No. A snapshot can only be restored inside its own project (tested in the lab: the cross-project restore was rejected), and the new project's point-in-time history starts at the move (tested in the lab). So keep the old project for at least one restore window, 2 to 30 days and 7 by default (docs), and set the snapshot schedule again on the new project (docs).

## Reference files

| Read | When the question is about |
|---|---|
| [lab-walkthrough.md](lab-walkthrough.md) | What a module, step, or cell of the lab or the preflight does, what its output should look like, its settings, re-running cells, and why it's built that way |
| [playbook.md](playbook.md) | Promoting versus moving, the five steps, the cutover and write pause, child branches and their own data, multiple databases, synced tables, access, identities, OAuth apps, major versions, after the move (the restore window, snapshots, keeping the old project), rollback, and doing it for real across workspaces |
| [troubleshooting.md](troubleshooting.md) | An error message, a warning, or a step that failed, in the lab, the preflight, a bundle, or a real move |
| [facts.md](facts.md) | The canonical list: limits (branches, root branches, computes, the restore window), numbers, and the test results behind them, each with its source |

## Always true

- A branch can't leave its project. Creating a branch whose parent is in another project fails with `source_branch field must point to the branch from the same Project`, even in the same workspace. Nothing in the API exports, copies, or moves a branch.
- So promoting to another workspace means rebuilding there: a bundle for the project, branches, and computes; migrations for the schema; and `pg_dump` and `pg_restore` only when the data itself has to move.
- Most releases are promotions: deploy the bundle, run the migrations, and no data crosses workspaces. A move happens when the environment relocates (a new workspace, cloud, or region) or needs a newer Postgres major version.
- A move is five steps, in order: put it all in Git; deploy the bundle and leave the new production un-migrated; restore production from a full dump, one database at a time; recreate the synced tables; then rebuild the child branches and migrate them (tested). Don't run migrations on the new production before the restore: the full dump brings the schema, the data, and the migration history together, and a restore into tables that already exist fails.
- While writes are paused, do only production's steps: the dump and restore, the syncs, and access, whose grants need the restored tables. Deploy the bundle and get sign-offs before the pause; rebuild the children after it. Pausing writes means stopping every writer and keeping it stopped; nothing in Lakebase does it for you.
- A move copies just the data, one database at a time. Point-in-time history, snapshots, access, and synced tables don't come along (tested). Keep the old project for at least one restore window (2 to 30 days, 7 by default, per the docs), and set the window and the snapshot schedule again on the new project.
- Children only see what their parent had when they were created, so rebuild the child branches after production is restored: delete them, youngest first, redeploy, and migrate them (tested). For a child's own data, load its branch-only tables with a data-only dump of just those tables, and script its edits to rows production also has; a data-only dump of the whole child fails on duplicate keys.
- Restore with `--no-owner --no-acl` and a filtered list that drops Lakebase's own platform entries; both are needed for a clean exit (tested).
- A project can have 3 root branches, but the ones beyond production come only from point-in-time or snapshot restores, so there's no empty second root to restore a dump into (docs). A dump goes into a new project's production.
- There's no in-place major version upgrade (docs). Bumping `pg_version` on a deployed bundle plans a delete and recreate of the whole project, data included, and `prevent_destroy` blocks it (tested). Upgrade with a move: the five steps above, with the new project on the newer version. The `pg_dump` client must be the same as or newer than the source's Postgres version.

## Seen in specific setups: say where, every time

- **The documented restore's errors.** It restored every row but exited 1: 18 errors into another workspace and 11 into a fresh project in the same workspace (our runs, Postgres 17.11, September 2026). Lakebase could change what goes into a dump, so the fix is to read your own dump's list.
- **Write pauses.** 25 min 49 s, then 5 min 48 s once only production's steps were in the pause, in the two live-app runs; about a minute in the lab. All small synthetic databases: not an estimate for anyone's move.
- **Serverless and another workspace's computes.** From serverless in an AWS workspace, Lakebase hostnames resolved to a Databricks proxy that refused an Azure workspace's computes with `External authorization failed`, and their public address worked (tested). Other pairs, like two workspaces in the same cloud, weren't tested. The lab tries the normal route first and falls back to the public address, and the preflight's "Second workspace: connect from here" check shows which route a given setup needs.

## What's outside this skill

- Disaster recovery: a standby in another region for failover. It's a different job, Private Preview, and not covered or tested here.
- Large databases, writes during the dump, classic clusters, and the bundle resources for databases, roles, catalogs, and synced tables weren't tested. Say so when they come up.

# Notebook settings and reruns

For a cell's explanation and expected output, read [the notebook](../../lakebase_move_lab.py). For an error, use [troubleshooting](troubleshooting.md). This file covers settings and what happens if you go back through a run.

## Settings

The three boxes are notebook widgets. They survive Python's restart, and a job can pass the same values as parameters.

| Parameter | Box | Default |
|---|---|---|
| `where` | 1. New home goes to | `This workspace`; the other choice is `Another workspace` |
| `other_url` | 2. Other workspace URL | Empty |
| `catalog` | 3. Catalog | `main`, for the optional synced-table exercise |

The helpers read these into `CATALOG` and `NEW_WORKSPACE_SECRETS`. `DO_SYNCED_TABLES` is a code setting in the helpers cell, not a widget. `CONFIRM_TEARDOWN` is in Module 7's last cell; its default, `True`, lets Run all delete the lab resources.

If a box changes while the notebook is idle, Databricks may rerun the cells that read it. During Run all, the changed value waits for the next run. Don't change a box to interrupt or redirect a running lab.

Once projects exist, setup refuses a different workspace choice or URL. Once the lab has created its schema, helpers refuse a different catalog. Change the box back, or finish cleanup with the original answers before starting over.

If the synced-table step skipped before creating a schema, you can put a usable catalog in box 3 and rerun **Module 1, Step 6**. If the notebook was uploaded or imported again, recheck all three boxes before creating resources: an upload reset them in testing.

## Jobs and service principals

For another workspace's interactive setup, follow the [README](../../README.md#optional-use-a-real-second-workspace).

A job can't answer the hidden token prompt. Store credentials first, or use the CLI command the setup cell prints. The scope belongs to the identity running the lab, so use the scope name from that identity's setup message.

Run the secret commands against the notebook's workspace. Set `SCOPE` to that scope name:

```bash
databricks secrets put-secret "$SCOPE" token
```

For a service principal, store `client-id` and `client-secret` instead of `token`:

```bash
databricks secrets put-secret "$SCOPE" client-id
databricks secrets put-secret "$SCOPE" client-secret
```

The saved host must match box 2 before either notebook uses its credentials. The lab and preflight share that scope; neither setup cell replaces it with a different destination.

## Starting over

If a run stops, follow **Module 7: Clean up** in the notebook. If Python restarted, that means running through Module 0 first, skipping Modules 1 through 6, then running Module 7. Don't click Run all while earlier projects remain.

After cleanup, start from Module 1 in the same session, or from the top in a new session. Cleanup is safe to repeat: with nothing left, it creates nothing and deletes nothing.

Most setup, migration, dump, filter, restore, access, and dev-work cells can be retried in the same session. Restore skips a database whose app tables already exist and keeps the original restore timestamp. These cells are different:

| If you repeat this cell | What changes |
|---|---|
| **Place a few orders, then pause writes** | Adds 25 orders and restarts the pause timer |
| **Point the app at the new home** | Adds five more orders on new production |
| **Move the synced table to the new home** | Recreates the sync |
| **Delete the dev branch, then redeploy** | Deletes development again, including work restored afterward |

After the switch, the copy checks no longer match: new production has orders the old home doesn't. If you want to repeat the whole move, clean up and start over.

Don't run two lab copies as the same identity. They share project and bundle names. The [resource names and tags](facts.md#the-lab-itself) explain how the lab identifies its own resources.

## Preflight results

Use **Summary** for the readiness verdict. A successful job status only means the checks finished; a failed check can still make the verdict `not ready`.

If leftovers fail, don't resubmit the same job. Open the preflight notebook, set `CLEAN_LEFTOVERS = True` in Settings, then rerun that cell and the leftovers check, or click Run all. Don't do this while your lab is active.

Each preflight gets its own timestamped names and removes preflight leftovers older than 30 minutes. Its Summary and result-return cells are separate because `dbutils.notebook.exit` replaces its cell's output in the notebook UI.

The [preflight skill](../lakebase-move-lab-preflight/SKILL.md) has the job-submit cell. The [test record](../../TESTING.md) has the measured runs and their limits.

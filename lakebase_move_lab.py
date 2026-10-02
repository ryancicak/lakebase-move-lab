# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0

# COMMAND ----------

# MAGIC %md
# MAGIC # Lakebase Move Lab
# MAGIC
# MAGIC This notebook walks you through moving a Lakebase environment, one cell at a time, on real Lakebase projects. It's the hands-on version of the *Promote Lakebase across workspaces* deck. Every cell actually runs, and every cell tells you what it's doing and why.
# MAGIC
# MAGIC **The whole lab in three lines:**
# MAGIC
# MAGIC 1. You can't move a Lakebase branch. It can't leave its project.
# MAGIC 2. So you rebuild in the new place: a **bundle** for the project and branches, **migrations** for the schema, and `pg_dump` and `pg_restore` for the data, only when the data has to come along.
# MAGIC 3. Some things never come along: access, synced tables, and point-in-time history. You set up access and synced tables again, and history starts over.
# MAGIC
# MAGIC Here's the plan:
# MAGIC
# MAGIC 0. See why a branch can't just move.
# MAGIC 1. **Build the old home:** production with two databases, access rules, a dev branch, and a synced table.
# MAGIC 2. **Promote** a change the everyday way: a migration, no data.
# MAGIC 3. **Build the new home** with a bundle, and watch the obvious shortcut fail.
# MAGIC 4. **Move the data,** check it, rebuild access, and switch the app. Then rebuild the dev branch.
# MAGIC 5. **See what stays behind.**
# MAGIC 6. **Get the checklist** for doing it for real.
# MAGIC 7. **Clean up.**
# MAGIC
# MAGIC > It runs on Databricks serverless (environment version 5) in about 5 minutes. It installs what it needs as it goes, creates two small Lakebase projects, and deletes them at the end.
# MAGIC
# MAGIC > **Two projects stand in for two workspaces.** A branch can't leave its project, even inside one workspace. So moving between two projects is the same job as moving between workspaces. Where a real move between workspaces is different, the lab says so. Have a second workspace? Pick it in **Choose your setup**, a few cells down.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Before you start
# MAGIC
# MAGIC * **Use serverless compute.** The notebook asks for environment version 5, and versions 1 through 4 passed too. A classic cluster with internet access should work, but we haven't tested one.
# MAGIC * **You need permission to create Lakebase projects.**
# MAGIC * **Run the cells in order.** Each one prints what it did, so you can stop and look anytime.
# MAGIC
# MAGIC ### Choose your setup
# MAGIC
# MAGIC Run the next cell. It puts three boxes at the top of the notebook:
# MAGIC
# MAGIC 1. **New home goes to**: where the new home gets built.
# MAGIC    * **This workspace**, the default: two projects in this workspace stand in for two workspaces. Nothing to set up.
# MAGIC    * **Another workspace**: a real second workspace. You'll need a personal access token from it. (In that workspace, it's under **Settings**, **Developer**, **Access tokens**.)
# MAGIC 2. **Other workspace URL**: only for another workspace, for example `https://adb-1234567890123456.7.azuredatabricks.net`.
# MAGIC 3. **Catalog**: for the synced-table steps, one where you can create a schema. The default is `main`. If you can't create a schema there, no problem: the lab skips those steps and tells you why.
# MAGIC
# MAGIC Change a box, then run the cell again. If you picked another workspace, it asks for the token in a hidden box the first time, keeps it in a secret scope of your own, and checks that it works. Then click **Run all**.
# MAGIC
# MAGIC > With another workspace, a few things work differently. Serverless sends Lakebase hostnames to a Databricks proxy, which refused the other workspace's computes in testing, so the lab connects to their public address instead (found in public DNS). If that workspace has its own metastore, the lab skips the synced table on the new side, because its Delta source would have to be copied over first. And Databricks hides anything that matches a secret, so that workspace's URL shows up as `[REDACTED]` in the output.

# COMMAND ----------

# DBTITLE 1,Choose your setup
"""Put the setup questions at the top of the notebook, and sign you in to the other workspace if you pick one.

For another workspace, its URL and your token go in a secret scope of your own, lb-move-lab-<you>.
The token is asked for in a hidden box. It's never shown, and it's never saved in the notebook.
"""
import getpass
import re

from databricks.sdk import WorkspaceClient

THIS, OTHER = "This workspace", "Another workspace"
dbutils.widgets.dropdown("where", THIS, [THIS, OTHER], "1. New home goes to")
dbutils.widgets.text("other_url", "", "2. Other workspace URL")
dbutils.widgets.text("catalog", "main", "3. Catalog")

w = WorkspaceClient()
user = w.current_user.me().user_name
scope = "lb-move-lab-" + (re.sub(r"[^a-z0-9]+", "-", user.split("@")[0].lower()).strip("-")[:16].rstrip("-") or "user")


def ask_for_token(prompt):
    """A hidden box for the token. A job can't answer it, so then it says how to store the token instead."""
    try:
        return getpass.getpass(prompt).strip()
    except Exception:
        raise RuntimeError("No working token for the other workspace yet. Run this cell yourself once, or store "
                           f"one with the Databricks CLI: databricks secrets put-secret {scope} token") from None


def signed_in_as():
    """Sign in to the other workspace with what's in your scope, and return your user name there."""
    keys = {s.key for s in w.secrets.list_secrets(scope=scope)}
    secret = lambda key: dbutils.secrets.get(scope, key)
    if "client-id" in keys:  # a service principal, stored with the CLI
        other = WorkspaceClient(host=secret("host"), client_id=secret("client-id"),
                                client_secret=secret("client-secret"), auth_type="oauth-m2m")
    else:
        other = WorkspaceClient(host=secret("host"), token=secret("token"), auth_type="pat")
    return other.current_user.me().user_name


if dbutils.widgets.get("where") == OTHER:
    url = dbutils.widgets.get("other_url").strip().rstrip("/")
    if not url:
        raise ValueError("You picked another workspace. Put its URL in box 2 at the top, then run this cell again.")
    url = "https://" + url.split("://")[-1]
    if scope not in {s.name for s in w.secrets.list_scopes()}:
        w.secrets.create_scope(scope=scope)
    w.secrets.put_secret(scope=scope, key="host", string_value=url)
    stored = {s.key for s in w.secrets.list_secrets(scope=scope)}
    if not stored & {"token", "client-id"}:
        w.secrets.put_secret(scope=scope, key="token", string_value=ask_for_token(
            "Paste a personal access token from the other workspace (it stays hidden): "))
    for attempt in range(3):
        try:
            other_user = signed_in_as()
            break
        except Exception as e:
            if attempt == 2 or "client-id" in stored:
                raise RuntimeError(f"Couldn't sign in to the other workspace: {str(e)[:200]}") from None
            w.secrets.put_secret(scope=scope, key="token", string_value=ask_for_token(
                "That token didn't work in the other workspace. Paste another one (it stays hidden): "))
    print(f"✅ The new home goes to another workspace, where you're signed in as {other_user}.")
    print(f"   Its URL and your token are in secret scope {scope}. Only you and workspace admins can read it.")
else:
    print("✅ The new home goes in this workspace, as a second project. Nothing else to set up.")
print("   Catalog for the synced-table steps:", dbutils.widgets.get("catalog").strip() or "main")
print("\nChange a box at the top and run this cell again, or click Run all.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Why can't a branch just move?
# MAGIC
# MAGIC Short version: a branch belongs to its project, and it can't leave.
# MAGIC
# MAGIC A Lakebase **project** owns its storage and the history inside it. That history is what makes branches, point-in-time restore, and snapshots work. A **branch** is an instant copy of another branch *in the same project*, and it can't point anywhere else. So nothing in the API moves or exports a branch, not even to another project in the same workspace.
# MAGIC
# MAGIC ```
# MAGIC Project                       owns the storage and its history
# MAGIC  ├── Branch                   an instant copy of a branch in the SAME project
# MAGIC  │    ├── Compute             what you connect to (its host)
# MAGIC  │    └── Database            one or more per branch: databricks_postgres, reporting, ...
# MAGIC  │         └── Schema → Tables      plain Postgres
# MAGIC  ├── Point-in-time history    the restore window: 2 to 30 days, 7 by default
# MAGIC  └── Snapshots                can only be restored inside this project
# MAGIC ```
# MAGIC
# MAGIC So "promoting to another workspace" really means **rebuilding** there, and each piece comes from its own place:
# MAGIC
# MAGIC | Piece | On the new side, it comes from |
# MAGIC |---|---|
# MAGIC | Project, branches, computes | a **bundle**: `databricks bundle deploy` |
# MAGIC | Schema | your **migrations** (in a move, production's schema comes along in its dump) |
# MAGIC | Data | `pg_dump` and `pg_restore`, one database at a time, and **only** when the data has to move |
# MAGIC | Synced tables | created again on the new side, where they refill from the lakehouse |
# MAGIC | Roles, ownership, grants | your access script, run again |
# MAGIC | Point-in-time history, snapshots | nothing: they start over |
# MAGIC
# MAGIC Most of the time you're **promoting**: deploy the bundle, run the migrations, and no data crosses over. You only **move** when the environment itself relocates (a new workspace, cloud, or region, or a newer Postgres major version). That's when the data comes along.
# MAGIC
# MAGIC 📖 Learn more: [Branches](https://docs.databricks.com/aws/en/oltp/projects/branches) ·
# MAGIC [pg_dump and pg_restore](https://docs.databricks.com/aws/en/oltp/projects/pg-dump-restore) ·
# MAGIC [Bundle resources](https://docs.databricks.com/aws/en/dev-tools/bundles/resources)

# COMMAND ----------

# MAGIC %md
# MAGIC ### First, install the Python libraries
# MAGIC
# MAGIC We install two libraries: the **Databricks SDK**, to create projects and branches and get login tokens, and **psycopg**, the standard Python driver for Postgres. The nice thing is that ordinary Postgres tools just work, because this is plain Postgres. The next cell restarts Python so they load.
# MAGIC
# MAGIC > We hold `protobuf` below version 6 to match what serverless already has loaded. On older serverless versions, pip may print a red **dependency conflict** note about it. It comes from a preinstalled package the lab doesn't use, so you can ignore it.

# COMMAND ----------

# MAGIC %pip install --quiet -U "databricks-sdk>=0.81.0" "psycopg>=3.1" "protobuf<6"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 0: Set up your tools
# MAGIC
# MAGIC ### Install `pg_dump` and `pg_restore`
# MAGIC
# MAGIC A move copies each database with `pg_dump` and loads it with `pg_restore`. They're the standard Postgres tools, but serverless doesn't ship them, and you can't run `apt-get` there. So this cell downloads the official client package from the [PostgreSQL project's own package repository](https://apt.postgresql.org) and unpacks it on local disk. No admin rights needed.
# MAGIC
# MAGIC One rule to know: the client has to be the same version as your database's Postgres, or newer. The lab's projects run Postgres 17, so we install the version 17 client.
# MAGIC
# MAGIC The download also brings **libpq**, the Postgres client library, which psycopg uses too. (We skip psycopg's all-in-one `binary` package, because its built-in OpenSSL crashes on some serverless machines.)

# COMMAND ----------

# DBTITLE 1,Download and unpack the PostgreSQL 17 client tools
"""Download postgresql-client-17 and libpq5 from apt.postgresql.org and unpack them, no install needed.

The package index tells us the file for each package on this machine's Ubuntu release and CPU type.
"""
import gzip
import os
import platform
import subprocess
import tempfile
import urllib.request
from pathlib import Path

PG_VERSION = 17  # the Postgres version for both projects; the client must match or be newer


def install_pg_client(version: int = PG_VERSION):
    """Fetch postgresql-client-<version> and libpq5 from apt.postgresql.org and unpack them locally.

    Returns the folder with the binaries and the folder with libpq.
    """
    os_release = dict(line.strip().split("=", 1) for line in open("/etc/os-release") if "=" in line)
    codename = os_release["VERSION_CODENAME"].strip('"')  # for example "noble"
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    repo = "https://apt.postgresql.org/pub/repos/apt"

    # The package index lists the file for every package; pick the two we need.
    index = gzip.decompress(
        urllib.request.urlopen(f"{repo}/dists/{codename}-pgdg/main/binary-{arch}/Packages.gz", timeout=60).read()
    ).decode()
    wanted = {f"postgresql-client-{version}": None, "libpq5": None}
    for block in index.split("\n\n"):
        fields = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l and not l.startswith(" "))
        if fields.get("Package") in wanted:
            wanted[fields["Package"]] = fields["Filename"]
    missing = [name for name, filename in wanted.items() if not filename]
    if missing:
        raise RuntimeError(f"Couldn't find {missing} for {codename}/{arch} at {repo}")

    root = Path(tempfile.mkdtemp(prefix="pgclient-"))  # a fresh folder for this session
    for package, filename in wanted.items():
        deb = root / Path(filename).name
        urllib.request.urlretrieve(f"{repo}/{filename}", deb)
        subprocess.run(["dpkg-deb", "-x", str(deb), str(root / "files")], check=True)  # unpack, no install

    bin_dir = root / "files" / "usr" / "lib" / "postgresql" / str(version) / "bin"
    lib_dir = next((root / "files" / "usr" / "lib").glob("*-linux-gnu"))
    return bin_dir, lib_dir


PG_BIN, PG_LIB = install_pg_client()
PG_ENV = dict(os.environ, LD_LIBRARY_PATH=str(PG_LIB))  # so the tools load the libpq we unpacked
for tool in ("pg_dump", "pg_restore"):
    print(subprocess.run([str(PG_BIN / tool), "--version"], env=PG_ENV, capture_output=True, text=True).stdout.strip())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install the Databricks CLI
# MAGIC
# MAGIC The new home gets built by a **bundle**, and you deploy bundles with the Databricks CLI: `databricks bundle deploy`, the same command you'd run from your laptop or a CI pipeline. This cell downloads the CLI from [GitHub](https://github.com/databricks/cli/releases) into a temp folder. It signs in as **you**, with a token from this notebook's own sign-in, and it never prints the token.

# COMMAND ----------

# DBTITLE 1,Download the Databricks CLI
"""Download the Databricks CLI for this machine's CPU type and unpack the single binary into a temp folder."""
import io
import zipfile

CLI_VERSION = "1.17.0"  # the CLI version this lab was tested with
arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
url = f"https://github.com/databricks/cli/releases/download/v{CLI_VERSION}/databricks_cli_{CLI_VERSION}_linux_{arch}.zip"
CLI_DIR = Path(tempfile.mkdtemp(prefix="dbcli-"))
with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())) as z:
    z.extract("databricks", CLI_DIR)
CLI = CLI_DIR / "databricks"
CLI.chmod(0o755)
print(subprocess.run([str(CLI), "--version"], capture_output=True, text=True).stdout.strip())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Connect, name things, and set up helpers
# MAGIC
# MAGIC This cell does four things:
# MAGIC
# MAGIC * **Connects to Databricks.** In Lakebase, **your Databricks identity is your Postgres user**, and you log in with a short-lived token instead of a password. Every connection here gets a fresh token, so nothing expires mid-lab.
# MAGIC * **Names the two projects after you**, so a whole team can run the lab in one workspace: `lb-move-old-…` is the **old home** and `lb-move-new-…` is the **new home**.
# MAGIC * **Sets up helpers** we'll reuse. One takes a database's **fingerprint**: a row count plus a checksum of every row, for each table. That's how we'll prove two copies are identical.
# MAGIC * **Defines the app's migrations:** numbered SQL changes, run in order and recorded in a history table. That's what Flyway or Liquibase does for a real app.
# MAGIC
# MAGIC > Your answers from **Choose your setup** land here: `CATALOG`, and `NEW_WORKSPACE_SECRETS` if the new home goes to another workspace.

# COMMAND ----------

# DBTITLE 1,Connect, name the two projects, and define helpers
"""Connect to Databricks, pick per-user names, and define the helpers the rest of the lab uses."""
import ctypes.util
import json
import re
import shutil
import time
import urllib.request
from datetime import datetime, timezone

import pandas as pd

# psycopg's pure-Python mode finds libpq by asking ctypes for "pq". Answer with the copy we unpacked.
os.environ["PSYCOPG_IMPL"] = "python"
_find_library = ctypes.util.find_library
ctypes.util.find_library = lambda name: str(PG_LIB / "libpq.so.5") if name == "pq" else _find_library(name)
try:
    import psycopg
finally:
    ctypes.util.find_library = _find_library

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import (
    Branch,
    BranchSpec,
    Duration,
    Endpoint,
    EndpointSpec,
    EndpointType,
    Project,
    ProjectSpec,
    Snapshot,
    SnapshotSpec,
    SyncedTable,
    SyncedTableSyncedTableSpec,
    SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy,
    Timestamp,
)

w = WorkspaceClient()
me = w.current_user.me()
USER = me.user_name  # your Postgres user name
slug = re.sub(r"[^a-z0-9]+", "-", USER.split("@")[0].lower()).strip("-")[:16].rstrip("-") or "user"


def answer(name, default):
    """Your answer to a question in Choose your setup, from the boxes at the top (or its default)."""
    try:
        return dbutils.widgets.get(name).strip() or default
    except Exception:
        return default


# From Choose your setup. For another workspace, its URL and your credentials there are in a secret scope
# of your own: "host", plus "token", or "client-id" and "client-secret" for a service principal.
NEW_WORKSPACE_SECRETS = f"lb-move-lab-{slug}" if answer("where", "") == "Another workspace" else None


def sign_in_elsewhere(scope):
    """Sign in to the new home's workspace with the address and credentials in a secret scope."""
    def secret(key):
        try:
            return dbutils.secrets.get(scope, key)
        except Exception:
            return None

    host, token, client_id = secret("host"), secret("token"), secret("client-id")
    if not host or not (token or client_id):
        raise ValueError(f"No URL or token stored for the other workspace yet (secret scope {scope}). "
                         "Run Choose your setup, the first code cell, and paste a token when it asks.")
    if client_id:
        return WorkspaceClient(host=host, client_id=client_id, client_secret=secret("client-secret"),
                               auth_type="oauth-m2m")
    return WorkspaceClient(host=host, token=token, auth_type="pat")


w_new = sign_in_elsewhere(NEW_WORKSPACE_SECRETS) if NEW_WORKSPACE_SECRETS else w  # the new home's workspace
TWO_WORKSPACES = w_new is not w
NEW_USER = w_new.current_user.me().user_name if TWO_WORKSPACES else USER  # your Postgres user over there

# Unique, readable names: your user name plus your numeric user id.
OLD_ID = f"lb-move-old-{slug}-{me.id}"  # the old home, in this workspace
NEW_ID = f"lb-move-new-{slug}-{me.id}"  # the new home, in this workspace or the other one
DB = "databricks_postgres"  # the default database in every Lakebase project
REPORTING_DB = "reporting"  # a second database the app uses (Module 1, Step 3)

# The bundle that builds the new home (Module 3). The CLI keeps its deployment state under your home folder.
BUNDLE_NAME = "lb-move-lab"
BUNDLE_DIR = Path(tempfile.mkdtemp(prefix="lb_move_bundle_"))  # stands in for your Git checkout
BUNDLE_ROOT = f"/Workspace/Users/{NEW_USER}/.bundle/{BUNDLE_NAME}"  # in the new home's workspace

# Optional synced-table steps (Module 1, Step 6 and Module 4, Step 4).
DO_SYNCED_TABLES = True
CATALOG = answer("catalog", "main")  # from Choose your setup: a catalog where you can create a schema
UC_SCHEMA = "lb_move_" + slug.replace("-", "_")
SOURCE_TABLE = f"{CATALOG}.{UC_SCHEMA}.product_catalog"  # a lakehouse (Delta) table
SYNCED_TABLE = f"{CATALOG}.{UC_SCHEMA}.product_catalog_synced"  # its copy inside Lakebase

WORK_DIR = Path(tempfile.mkdtemp(prefix="lb_move_"))  # dump files for this session


def project_path(pid):
    return f"projects/{pid}"


def branch_path(pid, branch):
    return f"projects/{pid}/branches/{branch}"


def client(pid):
    """The workspace a project lives in. The new home can be in another workspace."""
    return w_new if pid == NEW_ID else w


def pg_user(pid):
    """Your Postgres user name in the project's workspace."""
    return NEW_USER if pid == NEW_ID else USER


def project_exists(pid):
    return any(p.name == project_path(pid) for p in client(pid).postgres.list_projects())


def create_project(pid, label):
    """Create a Postgres project (or reuse it). It comes with a production branch and its compute."""
    if project_exists(pid):
        print(f"Reusing project {pid}")
        return
    client(pid).postgres.create_project(
        project=Project(spec=ProjectSpec(display_name=label, pg_version=PG_VERSION)), project_id=pid
    ).wait()
    print(f"Created project {pid} (Postgres {PG_VERSION})")


def create_branch(pid, branch, source="production"):
    """Create a child branch from another branch in the SAME project (or reuse it)."""
    try:
        client(pid).postgres.get_branch(name=branch_path(pid, branch))
        print(f"Branch {branch} already exists in {pid}")
        return
    except Exception:
        pass
    client(pid).postgres.create_branch(
        parent=project_path(pid),
        branch=Branch(spec=BranchSpec(source_branch=branch_path(pid, source), no_expiry=True)),
        branch_id=branch,
    ).wait()
    print(f"Created branch {branch} from {source} in {pid}")


def endpoint_of(pid, branch, timeout=300):
    """Find the branch's compute and wait until it has a host. Creates one if none shows up."""
    started, created = time.time(), False
    while True:
        endpoints = list(client(pid).postgres.list_endpoints(parent=branch_path(pid, branch)))
        for ep in endpoints:
            if ep.status and ep.status.hosts and ep.status.hosts.host:
                return ep.name, ep.status.hosts.host
        if not endpoints and not created and time.time() - started > 60:
            client(pid).postgres.create_endpoint(
                parent=branch_path(pid, branch),
                endpoint=Endpoint(spec=EndpointSpec(endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                                                    autoscaling_limit_min_cu=0.5, autoscaling_limit_max_cu=2.0)),
                endpoint_id="primary",
            ).wait()
            created = True
        if time.time() - started > timeout:
            raise TimeoutError(f"No compute with a host on {branch_path(pid, branch)}")
        time.sleep(5)


def login(pid, branch):
    """Return (host, token): where to connect, and a fresh one-hour login token."""
    endpoint, host = endpoint_of(pid, branch)
    return host, client(pid).postgres.generate_database_credential(endpoint=endpoint).token


def public_address(pid, host):
    """The public IP of a compute in another workspace, or None for computes in this one.

    On serverless, every Lakebase hostname resolves to a Databricks proxy, and in testing that proxy refused
    another workspace's computes. Their public address works, so we look it up in public DNS.
    """
    if pid != NEW_ID or not TWO_WORKSPACES:
        return None
    for url in (f"https://dns.google/resolve?name={host}&type=A",
                f"https://cloudflare-dns.com/dns-query?name={host}&type=A"):
        try:
            request = urllib.request.Request(url, headers={"accept": "application/dns-json"})
            answers = json.load(urllib.request.urlopen(request, timeout=15)).get("Answer", [])
            addresses = [a["data"] for a in answers if a.get("type") == 1]
            if addresses:
                return addresses[0]
        except Exception:
            pass
    raise RuntimeError(f"Couldn't look up {host} in public DNS (dns.google or cloudflare-dns.com)")


def connect(pid, branch, dbname=DB):
    """Open a Postgres connection to one database on a branch. Retries while the compute wakes up."""
    host, token = login(pid, branch)
    address = public_address(pid, host)
    for attempt in range(6):
        try:
            return psycopg.connect(host=host, dbname=dbname, user=pg_user(pid), password=token,
                                   sslmode="require", connect_timeout=30, autocommit=True,
                                   **({"hostaddr": address} if address else {}))
        except psycopg.OperationalError:
            if attempt == 5:
                raise
            time.sleep(10)


def query(pid, branch, sql_text, params=None, dbname=DB):
    """Run a query and return the rows as a table."""
    with connect(pid, branch, dbname) as conn:
        cur = conn.execute(sql_text, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def show(df):
    """Display a result table, or say there are no rows (display can't render an empty table)."""
    if df.empty:
        print("(no rows)")
    else:
        display(df)


def create_database(pid, branch, name):
    """Create a database on a branch unless it exists. CREATE DATABASE needs autocommit, which connect() uses."""
    with connect(pid, branch) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            print(f"Database {name} already exists on {branch} in {pid}")
        else:
            conn.execute(f'CREATE DATABASE "{name}"')
            print(f"Created database {name} on {branch} in {pid}")


def run_pg(tool, pid, branch, args, dbname=DB):
    """Run pg_dump or pg_restore against one database on a branch. The token goes in the environment, never on screen."""
    host, token = login(pid, branch)
    env = dict(PG_ENV, PGHOST=host, PGPORT="5432", PGUSER=pg_user(pid), PGPASSWORD=token,
               PGDATABASE=dbname, PGSSLMODE="require")
    address = public_address(pid, host)
    if address:
        env["PGHOSTADDR"] = address  # libpq still sends the hostname for TLS
    started = time.time()
    result = subprocess.run([str(PG_BIN / tool), *args], env=env, capture_output=True, text=True)
    return result.returncode, round(time.time() - started, 1), result.stderr.strip()


def cli(*args, cwd=BUNDLE_DIR):
    """Run the Databricks CLI as you, against the new home's workspace. Its token is never printed."""
    auth = w_new.config.authenticate().get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise RuntimeError("Couldn't get a token for the CLI from this notebook's sign-in")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(CLI_DIR),
           "DATABRICKS_HOST": w_new.config.host, "DATABRICKS_TOKEN": auth.split(" ", 1)[1]}
    result = subprocess.run([str(CLI), *args], env=env, cwd=cwd, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def fingerprint(pid, branch, dbname=DB, schema="app"):
    """Row count and an md5 of every row, per table. Two identical copies have identical fingerprints."""
    with connect(pid, branch, dbname) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY 1", (schema,)).fetchall()]
        rows = [(t, *conn.execute(
            f"SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {schema}.{t} x"
        ).fetchone()) for t in tables]
    return pd.DataFrame(rows, columns=["table", "rows", "md5"])


# The app's schema changes, in order. A real app keeps these as files in Git.
MIGRATIONS = {
    1: ("customers", """
        CREATE SCHEMA IF NOT EXISTS app;
        CREATE TABLE app.customers (
          customer_id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
          name text NOT NULL, email text NOT NULL UNIQUE,
          created_at timestamptz NOT NULL DEFAULT now())"""),
    2: ("orders", """
        CREATE TABLE app.orders (
          order_id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
          customer_id bigint NOT NULL REFERENCES app.customers,
          amount_cents int NOT NULL,
          placed_at timestamptz NOT NULL DEFAULT now())"""),
    3: ("coupons", """
        CREATE TABLE app.coupons (code text PRIMARY KEY, percent_off int NOT NULL CHECK (percent_off BETWEEN 1 AND 90));
        ALTER TABLE app.orders ADD COLUMN coupon_code text REFERENCES app.coupons"""),
    4: ("feature flags (unreleased)", """
        CREATE TABLE app.feature_flags (flag text PRIMARY KEY, enabled boolean NOT NULL, note text)"""),
}


def migrate(pid, branch, up_to):
    """Apply every migration up to `up_to` that this branch hasn't had yet, and record it.

    Once the app_owner role exists, migrations run as that role (SET ROLE), so everything they
    create belongs to it and picks up its default grants. That's the deck's "migrate as the owner role".
    """
    with connect(pid, branch) as conn:
        if not conn.execute("SELECT to_regclass('app.schema_migrations') IS NOT NULL").fetchone()[0]:
            conn.execute("CREATE SCHEMA IF NOT EXISTS app")  # first run only, before any roles exist
            conn.execute("CREATE TABLE app.schema_migrations ("
                         "version int PRIMARY KEY, description text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'app_owner'").fetchone():
            conn.execute("SET ROLE app_owner")
        done = {r[0] for r in conn.execute("SELECT version FROM app.schema_migrations").fetchall()}
        for version in sorted(MIGRATIONS):
            if version > up_to or version in done:
                continue
            description, ddl = MIGRATIONS[version]
            with conn.transaction():
                conn.execute(ddl)
                conn.execute("INSERT INTO app.schema_migrations (version, description) VALUES (%s, %s)",
                             (version, description))
            print(f"  applied V{version}: {description}")
        return [r[0] for r in conn.execute("SELECT version FROM app.schema_migrations ORDER BY 1").fetchall()]


print("Signed in as:", USER)
print("Old home:", OLD_ID, "in", w.config.host)
print("New home:", NEW_ID, "in", w_new.config.host + (f" (another workspace, as {NEW_USER})" if TWO_WORKSPACES else ""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 1: Build the old home
# MAGIC
# MAGIC First, let's build what a real team would have:
# MAGIC
# MAGIC * production, with the app's data in two databases and access rules;
# MAGIC * a dev branch with unreleased work and test data;
# MAGIC * a synced table fed from the lakehouse.
# MAGIC
# MAGIC This is what we'll move later.
# MAGIC
# MAGIC ### Step 1: Create the old project
# MAGIC
# MAGIC A **project** is the container. Creating one also creates its `production` branch and a compute to run your queries. The first run takes about a minute.

# COMMAND ----------

# DBTITLE 1,Create the old home's project
"""Create (or reuse) the old home's project, then wait for its production compute to get a host."""
create_project(OLD_ID, "Lakebase move lab: old home")
print("Production compute:", endpoint_of(OLD_ID, "production")[1])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2: Create the app's tables and data on production
# MAGIC
# MAGIC We run migrations V1 and V2 (customers and orders), then load 1,000 customers and 5,000 orders. Keep an eye on the `schema_migrations` table: it records which migrations ran, and that's how a migration tool knows what to run next.

# COMMAND ----------

# DBTITLE 1,Migrate production to V2 and load data
"""Run V1 and V2 on old production, then load customers and orders (only the first time)."""
print("Migrations on old production:", migrate(OLD_ID, "production", up_to=2))
with connect(OLD_ID, "production") as conn:
    if conn.execute("SELECT count(*) FROM app.customers").fetchone()[0] == 0:
        conn.execute("INSERT INTO app.customers (name, email) "
                     "SELECT 'Customer ' || g, 'customer' || g || '@example.com' FROM generate_series(1, 1000) g")
        conn.execute("INSERT INTO app.orders (customer_id, amount_cents) "
                     "SELECT 1 + g % 1000, 500 + (g * 37) % 20000 FROM generate_series(1, 5000) g")
show(query(OLD_ID, "production",
           "SELECT (SELECT count(*) FROM app.customers) AS customers, (SELECT count(*) FROM app.orders) AS orders"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3: Add a second database, `reporting`
# MAGIC
# MAGIC A branch can hold **more than one database**, all on the same compute. Our app keeps its stock levels in a second one, `reporting`. Remember this one: `pg_dump` and `pg_restore` work on **one database at a time**, so the move has to handle each database on its own.

# COMMAND ----------

# DBTITLE 1,Create the reporting database on production and load it
"""Create `reporting` next to `databricks_postgres` on old production, with 200 rows of stock levels."""
create_database(OLD_ID, "production", REPORTING_DB)
with connect(OLD_ID, "production", REPORTING_DB) as conn:
    conn.execute("CREATE SCHEMA IF NOT EXISTS app")
    conn.execute("CREATE TABLE IF NOT EXISTS app.stock ("
                 "sku text PRIMARY KEY, product text NOT NULL, on_hand int NOT NULL)")
    if conn.execute("SELECT count(*) FROM app.stock").fetchone()[0] == 0:
        conn.execute("INSERT INTO app.stock "
                     "SELECT 'SKU-' || g, 'Product ' || g, (g * 7) % 120 FROM generate_series(1, 200) g")
show(query(OLD_ID, "production", "SELECT datname AS database FROM pg_database WHERE NOT datistemplate ORDER BY 1"))
show(query(OLD_ID, "production", "SELECT count(*) AS stock_rows FROM app.stock", dbname=REPORTING_DB))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4: Set up access on production
# MAGIC
# MAGIC Real apps don't let everyone own everything, so we create two Postgres roles:
# MAGIC
# MAGIC * `app_owner` owns the app's schemas and tables. Migrations run as this role.
# MAGIC * `app_reader` can only read, like an analyst or a reporting tool.
# MAGIC
# MAGIC Here's the part to remember: **roles belong to the branch**, so we create them once. **Ownership and grants belong to each database**, so we set those up in both. We also set **default privileges**, so tables created later are readable too. Why does this matter? Because in the move, none of it comes along with the data.

# COMMAND ----------

# DBTITLE 1,Set up roles, ownership, and read access in both databases
"""Create the roles once for the branch, then set ownership, grants, and default privileges in each database."""
ROLES_SQL = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_owner') THEN CREATE ROLE app_owner NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_reader') THEN CREATE ROLE app_reader NOLOGIN; END IF;
END $$;
GRANT app_owner TO CURRENT_USER;
"""
GRANTS_SQL = """
ALTER SCHEMA app OWNER TO app_owner;
DO $$ DECLARE t record; BEGIN
  FOR t IN SELECT format('%I.%I', schemaname, tablename) AS name FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE 'ALTER TABLE ' || t.name || ' OWNER TO app_owner';
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA app TO app_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA app TO app_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app GRANT SELECT ON TABLES TO app_reader;
"""


def set_up_access(pid, branch, databases):
    with connect(pid, branch, databases[0]) as conn:
        conn.execute(ROLES_SQL)  # roles belong to the branch, so once is enough
    for db in databases:
        with connect(pid, branch, db) as conn:
            conn.execute(GRANTS_SQL)  # ownership and grants belong to each database


ACCESS_CHECK = """
SELECT c.relname AS "table", pg_get_userbyid(c.relowner) AS owner,
       has_table_privilege('app_reader', c.oid, 'SELECT') AS app_reader_can_read
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'app' AND c.relkind = 'r' ORDER BY 1
"""


def access_report(pid, branch, databases):
    """Each app table's owner, and whether app_reader can read it, database by database."""
    return pd.concat([query(pid, branch, ACCESS_CHECK, dbname=db).assign(database=db) for db in databases],
                     ignore_index=True)[["database", "table", "owner", "app_reader_can_read"]]


set_up_access(OLD_ID, "production", [DB, REPORTING_DB])
show(access_report(OLD_ID, "production", [DB, REPORTING_DB]))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 5: Create a dev branch and do some unreleased work
# MAGIC
# MAGIC A **branch** is an instant copy of its parent, both databases included. It's copy-on-write, so nothing actually gets copied up front. On `development` we:
# MAGIC
# MAGIC * run migrations V3 (coupons) and V4 (feature flags). V4 is **unreleased**, so production won't get it in this lab;
# MAGIC * add a test coupon, `DEV-TEST-50`, and put it on three orders. Those are changes to tables production also has;
# MAGIC * add two feature flags, in a table that exists **only** on this branch.
# MAGIC
# MAGIC Production doesn't see any of it. Branches are isolated both ways.

# COMMAND ----------

# DBTITLE 1,Create the dev branch and make dev-only changes
"""Branch old production into development, run V3 and V4 there, and add dev-only data."""
create_branch(OLD_ID, "development")
print("Migrations on old development:", migrate(OLD_ID, "development", up_to=4))
with connect(OLD_ID, "development") as conn:
    conn.execute("INSERT INTO app.coupons VALUES ('DEV-TEST-50', 50) ON CONFLICT DO NOTHING")
    conn.execute("UPDATE app.orders SET coupon_code = 'DEV-TEST-50' WHERE order_id IN (11, 22, 33)")
    conn.execute("INSERT INTO app.feature_flags VALUES ('new_checkout', true, 'Alex is testing'), "
                 "('dark_mode', false, 'not ready') ON CONFLICT DO NOTHING")

print("Development has:")
show(query(OLD_ID, "development",
           "SELECT version, description FROM app.schema_migrations ORDER BY 1"))
print("Production has:")
show(query(OLD_ID, "production",
           "SELECT version, description FROM app.schema_migrations ORDER BY 1"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 6 (optional): Add a synced table fed from the lakehouse
# MAGIC
# MAGIC Lots of Lakebase apps read reference data that lives in the lakehouse. A **synced table** keeps a copy of a Delta table inside Lakebase. We create a small Delta table of products and sync it into old production.
# MAGIC
# MAGIC Here's the catch for later: synced tables can't travel through `pg_dump`, so we'll recreate this one on the new side. Also, the create call comes back **before** the rows land, so this cell waits for the rows.
# MAGIC
# MAGIC 📖 Learn more: [Synced tables](https://docs.databricks.com/aws/en/oltp/projects/sync-tables)

# COMMAND ----------

# DBTITLE 1,Create a Delta table and sync it into old production
"""Create a 50-row Delta table in Unity Catalog, sync it into old production, and wait for the rows."""
def wait_for_sync(pid, synced_name, pg_table, expected_rows, timeout=900):
    """Wait until the synced table is online and Postgres has every row."""
    started = time.time()
    while True:
        status = client(pid).postgres.get_synced_table(name=f"synced_tables/{synced_name}").status
        state = str(status.detailed_state) if status else "unknown"
        try:
            rows = query(pid, "production", f"SELECT count(*) AS n FROM {pg_table}")["n"][0]
        except Exception:
            rows = 0
        if rows >= expected_rows and "ONLINE" in state:
            return state, rows, round(time.time() - started)
        if time.time() - started > timeout:
            raise TimeoutError(f"{synced_name}: state {state}, {rows} rows")
        time.sleep(15)


if DO_SYNCED_TABLES:
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{UC_SCHEMA}")
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {SOURCE_TABLE} (
                        product_id BIGINT NOT NULL, name STRING NOT NULL, price_cents INT NOT NULL,
                        CONSTRAINT product_catalog_pk PRIMARY KEY (product_id))
                      TBLPROPERTIES (delta.enableChangeDataFeed = true)""")
        if spark.table(SOURCE_TABLE).count() == 0:
            spark.sql(f"INSERT INTO {SOURCE_TABLE} SELECT id, concat('Product ', id), CAST(100 + id * 25 AS INT) "
                      f"FROM range(1, 51)")
        try:
            w.postgres.get_synced_table(name=f"synced_tables/{SYNCED_TABLE}")
            print("The synced table already exists, so we reuse it.")
        except Exception:
            w.postgres.create_synced_table(
                synced_table=SyncedTable(spec=SyncedTableSyncedTableSpec(
                    source_table_full_name=SOURCE_TABLE,
                    branch=branch_path(OLD_ID, "production"),
                    postgres_database=DB,
                    primary_key_columns=["product_id"],
                    scheduling_policy=SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy.SNAPSHOT,
                    create_database_objects_if_missing=True)),
                synced_table_id=SYNCED_TABLE).wait()
            print("Create call returned. Waiting for the rows to land...")
        state, rows, secs = wait_for_sync(OLD_ID, SYNCED_TABLE, f"{UC_SCHEMA}.product_catalog_synced", 50)
        print(f"Synced: {rows} rows in Postgres, state {state}, after {secs} s")
    except Exception as e:
        DO_SYNCED_TABLES = False
        print("Skipping the synced-table steps:", str(e)[:300])
else:
    print("Skipped (DO_SYNCED_TABLES = False)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 2: Promote a change the everyday way
# MAGIC
# MAGIC Most releases are **promotions**, not moves. Dev's V3 (coupons) is ready, so we promote it the way CI would: **run the migration on production**. No data moves, so dev's test coupon stays on dev.
# MAGIC
# MAGIC There's no merge button for branches. Promoting *is* running the same, already-tested migration on the next environment.
# MAGIC
# MAGIC After the release, production starts using a real coupon, `FALL10`.

# COMMAND ----------

# DBTITLE 1,Run V3 on production, then use the new table
"""Promote V3 to old production with the migration tool, then put the new table to use."""
print("Migrations on old production:", migrate(OLD_ID, "production", up_to=3))
with connect(OLD_ID, "production") as conn:
    conn.execute("INSERT INTO app.coupons VALUES ('FALL10', 10) ON CONFLICT DO NOTHING")
    conn.execute("UPDATE app.orders SET coupon_code = 'FALL10' WHERE order_id % 97 = 0 AND coupon_code IS NULL")

print("Coupons on production:")
show(query(OLD_ID, "production", "SELECT code, percent_off FROM app.coupons ORDER BY 1"))
print("Coupons on development:")
show(query(OLD_ID, "development", "SELECT code, percent_off FROM app.coupons ORDER BY 1"))

# COMMAND ----------

# MAGIC %md
# MAGIC Two things to notice:
# MAGIC
# MAGIC * Production got dev's **schema** change (V3), but **not** dev's test coupon. Promotion moves schema, not data.
# MAGIC * Dev doesn't have `FALL10`. A branch is a copy as of the moment it was created, and it never picks up its parent's later changes.
# MAGIC
# MAGIC And because V3 ran as `app_owner`, the new `coupons` table is already readable by `app_reader`. That's the default privileges at work:

# COMMAND ----------

# DBTITLE 1,The new table picked up the default grants
"""Show that the table V3 created belongs to app_owner and is readable by app_reader."""
show(access_report(OLD_ID, "production", [DB]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 3: Build the new home
# MAGIC
# MAGIC Now the bigger job. Say the old home's workspace is going away, so production has to **move**. A move is five steps:
# MAGIC
# MAGIC 1. Put it all in Git.
# MAGIC 2. Deploy the bundle, and leave production un-migrated.
# MAGIC 3. Restore production from a full dump, one database at a time.
# MAGIC 4. Recreate the synced tables, and let them fill.
# MAGIC 5. Recreate the child branches.
# MAGIC
# MAGIC This module does steps 1 and 2, then tries the obvious shortcut. Module 4 does the rest.
# MAGIC
# MAGIC ### Step 1: Put it all in Git
# MAGIC
# MAGIC The new home is described in a **bundle** file, `databricks.yml`. In a real move, it lives in Git next to your migrations and app code; here it goes in a temp folder. It declares the project, its two branches, and development's compute. Two settings worth knowing:
# MAGIC
# MAGIC * `lifecycle: { prevent_destroy: true }` on the project and production, so a stray `bundle destroy` can't delete them. Module 7 shows it.
# MAGIC * `history_retention_duration`, the restore window. It's a **setting**, so it doesn't come along with the data. You set it again on the new side.
# MAGIC
# MAGIC > Lakebase support in bundles is labeled **Beta**.
# MAGIC
# MAGIC 📖 Learn more: [Bundle resources](https://docs.databricks.com/aws/en/dev-tools/bundles/resources)

# COMMAND ----------

# DBTITLE 1,Step 1: write the bundle file (it would live in Git)
"""Write the new home's bundle file. guard=True adds lifecycle.prevent_destroy to the project and production."""
def write_bundle(guard=True):
    lifecycle = "\n      lifecycle: { prevent_destroy: true }" if guard else ""
    text = f"""bundle:
  name: {BUNDLE_NAME}

targets:
  new_home:
    default: true
    workspace:
      host: {w_new.config.host}

resources:
  postgres_projects:
    app:
      project_id: {NEW_ID}
      pg_version: {PG_VERSION}
      history_retention_duration: 604800s   # the restore window: 7 days
      purge_on_delete: true                 # lab only: frees the name as soon as it's deleted{lifecycle}

  postgres_branches:
    production:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: production
      replace_existing: true                # Lakebase makes production with the project; adopt it{lifecycle}
    development:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: development
      source_branch: ${{resources.postgres_branches.production.id}}
      no_expiry: true                       # every branch you add needs an expiry setting

  postgres_endpoints:
    development_primary:
      parent: ${{resources.postgres_branches.development.id}}
      endpoint_id: primary
      endpoint_type: ENDPOINT_TYPE_READ_WRITE
      replace_existing: true
"""
    (BUNDLE_DIR / "databricks.yml").write_text(text)
    return text


print(write_bundle())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2: Deploy the bundle
# MAGIC
# MAGIC `databricks bundle validate` checks the file, and `databricks bundle deploy` creates what it describes. Lakebase creates `production` along with the project, so the bundle **adopts** it (`replace_existing: true`) instead of failing.
# MAGIC
# MAGIC Notice the new production comes up **empty and un-migrated**. That's on purpose. Module 4's restore brings the data, the schema, and the migration history all at once. If the tables already existed, the restore would fail.

# COMMAND ----------

# DBTITLE 1,Step 2: databricks bundle validate, then deploy
"""Validate and deploy the bundle, the same commands you'd run from a laptop or CI."""
for args in (["bundle", "validate"], ["bundle", "deploy"]):
    rc, out = cli(*args)
    print(f"$ databricks {' '.join(args)}\n{out}\n")
    assert rc == 0, f"databricks {' '.join(args)} failed"

# COMMAND ----------

# DBTITLE 1,What the bundle built
"""Show the new home's computes, and that its production has no app tables yet."""
for branch in ("production", "development"):
    print(f"{branch}: compute at {endpoint_of(NEW_ID, branch)[1]}")
show(query(NEW_ID, "production",
           "SELECT string_agg(datname, ', ' ORDER BY datname) AS databases, "
           "(SELECT to_regclass('app.orders') IS NOT NULL) AS has_app_tables "
           "FROM pg_database WHERE NOT datistemplate"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### The shortcut: branch the new home from the old production?
# MAGIC
# MAGIC Before we copy any data, the obvious question: can we just create a branch in the new project whose parent is old production? Let's try it.

# COMMAND ----------

# DBTITLE 1,Try to branch the new home from the old home's production
"""Ask for a branch in the new project whose parent is in the old project. It's expected to fail."""
try:
    client(NEW_ID).postgres.create_branch(
        parent=project_path(NEW_ID),
        branch=Branch(spec=BranchSpec(source_branch=branch_path(OLD_ID, "production"), no_expiry=True)),
        branch_id="copied-production",
    ).wait()
    print("Unexpected: the branch was created")
except Exception as e:
    print("Rejected, as expected:")
    print("  ", str(e)[:300])

# COMMAND ----------

# MAGIC %md
# MAGIC **That's the big lesson.** A branch's parent has to be in the **same project**. You get the same error between two workspaces, and nothing in the API moves or exports a branch. So the new home gets **rebuilt**:
# MAGIC
# MAGIC * the **bundle** rebuilt the project and its branches (done),
# MAGIC * the **data** comes along only because we copy it on purpose, with `pg_dump` (next),
# MAGIC * and for the child branches, the **migrations** rebuild the schema.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 4: Move the data
# MAGIC
# MAGIC This is steps 3 to 5. With a live app, you pause writes before step 3. After step 4, you rebuild access, run a final check (the verification gate), switch the app, and resume writes. Step 5, the child branches, can wait until the app is live again.
# MAGIC
# MAGIC ### The app is live: write, then pause
# MAGIC
# MAGIC In real life, the app keeps writing to old production, so let's place a few new orders. Then we **pause writes** and take a **watermark**: the newest order ID and the row count. After the move, the new side has to match those numbers exactly.
# MAGIC
# MAGIC > In a real cutover, stop **every** writer: the app, jobs, scripts, and any app on a child branch. Make sure nothing is mid-transaction, then take the watermark. There's no live replication between projects, so anything written after the dump is lost.

# COMMAND ----------

# DBTITLE 1,Place a few orders, then pause writes and take a watermark
"""Simulate the live app, then pause writes: record the newest order and the count, and check for other sessions."""
with connect(OLD_ID, "production") as conn:
    conn.execute("INSERT INTO app.orders (customer_id, amount_cents) SELECT 1 + g, 1999 FROM generate_series(1, 25) g")
    WATERMARK = conn.execute("SELECT max(order_id), count(*) FROM app.orders").fetchone()
    busy = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() AND state = 'active' AND backend_type = 'client backend'").fetchone()[0]
PAUSE_STARTED = time.time()
print(f"Writes paused. Watermark: newest order_id {WATERMARK[0]}, {WATERMARK[1]} orders.")
print(f"Other active sessions right now: {busy}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3: Restore production from a full dump, one database at a time
# MAGIC
# MAGIC **First, list the databases.** `pg_dump` and `pg_restore` work on **one database** per run, and old production has more than one. So each database gets its own dump and its own restore. (The built-in `postgres` database is empty, so we skip it.)

# COMMAND ----------

# DBTITLE 1,Which databases does old production have?
"""List old production's databases. Each one needs its own dump and restore."""
databases = query(OLD_ID, "production", "SELECT datname AS database FROM pg_database WHERE NOT datistemplate ORDER BY 1")
show(databases)
APP_DATABASES = [d for d in databases.database if d != "postgres"]
print("Databases to move:", ", ".join(APP_DATABASES))

# COMMAND ----------

# MAGIC %md
# MAGIC **Dump each database.** We use the custom format (`-Fc`) so `pg_restore` can list and filter what's inside. In `databricks_postgres` we **exclude** the synced table, because synced tables can't travel through `pg_dump`. Step 4 recreates it instead.
# MAGIC
# MAGIC > Watch out: if the `--exclude-table` name has a typo, `pg_dump` doesn't complain. The synced table just quietly stays in the dump. That's why the cell checks each dump to make sure it's gone.

# COMMAND ----------

# DBTITLE 1,pg_dump each database on old production
"""One pg_dump per database, in custom format, then list each dump's table of contents."""
DUMPS, LISTINGS = {}, {}
for db in APP_DATABASES:
    DUMPS[db] = WORK_DIR / f"{db}.dump"
    args = ["-Fc", "-f", str(DUMPS[db])]
    if DO_SYNCED_TABLES and db == DB:
        args.append(f"--exclude-table={UC_SCHEMA}.product_catalog_synced")
    rc, secs, err = run_pg("pg_dump", OLD_ID, "production", args, dbname=db)
    assert rc == 0, f"pg_dump of {db} failed: {err}"
    print(f"{db}: pg_dump exit code 0 in {secs} s, {DUMPS[db].stat().st_size:,} bytes")
    LISTINGS[db] = subprocess.run([str(PG_BIN / "pg_restore"), "-l", str(DUMPS[db])], env=PG_ENV,
                                  capture_output=True, text=True, check=True).stdout
print("Synced table entries left in the dumps:",
      sum("product_catalog_synced" in l for text in LISTINGS.values() for l in text.splitlines()))

# COMMAND ----------

# MAGIC %md
# MAGIC **Filter out Lakebase's own entries.** Here's a surprise: a Lakebase dump includes a few of Lakebase's own platform objects, and restoring those into another project fails. So we list what's in each dump with `pg_restore -l` and comment out (`;`) those lines. It's the same filter the deck uses.

# COMMAND ----------

# DBTITLE 1,Filter Lakebase's own entries out of each dump
"""Write a filtered table of contents per dump: Lakebase's platform entries get a leading ';'."""
PLATFORM = re.compile(r" (cloud_admin|databricks_control_plane)$|__db_system")
TOCS = {}
for db, text in LISTINGS.items():
    lines = text.splitlines()
    TOCS[db] = WORK_DIR / f"{db}.toc"
    TOCS[db].write_text("\n".join((";" + l) if PLATFORM.search(l) else l for l in lines) + "\n")
    print(f"{db}: {len(lines)} entries in the dump, {sum(bool(PLATFORM.search(l)) for l in lines)} commented out")
print(f"\nFor example, in {DB}:")
for l in [l for l in LISTINGS[DB].splitlines() if PLATFORM.search(l)][:6]:
    print("  ", l[:140])
print("   ...")

# COMMAND ----------

# MAGIC %md
# MAGIC **Create the extra databases on the new side.** Every new project starts with `databricks_postgres`, but `pg_restore` restores *into* an existing database, so `reporting` has to exist on new production first.

# COMMAND ----------

# DBTITLE 1,Create the extra databases on new production
"""Create every database besides databricks_postgres on new production, ready for its restore."""
for db in APP_DATABASES:
    if db != DB:
        create_database(NEW_ID, "production", db)
show(query(NEW_ID, "production", "SELECT datname AS database FROM pg_database WHERE NOT datistemplate ORDER BY 1"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Restore each database into new production.** The flags matter:
# MAGIC
# MAGIC * `--no-owner --no-acl`: skip the old side's owners and grants, because those roles don't exist here. We rebuild access in a later step.
# MAGIC * `--single-transaction --exit-on-error`: all or nothing. If anything fails, nothing lands, and you can safely try again.
# MAGIC * `-L`: restore only what's in that database's filtered list.
# MAGIC
# MAGIC > Why not the plain `pg_restore` from the docs? In our tests, it copied every row but still ended in errors. These flags and the filter fix that.
# MAGIC
# MAGIC We also note the time right before the first restore. Module 5 uses it.

# COMMAND ----------

# DBTITLE 1,pg_restore each database into new production
"""Restore each dump into its own database on new production. Databases that already have tables are skipped."""
def has_app_tables(pid, branch, dbname):
    return bool(query(pid, branch, "SELECT count(*) > 0 AS has FROM information_schema.tables "
                                   "WHERE table_schema = 'app'", dbname=dbname)["has"][0])


pending = [db for db in APP_DATABASES if not has_app_tables(NEW_ID, "production", db)]
if not pending:
    print("New production already has every database's tables. Skipping the restore (run Module 7 to start over).")
else:
    RESTORE_STARTED = datetime.now(timezone.utc)
    time.sleep(5)  # keep this timestamp strictly before the restore
    for db in pending:
        rc, secs, err = run_pg("pg_restore", NEW_ID, "production",
                               ["--no-owner", "--no-acl", "--single-transaction", "--exit-on-error",
                                "-L", str(TOCS[db]), "-d", db, str(DUMPS[db])], dbname=db)
        assert rc == 0, f"pg_restore of {db} failed: {err}"
        print(f"{db}: pg_restore exit code 0 in {secs} s")

# COMMAND ----------

# MAGIC %md
# MAGIC **Now prove it.** We compare fingerprints table by table, in every database, then check the watermark and the migration history. Every row's checksum should match.

# COMMAND ----------

# DBTITLE 1,Compare old and new production, database by database
"""Fingerprint every table in every moved database on both sides, then check the watermark and history."""
frames = []
for db in APP_DATABASES:
    merged = fingerprint(OLD_ID, "production", db).merge(
        fingerprint(NEW_ID, "production", db), on="table", how="outer", suffixes=("_old", "_new"))
    frames.append(merged.assign(database=db))
compare = pd.concat(frames, ignore_index=True)
compare["identical"] = (compare.rows_old == compare.rows_new) & (compare.md5_old == compare.md5_new)
show(compare[["database", "table", "rows_old", "rows_new", "identical"]])

new_mark = query(NEW_ID, "production", "SELECT max(order_id) AS newest, count(*) AS orders FROM app.orders").iloc[0]
print(f"Watermark: old {WATERMARK[0]} / {WATERMARK[1]}   new {new_mark.newest} / {new_mark.orders}")
print("Migration history on new production:",
      query(NEW_ID, "production", "SELECT version FROM app.schema_migrations ORDER BY 1")["version"].tolist())
assert compare.identical.all() and new_mark.newest == WATERMARK[0], (
    "The copy doesn't match. If you re-ran earlier cells after the restore, run Module 7 (clean up) and start over.")
print("✅ New production is an exact copy of old production, in every database.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4 (optional): Recreate the synced table on new production
# MAGIC
# MAGIC The synced table refills from the lakehouse table, which already exists here. (In a move between workspaces, that lakehouse table has to exist on the new side too.)
# MAGIC
# MAGIC > **One name, one project.** A synced table's name can only point at one project per metastore, and two workspaces in the same region usually share one. So we delete the old sync first, during the write pause. Then we create the new one with the same name, so the app sees the same table. With separate metastores, like a move across regions or clouds, you could create the new sync before the pause.
# MAGIC
# MAGIC Same as before, the create call returns before the rows land, so we wait. Then we prove it's current: the Delta version it last synced should match the newest version in the Delta table's history.
# MAGIC
# MAGIC > Using a second workspace with its own metastore? Then this step is skipped: the source Delta table would have to be copied over first, and that's its own job.

# COMMAND ----------

# DBTITLE 1,Move the synced table to the new home
"""Delete the old project's sync, create the same synced table on new production, and prove it's current."""
NEW_SYNC = DO_SYNCED_TABLES
if NEW_SYNC and TWO_WORKSPACES and w.metastores.current().metastore_id != w_new.metastores.current().metastore_id:
    NEW_SYNC = False
    print("Skipped: the new home's workspace has its own metastore, so the source Delta table would have to be\n"
          "copied there first, which is a separate job. The old sync keeps running until cleanup.")
elif NEW_SYNC:
    sync_started = time.time()
    w.postgres.delete_synced_table(name=f"synced_tables/{SYNCED_TABLE}").wait()
    print("Removed the old project's sync")
    for attempt in range(10):
        try:
            client(NEW_ID).postgres.create_synced_table(
                synced_table=SyncedTable(spec=SyncedTableSyncedTableSpec(
                    source_table_full_name=SOURCE_TABLE,
                    branch=branch_path(NEW_ID, "production"),
                    postgres_database=DB,
                    primary_key_columns=["product_id"],
                    scheduling_policy=SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy.SNAPSHOT,
                    create_database_objects_if_missing=True)),
                synced_table_id=SYNCED_TABLE).wait()
            break
        except Exception as e:
            if attempt == 9:
                raise
            print("  name still being released, retrying:", str(e)[:120])
            time.sleep(20)
    state, rows, secs = wait_for_sync(NEW_ID, SYNCED_TABLE, f"{UC_SCHEMA}.product_catalog_synced", 50)
    SYNC_SECS = round(time.time() - sync_started)
    synced_version = client(NEW_ID).postgres.get_synced_table(
        name=f"synced_tables/{SYNCED_TABLE}").status.last_sync.delta_table_sync_info.delta_commit_version
    newest_version = spark.sql(f"DESCRIBE HISTORY {SOURCE_TABLE} LIMIT 1").first()["version"]
    print(f"New sync: {rows} rows after {secs} s. Synced Delta version {synced_version}, newest {newest_version}.")
    assert synced_version == newest_version, "The synced table is behind its source"
    print("✅ The synced table on new production is current.")
else:
    print("Skipped (no synced table)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Set up access before the switch
# MAGIC
# MAGIC We restored with `--no-owner --no-acl`, so the new side has **none** of the old access rules. The roles don't even exist, and every table, in both databases, belongs to whoever ran the restore. Let's look:

# COMMAND ----------

# DBTITLE 1,Check access on new production right after the restore
"""Show that app_owner and app_reader don't exist yet, and who owns each table now."""
show(query(NEW_ID, "production",
           "SELECT rolname AS role FROM pg_roles WHERE rolname IN ('app_owner', 'app_reader')"))
OWNERS_SQL = ("SELECT c.relname AS \"table\", pg_get_userbyid(c.relowner) AS owner FROM pg_class c "
              "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'app' AND c.relkind = 'r' ORDER BY 1")
show(pd.concat([query(NEW_ID, "production", OWNERS_SQL, dbname=db).assign(database=db) for db in APP_DATABASES],
               ignore_index=True)[["database", "table", "owner"]])

# COMMAND ----------

# MAGIC %md
# MAGIC So we rebuild it: the same roles, once for the branch, then the same ownership, grants, and default privileges in each database. We do it on production **before** rebuilding the child branches, so they get it too.
# MAGIC
# MAGIC > Moving between workspaces? The identities may be different too. Workspaces in one account can share users and service principals, but another account means different ones. Either way, recreate their Postgres roles in the new project. Passwords never come across, so password-based roles need new ones.

# COMMAND ----------

# DBTITLE 1,Rebuild access on new production
"""Run the same access script on new production, for every database we moved."""
set_up_access(NEW_ID, "production", APP_DATABASES)
show(access_report(NEW_ID, "production", APP_DATABASES))

# COMMAND ----------

# MAGIC %md
# MAGIC ### The verification gate
# MAGIC
# MAGIC Don't switch the app until everything checks out. Once the first write lands on the new side, going back means a reverse move, so this is your last easy exit.

# COMMAND ----------

# DBTITLE 1,Check everything before the switch
"""Run every check, plus an app smoke test inside a transaction that always rolls back."""
def sequences(pid, dbname):
    return dict(query(pid, "production",
                      "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'app'",
                      dbname=dbname).values.tolist())


sequences_match = all(sequences(NEW_ID, db) == sequences(OLD_ID, db) for db in APP_DATABASES)

# The smoke test an app would run: write a test row and read it back, inside a transaction that
# always rolls back. The explicit order_id keeps it from using up a sequence value.
with connect(NEW_ID, "production") as conn:
    with conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO app.orders (order_id, customer_id, amount_cents) VALUES (-1, 1, 100)")
        smoke_ok = conn.execute("SELECT count(*) FROM app.orders WHERE order_id = -1").fetchone()[0] == 1

checks = {
    "Every database identical (rows and checksums)": bool(compare.identical.all()),
    "Watermark matches": int(new_mark.newest) == int(WATERMARK[0]),
    "Sequences carried over": sequences_match,
    "Migration history carried over": query(NEW_ID, "production", "SELECT max(version) AS v FROM app.schema_migrations")["v"][0] == 3,
    "app_reader can read every table": bool(access_report(NEW_ID, "production", APP_DATABASES).app_reader_can_read.all()),
    "Synced table current (or not used)": True if not globals().get("NEW_SYNC") else bool(synced_version == newest_version),
    "App smoke test (write and read)": smoke_ok,
}
show(pd.DataFrame([(k, "✅" if v else "❌") for k, v in checks.items()], columns=["check", "result"]))
assert all(checks.values()), "Don't switch: a check failed"
print("All checks passed. Safe to switch.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Switch the app and resume writes
# MAGIC
# MAGIC For a real app, switching means changing its connection settings. The **host** changes, and for an app that signs in with OAuth, so do the workspace and the endpoint it gets tokens from. Then writes resume on the new side.
# MAGIC
# MAGIC Watch the order IDs: they pick up right after the watermark, because the dump carried the sequence values. The cell also tells you how long writes were paused.

# COMMAND ----------

# DBTITLE 1,Point the app at the new home and place new orders
"""Show both hosts, place five orders on the new home, and report how long writes were paused."""
if TWO_WORKSPACES:
    print("Old workspace:", w.config.host)
    print("New workspace:", w_new.config.host)
print("Old host:", login(OLD_ID, "production")[0])
print("New host:", login(NEW_ID, "production")[0])
with connect(NEW_ID, "production") as conn:
    new_ids = [r[0] for r in conn.execute(
        "INSERT INTO app.orders (customer_id, amount_cents) SELECT 1 + g, 2499 FROM generate_series(1, 5) g "
        "RETURNING order_id").fetchall()]
paused = round(time.time() - PAUSE_STARTED)
print("New orders on the new home:", new_ids, f"(the watermark was {WATERMARK[0]})")
old_newest = query(OLD_ID, "production", "SELECT max(order_id) AS m FROM app.orders")["m"][0]
print(f"Old home's newest order is still {old_newest}. It's stale from here on.")
print(f"\nWrites were paused for {paused} s, from the watermark to the first new order "
      "(if you stopped to read along, that's in there too).")
if DO_SYNCED_TABLES and "SYNC_SECS" in globals():
    print(f"Swapping the synced table took {SYNC_SECS} s of it. With separate metastores, "
          "you'd create the new sync before the pause.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 5: Rebuild the child branches
# MAGIC
# MAGIC The app only talks to production, so this can happen after the switch, with the app already live.
# MAGIC
# MAGIC Here's the catch. The bundle created the new `development` branch back in Module 3, **before** the restore, when production was empty. A branch is a copy as of the moment it's created, and it never picks up later changes. So what's in it?

# COMMAND ----------

# DBTITLE 1,Look inside the dev branch the bundle created before the restore
"""Check whether the new development branch has the app's tables."""
show(query(NEW_ID, "development", "SELECT to_regclass('app.orders') IS NOT NULL AS has_app_tables"))

# COMMAND ----------

# MAGIC %md
# MAGIC **Nothing.** It's still a copy of the empty production. The fix is "delete, redeploy, then migrate": delete the branch, then run `bundle deploy` again. The bundle sees `development` is missing and creates it, this time from the restored production. So it gets everything at once: both databases, the data, the schema, and the access rules we just set up.
# MAGIC
# MAGIC > Only do this with brand-new branches on the **new** side. Deleting a branch deletes whatever is on it.

# COMMAND ----------

# DBTITLE 1,Delete the dev branch, then redeploy to recreate it
"""Delete the empty child, let the bundle recreate it from the restored production, and look at what it got."""
client(NEW_ID).postgres.delete_branch(name=branch_path(NEW_ID, "development"), purge=True).wait()
print("Deleted the empty development branch\n")
rc, out = cli("bundle", "deploy")
print(f"$ databricks bundle deploy\n{out}\n")
assert rc == 0, "bundle deploy failed"
show(query(NEW_ID, "development",
           "SELECT (SELECT count(*) FROM app.orders) AS orders, "
           "(SELECT max(version) FROM app.schema_migrations) AS migrated_to, "
           "has_table_privilege('app_reader', 'app.orders', 'SELECT') AS app_reader_can_read"))
show(query(NEW_ID, "development", "SELECT count(*) AS stock_rows FROM app.stock", dbname=REPORTING_DB))

# COMMAND ----------

# MAGIC %md
# MAGIC The rebuilt branch matches **today's** production, so it doesn't have dev's own work yet. We bring that back in two parts:
# MAGIC
# MAGIC 1. **Schema:** replay dev's unreleased migration, V4, with the migration tool.
# MAGIC 2. **Data:**
# MAGIC    * Tables that exist **only** on dev, like `feature_flags`, come across with a **data-only** dump of just those tables.
# MAGIC    * Changes dev made to tables production also has, like the `DEV-TEST-50` coupon and the three orders that use it, get **reconciled** on purpose.
# MAGIC
# MAGIC Why not just dump all of dev, data only? That dump includes production's rows too, so it collides with the rows the rebuilt branch already has. The optional cell after this one shows it failing.

# COMMAND ----------

# DBTITLE 1,Bring back dev's own work: V4, its own table, and its changed rows
"""Bring dev's own work to the rebuilt branch: its migration, its dev-only table, and its changes to shared rows."""
print("Migrations on new development:", migrate(NEW_ID, "development", up_to=4))

# Dev-only table: a data-only dump of just that table, restored after the migration created it.
flags_there = query(NEW_ID, "development", "SELECT count(*) AS n FROM app.feature_flags")["n"][0]
if flags_there:
    print(f"New development already has {flags_there} feature flags, so we skip the copy.")
else:
    FLAGS = WORK_DIR / "dev_flags.dump"
    rc, secs, err = run_pg("pg_dump", OLD_ID, "development", ["-Fc", "--data-only", "-t", "app.feature_flags", "-f", str(FLAGS)])
    print(f"Dumped dev's feature flags: exit {rc}")
    rc, secs, err = run_pg("pg_restore", NEW_ID, "development",
                           ["--data-only", "--no-owner", "--no-acl", "--single-transaction", "--exit-on-error", "-d", DB, str(FLAGS)])
    print(f"Restored them into new development: exit {rc}" + ("" if rc == 0 else f" ({err})"))

# Shared tables: find what dev changed relative to production, and apply exactly that.
dev_coupons = query(OLD_ID, "development", "SELECT code, percent_off FROM app.coupons")
prod_codes = set(query(OLD_ID, "production", "SELECT code FROM app.coupons")["code"])
dev_only = dev_coupons[~dev_coupons.code.isin(prod_codes)]
dev_orders = query(OLD_ID, "development", "SELECT order_id, coupon_code FROM app.orders WHERE coupon_code = ANY(%s)",
                   (dev_only.code.tolist(),))
with connect(NEW_ID, "development") as conn:
    with conn.transaction():
        for code, pct in dev_only.values.tolist():
            conn.execute("INSERT INTO app.coupons VALUES (%s, %s) ON CONFLICT DO NOTHING", (code, int(pct)))
        for order_id, code in dev_orders.values.tolist():
            conn.execute("UPDATE app.orders SET coupon_code = %s WHERE order_id = %s", (code, int(order_id)))
print(f"Reconciled {len(dev_only)} dev-only coupon(s) and {len(dev_orders)} order update(s)")

show(query(NEW_ID, "development",
           "SELECT (SELECT string_agg(code, ', ' ORDER BY code) FROM app.coupons) AS coupons, "
           "(SELECT count(*) FROM app.feature_flags) AS feature_flags, "
           "(SELECT count(*) FROM app.orders WHERE coupon_code = 'DEV-TEST-50') AS orders_on_dev_coupon, "
           "has_table_privilege('app_reader', 'app.feature_flags', 'SELECT') AS app_reader_can_read_flags"))

# COMMAND ----------

# MAGIC %md
# MAGIC Now development has dev's own work **plus** today's production data, including `FALL10` and the orders placed after the switch. That's usually what you want for a dev branch.
# MAGIC
# MAGIC **Optional:** watch the "just dump all of dev" shortcut fail. Thanks to `--single-transaction`, nothing changes when it does.

# COMMAND ----------

# DBTITLE 1,(Optional) The shortcut that fails: dump all of dev
"""Try a data-only dump of dev's whole app schema into the rebuilt branch. It's expected to fail on duplicate keys."""
FULL_DEV = WORK_DIR / "dev_full_data.dump"
run_pg("pg_dump", OLD_ID, "development", ["-Fc", "--data-only", "-n", "app", "-f", str(FULL_DEV)])
rc, secs, err = run_pg("pg_restore", NEW_ID, "development",
                       ["--data-only", "--no-owner", "--no-acl", "--single-transaction", "--exit-on-error", "-d", DB, str(FULL_DEV)])
print("pg_restore exit code:", rc)
print("Error:", next((l for l in err.splitlines() if "duplicate key" in l or "ERROR" in l), err[:200]))
print("New development still has", query(NEW_ID, "development", "SELECT count(*) AS n FROM app.customers")["n"][0],
      "customers: the failed restore changed nothing.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 5: What doesn't come along
# MAGIC
# MAGIC A move carries **just the data**. Each project keeps its own point-in-time history and its own snapshots, and you can't use them from another project.
# MAGIC
# MAGIC ### Point-in-time history starts over
# MAGIC
# MAGIC Let's ask the new home for production as it was **just before the restore**:
# MAGIC
# MAGIC 📖 Learn more: [Point-in-time restore](https://docs.databricks.com/aws/en/oltp/projects/point-in-time-restore) ·
# MAGIC [Snapshots](https://docs.databricks.com/aws/en/oltp/projects/snapshots)

# COMMAND ----------

# DBTITLE 1,Try to restore the new home to before the move
"""Create a point-in-time branch of new production as of just before the restore, look inside, and delete it."""
try:
    RESTORE_STARTED
except NameError:
    raise RuntimeError("Run the restore cell in Module 4 first")

client(NEW_ID).postgres.create_branch(
    parent=project_path(NEW_ID),
    branch=Branch(spec=BranchSpec(source_branch=branch_path(NEW_ID, "production"),
                                  source_branch_time=Timestamp(seconds=int(RESTORE_STARTED.timestamp())),
                                  ttl=Duration(seconds=86400))),
    branch_id="before-the-move",
).wait()
show(query(NEW_ID, "before-the-move", "SELECT to_regclass('app.orders') IS NOT NULL AS has_app_tables"))
client(NEW_ID).postgres.delete_branch(name=branch_path(NEW_ID, "before-the-move"), purge=True).wait()
print("(Deleted the before-the-move branch again.)")

# COMMAND ----------

# MAGIC %md
# MAGIC **Empty.** The new project's history only goes back to the move. Anything older lives in the **old** project's history, and only for its restore window (7 days by default, up to 30). So keep the old project around for at least one restore window after you switch.
# MAGIC
# MAGIC ### Snapshots stay behind too
# MAGIC
# MAGIC A snapshot is a saved copy of a branch that you can restore later. Let's take one on old production and try to restore it in the new home.

# COMMAND ----------

# DBTITLE 1,Snapshot old production, then try to restore it in the new home
"""Snapshot old production, then ask the new project for a branch from that snapshot. It's expected to fail."""
try:
    for attempt in range(3):  # snapshot creation can fail once in a while; try again before giving up
        try:
            client(OLD_ID).postgres.create_snapshot(
                parent=project_path(OLD_ID),
                snapshot=Snapshot(spec=SnapshotSpec(source_branch=branch_path(OLD_ID, "production"), ttl=Duration(seconds=86400))),
                snapshot_id="before-the-move",
            ).wait()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(15)
    snapshot = f"{project_path(OLD_ID)}/snapshots/before-the-move"
    print("Created snapshot:", snapshot)
    try:
        client(NEW_ID).postgres.create_branch(
            parent=project_path(NEW_ID),
            branch=Branch(spec=BranchSpec(source_snapshot=snapshot, no_expiry=True)),
            branch_id="from-old-snapshot",
        ).wait()
        print("Unexpected: the branch was created")
    except Exception as e:
        print("Rejected, as expected:")
        print("  ", str(e)[:300])
    client(OLD_ID).postgres.delete_snapshot(name=snapshot).wait()
except Exception as e:
    print("Couldn't create a snapshot here, so skipping this demo:", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC Same as branches: a snapshot can only be restored inside its own project. On the new side, set the restore window and a snapshot schedule again. They're settings, not data. (The bundle already set the restore window.)
# MAGIC
# MAGIC ## What you did
# MAGIC
# MAGIC * **Promoted** a change with a migration, and no data crossed over.
# MAGIC * **Built** the new home with `databricks bundle deploy`, and saw why a branch can't just move.
# MAGIC * **Moved** production with one `pg_dump` and one filtered `pg_restore` per database, and proved every copy exact with checksums.
# MAGIC * **Recreated** the synced table on the new side instead of copying it.
# MAGIC * **Rebuilt** access: roles once per branch, ownership and grants in each database.
# MAGIC * **Passed** the verification gate, switched the app, and resumed writes.
# MAGIC * **Rebuilt** the dev branch with "delete, redeploy", then brought back its own work: a migration, a dev-only table, and its changed rows.
# MAGIC * **Saw** that point-in-time history and snapshots stay with the old project.
# MAGIC
# MAGIC That's the whole playbook, end to end.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 6: Doing it for real
# MAGIC
# MAGIC This lab moved one small environment in a few minutes. Here's the same job as a checklist for a real one, plus what to add around the steps you just ran.
# MAGIC
# MAGIC **Before the day**
# MAGIC
# MAGIC * **Decide what data has to move,** per project, then per branch and database. Usually it's only production's. Dev and test data stay behind, and child branches get rebuilt from the new production.
# MAGIC * **Put it all in Git:** the bundle (with `lifecycle.prevent_destroy` on the project and production), the migrations, and the app's settings.
# MAGIC * **List every database** on each branch you're moving. Each one gets its own dump and restore, and any database besides `databricks_postgres` needs a `CREATE DATABASE` on the new side first.
# MAGIC * **Map identities.** Workspaces in one account can share users and service principals; another account means new ones. Either way, recreate their Postgres roles in the new project. Password roles get new passwords, and OAuth apps need the new workspace and endpoint.
# MAGIC * **Check synced tables.** Their source tables have to exist on the new side. If both workspaces share a metastore, plan to remove the old sync during the pause, like this lab did.
# MAGIC * **Check versions.** The `pg_dump` client has to be the same version as the source's Postgres, or newer. Need a newer major version? Create the new project on it. Lakebase doesn't upgrade a project's major version in place.
# MAGIC * **Get sign-off before you pause.** Waiting on an approval during the pause just makes the pause longer.
# MAGIC
# MAGIC **On the day**
# MAGIC
# MAGIC 1. **Stop every writer:** the app, jobs, scripts, and any app on a child branch. Make sure nothing is mid-transaction, then take a watermark.
# MAGIC 2. **Dump and restore each database:** filter out Lakebase's platform entries, and restore with `--no-owner --no-acl --single-transaction --exit-on-error`.
# MAGIC 3. **Check it:** row counts and checksums, the watermark, sequences, and migration history.
# MAGIC 4. **Recreate synced tables** and let them fill.
# MAGIC 5. **Rebuild access:** roles, ownership, grants, and default privileges.
# MAGIC 6. **Run the gate, switch the app, and resume writes.** Before the first new write, going back is just pointing the app back, after recreating any old sync you removed during the pause. After it, going back is a reverse move.
# MAGIC 7. **Rebuild the child branches** from the new production (delete, redeploy), then bring back each one's own work.
# MAGIC
# MAGIC **After**
# MAGIC
# MAGIC * **Keep the old project for at least one restore window** (7 days by default, up to 30). Its point-in-time history and snapshots are your only way back to before the move.
# MAGIC * **Set the restore window and the snapshot schedule** on the new project. They're settings, so they don't come along.
# MAGIC
# MAGIC 📖 Learn more: [pg_dump and pg_restore](https://docs.databricks.com/aws/en/oltp/projects/pg-dump-restore) ·
# MAGIC [Postgres version support](https://docs.databricks.com/aws/en/oltp/projects/postgres-version-support) ·
# MAGIC [Manage projects](https://docs.databricks.com/aws/en/oltp/projects/manage-projects)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 7: Clean up
# MAGIC
# MAGIC Lakebase bills for compute (close to zero when idle) and for storage, so let's delete what the lab created. The new home came from a bundle, so we tear it down the bundle way, and that gives us one last lesson.
# MAGIC
# MAGIC ### Step 1: Try to destroy the new home
# MAGIC
# MAGIC Remember `prevent_destroy` in the bundle file? Let's run `databricks bundle destroy` with it still there.

# COMMAND ----------

# DBTITLE 1,Step 1: try bundle destroy with the guard in place
"""Run bundle destroy while prevent_destroy is in the file. It should refuse, and nothing gets deleted."""
if "write_bundle" not in globals():
    print("The bundle wasn't deployed in this session, so there's nothing to try. Go on to the next cell.")
else:
    write_bundle(guard=True)  # make sure the guard is in the file for this demo
    rc, out = cli("bundle", "destroy", "--auto-approve")
    print(f"$ databricks bundle destroy --auto-approve   (exit code {rc})\n{out}\n")
    print("The new home still exists:", project_exists(NEW_ID))

# COMMAND ----------

# MAGIC %md
# MAGIC **Refused.** That's the guard doing its job: nobody deletes production with a stray command. To really delete it, someone has to take the guard out of the file first. In real life, that's a change someone reviews in Git.
# MAGIC
# MAGIC ### Step 2: Remove the guard and delete everything
# MAGIC
# MAGIC This cell takes `prevent_destroy` out of the bundle file, redeploys, and runs `bundle destroy` for real. The bundle sets `purge_on_delete`, so the project is deleted right away and its name is free for your next run. Then it deletes everything the bundle never owned: the old home, the synced table, the Unity Catalog schema, and the local files. With a second workspace, it cleans up both, and deletes the secret scope that holds your token. (The token keeps working until it expires, so revoke it in that workspace if you're done.) It's destructive, so it only runs while `CONFIRM_TEARDOWN = True`.

# COMMAND ----------

# DBTITLE 1,Step 2: remove the guard and delete everything
"""Delete everything the lab created: the synced table, the new home (with the bundle), the old home,
the Unity Catalog schema, the bundle's workspace folder, and the local files."""
CONFIRM_TEARDOWN = True

if not CONFIRM_TEARDOWN:
    print("Teardown skipped. Set CONFIRM_TEARDOWN = True to delete the lab's projects.")
else:
    try:
        w.postgres.delete_synced_table(name=f"synced_tables/{SYNCED_TABLE}").wait()
        print("Deleted the synced table")
    except Exception:
        print("No synced table to delete")
    if "write_bundle" in globals():
        write_bundle(guard=False)  # the reviewed change: no more prevent_destroy
        for args in (["bundle", "deploy"], ["bundle", "destroy", "--auto-approve"]):
            rc, out = cli(*args)
            print(f"\n$ databricks {' '.join(args)}   (exit code {rc})\n{out}")
    for pid in (NEW_ID, OLD_ID):  # the old home was never in the bundle
        if project_exists(pid):
            client(pid).postgres.delete_project(name=project_path(pid), purge=True).wait()
            print("\nDeleted project", pid)
    try:
        spark.sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{UC_SCHEMA} CASCADE")  # only this lab's own schema
        print("Dropped schema", f"{CATALOG}.{UC_SCHEMA} (if it existed)")
    except Exception as e:
        if "NOT_FOUND" in str(e) or "NO_SUCH" in str(e):
            print("No lab schema to drop")
        else:
            print("Couldn't drop the lab schema:", str(e)[:120])
    try:
        w_new.workspace.delete(BUNDLE_ROOT, recursive=True)  # only this lab's bundle folder
    except Exception:
        pass
    if NEW_WORKSPACE_SECRETS:
        try:
            w.secrets.delete_scope(scope=NEW_WORKSPACE_SECRETS)  # the scope Choose your setup made for your token
            print(f"Deleted secret scope {NEW_WORKSPACE_SECRETS}. The token keeps working until it expires, "
                  "so revoke it in the other workspace if you're done with it.")
        except Exception:
            print(f"Couldn't delete secret scope {NEW_WORKSPACE_SECRETS}; delete it yourself if you're done with it.")
    for folder in (WORK_DIR, BUNDLE_DIR):
        shutil.rmtree(folder, ignore_errors=True)
    print("Done.")

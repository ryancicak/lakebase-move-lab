# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC <!-- Copyright 2026 Databricks, Inc. SPDX-License-Identifier: Apache-2.0 -->
# MAGIC # Lakebase Move Lab
# MAGIC
# MAGIC Release coupons without bringing dev's test orders into production. Then move the app to a new home, with production's customers, orders, and stock data.
# MAGIC
# MAGIC Lakebase is managed Postgres in Databricks. You'll create two small projects, an **old home** and a **new home**, here in this workspace. SQL stands in for the ordering app; the database operations are real. There's no separate app or CI/CD pipeline to install.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Before you start
# MAGIC
# MAGIC * Select **Serverless** in this notebook's compute dropdown. A SQL warehouse is a different kind of compute.
# MAGIC * Open the grid icon at the top right. You need **Lakebase Postgres** there and permission to create projects. Use a workspace where you're allowed to create lab resources.
# MAGIC * For your first run, use **Shift+Enter** to run one cell and move to the next. Read the short explanation above each cell; you can skim the helper code. **Run all** also works and takes a few minutes.
# MAGIC
# MAGIC **Run all includes cleanup.** To look at a project in Lakebase, open its link when you reach the first checkpoint. Don't change the setup boxes once the lab has started.
# MAGIC
# MAGIC If a run stops, follow **Module 7: Clean up** before trying again. Don't click Run all to recover a stopped run.
# MAGIC
# MAGIC ### Setup (the defaults are fine)
# MAGIC
# MAGIC Run the next cell. Three boxes appear at the top:
# MAGIC
# MAGIC * **1. New home goes to:** leave **This workspace**.
# MAGIC * **2. Other workspace URL:** leave it empty.
# MAGIC * **3. Catalog:** leave `main`. This is only for the optional exercise that copies product data from the lakehouse into Lakebase.
# MAGIC
# MAGIC If you can't create a schema in `main`, that exercise skips and the rest still works. Already have a catalog you can use? Put its name in box 3 before starting. Save the second-workspace option for another run.

# COMMAND ----------

# DBTITLE 1,Choose your setup (defaults are fine)
"""Put the setup questions at the top of the notebook, and sign you in to the other workspace if you pick one.

For another workspace, its URL and your token go in a secret scope of your own, lb-move-lab-<you>-<your user id>.
The token is asked for in a hidden box. It's never shown, and it's never saved in the notebook.
"""
import getpass
import re
from urllib.parse import urlsplit

from databricks.sdk import WorkspaceClient

THIS, OTHER = "This workspace", "Another workspace"
dbutils.widgets.dropdown("where", THIS, [THIS, OTHER], "1. New home goes to")
dbutils.widgets.text("other_url", "", "2. Other workspace URL (leave empty)")
dbutils.widgets.text("catalog", "main", "3. Catalog for optional synced table")

w = WorkspaceClient()
me = w.current_user.me()
slug = re.sub(r"[^a-z0-9]+", "-", me.user_name.split("@")[0].lower()).strip("-")[:16].rstrip("-") or "user"
scope = f"lb-move-lab-{slug}-{me.id}"  # your user id keeps it yours, even when user names start alike


def workspace_url(value):
    """Use the workspace's HTTPS host, even when someone pastes a link to a page inside it."""
    parsed = urlsplit(value if "://" in value else "https://" + value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port
            or host.startswith("accounts.")
            or not host.endswith((".cloud.databricks.com", ".azuredatabricks.net", ".gcp.databricks.com"))):
        raise ValueError("Use your Databricks workspace URL, starting with https://. "
                         "Don't use an account-console address or a link to another site.")
    return f"https://{host}"


# A box change can run this cell before the helpers cell. Stop before changing the saved destination.
if globals().get("LAB_CREATED") and (
        dbutils.widgets.get("where") != WHERE
        or (WHERE == OTHER and dbutils.widgets.get("other_url").strip().rstrip("/") != OTHER_URL)):
    raise RuntimeError("The lab has already started with a different workspace choice. Change the box back "
                       "to keep going. To use a new workspace, clean up in Module 7 first.")


def ask_for_token(prompt):
    """A hidden box for the token. A job can't answer it, so then it says how to store the token instead."""
    try:
        token = getpass.getpass(prompt).strip()
    except Exception:
        raise RuntimeError("No working token for the other workspace yet. Run this cell yourself once, or store "
                           f"one with the Databricks CLI: databricks secrets put-secret {scope} token") from None
    if not token:
        raise ValueError("The token box was empty. Copy a personal access token from the other workspace, "
                         "then run this cell again and paste it into the hidden box.")
    return token


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
    url = workspace_url(url)
    if scope not in {s.name for s in w.secrets.list_scopes()}:
        w.secrets.create_scope(scope=scope)
    stored = {s.key for s in w.secrets.list_secrets(scope=scope)}
    if "host" in stored and workspace_url(dbutils.secrets.get(scope, "host")) != url:
        raise RuntimeError("This secret scope already points to a different workspace. Clean up the earlier lab "
                           "with its original settings in Module 7 first. If you only ran preflight, delete the "
                           f"scope: databricks secrets delete-scope {scope}")
    w.secrets.put_secret(scope=scope, key="host", string_value=url)
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
    print("✅ Both homes stay in this workspace. Nothing else to set up.")
print("   Catalog for the synced-table steps:", dbutils.widgets.get("catalog").strip() or "main")
print("\nFor your first run, press Shift+Enter and go cell by cell.")
print("Run all works too, and deletes the lab resources at the end.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 0: Set up your tools
# MAGIC
# MAGIC ### Install the Python libraries
# MAGIC
# MAGIC These libraries let the notebook create Lakebase resources and talk to Postgres. Run the install cell, then the restart cell.
# MAGIC
# MAGIC The restart note and orange **Core Python package version(s) changed** box are expected. On older serverless versions, you may also see a `protobuf` conflict note from a preinstalled package this lab doesn't use.

# COMMAND ----------

# MAGIC %pip install --quiet -U "databricks-sdk==0.146.0" "psycopg==3.3.6" "protobuf<6"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Confirm Lakebase is available here
"""Fail fast if this workspace can't list Lakebase projects, before the downloads."""
from databricks.sdk import WorkspaceClient

try:
    _probe = WorkspaceClient()
    _visible = sum(1 for _ in _probe.postgres.list_projects())
except Exception as e:
    raise RuntimeError(
        "This workspace doesn't look like it can use Lakebase yet. Open the product switcher (grid, top right) "
        "and check for Lakebase Postgres. If it's missing, or you don't have permission to create projects, "
        "stop here. Later cells will fail the same way. "
        f"({type(e).__name__}: {' '.join(str(e).split())[:200]})"
    ) from None
print(f"Lakebase API answered as {_probe.current_user.me().user_name} ({_visible} project(s) visible).")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install `pg_dump` and `pg_restore`
# MAGIC
# MAGIC `pg_dump` saves a database to a file. `pg_restore` loads that file into another database. We'll use them for the move, not for the coupon release.
# MAGIC
# MAGIC Serverless doesn't include these tools, so this cell downloads and unpacks them. No admin rights needed. It should print a version number for each tool.

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
import time
import urllib.request
from pathlib import Path

PG_VERSION = 17  # the Postgres version for both projects; the client must match or be newer


def download(url):
    """Read a file from the internet, and try again if the connection drops partway."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Couldn't download {url} ({type(e).__name__}: {e}). Check that serverless "
                                   "compute can reach apt.postgresql.org, then run this cell again.") from None
            time.sleep(5)


def install_pg_client(version: int = PG_VERSION):
    """Fetch postgresql-client-<version> and libpq5 from apt.postgresql.org and unpack them locally.

    Returns the folder with the binaries and the folder with libpq.
    """
    os_release = dict(line.strip().split("=", 1) for line in open("/etc/os-release") if "=" in line)
    codename = os_release["VERSION_CODENAME"].strip('"')  # for example "noble"
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    repo = "https://apt.postgresql.org/pub/repos/apt"

    # The package index lists the file for every package; pick the two we need.
    index = gzip.decompress(download(f"{repo}/dists/{codename}-pgdg/main/binary-{arch}/Packages.gz")).decode()
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
        deb.write_bytes(download(f"{repo}/{filename}"))
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
# MAGIC We'll describe the new project in a configuration file called a **bundle**, then ask Databricks to build it. The CLI is the command-line tool that runs that request.
# MAGIC
# MAGIC This cell downloads it and prints its version. It uses your notebook's sign-in, so there's no CLI login to set up.

# COMMAND ----------

# DBTITLE 1,Download the Databricks CLI
"""Download the Databricks CLI for this machine's CPU type and unpack the single binary into a temp folder."""
import io
import platform
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

CLI_VERSION = "1.17.0"  # the CLI version this lab was tested with
arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
url = f"https://github.com/databricks/cli/releases/download/v{CLI_VERSION}/databricks_cli_{CLI_VERSION}_linux_{arch}.zip"
CLI_DIR = Path(tempfile.mkdtemp(prefix="dbcli-"))
for attempt in range(3):  # a download from GitHub sometimes drops partway, so try again
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            archive = response.read()
        break
    except Exception as e:
        if attempt == 2:
            raise RuntimeError(f"Couldn't download the CLI from GitHub ({type(e).__name__}: {e}). Check that "
                               "serverless compute can reach github.com, then run this cell again.") from None
        time.sleep(5)
with zipfile.ZipFile(io.BytesIO(archive)) as z:
    z.extract("databricks", CLI_DIR)
CLI = CLI_DIR / "databricks"
CLI.chmod(0o755)
print(subprocess.run([str(CLI), "--version"], capture_output=True, text=True).stdout.strip())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Connect, name things, and set up helpers
# MAGIC
# MAGIC This cell gives the projects names that are unique to you and defines the functions we'll use later. You don't have to read all of it to follow the lab.
# MAGIC
# MAGIC Before moving on, check **Signed in as**, **Old home**, and **New home** in the output. On this first run, both homes should list the workspace you're in. The notebook gets a fresh, short-lived Postgres login token for each connection; you don't need to manage one.

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
from urllib.parse import urlsplit

import pandas as pd

# Databricks runs this cell on its own when a box at the top changes, even before the cells above have run.
if "PG_LIB" not in globals() or "CLI" not in globals():
    raise RuntimeError("This cell needs the tools from the cells above, and they haven't run in this session yet. "
                       "Run from the top through Module 0. If you're cleaning up, skip Modules 1 through 6 "
                       "and run Module 7. Otherwise, continue cell by cell.")

# psycopg's pure-Python mode finds libpq by asking ctypes for "pq". Answer with the copy we unpacked.
os.environ["PSYCOPG_IMPL"] = "python"
_find_library = ctypes.util.find_library
ctypes.util.find_library = lambda name: str(PG_LIB / "libpq.so.5") if name == "pq" else _find_library(name)
try:
    import psycopg
finally:
    ctypes.util.find_library = _find_library

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
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


# Databricks runs this cell again when a box at the top changes. Once the lab has made something, a change that
# would lose track of it is refused: the new home's workspace, or the catalog the lab's schema is in.
if globals().get("LAB_CREATED") and (answer("where", "") != WHERE or
                                     (WHERE == "Another workspace"
                                      and answer("other_url", "").rstrip("/") != OTHER_URL) or
                                     (LAB_SCHEMA in LAB_CREATED and answer("catalog", "main") != CATALOG)):
    raise RuntimeError("A box at the top changed after the lab started using it. To keep going, change it back. "
                       "To use the new answer, run Module 7 (Clean up), then click Run all.")

# From Choose your setup. For another workspace, its URL and your credentials there are in a secret scope
# of your own: "host", plus "token", or "client-id" and "client-secret" for a service principal.
WHERE = answer("where", "")
OTHER_URL = answer("other_url", "").rstrip("/")
NEW_WORKSPACE_SECRETS = f"lb-move-lab-{slug}-{me.id}" if WHERE == "Another workspace" else None


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
    url = OTHER_URL if "://" in OTHER_URL else "https://" + OTHER_URL
    if host.rstrip("/") != f"https://{urlsplit(url).hostname}":
        raise RuntimeError("The saved workspace address doesn't match box 2. Put the original address back "
                           "and clean up in Module 7 before choosing another workspace.")
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
OLD_LABEL, NEW_LABEL = "Lakebase move lab: old home", "Lakebase move lab: new home"  # marks the projects the lab makes
LAB_CREATED = globals().get("LAB_CREATED", set())  # what this session made; re-runs reuse it, nothing older
DB = "databricks_postgres"  # the default database in every Lakebase project
REPORTING_DB = "reporting"  # a second database the app uses (Module 1, Step 3)

# The bundle that builds the new home (Module 3). The CLI keeps its deployment state under your home folder.
BUNDLE_NAME = "lb-move-lab"
BUNDLE_DIR = globals().get("BUNDLE_DIR") or Path(tempfile.mkdtemp(prefix="lb_move_bundle_"))  # like a Git checkout
BUNDLE_ROOT = f"/Workspace/Users/{NEW_USER}/.bundle/{BUNDLE_NAME}"  # in the new home's workspace

# Optional synced-table steps (Module 1, Step 6 and Module 4's sync rebuild).
DO_SYNCED_TABLES = True
CATALOG = answer("catalog", "main")  # from Choose your setup: a catalog where you can create a schema
UC_SCHEMA = f"lb_move_{slug.replace('-', '_')}_{me.id}"  # your user id keeps it yours
LAB_SCHEMA = f"{CATALOG}.{UC_SCHEMA}"  # the lab's own Unity Catalog schema; Module 7 drops it
SOURCE_TABLE = f"{LAB_SCHEMA}.product_catalog"  # a lakehouse (Delta) table
SYNCED_TABLE = f"{LAB_SCHEMA}.product_catalog_synced"  # its copy inside Lakebase

WORK_DIR = globals().get("WORK_DIR") or Path(tempfile.mkdtemp(prefix="lb_move_"))  # dump files for this session

# Say now if the optional synced-table steps will skip, instead of waiting until Module 1 Step 6.
if DO_SYNCED_TABLES:
    try:
        if not spark.sql(f"SHOW SCHEMAS IN {CATALOG} LIKE '{UC_SCHEMA}'").count():
            spark.sql(f"CREATE SCHEMA {LAB_SCHEMA}")
            spark.sql(f"DROP SCHEMA {LAB_SCHEMA} CASCADE")
        print(f"Synced-table steps will use catalog {CATALOG}.")
    except Exception as e:
        reason = " ".join(str(e).split("JVM stacktrace")[0].split())
        if any(s in reason for s in ("PERMISSION_DENIED", "NO_SUCH_CATALOG", "CATALOG_NOT_FOUND")):
            DO_SYNCED_TABLES = False
            print(f"Synced-table steps will skip: {reason[:220]}")
            print("The rest of the lab still runs. To include them, put a catalog you own in box 3, then click Run all.")
        else:
            print("Couldn't probe the catalog for synced tables yet:", reason[:220])


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


def claim(pid, label):
    """Stop if a project with this name exists but wasn't made in this session.

    A leftover from an earlier run, or someone else's project with the same name, is never reused,
    so the lab's cleanup only ever deletes what the lab made.
    """
    if pid in LAB_CREATED or not project_exists(pid):
        return
    found = client(pid).postgres.get_project(name=project_path(pid)).status.display_name
    if found == label:
        raise RuntimeError(f"Project {pid} is left over from an earlier run of this lab. Do not click Run all: "
                           "that hits this error again and never reaches cleanup. Scroll to Module 7 and run its "
                           "two cells. If Python restarted, run from the top through Module 0 only, skip Modules "
                           "1–6, then Module 7.")
    raise RuntimeError(f"A project named {pid} already exists, and this lab didn't make it (it's called {found!r}). "
                       "Delete or rename it, then start again.")


def create_project(pid, label):
    """Create a Postgres project, or reuse the one this session made. It comes with a production branch and its compute."""
    claim(pid, label)
    if pid in LAB_CREATED and project_exists(pid):
        print(f"Reusing project {pid}, made earlier in this session")
        return
    try:
        client(pid).postgres.create_project(
            project=Project(spec=ProjectSpec(display_name=label, pg_version=PG_VERSION)), project_id=pid
        ).wait()
        print(f"Created project {pid} (Postgres {PG_VERSION})")
    finally:
        if project_exists(pid):
            found = client(pid).postgres.get_project(name=project_path(pid)).status.display_name
            if found == label:  # so a retry after a half-finished create can reuse it
                LAB_CREATED.add(pid)


def create_branch(pid, branch, source="production"):
    """Create a child branch from another branch in the SAME project (or reuse it)."""
    try:
        client(pid).postgres.get_branch(name=branch_path(pid, branch))
        print(f"Branch {branch} already exists in {pid}")
        return
    except NotFound:
        pass
    except Exception as e:
        if "RESOURCE_DOES_NOT_EXIST" not in str(e) and "NOT_FOUND" not in str(e).upper():
            raise
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


ROUTES = {}  # a new-home compute's host -> its public IP if the normal route was refused, else None


def public_address(host):
    """A compute's public IP, from public DNS."""
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
    """Open a Postgres connection to one database on a branch. Retries while the compute wakes up.

    For a compute in another workspace, the normal route comes first. In testing (serverless in an AWS workspace,
    computes in an Azure one), Lakebase hostnames resolved to a Databricks proxy that either refused them with
    "External authorization failed" or presented a certificate for the wrong hostname. On either error, the lab
    tries that compute's public address, with the same hostname and certificate verification.
    """
    host, token = login(pid, branch)
    elsewhere = TWO_WORKSPACES and pid == NEW_ID
    attempt = 0
    while attempt < 6:
        try:
            conn = psycopg.connect(host=host, dbname=dbname, user=pg_user(pid), password=token,
                                   sslmode="verify-full", sslrootcert="system", connect_timeout=30, autocommit=True,
                                   **({"hostaddr": ROUTES[host]} if ROUTES.get(host) else {}))
            if elsewhere:
                ROUTES.setdefault(host, None)
            return conn
        except psycopg.OperationalError as e:
            message = str(e)
            route_refused = "External authorization failed" in message or (
                "server certificate for" in message and "does not match host name" in message)
            if elsewhere and host not in ROUTES and route_refused:
                ROUTES[host] = public_address(host)
                print("(The normal route to a new-home compute was refused, so the lab uses its public address.)")
                continue  # changing routes gets its own attempt, even on the last retry
            attempt += 1
            if attempt == 6:
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
    if TWO_WORKSPACES and pid == NEW_ID and host not in ROUTES:
        connect(pid, branch, dbname).close()  # finds out which route this compute needs
    env = dict(PG_ENV, PGHOST=host, PGPORT="5432", PGUSER=pg_user(pid), PGPASSWORD=token,
               PGDATABASE=dbname, PGSSLMODE="verify-full", PGSSLROOTCERT="system", PGCONNECT_TIMEOUT="30")
    if ROUTES.get(host):
        env["PGHOSTADDR"] = ROUTES[host]  # TCP to this IP; hostname in PGHOST is still verified
    started = time.time()
    result = subprocess.run([str(PG_BIN / tool), *args], env=env, capture_output=True, text=True, timeout=600)
    return result.returncode, round(time.time() - started, 1), result.stderr.strip()


def cli(*args, cwd=BUNDLE_DIR):
    """Run the Databricks CLI as you, against the new home's workspace. Its token is never printed."""
    auth = w_new.config.authenticate().get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise RuntimeError("Couldn't get a token for the CLI from this notebook's sign-in")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(CLI_DIR),
           "DATABRICKS_HOST": w_new.config.host, "DATABRICKS_TOKEN": auth.split(" ", 1)[1]}
    result = subprocess.run([str(CLI), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=900)
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
    create belongs to it and picks up its default grants.
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
# MAGIC ### Step 1: Create the old project
# MAGIC
# MAGIC A **project** holds your Lakebase branches. Creating one gives you a `production` branch and a **compute**, which runs Postgres and provides the address you connect to. Let's create it.

# COMMAND ----------

# DBTITLE 1,Create the old home's project
"""Create (or reuse) the old home's project, wait for its production compute to get a host, and link to it in Lakebase."""
create_project(OLD_ID, OLD_LABEL)
print("Production compute:", endpoint_of(OLD_ID, "production")[1])
# The Lakebase UI finds a project by its uid, not its name.
project_uid = client(OLD_ID).postgres.get_project(name=project_path(OLD_ID)).uid
print("See it in Lakebase Postgres:", f"{client(OLD_ID).config.host.rstrip('/')}/lakebase/projects/{project_uid}")

# COMMAND ----------

# MAGIC %md
# MAGIC Open **See it in Lakebase Postgres** above in another tab. You should see your project and its `production` branch. The host in the output is the address an app would connect to.
# MAGIC
# MAGIC Come back here to add the app's tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2: Create the app's tables and data on production
# MAGIC
# MAGIC A **migration** is a saved SQL change, like "create the orders table." V1 creates customers; V2 creates orders. The tables live in `app`, a Postgres **schema** that groups tables inside a database.
# MAGIC
# MAGIC The helper records each version in `app.schema_migrations`, so a rerun won't apply it twice. A real team uses a tool such as Flyway or Liquibase for this.
# MAGIC
# MAGIC This cell also loads test data. You should see **1,000 customers and 5,000 orders**.

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
# MAGIC Our orders are in `databricks_postgres`, the database Lakebase created for us. Let's put stock levels in a second database, `reporting`, on the same branch.
# MAGIC
# MAGIC You should see **200 stock rows**. Later, each database needs its own dump and restore. Copying the orders database alone would leave the stock data behind.

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
# MAGIC A reporting tool should be able to read orders without changing them. We'll use two Postgres **roles**, which are names we give permissions to:
# MAGIC
# MAGIC * `app_owner` owns the app's schemas and tables. Migrations run as this role.
# MAGIC * `app_reader` can only read, like an analyst or a reporting tool.
# MAGIC
# MAGIC Create the roles once for the branch, then set ownership and read permissions in each database. **Default privileges** give future tables the same read access.
# MAGIC
# MAGIC In the output, every table should belong to `app_owner`, and `app_reader_can_read` should be `true`. We'll rebuild these permissions after the move.

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
# MAGIC A **branch** gives us a separate copy of production to work on, both databases included. It starts with what production has right now. Later changes stay on the branch where you make them.
# MAGIC
# MAGIC Lakebase shares the unchanged storage, so creating a branch doesn't copy every row up front. That's called copy-on-write. On `development` we:
# MAGIC
# MAGIC * run migrations V3 (coupons) and V4 (feature flags). V4 is **unreleased**, so production won't get it in this lab;
# MAGIC * add a test coupon, `DEV-TEST-50`, and put it on three orders. Those are changes to tables production also has;
# MAGIC * add two feature flags, in a table that exists **only** on this branch.
# MAGIC
# MAGIC Look at the two migration tables below: **development has V1 through V4; production still has only V1 and V2.** Our experiments haven't changed production.

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
# MAGIC Suppose your product list already lives in the lakehouse. A **synced table** puts a read-only copy inside Lakebase so the app can read it alongside its orders.
# MAGIC
# MAGIC We'll create 50 products in a lakehouse table (a Delta table), then sync them into old production. If this exercise skips because of your catalog permissions, you can keep going.
# MAGIC
# MAGIC The sync should reach **50 rows** and an **ONLINE** state. The create call returns before the rows arrive, so the cell waits for them. This table won't go in our dump; we'll recreate its sync on the new side.

# COMMAND ----------

# DBTITLE 1,Create a Delta table and sync it into old production
"""Create a 50-row Delta table in Unity Catalog, sync it into old production, and wait for the rows."""
def wait_for_sync(pid, synced_name, pg_table, expected_rows, timeout=900):
    """Wait until the synced table is online and Postgres has every row."""
    started, failures = time.time(), 0
    while True:
        status = client(pid).postgres.get_synced_table(name=f"synced_tables/{synced_name}").status
        state = status.detailed_state.value if status and status.detailed_state else "unknown"
        try:
            rows = query(pid, "production", f"SELECT count(*) AS n FROM {pg_table}")["n"][0]
            failures = 0
        except Exception:
            failures += 1
            if failures >= 3:
                raise
            rows = 0
        if "FAILED" in state:
            raise RuntimeError(f"{synced_name} failed to sync: state {state}, {rows} rows")
        if rows >= expected_rows and "ONLINE" in state:
            return state, rows, round(time.time() - started)
        if time.time() - started > timeout:
            raise TimeoutError(f"{synced_name}: state {state}, {rows} rows")
        time.sleep(15)


def create_synced_table(pid, attempts=1):
    """Create the lab's synced table on a project's production. Retries while a just-deleted name is released."""
    for attempt in range(attempts):
        try:
            client(pid).postgres.create_synced_table(
                synced_table=SyncedTable(spec=SyncedTableSyncedTableSpec(
                    source_table_full_name=SOURCE_TABLE,
                    branch=branch_path(pid, "production"),
                    postgres_database=DB,
                    primary_key_columns=["product_id"],
                    scheduling_policy=SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy.SNAPSHOT,
                    create_database_objects_if_missing=True)),
                synced_table_id=SYNCED_TABLE).wait()
            LAB_CREATED.add(SYNCED_TABLE)
            return
        except Exception as e:
            if attempt == attempts - 1:
                raise
            print("  name still being released, retrying:", str(e)[:120])
            time.sleep(20)


if DO_SYNCED_TABLES:
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {LAB_SCHEMA}")
        LAB_CREATED.add(LAB_SCHEMA)
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {SOURCE_TABLE} (
                        product_id BIGINT NOT NULL, name STRING NOT NULL, price_cents INT NOT NULL,
                        CONSTRAINT product_catalog_pk PRIMARY KEY (product_id))
                      TBLPROPERTIES (delta.enableChangeDataFeed = true)""")
        if spark.table(SOURCE_TABLE).count() == 0:
            spark.sql(f"INSERT INTO {SOURCE_TABLE} SELECT id, concat('Product ', id), CAST(100 + id * 25 AS INT) "
                      f"FROM range(1, 51)")
        try:
            w.postgres.get_synced_table(name=f"synced_tables/{SYNCED_TABLE}")
            exists = True
        except Exception:
            exists = False
        if exists and SYNCED_TABLE in LAB_CREATED:
            print("The synced table already exists from earlier in this session, so we reuse it.")
            owner = NEW_ID if globals().get("NEW_SYNC") else OLD_ID  # after Module 4's swap, the name lives on the new home
        else:
            if exists:  # its name has your user id in it, so it's yours: a leftover from an earlier run
                w.postgres.delete_synced_table(name=f"synced_tables/{SYNCED_TABLE}").wait()
                print("Deleted a synced table left over from an earlier run.")
            create_synced_table(OLD_ID, attempts=10 if exists else 1)
            print("Create call returned. Waiting for the rows to land...")
            owner, NEW_SYNC = OLD_ID, False  # it stays on the old home until Module 4 moves it
        state, rows, secs = wait_for_sync(owner, SYNCED_TABLE, f"{UC_SCHEMA}.product_catalog_synced", 50)
        print(f"Synced: {rows} rows in Postgres, state {state}, after {secs} s")
    except Exception as e:
        DO_SYNCED_TABLES = False
        reason = re.sub(r"^\([\w.$]+\)\s*", "", " ".join(str(e).split("JVM stacktrace")[0].split()))
        if any(s in reason for s in ("PERMISSION_DENIED", "NO_SUCH_CATALOG", "CATALOG_NOT_FOUND")):
            print(f"Skipping the synced-table steps. {reason[:400]}\n\n"
                  "The rest of the lab still runs. To include them, put a catalog where you can create a schema "
                  "in box 3 at the top. Then run this cell again, or, in a Run all, click Run all again once it "
                  "finishes.")
        else:
            print("Skipping the synced-table steps after an unexpected error. The rest of the lab still runs; "
                  f"please report this one:\n{type(e).__name__}: {reason[:800]}")
else:
    print("Skipped (DO_SYNCED_TABLES = False)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 2: Release the coupon change
# MAGIC
# MAGIC **Run the tested V3 migration on production.** That's a promotion: release the coupon feature without copying development's rows.
# MAGIC
# MAGIC Production keeps its customers and orders and gets **`FALL10`**. Development should still have **`DEV-TEST-50`**, its test coupon.

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
# MAGIC Check access on the new table too. V3 ran as `app_owner`, so its default privileges should give `app_reader` read access to `coupons`.

# COMMAND ----------

# DBTITLE 1,The new table picked up the default grants
"""Show that the table V3 created belongs to app_owner and is readable by app_reader."""
show(access_report(OLD_ID, "production", [DB]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 3: Build the new home
# MAGIC
# MAGIC Build an empty **new home** with a bundle. Both projects stay here on your first run; the second-workspace option uses the same steps.
# MAGIC
# MAGIC ### Step 1: Describe the new home
# MAGIC
# MAGIC The bundle file, `databricks.yml`, says what to create: a project, two branches, and development's compute. In a real release, you keep it in Git next to your migrations and app code. Here we write it to a temporary folder.
# MAGIC
# MAGIC The file below lists `production` and `development`. Two settings matter later:
# MAGIC
# MAGIC * `lifecycle: { prevent_destroy: true }` on the project and production, so a stray `bundle destroy` can't delete them. Module 7 shows it.
# MAGIC * `history_retention_duration`, the restore window. It's a **setting**, so it doesn't come along with the data. You set it again on the new side.

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
      display_name: "{NEW_LABEL}"   # how cleanup knows the lab made it
      pg_version: {PG_VERSION}
      history_retention_duration: 604800s           # the restore window: 7 days
      purge_on_delete: true                         # lab only: frees the name as soon as it's deleted{lifecycle}

  postgres_branches:
    production:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: production
      replace_existing: true                        # Lakebase makes production with the project; adopt it{lifecycle}
    development:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: development
      source_branch: ${{resources.postgres_branches.production.id}}
      no_expiry: true                               # every branch you add needs an expiry setting

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
# MAGIC The output should say **`Validation OK!`**, then show a successful deploy. In the next cell, **`has_app_tables` should be `false`**: the bundle creates resources, not app tables or rows. Leave production empty so the full restore can create them.

# COMMAND ----------

# DBTITLE 1,Step 2: databricks bundle validate, then deploy
"""Validate and deploy the bundle, the same commands you'd run from a laptop or CI."""
claim(NEW_ID, NEW_LABEL)  # never adopt a leftover new home from an earlier run
try:
    for args in (["bundle", "validate"], ["bundle", "deploy"]):
        rc, out = cli(*args)
        print(f"$ databricks {' '.join(args)}\n{out}\n")
        assert rc == 0, f"databricks {' '.join(args)} failed"
finally:
    if project_exists(NEW_ID):  # made by this deploy, even a half-finished one, so a retry can reuse it
        LAB_CREATED.add(NEW_ID)

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
# MAGIC Branching was quick inside the old project. Could we do that here too, instead of dumping and restoring? Let's ask for a branch in the new project that starts from old production. **This request should be rejected.** The next cell prints the reason.

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
    print("Rejected, as expected:" if "same project" in str(e).lower() else "Unexpected error:")
    print("  ", str(e)[:300])

# COMMAND ----------

# MAGIC %md
# MAGIC A branch's parent has to be in the same project. To get the orders into this one, use a dump and restore.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 4: Move the data
# MAGIC
# MAGIC **Pause writes, copy, check, rebuild the sync and access, then switch.** Pointing the app at the new host is the **cutover**. Development can wait until the app is running again.
# MAGIC
# MAGIC ### The app is live: write, then pause (simulated)
# MAGIC
# MAGIC Place 25 more orders, then stop. Save a **watermark**, the newest order ID and total count, to check against after the copy. You should see **order 5025 and 5,025 orders**.
# MAGIC
# MAGIC This pause is simulated. The cell stops placing orders and checks for other sessions running a statement or holding a transaction open. If it finds one, it refuses to continue.
# MAGIC
# MAGIC For a real app, this check doesn't stop future writes. Use the repo's <a href="$./skills/lakebase-move-lab-expert/playbook.md">production playbook</a> to stop and keep every writer stopped before dumping.

# COMMAND ----------

# DBTITLE 1,Place a few orders, then pause writes (simulated) and take a watermark
"""Simulate the live app, then pause writes: record the newest order and the count, and stop if anything else is writing."""
with connect(OLD_ID, "production") as conn:
    conn.execute("INSERT INTO app.orders (customer_id, amount_cents) SELECT 1 + g, 1999 FROM generate_series(1, 25) g")
    WATERMARK = conn.execute("SELECT max(order_id), count(*) FROM app.orders").fetchone()
PAUSE_STARTED = time.time()
print(f"Writes paused (simulated: our pretend app just stops). Watermark: newest order_id {WATERMARK[0]}, "
      f"{WATERMARK[1]} orders.")

# The check a real cutover needs: no other session may be running a statement or holding a transaction open.
OPEN_SESSIONS = ("SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND backend_type = 'client backend' "
                 "AND datname = ANY(%s) AND state IN ('active', 'idle in transaction', 'idle in transaction (aborted)')")
with connect(OLD_ID, "production") as conn:
    for attempt in range(4):  # give a passing query a few seconds to finish
        busy = conn.execute(OPEN_SESSIONS, ([DB, REPORTING_DB],)).fetchone()[0]
        if not busy:
            break
        time.sleep(5)
assert not busy, (f"Don't dump yet: {busy} other session(s) are running a statement or holding a transaction open. "
                  "Stop them, then run this cell again.")
print("No other session is running a statement or holding a transaction open.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Copy both production databases
# MAGIC
# MAGIC **First, list the databases.** Old production has more than one, so each gets its own dump and its own restore. (The built-in `postgres` database is empty, so we skip it.)

# COMMAND ----------

# DBTITLE 1,Which databases does old production have?
"""List old production's databases. Each one needs its own dump and restore."""
databases = query(OLD_ID, "production", "SELECT datname AS database FROM pg_database WHERE NOT datistemplate ORDER BY 1")
show(databases)
APP_DATABASES = [d for d in databases.database if d != "postgres"]
print("Databases to move:", ", ".join(APP_DATABASES))

# COMMAND ----------

# MAGIC %md
# MAGIC **Dump each database.** We use the custom format (`-Fc`) so `pg_restore` can list and filter what's inside. In `databricks_postgres` we **exclude** the synced table. We'll recreate its sync after the restore.
# MAGIC
# MAGIC If the `--exclude-table` name has a typo, `pg_dump` doesn't complain, and the synced table quietly stays in the dump. So the cell checks that it's gone.

# COMMAND ----------

# DBTITLE 1,pg_dump each database on old production
"""One pg_dump per database, in custom format. Then check that the synced table isn't in any dump."""
DUMPS, LISTINGS = {}, {}
for db in APP_DATABASES:
    DUMPS[db] = WORK_DIR / f"{db}.dump"
    args = ["-Fc", "-f", str(DUMPS[db])]
    if db == DB:  # excluding a table that isn't there is harmless
        args.append(f"--exclude-table={UC_SCHEMA}.product_catalog_synced")
    rc, secs, err = run_pg("pg_dump", OLD_ID, "production", args, dbname=db)
    assert rc == 0, f"pg_dump of {db} failed: {err}"
    print(f"{db}: pg_dump exit code 0 in {secs} s, {DUMPS[db].stat().st_size:,} bytes")
    LISTINGS[db] = subprocess.run([str(PG_BIN / "pg_restore"), "-l", str(DUMPS[db])], env=PG_ENV,
                                  capture_output=True, text=True, check=True).stdout
left_in_dumps = sum("product_catalog_synced" in l for text in LISTINGS.values() for l in text.splitlines())
print("Synced table entries left in the dumps (should be 0):", left_in_dumps)
assert left_in_dumps == 0, "The synced table is still in the dump. Check the --exclude-table name."

# COMMAND ----------

# MAGIC %md
# MAGIC **Leave Lakebase's own objects alone.** The dump includes some objects Lakebase manages, and the new project already has its own versions. Trying to restore those causes errors.
# MAGIC
# MAGIC `pg_restore -l` lists what's in the dump. This cell puts a `;` in front of the platform entries so the restore skips them. The app's entries stay in the list. For a real move, inspect your own dump's list before using this filter.

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
# MAGIC **Restore each database into new production.** Each database should finish with **exit code 0**, meaning the command succeeded. Here's what the options do:
# MAGIC
# MAGIC * `--no-owner --no-acl`: skip the old side's owners and grants, because those roles don't exist here. We rebuild access in a later step.
# MAGIC * `--single-transaction --exit-on-error`: all or nothing. If anything fails, nothing lands, and you can safely try again.
# MAGIC * `-L`: restore only what's in that database's filtered list.
# MAGIC
# MAGIC Rows appearing isn't enough: a nonzero exit is a failure. The cell also saves the time before the first restore for Module 5.

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
    if pending == APP_DATABASES:  # nothing has landed yet; a retry after a partial restore keeps the first time
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
# MAGIC **Check the copy, database by database.** First we compare each database's app schema: its tables, columns, keys, indexes, constraints, and sequences. A **sequence** is a counter Postgres uses to give a new row its ID, like the next order number.
# MAGIC
# MAGIC Then we compare every app table's row count and **checksum**, a value calculated from all its rows. Matching checksums help us check the contents, not just how many rows there are.
# MAGIC
# MAGIC Every table should show **`identical = true`**, the watermark should match, and migrations should be **`[1, 2, 3]`**. This comparison covers the app's schema and rows. Access, project history, and synced tables need their own checks.

# COMMAND ----------

# DBTITLE 1,Compare old and new production, database by database
"""Compare the app schema's definitions and every app table's fingerprint on both sides, then the watermark and history."""
def schema_definitions(pid, dbname):
    """The app schema's definitions from a schema-only dump, without owners, grants, and the dump's own lines."""
    path = WORK_DIR / f"schema_{pid}_{dbname}.sql"
    rc, secs, err = run_pg("pg_dump", pid, "production",
                           ["--schema-only", "--no-owner", "--no-acl", "-n", "app", "-f", str(path)], dbname=dbname)
    assert rc == 0, f"pg_dump --schema-only of {dbname} failed: {err}"
    return [l for l in path.read_text().splitlines()
            if l.strip() and not l.startswith(("--", "\\restrict", "\\unrestrict", "SET ", "SELECT pg_catalog."))]


schemas_match = {db: schema_definitions(OLD_ID, db) == schema_definitions(NEW_ID, db) for db in APP_DATABASES}
for db, same in schemas_match.items():
    print(f"{db}: app schema definitions {'match' if same else 'DIFFER'}")

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
watermark_matches = (int(new_mark.newest), int(new_mark.orders)) == tuple(WATERMARK)
assert all(schemas_match.values()) and compare.identical.all() and watermark_matches, (
    "The copy doesn't match. If you re-ran earlier cells after the restore, run Module 7 (clean up) and start over.")
print("✅ New production matches old production: the same app schema and the same rows in every app table, "
      "in every database.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Recreate the synced table (optional)
# MAGIC
# MAGIC The product list comes from the Delta table, not from our dump. We'll remove the old sync and create a new one with the same name, pointing at new production. In this workspace, that name can only point at one project at a time.
# MAGIC
# MAGIC The new sync should have **50 rows** and matching Delta versions. That tells us it has caught up. With a second workspace that has its own metastore (the catalog of lakehouse tables), this step skips: we'd need to copy its source table there first.

# COMMAND ----------

# DBTITLE 1,Move the synced table to the new home
"""Delete the old project's sync, create the same synced table on new production, and prove it's current."""
NEW_SYNC = DO_SYNCED_TABLES and SYNCED_TABLE in LAB_CREATED  # only if Module 1 made one in this session
if NEW_SYNC and TWO_WORKSPACES and w.metastores.current().metastore_id != w_new.metastores.current().metastore_id:
    NEW_SYNC = False
    print("Skipped: the new home's workspace has its own metastore, so the source Delta table would have to be\n"
          "copied there first, which is a separate job. The old sync keeps running until cleanup.")
elif NEW_SYNC:
    sync_started = time.time()
    w.postgres.delete_synced_table(name=f"synced_tables/{SYNCED_TABLE}").wait()
    print("Removed the old project's sync")
    create_synced_table(NEW_ID, attempts=10)
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
# MAGIC `--no-owner --no-acl` left out the old app's access rules. Every restored table belongs to whoever ran the restore, and `app_reader` doesn't exist here yet. Check it before rebuilding access.

# COMMAND ----------

# DBTITLE 1,Check access on new production right after the restore
"""Show that app_owner and app_reader don't exist yet, and who owns each table now."""
roles = query(NEW_ID, "production",
              "SELECT rolname FROM pg_roles WHERE rolname IN ('app_owner', 'app_reader') ORDER BY 1").rolname
print("The app's roles on new production:", ", ".join(roles) or "none yet (no app_owner, no app_reader)")
OWNERS_SQL = ("SELECT c.relname AS \"table\", pg_get_userbyid(c.relowner) AS owner FROM pg_class c "
              "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'app' AND c.relkind = 'r' ORDER BY 1")
show(pd.concat([query(NEW_ID, "production", OWNERS_SQL, dbname=db).assign(database=db) for db in APP_DATABASES],
               ignore_index=True)[["database", "table", "owner"]])

# COMMAND ----------

# MAGIC %md
# MAGIC Recreate the roles once for the branch, then ownership, grants, and default privileges in each database. Do this on production before rebuilding development, so it inherits the access rules.

# COMMAND ----------

# DBTITLE 1,Rebuild access on new production
"""Run the same access script on new production, for every database we moved."""
set_up_access(NEW_ID, "production", APP_DATABASES)
show(access_report(NEW_ID, "production", APP_DATABASES))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Last checklist before you switch
# MAGIC
# MAGIC You need **7 of 7 checks passed** before switching. The checks cover both databases, the order watermark, access, the sync if we used it, and a test order that rolls back.
# MAGIC
# MAGIC Don't switch if a check fails. Before the first new write, the old side still has everything. After new writes land, pointing back would leave those orders behind.

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
    "App schema and every app table identical, in every database": bool(all(schemas_match.values())
                                                                        and compare.identical.all()),
    "Watermark matches": watermark_matches,
    "Sequences carried over": sequences_match,
    "Migration history carried over": query(NEW_ID, "production", "SELECT max(version) AS v FROM app.schema_migrations")["v"][0] == 3,
    "app_reader can read every table": bool(access_report(NEW_ID, "production", APP_DATABASES).app_reader_can_read.all()),
    "Synced table current (or not used)": (
        True if not globals().get("NEW_SYNC")
        else "synced_version" in globals() and synced_version == newest_version),
    "App smoke test (write and read)": smoke_ok,
}
show(pd.DataFrame([(k, "✅" if v else "❌") for k, v in checks.items()], columns=["check", "result"]))
passed = sum(1 for v in checks.values() if v)
print(f"{passed} of {len(checks)} checks passed.")
assert all(checks.values()), "Don't switch: a check failed"
print("All checks passed. Safe to switch.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Switch the app and resume writes
# MAGIC
# MAGIC Point the simulated app at the new host and place five orders. They should be **5026 through 5030** because the dump carried the order-ID counter too.
# MAGIC
# MAGIC The cell prints the simulated write pause for this tiny database. It's not an estimate for your app. A real pause includes the dump, restore, checks, and rebuilding the sync and access.

# COMMAND ----------

# DBTITLE 1,Point the app at the new home and place new orders
"""Show both hosts, place five orders on the new home, and report how long writes were paused."""
if TWO_WORKSPACES:
    print("Old workspace:", w.config.host)
    print("New workspace:", w_new.config.host)
print("Old host:", endpoint_of(OLD_ID, "production")[1])
print("New host:", endpoint_of(NEW_ID, "production")[1])
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
    print(f"Swapping the synced table took {SYNC_SECS} s of it.")
print("That's for this tiny lab database. Yours depends on your data, so time a practice dump and restore first.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Rebuild development
# MAGIC
# MAGIC The bundle created `development` before the restore, when new production was empty. Check whether it has any app tables.

# COMMAND ----------

# DBTITLE 1,Look inside the dev branch the bundle created before the restore
"""Check whether the new development branch has the app's tables."""
show(query(NEW_ID, "development", "SELECT to_regclass('app.orders') IS NOT NULL AS has_app_tables"))

# COMMAND ----------

# MAGIC %md
# MAGIC Delete that empty branch and run `bundle deploy` again. The replacement starts from production as it is now, with both databases and their access rules.
# MAGIC
# MAGIC Only do this with brand-new branches on the new side. Deleting a branch deletes whatever is on it.

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
# MAGIC The rebuilt branch starts from production after the switch. It has `FALL10` and the new orders, but not the dev-only work. We'll add that back:
# MAGIC
# MAGIC 1. Run the unreleased migration, **V4**, to create `feature_flags`.
# MAGIC 2. Copy the two feature flags with a **data-only** dump of just that dev-only table.
# MAGIC 3. For tables production also has, apply **just dev's changes**: the `DEV-TEST-50` coupon and the three orders that use it. That's what we mean by reconciling the data.
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
    assert rc == 0, f"pg_dump of dev's feature flags failed: {err}"
    print(f"Dumped dev's feature flags: exit {rc}")
    rc, secs, err = run_pg("pg_restore", NEW_ID, "development",
                           ["--data-only", "--no-owner", "--no-acl", "--single-transaction", "--exit-on-error", "-d", DB, str(FLAGS)])
    assert rc == 0, f"pg_restore of dev's feature flags failed: {err}"
    print(f"Restored them into new development: exit {rc}")

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
# MAGIC **Optional:** watch the "just dump all of dev" shortcut fail. Thanks to `--single-transaction`, nothing changes when it does.

# COMMAND ----------

# DBTITLE 1,(Optional) The shortcut that fails: dump all of dev
"""Try a data-only dump of dev's whole app schema into the rebuilt branch. It's expected to fail on duplicate keys."""
FULL_DEV = WORK_DIR / "dev_full_data.dump"
rc, secs, err = run_pg("pg_dump", OLD_ID, "development", ["-Fc", "--data-only", "-n", "app", "-f", str(FULL_DEV)])
assert rc == 0, f"pg_dump of development failed: {err}"
rc, secs, err = run_pg("pg_restore", NEW_ID, "development",
                       ["--data-only", "--no-owner", "--no-acl", "--single-transaction", "--exit-on-error", "-d", DB, str(FULL_DEV)])
dup = "duplicate key" in err
print("Rejected, as expected:" if rc and dup else "Unexpected:", f"(pg_restore exit code {rc})")
if rc:
    print("  ", next((l for l in err.splitlines() if "duplicate key" in l or "ERROR" in l), err[:200]))
print("New development still has", query(NEW_ID, "development", "SELECT count(*) AS n FROM app.customers")["n"][0],
      "customers" + (": the failed restore changed nothing." if rc else "."))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 5: What doesn't come along
# MAGIC
# MAGIC If you need to recover an order from before the move, use the old project's history. It wasn't in the dump.
# MAGIC
# MAGIC ### The new home has its own history
# MAGIC
# MAGIC **Point-in-time restore** lets you create a branch from an earlier moment. Let's ask the new home for production as it was **just before the restore**. It should have **`has_app_tables = false`**: this project hadn't received our app yet.

# COMMAND ----------

# DBTITLE 1,Try to restore the new home to before the move
"""Create a point-in-time branch of new production as of just before the restore, look inside, and delete it."""
try:
    RESTORE_STARTED
except NameError:
    raise RuntimeError("This session has no record of when the restore started: it hasn't run yet, or it ran before "
                       "the notebook restarted. Run the restore cell in Module 4, or run Module 7 and start over.")

client(NEW_ID).postgres.create_branch(
    parent=project_path(NEW_ID),
    branch=Branch(spec=BranchSpec(source_branch=branch_path(NEW_ID, "production"),
                                  source_branch_time=Timestamp(seconds=int(RESTORE_STARTED.timestamp())),
                                  ttl=Duration(seconds=86400))),
    branch_id="before-the-move",
).wait()
try:
    show(query(NEW_ID, "before-the-move", "SELECT to_regclass('app.orders') IS NOT NULL AS has_app_tables"))
finally:
    client(NEW_ID).postgres.delete_branch(name=branch_path(NEW_ID, "before-the-move"), purge=True).wait()
    print("(Deleted the before-the-move branch.)")

# COMMAND ----------

# MAGIC %md
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
        try:
            client(NEW_ID).postgres.create_branch(
                parent=project_path(NEW_ID),
                branch=Branch(spec=BranchSpec(source_snapshot=snapshot, no_expiry=True)),
                branch_id="from-old-snapshot",
            ).wait()
            print("Unexpected: the branch was created")
            try:
                client(NEW_ID).postgres.delete_branch(
                    name=branch_path(NEW_ID, "from-old-snapshot"), purge=True).wait()
            except Exception as e:
                print("Couldn't delete the unexpected from-old-snapshot branch:", str(e)[:200])
        except Exception as e:
            print("Rejected, as expected:" if "same project" in str(e).lower() else "Unexpected error:")
            print("  ", str(e)[:300])
    finally:
        try:
            client(OLD_ID).postgres.delete_snapshot(name=snapshot).wait()
        except Exception as e:
            print("Couldn't delete snapshot before-the-move:", str(e)[:200])
except Exception as e:
    print("Couldn't create a snapshot here, so skipping this demo:", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC A snapshot can only be restored inside its own project. Keep the old project for pre-move recovery, and set a snapshot schedule on the new one. The bundle already set its restore window.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 6: Doing it for real
# MAGIC
# MAGIC Before moving a real app, use the repo's <a href="$./skills/lakebase-move-lab-expert/playbook.md">production playbook</a>. The <a href="$./TESTING.md">test record</a> lists what ran here and what hasn't been tested. If you imported only this notebook, open those files in the GitHub repo.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 7: Clean up
# MAGIC
# MAGIC Run these two cells to delete the lab resources, including anything from a stopped run.
# MAGIC
# MAGIC **This deletes the made-up app data too.** For a real move, keep the old project for recovery.
# MAGIC
# MAGIC If Python restarted or the notebook detached, first run from the top through **Module 0 only**, skip Modules 1 through 6, then run these cells. Cleanup skips missing resources and only deletes projects with the lab's name tag ("Lakebase move lab: ...").
# MAGIC
# MAGIC ### Step 1: Try to destroy the new home
# MAGIC
# MAGIC Try `databricks bundle destroy` with `prevent_destroy` still in the bundle file.

# COMMAND ----------

# DBTITLE 1,Step 1: try bundle destroy with the guard in place
"""Run bundle destroy while prevent_destroy is in the file. It should refuse, and nothing gets deleted."""
if "write_bundle" not in globals() or not project_exists(NEW_ID):
    print("There's no new home from this session to try it on. Go on to the next cell.")
else:
    write_bundle(guard=True)  # make sure the guard is in the file for this demo
    rc, out = cli("bundle", "destroy", "--auto-approve")
    print(f"$ databricks bundle destroy --auto-approve   (exit code {rc})\n{out}\n")
    print("Refused, as expected." if rc and "prevent_destroy" in out else "Unexpected: the guard didn't stop it.")
    print("The new home still exists:", project_exists(NEW_ID))

# COMMAND ----------

# MAGIC %md
# MAGIC **Refused.** With `prevent_destroy` in the bundle, this `bundle destroy` can't delete production. To delete it through the bundle, someone has to take the guard out of the file first. In a real release, that's a change someone reviews in Git.
# MAGIC
# MAGIC ### Step 2: Remove the guard and delete everything
# MAGIC
# MAGIC Remove `prevent_destroy`, redeploy, then destroy. `purge_on_delete` frees the project's name for your next run. This also removes the old home, synced table, Unity Catalog schema, and local files. In two-workspace mode it deletes the secret scope too; revoke the token in the other workspace when you're done.
# MAGIC
# MAGIC `CONFIRM_TEARDOWN` is `True`, so **Run all** deletes the lab resources. To keep them briefly and look around, change it to `False` **in this cell**. When you're done, set it back to `True` and run the cell to clean up.
# MAGIC
# MAGIC The cell should finish with **`Done.`**. Your notebook and Git folder stay.

# COMMAND ----------

# DBTITLE 1,Step 2: remove the guard and delete everything
"""Delete everything the lab created: the synced table, the new home (with the bundle), the old home,
the Unity Catalog schema, the bundle's workspace folder, and the local files."""
CONFIRM_TEARDOWN = True

if "OLD_ID" not in globals():
    raise RuntimeError("Python restarted since the lab ran. Run the cells from the top through Module 0, "
                       "then run this cell again.")
if not CONFIRM_TEARDOWN:
    print("Teardown skipped. Set CONFIRM_TEARDOWN = True to delete the lab's projects.")
else:
    deleted_sync = False
    sync_clients = [client(NEW_ID)]
    if w is not sync_clients[0]:
        sync_clients.append(w)
    for who in sync_clients:
        try:
            who.postgres.delete_synced_table(name=f"synced_tables/{SYNCED_TABLE}").wait()
            deleted_sync = True
        except Exception as e:
            if "NOT_FOUND" not in str(e).upper() and "does not exist" not in str(e).lower():
                print(f"Couldn't delete synced table via {who.config.host}: {type(e).__name__}: {str(e)[:160]}")
    print("Deleted the synced table" if deleted_sync else "No synced table to delete")
    tagged = project_exists(NEW_ID) and (
        client(NEW_ID).postgres.get_project(name=project_path(NEW_ID)).status.display_name == NEW_LABEL)
    if "write_bundle" in globals() and tagged:  # a deploy with no new home would build one just to destroy it
        write_bundle(guard=False)  # the reviewed change: no more prevent_destroy
        for args in (["bundle", "deploy"], ["bundle", "destroy", "--auto-approve"]):
            rc, out = cli(*args)
            print(f"\n$ databricks {' '.join(args)}   (exit code {rc})\n{out}")
    for pid, label in ((NEW_ID, NEW_LABEL), (OLD_ID, OLD_LABEL)):  # the old home was never in the bundle
        if project_exists(pid):
            found = client(pid).postgres.get_project(name=project_path(pid)).status.display_name
            if found != label:
                print(f"\nLeft {pid} alone: this lab didn't make it (it's called {found!r}).")
                continue
            client(pid).postgres.delete_project(name=project_path(pid), purge=True).wait()
            print("\nDeleted project", pid)
    try:
        if spark.sql(f"SHOW SCHEMAS IN {CATALOG} LIKE '{UC_SCHEMA}'").count():
            spark.sql(f"DROP SCHEMA {LAB_SCHEMA} CASCADE")  # only this lab's own schema
            print("Dropped schema", LAB_SCHEMA)
        else:
            print("No lab schema to drop")
    except Exception as e:
        if "NOT_FOUND" in str(e) or "NO_SUCH" in str(e):
            print("No lab schema to drop")
        else:
            print("Couldn't drop the lab schema:", str(e)[:120])
    try:
        w_new.workspace.delete(BUNDLE_ROOT, recursive=True)  # only this lab's bundle folder
    except NotFound:
        print("No bundle folder to delete")
    except Exception as e:
        print(f"Couldn't delete the bundle folder {BUNDLE_ROOT}: {type(e).__name__}: {str(e)[:160]}")
    if NEW_WORKSPACE_SECRETS:
        try:
            w.secrets.delete_scope(scope=NEW_WORKSPACE_SECRETS)  # the scope Choose your setup made for your token
            print(f"Deleted secret scope {NEW_WORKSPACE_SECRETS}. The token keeps working until it expires, "
                  "so revoke it in the other workspace if you're done with it.")
        except Exception:
            print(f"Couldn't delete secret scope {NEW_WORKSPACE_SECRETS}; delete it yourself if you're done with it.")
    for folder in (WORK_DIR, BUNDLE_DIR):  # emptied, not removed, so you can go through the lab again here
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(exist_ok=True)
    LAB_CREATED.clear()
    print("Done.")

# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0

# COMMAND ----------

# MAGIC %md
# MAGIC # Lakebase Move Lab: preflight check
# MAGIC
# MAGIC Run this **before** the lab. In about 3 minutes it tries everything the lab needs, the same way the lab does it, and tells you exactly what to fix, so nobody hits a wall halfway through.
# MAGIC
# MAGIC It checks:
# MAGIC
# MAGIC * **Downloads:** the Python packages from PyPI, the PostgreSQL client tools from apt.postgresql.org, and the Databricks CLI from GitHub.
# MAGIC * **Sign-in:** the SDK and the CLI both sign in as you, with nothing to configure.
# MAGIC * **Lakebase:** a bundle deploys a project; you can connect, create a second database, set up roles and grants, run `pg_dump` and a filtered `pg_restore`, and create point-in-time branches and snapshots.
# MAGIC * **Synced tables:** you can create a schema in the lab's catalog and sync a Delta table into Lakebase.
# MAGIC * **Cleanup:** `prevent_destroy` guards the bundle, and everything this check creates gets deleted.
# MAGIC * **Leftovers:** nothing from an earlier lab run is still around.
# MAGIC
# MAGIC It creates one small throwaway project, `lb-move-pre-…`, and deletes it at the end. Run it the way you'll run the lab: on serverless, as yourself. The last cell prints the verdict: ✅ ready, ⚠️ ready with notes, or ❌ fix these first.
# MAGIC
# MAGIC > You can also ask **Genie Code** to run this check and explain the results. See the repo's README.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Install the Python libraries
# MAGIC
# MAGIC The same install as the lab's first cell. If this cell fails, the lab's will too; usually that means serverless can't reach PyPI. Ask your workspace admin to allow PyPI, or a PyPI mirror, for serverless compute.

# COMMAND ----------

# MAGIC %pip install --quiet -U "databricks-sdk>=0.81.0" "psycopg>=3.1" "protobuf<6"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Settings and how checks are recorded
# MAGIC
# MAGIC Set **catalog** (the widget at the top) to the catalog you'll use for the lab's synced table; the lab's default is `main`. Each check records ✅ **pass**, ⚠️ **warning** (the lab still runs, minus a step), ❌ **fail** (fix it before the lab), or ⏭️ **skipped** (a check it depends on failed), with the fix.

# COMMAND ----------

# DBTITLE 1,Settings and the check harness
"""Read the settings, then define how each check is run and recorded."""
import ctypes.util
import gzip
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

dbutils.widgets.text("catalog", "main", "Catalog for the lab's synced table")
CATALOG = dbutils.widgets.get("catalog").strip() or "main"
CLEAN_LEFTOVERS = False  # True deletes what an earlier lab run left behind (its projects, schema, and bundle folder)

PG_VERSION = 17  # the lab's Postgres version
CLI_VERSION = "1.17.0"  # the CLI version the lab downloads

RESULTS, PASSED = [], set()
ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️"}


class Warn(Exception):
    """Raised by a check when the lab can still run, minus a step."""


def check(name, fix, needs=()):
    """Run the decorated function right away as a check, and record its result with the fix."""
    def run(fn):
        started, missing = time.time(), [n for n in needs if n not in PASSED]
        if missing:
            status, detail = "skip", "needs: " + ", ".join(missing)
        else:
            try:
                status, detail = "pass", fn() or ""
                PASSED.add(name)
            except Warn as e:
                status, detail = "warn", str(e)
            except Exception as e:
                status, detail = "fail", brief(e, 450)
        detail = " ".join(str(detail).split())[:500]
        RESULTS.append({"check": name, "status": status, "detail": detail,
                        "fix": fix if status in ("warn", "fail") else "",
                        "seconds": round(time.time() - started, 1)})
        print(f"{ICON[status]} {name}: {detail}")
    return run


def tail(text, lines=6):
    """The last few lines of a command's output, joined for an error message."""
    return " | ".join(text.strip().splitlines()[-lines:])


def brief(e, limit=200):
    """An exception as one short line, without Spark's JVM stack trace."""
    return f"{type(e).__name__}: {' '.join(str(e).split('JVM stacktrace')[0].split())[:limit]}"


print("Catalog for the synced-table check:", CATALOG)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Compute, downloads, and sign-in
# MAGIC
# MAGIC The lab downloads the PostgreSQL client tools and the Databricks CLI, loads psycopg on the downloaded `libpq`, and signs in to Databricks two ways: the SDK and the CLI. This cell does all of that exactly as the lab does.

# COMMAND ----------

# DBTITLE 1,Compute, downloads, and sign-in
"""Check the compute, the downloads the lab makes, and that the SDK and the CLI both sign in as you."""
SDK_CHECK = "Databricks SDK and the Lakebase API"


@check("Serverless compute", "Attach serverless compute. The notebook asks for environment version 5, the way the lab runs.")
def _():
    os_name = dict(l.strip().split("=", 1) for l in open("/etc/os-release") if "=" in l).get("PRETTY_NAME", "").strip('"')
    runtime = os.environ.get("DATABRICKS_RUNTIME_VERSION", "")
    detail = (f"environment {os.environ.get('DATABRICKS_ENV_VERSION', '?')} ({runtime or 'unknown runtime'}), "
              f"Python {platform.python_version()}, {platform.machine()}, {os_name}")
    if os.environ.get("IS_SERVERLESS", "").lower() not in ("true", "1") and not runtime.startswith("client."):
        raise Warn(f"not serverless ({detail}). The lab was tested on serverless.")
    return detail


@check("Python packages (PyPI)", "Allow serverless compute to reach PyPI, or a PyPI mirror. The lab's first cell installs the same packages.")
def _():
    import importlib.metadata as md
    sdk = md.version("databricks-sdk")
    if tuple(int(x) for x in sdk.split(".")[:2]) < (0, 81):
        raise RuntimeError(f"databricks-sdk {sdk} is older than 0.81, so it has no Lakebase API")
    return f"databricks-sdk {sdk}, psycopg {md.version('psycopg')}, protobuf {md.version('protobuf')}"


def install_pg_client(version=PG_VERSION):
    """Fetch postgresql-client-<version> and libpq5 from apt.postgresql.org and unpack them locally (the lab's installer)."""
    os_release = dict(line.strip().split("=", 1) for line in open("/etc/os-release") if "=" in line)
    codename = os_release["VERSION_CODENAME"].strip('"')
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    repo = "https://apt.postgresql.org/pub/repos/apt"
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
    root = Path(tempfile.mkdtemp(prefix="pgclient-"))
    for package, filename in wanted.items():
        deb = root / Path(filename).name
        urllib.request.urlretrieve(f"{repo}/{filename}", deb)
        subprocess.run(["dpkg-deb", "-x", str(deb), str(root / "files")], check=True)
    bin_dir = root / "files" / "usr" / "lib" / "postgresql" / str(version) / "bin"
    lib_dir = next((root / "files" / "usr" / "lib").glob("*-linux-gnu"))
    return bin_dir, lib_dir


@check("PostgreSQL client tools (apt.postgresql.org)",
       "Allow serverless compute to reach apt.postgresql.org over HTTPS. Your workspace admin manages serverless network access.")
def _():
    global PG_BIN, PG_LIB, PG_ENV
    PG_BIN, PG_LIB = install_pg_client()
    PG_ENV = dict(os.environ, LD_LIBRARY_PATH=str(PG_LIB))
    return "; ".join(subprocess.run([str(PG_BIN / tool), "--version"], env=PG_ENV, capture_output=True,
                                    text=True, check=True).stdout.strip() for tool in ("pg_dump", "pg_restore"))


@check("psycopg on the downloaded libpq", "This is how the lab loads psycopg. Send the error to the lab's owner.",
       needs=("PostgreSQL client tools (apt.postgresql.org)", "Python packages (PyPI)"))
def _():
    global psycopg
    # psycopg's pure-Python mode finds libpq by asking ctypes for "pq". Answer with the copy we unpacked.
    os.environ["PSYCOPG_IMPL"] = "python"
    _find_library = ctypes.util.find_library
    ctypes.util.find_library = lambda name: str(PG_LIB / "libpq.so.5") if name == "pq" else _find_library(name)
    try:
        import psycopg as loaded
    finally:
        ctypes.util.find_library = _find_library
    psycopg = loaded
    return f"psycopg {psycopg.__version__} ({psycopg.pq.__impl__} mode), libpq {psycopg.pq.version()}"


@check(SDK_CHECK, "Lakebase has to be available in this workspace's region, and you need permission to use it. Ask your workspace admin.",
       needs=("Python packages (PyPI)",))
def _():
    global w, me, USER, slug
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    me = w.current_user.me()
    USER = me.user_name
    slug = re.sub(r"[^a-z0-9]+", "-", USER.split("@")[0].lower()).strip("-")[:16].rstrip("-") or "user"  # the lab's naming
    visible = sum(1 for _ in w.postgres.list_projects())
    return f"signed in as {USER}; the Lakebase API answered ({visible} project(s) visible to you)"


@check("Databricks CLI (github.com)",
       "Allow serverless compute to reach github.com over HTTPS. The lab downloads the CLI from there for its bundle steps.")
def _():
    global CLI, CLI_DIR
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    url = f"https://github.com/databricks/cli/releases/download/v{CLI_VERSION}/databricks_cli_{CLI_VERSION}_linux_{arch}.zip"
    CLI_DIR = Path(tempfile.mkdtemp(prefix="dbcli-"))
    with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())) as z:
        z.extract("databricks", CLI_DIR)
    CLI = CLI_DIR / "databricks"
    CLI.chmod(0o755)
    return subprocess.run([str(CLI), "--version"], capture_output=True, text=True, check=True).stdout.strip()


def cli(*args, cwd=None):
    """Run the Databricks CLI as you. Its token comes from this notebook's sign-in and is never printed."""
    auth = w.config.authenticate().get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise RuntimeError("couldn't get a token for the CLI from this notebook's sign-in")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(CLI_DIR),
           "DATABRICKS_HOST": w.config.host, "DATABRICKS_TOKEN": auth.split(" ", 1)[1]}
    result = subprocess.run([str(CLI), *args], env=env, cwd=cwd, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


@check("CLI signs in as you", "The CLI signs in with this notebook's own sign-in. Send the error to the lab's owner.",
       needs=("Databricks CLI (github.com)", SDK_CHECK))
def _():
    rc, out = cli("current-user", "me", "-o", "json")
    if rc:
        raise RuntimeError(tail(out))
    name = json.loads(out)["userName"]
    if name != USER:
        raise RuntimeError(f"the CLI signed in as {name}, not {USER}")
    return f"signed in as {name}"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Leftovers from an earlier lab run
# MAGIC
# MAGIC The lab names its projects, schema, and bundle folder after you, and expects to start clean. If an earlier run didn't reach its cleanup module, this check finds what's left. Set `CLEAN_LEFTOVERS = True` in the settings cell and run the check again to delete them.

# COMMAND ----------

# DBTITLE 1,Leftovers from an earlier lab run
"""Look for the projects, schema, and bundle folder an earlier lab run would leave behind."""
SDK_OK = SDK_CHECK in PASSED


def project_exists(pid):
    return any(p.name == f"projects/{pid}" for p in w.postgres.list_projects())


def folder_exists(path):
    try:
        w.workspace.get_status(path)
        return True
    except Exception:
        return False


def schema_exists(full_name):
    try:
        w.schemas.get(full_name)
        return True
    except Exception:
        return False


if SDK_OK:
    LAB_PROJECTS = [f"lb-move-old-{slug}-{me.id}", f"lb-move-new-{slug}-{me.id}"]
    LAB_SCHEMA = f"{CATALOG}.lb_move_{slug.replace('-', '_')}"
    LAB_BUNDLE_ROOT = f"/Workspace/Users/{USER}/.bundle/lb-move-lab"


@check("No leftovers from an earlier lab run",
       "Run the lab's Module 7 (clean up), or set CLEAN_LEFTOVERS = True in this notebook's settings cell and run the check again.",
       needs=(SDK_CHECK,))
def _():
    found = [f"project {pid}" for pid in LAB_PROJECTS if project_exists(pid)]
    found += [f"schema {LAB_SCHEMA}"] if schema_exists(LAB_SCHEMA) else []
    found += [f"bundle folder {LAB_BUNDLE_ROOT}"] if folder_exists(LAB_BUNDLE_ROOT) else []
    if not found:
        return "nothing found"
    if not CLEAN_LEFTOVERS:
        raise RuntimeError("found " + ", ".join(found) + ". The lab would trip over them instead of starting clean.")
    try:
        w.postgres.delete_synced_table(name=f"synced_tables/{LAB_SCHEMA}.product_catalog_synced").wait()
    except Exception:
        pass
    for pid in LAB_PROJECTS:
        if project_exists(pid):
            w.postgres.delete_project(name=f"projects/{pid}", purge=True).wait()
    if schema_exists(LAB_SCHEMA):
        spark.sql(f"DROP SCHEMA IF EXISTS {LAB_SCHEMA} CASCADE")
    if folder_exists(LAB_BUNDLE_ROOT):
        w.workspace.delete(LAB_BUNDLE_ROOT, recursive=True)
    return "deleted " + ", ".join(found)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Lakebase: the steps the lab relies on
# MAGIC
# MAGIC A bundle deploys a throwaway project the way the lab builds its new home: the project, an adopted `production` branch, and a `development` branch with its own compute. Then the check connects with a login token, creates a second database, sets up roles and grants with the lab's own SQL, runs `pg_dump` and a filtered `pg_restore` into the second database, and tries a point-in-time branch and a snapshot.

# COMMAND ----------

# DBTITLE 1,Lakebase: bundle, connection, databases, roles, dump and restore, branches, snapshots
"""Deploy a throwaway project with a bundle, then try each Lakebase step the lab uses on it."""
from databricks.sdk.service.postgres import (
    Branch,
    BranchSpec,
    Duration,
    Endpoint,
    EndpointSpec,
    EndpointType,
    Snapshot,
    SnapshotSpec,
    Timestamp,
)

BUNDLE_CHECK, CONNECT_CHECK = "Bundle deploys a Lakebase project", "Connect with a login token"
DB, SECOND_DB = "databricks_postgres", "reporting"
PLATFORM = re.compile(r" (cloud_admin|databricks_control_plane)$|__db_system")  # the lab's filter
BUNDLE_DIR = Path(tempfile.mkdtemp(prefix="lb_pre_bundle_"))
WORK_DIR = Path(tempfile.mkdtemp(prefix="lb_pre_"))
if SDK_OK:
    PRE_ID = f"lb-move-pre-{slug}-{me.id}"
    PRE_BUNDLE = "lb-move-lab-preflight"
    PRE_BUNDLE_ROOT = f"/Workspace/Users/{USER}/.bundle/{PRE_BUNDLE}"
    # Clear out anything a crashed earlier preflight left behind. These are this check's own names.
    if project_exists(PRE_ID):
        w.postgres.delete_project(name=f"projects/{PRE_ID}", purge=True).wait()
        print("Removed a project an earlier preflight left behind")
    if folder_exists(PRE_BUNDLE_ROOT):
        w.workspace.delete(PRE_BUNDLE_ROOT, recursive=True)


def write_bundle(guard=True):
    """The lab's bundle shape, for the throwaway project. guard=True adds lifecycle.prevent_destroy."""
    lifecycle = "\n      lifecycle: { prevent_destroy: true }" if guard else ""
    (BUNDLE_DIR / "databricks.yml").write_text(f"""bundle:
  name: {PRE_BUNDLE}

targets:
  preflight:
    default: true
    workspace:
      host: {w.config.host}

resources:
  postgres_projects:
    app:
      project_id: {PRE_ID}
      pg_version: {PG_VERSION}
      history_retention_duration: 604800s
      purge_on_delete: true{lifecycle}

  postgres_branches:
    production:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: production
      replace_existing: true{lifecycle}
    development:
      parent: ${{resources.postgres_projects.app.id}}
      branch_id: development
      source_branch: ${{resources.postgres_branches.production.id}}
      no_expiry: true

  postgres_endpoints:
    development_primary:
      parent: ${{resources.postgres_branches.development.id}}
      endpoint_id: primary
      endpoint_type: ENDPOINT_TYPE_READ_WRITE
      replace_existing: true
""")


def endpoint_of(branch, timeout=300):
    """Find the branch's compute and wait until it has a host. Creates one if none shows up (the lab's helper)."""
    parent = f"projects/{PRE_ID}/branches/{branch}"
    started, created = time.time(), False
    while True:
        endpoints = list(w.postgres.list_endpoints(parent=parent))
        for ep in endpoints:
            if ep.status and ep.status.hosts and ep.status.hosts.host:
                return ep.name, ep.status.hosts.host
        if not endpoints and not created and time.time() - started > 60:
            w.postgres.create_endpoint(
                parent=parent,
                endpoint=Endpoint(spec=EndpointSpec(endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                                                    autoscaling_limit_min_cu=0.5, autoscaling_limit_max_cu=2.0)),
                endpoint_id="primary",
            ).wait()
            created = True
        if time.time() - started > timeout:
            raise TimeoutError(f"no compute with a host on {parent}")
        time.sleep(5)


def connect(branch, dbname=DB):
    """Open a Postgres connection with a fresh login token. Retries while the compute wakes up."""
    endpoint, host = endpoint_of(branch)
    token = w.postgres.generate_database_credential(endpoint=endpoint).token
    for attempt in range(6):
        try:
            return psycopg.connect(host=host, dbname=dbname, user=USER, password=token,
                                   sslmode="require", connect_timeout=30, autocommit=True)
        except psycopg.OperationalError:
            if attempt == 5:
                raise
            time.sleep(10)


def run_pg(tool, branch, args, dbname=DB):
    """Run pg_dump or pg_restore against one database. The token goes in the environment, never on screen."""
    endpoint, host = endpoint_of(branch)
    token = w.postgres.generate_database_credential(endpoint=endpoint).token
    env = dict(PG_ENV, PGHOST=host, PGPORT="5432", PGUSER=USER, PGPASSWORD=token, PGDATABASE=dbname, PGSSLMODE="require")
    result = subprocess.run([str(PG_BIN / tool), *args], env=env, capture_output=True, text=True)
    return result.returncode, result.stderr.strip()


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


@check(BUNDLE_CHECK,
       "You need permission to create Lakebase projects, and your home folder has to be writable (bundles keep their "
       "state in ~/.bundle). The error says which; ask your workspace admin for the permission it names.",
       needs=("CLI signs in as you",))
def _():
    global DEPLOYED_AT
    write_bundle(guard=True)
    for args in (["bundle", "validate"], ["bundle", "deploy"]):
        rc, out = cli(*args, cwd=BUNDLE_DIR)
        if rc:
            raise RuntimeError(f"databricks {' '.join(args)}: {tail(out)}")
    DEPLOYED_AT = time.time()
    created = re.search(r"Resources: (\d+) created", out)
    return f"{PRE_ID}: {created.group(1) if created else 'all'} resources created (project, production, development, and its compute)"


@check(CONNECT_CHECK,
       "Serverless compute has to reach the Lakebase endpoint on port 5432. A timeout points at the serverless network "
       "policy; an authentication error should go to the lab's owner.",
       needs=(BUNDLE_CHECK, "psycopg on the downloaded libpq"))
def _():
    with connect("production") as conn:
        user, version = conn.execute("SELECT current_user, current_setting('server_version')").fetchone()
    return f"connected as {user}, Postgres {version}"


@check("Create a second database", "The move creates databases on the new side. Send the error to the lab's owner.",
       needs=(CONNECT_CHECK,))
def _():
    with connect("production") as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (SECOND_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{SECOND_DB}"')
    return f"created {SECOND_DB} next to {DB}"


@check("Roles, ownership, and grants", "The lab rebuilds access with this SQL. Send the error to the lab's owner.",
       needs=(CONNECT_CHECK,))
def _():
    with connect("production") as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS app")
        conn.execute("CREATE TABLE IF NOT EXISTS app.items (id int PRIMARY KEY, name text NOT NULL)")
        conn.execute("INSERT INTO app.items SELECT g, 'item ' || g FROM generate_series(1, 100) g ON CONFLICT DO NOTHING")
        conn.execute(ROLES_SQL)
        conn.execute(GRANTS_SQL)
        conn.execute("SET ROLE app_owner")  # the lab runs migrations as the owner role
        conn.execute("CREATE TABLE IF NOT EXISTS app.made_by_owner (id int)")
        conn.execute("RESET ROLE")
        owner, readable = conn.execute(
            "SELECT pg_get_userbyid(relowner), has_table_privilege('app_reader', oid, 'SELECT') "
            "FROM pg_class WHERE oid = 'app.made_by_owner'::regclass").fetchone()
    if owner != "app_owner" or not readable:
        raise RuntimeError(f"a table made as app_owner is owned by {owner}, readable by app_reader: {readable}")
    return "migrations can run as app_owner, and app_reader can read the tables they create"


@check("pg_dump and a filtered pg_restore", "This is the move itself. Send the error to the lab's owner.",
       needs=("Create a second database", "Roles, ownership, and grants"))
def _():
    dump, toc = WORK_DIR / "preflight.dump", WORK_DIR / "preflight.toc"
    rc, err = run_pg("pg_dump", "production", ["-Fc", "-f", str(dump)])
    if rc:
        raise RuntimeError("pg_dump: " + tail(err))
    listing = subprocess.run([str(PG_BIN / "pg_restore"), "-l", str(dump)], env=PG_ENV,
                             capture_output=True, text=True, check=True).stdout.splitlines()
    filtered = sum(bool(PLATFORM.search(l)) for l in listing)
    toc.write_text("\n".join((";" + l) if PLATFORM.search(l) else l for l in listing) + "\n")
    rc, err = run_pg("pg_restore", "production", ["--no-owner", "--no-acl", "--single-transaction", "--exit-on-error",
                                                  "-L", str(toc), "-d", SECOND_DB, str(dump)], dbname=SECOND_DB)
    if rc:
        raise RuntimeError("pg_restore: " + tail(err))
    with connect("production", SECOND_DB) as conn:
        rows = conn.execute("SELECT count(*) FROM app.items").fetchone()[0]
    if rows != 100:
        raise RuntimeError(f"expected 100 rows in {SECOND_DB}, found {rows}")
    return f"filtered {filtered} of {len(listing)} dump entries; all 100 rows restored into {SECOND_DB}"


@check("Child branch and its compute", "The lab works on child branches. Send the error to the lab's owner.",
       needs=(BUNDLE_CHECK, "psycopg on the downloaded libpq"))
def _():
    with connect("development") as conn:
        conn.execute("SELECT 1")
    return "the bundle's development branch answered on its own compute"


@check("Point-in-time branch", "The lab shows point-in-time history with this. Send the error to the lab's owner.",
       needs=(CONNECT_CHECK,))
def _():
    when = max(time.time() - 3, DEPLOYED_AT + 2)  # a moment the project's history covers
    time.sleep(max(0.0, when + 2 - time.time()))
    w.postgres.create_branch(
        parent=f"projects/{PRE_ID}",
        branch=Branch(spec=BranchSpec(source_branch=f"projects/{PRE_ID}/branches/production",
                                      source_branch_time=Timestamp(seconds=int(when)), ttl=Duration(seconds=3600))),
        branch_id="preflight-pitr",
    ).wait()
    try:
        with connect("preflight-pitr") as conn:
            conn.execute("SELECT 1")
    finally:
        w.postgres.delete_branch(name=f"projects/{PRE_ID}/branches/preflight-pitr", purge=True).wait()
    return "created a branch from a past moment, connected to it, and deleted it"


@check("Snapshots", "Only a warning: the lab skips its snapshot demo when it can't create a snapshot.",
       needs=(BUNDLE_CHECK,))
def _():
    for attempt in range(3):
        try:
            w.postgres.create_snapshot(
                parent=f"projects/{PRE_ID}",
                snapshot=Snapshot(spec=SnapshotSpec(source_branch=f"projects/{PRE_ID}/branches/production",
                                                    ttl=Duration(seconds=86400))),
                snapshot_id="preflight",
            ).wait()
            break
        except Exception as e:
            if attempt == 2:
                raise Warn(f"couldn't create a snapshot in 3 tries ({brief(e, 150)}); "
                           "if that happens in the lab, it skips its snapshot demo")
            time.sleep(15)
    w.postgres.delete_snapshot(name=f"projects/{PRE_ID}/snapshots/preflight").wait()
    return "created and deleted a snapshot" + (f" (on try {attempt + 1})" if attempt else "")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Synced tables
# MAGIC
# MAGIC The lab syncs a small Delta table into Lakebase. This needs a catalog where you can create a schema and a table. If you can't, the lab still runs and skips its synced-table steps, so these two checks are warnings, not failures.

# COMMAND ----------

# DBTITLE 1,Synced table: a schema in your catalog, and a Delta table synced into Lakebase
"""Create a schema and a 10-row Delta table in the catalog, sync it into the throwaway project, and wait for the rows."""
from databricks.sdk.service.postgres import (
    SyncedTable,
    SyncedTableSyncedTableSpec,
    SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy,
)

SCHEMA_CHECK = f"Schema and Delta table in {CATALOG}"
if SDK_OK:
    PRE_SCHEMA = f"{CATALOG}.lb_move_pre_{slug.replace('-', '_')}"
    PRE_SOURCE, PRE_SYNCED = f"{PRE_SCHEMA}.preflight_source", f"{PRE_SCHEMA}.preflight_synced"


@check(SCHEMA_CHECK,
       f"Only a warning: without it the lab skips its synced-table steps. To include them, use a catalog where you can "
       f"create schemas (set it in the lab's CATALOG and this check's catalog widget), or ask for CREATE SCHEMA on {CATALOG}.",
       needs=(SDK_CHECK,))
def _():
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {PRE_SCHEMA}")
        spark.sql(f"""CREATE OR REPLACE TABLE {PRE_SOURCE} (
                        id BIGINT NOT NULL, name STRING, CONSTRAINT preflight_pk PRIMARY KEY (id))
                      TBLPROPERTIES (delta.enableChangeDataFeed = true)""")
        spark.sql(f"INSERT INTO {PRE_SOURCE} SELECT id, concat('row ', id) FROM range(1, 11)")
    except Exception as e:
        raise Warn(f"can't create a schema and table in {CATALOG} ({brief(e)}). The lab will skip its synced-table steps.")
    return f"created {PRE_SCHEMA} with a 10-row Delta table"


@check("Synced table into Lakebase",
       "Only a warning: without it the lab skips its synced-table steps. The error says why it failed.",
       needs=(SCHEMA_CHECK, CONNECT_CHECK))
def _():
    started = time.time()
    try:
        w.postgres.create_synced_table(
            synced_table=SyncedTable(spec=SyncedTableSyncedTableSpec(
                source_table_full_name=PRE_SOURCE,
                branch=f"projects/{PRE_ID}/branches/production",
                postgres_database=DB,
                primary_key_columns=["id"],
                scheduling_policy=SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy.SNAPSHOT,
                create_database_objects_if_missing=True)),
            synced_table_id=PRE_SYNCED).wait()
        pg_table = PRE_SYNCED.split(".", 1)[1]  # the schema.table name inside Postgres
        while True:
            status = w.postgres.get_synced_table(name=f"synced_tables/{PRE_SYNCED}").status
            state = str(status.detailed_state) if status else "unknown"
            try:
                with connect("production") as conn:
                    rows = conn.execute(f"SELECT count(*) FROM {pg_table}").fetchone()[0]
            except Exception:
                rows = 0
            if rows >= 10 and "ONLINE" in state:
                break
            if time.time() - started > 600:
                raise TimeoutError(f"state {state} and {rows} rows after 10 minutes")
            time.sleep(10)
    except Exception as e:
        raise Warn(f"couldn't sync a table ({brief(e)}). The lab will skip its synced-table steps.")
    return f"all 10 rows landed in Lakebase in {round(time.time() - started)} s"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Cleanup
# MAGIC
# MAGIC First the check confirms that `prevent_destroy` refuses a `bundle destroy`, as it will in the lab's last module. Then it takes the guard out, destroys the throwaway project with the bundle, and deletes the schema and the bundle folder. This cell runs even if earlier checks failed.

# COMMAND ----------

# DBTITLE 1,Cleanup: the guard, then delete everything this check created
"""Show that prevent_destroy blocks bundle destroy, then remove the guard and delete everything this check created."""
@check("prevent_destroy guards the bundle", "The lab's cleanup relies on this. Send the output to the lab's owner.",
       needs=(BUNDLE_CHECK,))
def _():
    write_bundle(guard=True)
    rc, out = cli("bundle", "destroy", "--auto-approve", cwd=BUNDLE_DIR)
    if rc == 0:
        raise RuntimeError("bundle destroy went through even with prevent_destroy set")
    if "prevent_destroy" not in out:
        raise RuntimeError(tail(out))
    return "bundle destroy refused, as it will in the lab's last module"


@check("Cleanup", "Delete what's left yourself; the detail lists it.")
def _():
    if not SDK_OK:
        return "nothing was created"
    problems = []
    try:
        w.postgres.delete_synced_table(name=f"synced_tables/{PRE_SYNCED}").wait()
    except Exception:
        pass
    if BUNDLE_CHECK in PASSED:
        write_bundle(guard=False)
        for args in (["bundle", "deploy"], ["bundle", "destroy", "--auto-approve"]):
            rc, out = cli(*args, cwd=BUNDLE_DIR)
            if rc:
                problems.append(f"databricks {' '.join(args)}: {tail(out, 2)}")
    if project_exists(PRE_ID):
        w.postgres.delete_project(name=f"projects/{PRE_ID}", purge=True).wait()
    try:
        spark.sql(f"DROP SCHEMA IF EXISTS {PRE_SCHEMA} CASCADE")
    except Exception as e:
        if "NOT_FOUND" not in str(e) and "NO_SUCH" not in str(e):
            problems.append(f"schema: {str(e)[:120]}")
    if folder_exists(PRE_BUNDLE_ROOT):
        w.workspace.delete(PRE_BUNDLE_ROOT, recursive=True)
    for folder in (WORK_DIR, BUNDLE_DIR):
        shutil.rmtree(folder, ignore_errors=True)
    left = [name for name, there in ((f"project {PRE_ID}", project_exists(PRE_ID)),
                                     (f"schema {PRE_SCHEMA}", schema_exists(PRE_SCHEMA)),
                                     (f"folder {PRE_BUNDLE_ROOT}", folder_exists(PRE_BUNDLE_ROOT))) if there]
    if left:
        raise RuntimeError("still there: " + ", ".join(left) + ("; " + "; ".join(problems) if problems else ""))
    return "deleted the throwaway project, synced table, schema, and bundle folder"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Summary
# MAGIC
# MAGIC Every check, its result, and the fix for anything that isn't ✅. The notebook also returns these results, so Genie Code or a job can read them.

# COMMAND ----------

# DBTITLE 1,Summary
"""Show every check with its result and fix, print the verdict, and return the results to whoever ran this notebook."""
fails = [r for r in RESULTS if r["status"] == "fail"]
warns = [r for r in RESULTS if r["status"] == "warn"]
VERDICT = "not ready" if fails else ("ready with notes" if warns else "ready")
summary = pd.DataFrame(RESULTS)
summary.insert(1, "result", summary.status.map(lambda s: f"{ICON[s]} {s}"))
display(summary[["check", "result", "detail", "fix", "seconds"]])
print({
    "ready": "✅ Ready for the lab.",
    "ready with notes": "⚠️ Ready for the lab, with the notes above.",
    "not ready": f"❌ Not ready: fix the {len(fails)} item(s) marked ❌, then run this check again.",
}[VERDICT])
dbutils.notebook.exit(json.dumps({"verdict": VERDICT, "user": globals().get("USER"), "catalog": CATALOG, "results": RESULTS}))

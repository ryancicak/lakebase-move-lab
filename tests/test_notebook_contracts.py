# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Check notebook helpers without compute, credentials, or database connections."""

import ast
import contextlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ("lakebase_move_lab.py", "lakebase_move_lab_preflight.py")
AWS = "https://dbc-7bae415f-6ff0.cloud.databricks.com"
AZURE = "https://adb-984752964297111.11.azuredatabricks.net"
HOST = "ep-example.database.us-west-2.cloud.databricks.com"
ROUTE_ERRORS = (
    "External authorization failed",
    'server certificate for "*.database.cloud.databricks.com" does not match host name "ep-azure.example"',
)


def source(name):
    return (ROOT / name).read_text()


def load_function(notebook, name, namespace):
    tree = ast.parse(source(notebook))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, notebook, "exec"), namespace)
    return namespace[name]


class NotebookSyntaxTests(unittest.TestCase):
    def test_every_python_cell_parses_on_python_310(self):
        for notebook in NOTEBOOKS:
            for number, cell in enumerate(source(notebook).split("# COMMAND ----------"), 1):
                with self.subTest(notebook=notebook, cell=number):
                    ast.parse(cell, feature_version=(3, 10))

    def test_notebook_header_is_preserved(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                self.assertTrue(source(notebook).startswith("# Databricks notebook source\n"))


class WorkspaceUrlTests(unittest.TestCase):
    def test_workspace_addresses_and_browser_links(self):
        cases = {
            AWS + "/": AWS,
            AZURE: AZURE,
            AZURE.removeprefix("https://") + "/": AZURE,
            AZURE + "/editor/notebooks/123?o=984752964297111": AZURE,
            "https://example.1.gcp.databricks.com/?o=123": "https://example.1.gcp.databricks.com",
        }
        for notebook in NOTEBOOKS:
            normalize = load_function(notebook, "workspace_url", {"urlsplit": urlsplit})
            for value, expected in cases.items():
                with self.subTest(notebook=notebook, value=value):
                    self.assertEqual(normalize(value), expected)

    def test_rejects_non_workspace_destinations(self):
        cases = (
            "",
            "http://" + AZURE.removeprefix("https://"),
            "https://github.com/ryancicak/lakebase-move-lab",
            AZURE + ".example.com",
            "https://accounts.cloud.databricks.com",
            "https://accounts.azuredatabricks.net",
            "https://user:password@" + AZURE.removeprefix("https://"),
            AZURE + ":8443",
        )
        for notebook in NOTEBOOKS:
            normalize = load_function(notebook, "workspace_url", {"urlsplit": urlsplit})
            for value in cases:
                with self.subTest(notebook=notebook, value=value):
                    with self.assertRaises(ValueError):
                        normalize(value)


class FakeWidgets:
    def __init__(self, values):
        self.values = dict(values)

    def dropdown(self, name, default, choices, label):
        self.values.setdefault(name, default)

    def text(self, name, default, label):
        self.values.setdefault(name, default)

    def get(self, name):
        return self.values[name]


class SetupGuardTests(unittest.TestCase):
    def run_setup(self, values, state, notebook=NOTEBOOKS[0], secrets=None):
        secrets = secrets or {}
        workspace = MagicMock()
        workspace.current_user.me.return_value = types.SimpleNamespace(
            user_name="sam.learner@example.com", id="42")
        workspace.secrets.list_scopes.return_value = (
            [types.SimpleNamespace(name="lb-move-lab-sam-learner-42")] if secrets else [])
        workspace.secrets.list_secrets.return_value = [types.SimpleNamespace(key=key) for key in secrets]
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = MagicMock(return_value=workspace)
        namespace = dict(state, dbutils=types.SimpleNamespace(
            widgets=FakeWidgets(values),
            secrets=types.SimpleNamespace(get=MagicMock(side_effect=lambda scope, key: secrets[key]))))
        cell = next(cell for cell in source(notebook).split("# COMMAND ----------")
                    if "# DBTITLE 1,Choose your setup" in cell)
        output, error = io.StringIO(), None
        with patch.dict(sys.modules, {"databricks.sdk": sdk}), contextlib.redirect_stdout(output):
            try:
                exec(compile(cell, notebook, "exec"), namespace)
            except (RuntimeError, ValueError) as caught:
                error = caught
        workspace.setup_output = output.getvalue()
        return workspace, error

    def test_cannot_change_workspace_mode_after_resources_exist(self):
        workspace, error = self.run_setup(
            {"where": "Another workspace", "other_url": AZURE, "catalog": "main"},
            {"LAB_CREATED": {"old"}, "WHERE": "This workspace", "OTHER_URL": ""})
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("Module 7", str(error))
        workspace.secrets.create_scope.assert_not_called()
        workspace.secrets.put_secret.assert_not_called()

    def test_cannot_change_destination_after_resources_exist(self):
        workspace, error = self.run_setup(
            {"where": "Another workspace", "other_url": AZURE, "catalog": "main"},
            {"LAB_CREATED": {"old"}, "WHERE": "Another workspace", "OTHER_URL": AWS})
        self.assertIsInstance(error, RuntimeError)
        workspace.secrets.create_scope.assert_not_called()
        workspace.secrets.put_secret.assert_not_called()

    def test_same_workspace_defaults_need_no_secrets(self):
        workspace, error = self.run_setup(
            {"where": "This workspace", "other_url": "", "catalog": "main"}, {})
        self.assertIsNone(error)
        workspace.secrets.create_scope.assert_not_called()
        workspace.secrets.put_secret.assert_not_called()

    def test_invalid_url_cannot_be_saved(self):
        workspace, error = self.run_setup(
            {"where": "Another workspace", "other_url": "https://example.com", "catalog": "main"}, {})
        self.assertIsInstance(error, ValueError)
        workspace.secrets.create_scope.assert_not_called()
        workspace.secrets.put_secret.assert_not_called()

    def test_empty_token_is_not_saved(self):
        with patch("getpass.getpass", return_value="   "):
            workspace, error = self.run_setup(
                {"where": "Another workspace", "other_url": AZURE, "catalog": "main"}, {})
        self.assertIsInstance(error, ValueError)
        self.assertIn("token box was empty", str(error))
        self.assertEqual([call.kwargs["key"] for call in workspace.secrets.put_secret.call_args_list], ["host"])

    def test_neither_setup_can_retarget_shared_credentials(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                workspace, error = self.run_setup(
                    {"where": "Another workspace", "other_url": AZURE, "catalog": "main"}, {},
                    notebook=notebook, secrets={"host": AWS, "token": "test-token"})
                self.assertIn("already points to a different workspace",
                              str(error) if error else workspace.setup_output)
                workspace.secrets.create_scope.assert_not_called()
                workspace.secrets.put_secret.assert_not_called()

    def test_saved_destination_can_be_reused_in_both_notebooks(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                workspace, error = self.run_setup(
                    {"where": "Another workspace", "other_url": AZURE + "/", "catalog": "main"}, {},
                    notebook=notebook, secrets={"host": AZURE, "token": "test-token"})
                self.assertIsNone(error)
                self.assertIn("signed in as", workspace.setup_output)
                workspace.secrets.put_secret.assert_called_once_with(
                    scope="lb-move-lab-sam-learner-42", key="host", string_value=AZURE)

    def test_preflight_does_not_save_an_empty_token(self):
        with patch("getpass.getpass", return_value=""):
            workspace, error = self.run_setup(
                {"where": "Another workspace", "other_url": AZURE, "catalog": "main"}, {},
                notebook=NOTEBOOKS[1])
        self.assertIsNone(error)  # preflight reports the setup problem instead of stopping
        self.assertIn("token box was empty", workspace.setup_output)
        self.assertEqual([call.kwargs["key"] for call in workspace.secrets.put_secret.call_args_list], ["host"])


class StoredDestinationTests(unittest.TestCase):
    def sign_in(self, notebook, saved_host, widget_url):
        secrets = {"host": saved_host, "token": "test-token"}
        factory = MagicMock()
        namespace = {
            "WorkspaceClient": factory, "OTHER_URL": widget_url, "NEW_SCOPE": "lab-scope",
            "answer": lambda name, default: widget_url,
            "urlsplit": urlsplit,
            "dbutils": types.SimpleNamespace(
                secrets=types.SimpleNamespace(get=lambda scope, key: secrets[key])),
        }
        if notebook == NOTEBOOKS[0]:
            function = load_function(notebook, "sign_in_elsewhere", namespace)
            return factory, lambda: function("lab-scope")
        cell = next(cell for cell in source(notebook).split("# COMMAND ----------")
                    if "# DBTITLE 1,Second workspace: sign-in" in cell)
        function = next(node for node in ast.walk(ast.parse(cell))
                        if isinstance(node, ast.FunctionDef)
                        and any(isinstance(decorator, ast.Call)
                                and isinstance(decorator.args[0], ast.Name)
                                and decorator.args[0].id == "NEW_SIGN_IN"
                                for decorator in node.decorator_list))
        function.decorator_list = []
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     notebook, "exec"), namespace)
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = factory

        def invoke():
            with patch.dict(sys.modules, {"databricks.sdk": sdk}):
                return namespace["_"]()

        return factory, invoke

    def test_changed_saved_host_is_rejected_before_sign_in(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                factory, invoke = self.sign_in(notebook, AWS, AZURE)
                with self.assertRaisesRegex(RuntimeError, "doesn't match box 2"):
                    invoke()
                factory.assert_not_called()

    def test_browser_links_and_schemeless_urls_match_the_saved_host(self):
        for notebook in NOTEBOOKS:
            for value in (AZURE + "/editor/notebooks/123", AZURE.removeprefix("https://") + "/"):
                with self.subTest(notebook=notebook, value=value):
                    factory, invoke = self.sign_in(notebook, AZURE, value)
                    invoke()
                    self.assertEqual(factory.call_args.kwargs["host"], AZURE)


class TokenInputTests(unittest.TestCase):
    def test_a_job_gets_storage_instructions(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                ask = load_function(notebook, "ask_for_token", {
                    "getpass": types.SimpleNamespace(getpass=MagicMock(side_effect=RuntimeError("no stdin"))),
                    "scope": "lab-scope",
                })
                with self.assertRaisesRegex(RuntimeError, "put-secret lab-scope token"):
                    ask("Token:")

    def test_hidden_input_trims_a_nonempty_token(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                ask = load_function(notebook, "ask_for_token", {
                    "getpass": types.SimpleNamespace(getpass=MagicMock(return_value=" test-token ")),
                })
                self.assertEqual(ask("Token:"), "test-token")

    def test_hidden_input_rejects_an_empty_token(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                ask = load_function(notebook, "ask_for_token", {
                    "getpass": types.SimpleNamespace(getpass=MagicMock(return_value="")),
                })
                with self.assertRaisesRegex(ValueError, "token box was empty"):
                    ask("Token:")


class PreflightCleanupTests(unittest.TestCase):
    def run_cleanup(self, second_workspace):
        tree = ast.parse(source(NOTEBOOKS[1]))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and any(isinstance(decorator, ast.Call)
                                and isinstance(decorator.args[0], ast.Constant)
                                and decorator.args[0].value == "Cleanup"
                                for decorator in node.decorator_list))
        function.decorator_list = []
        namespace = {
            "SDK_OK": True, "w": MagicMock(), "w_new": MagicMock() if second_workspace else None,
            "NEW_SCOPE": "lab-test-scope", "NEW_USER": "learner", "PRE_ID": "pre-test",
            "PRE_SYNCED": "catalog.schema.sync", "PRE_SCHEMA": "catalog.schema",
            "PRE_BUNDLE": "pre-bundle", "PRE_BUNDLE_ROOT": "/Workspace/Users/learner/.bundle/pre-bundle",
            "BUNDLE_CHECK": "bundle-check", "NEW_BUNDLE": "new-bundle-check",
            "PASSED": {"bundle-check", "new-bundle-check"},
            "WORK_DIR": Path("/test/work"), "BUNDLE_DIR": Path("/test/bundle"),
            "BUNDLE_DIR_NEW": Path("/test/new-bundle"), "shutil": MagicMock(),
            "project_exists": MagicMock(return_value=False), "folder_exists": MagicMock(return_value=False),
            "schema_exists": MagicMock(return_value=False), "spark": MagicMock(),
            "write_bundle": MagicMock(), "cli": MagicMock(return_value=(0, "")),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     NOTEBOOKS[1], "exec"), namespace)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = namespace["_"]()
        return namespace, output.getvalue(), result

    def test_second_workspace_cleanup_works_after_python_restart(self):
        namespace, output, result = self.run_cleanup(second_workspace=True)
        self.assertIn("secret scope lab-test-scope", output)
        self.assertIn("in both workspaces", result)
        self.assertEqual(namespace["cli"].call_count, 3)
        namespace["w"].secrets.delete_scope.assert_not_called()

    def test_same_workspace_cleanup_needs_no_secret_scope(self):
        namespace, output, result = self.run_cleanup(second_workspace=False)
        self.assertNotIn("secret scope", output)
        self.assertNotIn("both workspaces", result)
        self.assertEqual(namespace["cli"].call_count, 2)


class TlsTests(unittest.TestCase):
    def namespace(self):
        workspace = MagicMock()
        workspace.postgres.generate_database_credential.return_value = types.SimpleNamespace(token="test-token")
        other = MagicMock()
        other.postgres.generate_database_credential.return_value = types.SimpleNamespace(token="test-token")
        return {
            "DB": "databricks_postgres", "USER": "learner", "NEW_USER": "learner",
            "NEW_ID": "new", "TWO_WORKSPACES": False, "ROUTES": {},
            "login": MagicMock(return_value=(HOST, "test-token")),
            "endpoint_of": MagicMock(return_value=("endpoint", HOST)),
            "pg_user": MagicMock(return_value="learner"),
            "w": workspace, "w_new": other, "psycopg": types.SimpleNamespace(
                connect=MagicMock(), OperationalError=ConnectionError),
            "time": MagicMock(), "public_address": MagicMock(return_value="203.0.113.10"),
            "PG_BIN": Path("/test/bin"), "PG_ENV": {"PGSSLMODE": "require"},
            "BUNDLE_DIR": Path("/test/bundle"), "subprocess": MagicMock(),
        }

    def test_connections_verify_the_host_with_system_trust(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                connect = load_function(notebook, "connect", namespace)
                if notebook == NOTEBOOKS[0]:
                    connect("old", "production")
                else:
                    connect("production")
                options = namespace["psycopg"].connect.call_args.kwargs
                self.assertEqual(options["host"], HOST)
                self.assertEqual(options["sslmode"], "verify-full")
                self.assertEqual(options["sslrootcert"], "system")
                self.assertTrue(options["autocommit"])

    def test_public_route_keeps_host_verification(self):
        for notebook in NOTEBOOKS:
            for error in ROUTE_ERRORS:
                with self.subTest(notebook=notebook, error=error):
                    namespace = self.namespace()
                    namespace["TWO_WORKSPACES"] = True
                    namespace["psycopg"].connect.side_effect = (ConnectionError(error), MagicMock())
                    connect = load_function(notebook, "connect", namespace)
                    with contextlib.redirect_stdout(io.StringIO()):
                        if notebook == NOTEBOOKS[0]:
                            connect("new", "production")
                        else:
                            connect("production", ws=namespace["w_new"])
                    options = namespace["psycopg"].connect.call_args.kwargs
                    self.assertEqual(options["host"], HOST)
                    self.assertEqual(options["hostaddr"], "203.0.113.10")
                    self.assertEqual(options["sslmode"], "verify-full")
                    self.assertEqual(options["sslrootcert"], "system")
                    namespace["public_address"].assert_called_once_with(HOST)

    def test_same_workspace_does_not_switch_routes(self):
        for notebook in NOTEBOOKS:
            for error in ROUTE_ERRORS:
                with self.subTest(notebook=notebook, error=error):
                    namespace = self.namespace()
                    namespace["psycopg"].connect.side_effect = ConnectionError(error)
                    connect = load_function(notebook, "connect", namespace)
                    with self.assertRaises(ConnectionError):
                        if notebook == NOTEBOOKS[0]:
                            connect("old", "production")
                        else:
                            connect("production")
                    namespace["public_address"].assert_not_called()

    def test_other_tls_errors_do_not_switch_routes(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["TWO_WORKSPACES"] = True
                namespace["psycopg"].connect.side_effect = ConnectionError("SSL error: certificate verify failed")
                connect = load_function(notebook, "connect", namespace)
                with self.assertRaises(ConnectionError):
                    if notebook == NOTEBOOKS[0]:
                        connect("new", "production")
                    else:
                        connect("production", ws=namespace["w_new"])
                namespace["public_address"].assert_not_called()

    def test_public_route_does_not_relax_tls_on_another_failure(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["TWO_WORKSPACES"] = True
                namespace["psycopg"].connect.side_effect = ConnectionError(ROUTE_ERRORS[1])
                connect = load_function(notebook, "connect", namespace)
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ConnectionError):
                    if notebook == NOTEBOOKS[0]:
                        connect("new", "production")
                    else:
                        connect("production", ws=namespace["w_new"])
                namespace["public_address"].assert_called_once_with(HOST)
                for call in namespace["psycopg"].connect.call_args_list:
                    self.assertEqual(call.kwargs["host"], HOST)
                    self.assertEqual(call.kwargs["sslmode"], "verify-full")
                    self.assertEqual(call.kwargs["sslrootcert"], "system")

    def test_public_route_is_tried_even_on_the_last_retry(self):
        for notebook in NOTEBOOKS:
            for error in ROUTE_ERRORS:
                with self.subTest(notebook=notebook, error=error):
                    namespace = self.namespace()
                    namespace["TWO_WORKSPACES"] = True
                    connection = MagicMock()
                    namespace["psycopg"].connect.side_effect = [
                        *[ConnectionError("compute is paused") for _ in range(5)],
                        ConnectionError(error), connection,
                    ]
                    connect = load_function(notebook, "connect", namespace)
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = (connect("new", "production") if notebook == NOTEBOOKS[0]
                                  else connect("production", ws=namespace["w_new"]))
                    self.assertIs(result, connection)
                    self.assertEqual(namespace["psycopg"].connect.call_count, 7)
                    namespace["public_address"].assert_called_once_with(HOST)
                    self.assertEqual(namespace["psycopg"].connect.call_args.kwargs["hostaddr"], "203.0.113.10")

    def test_retry_exhaustion_raises_instead_of_returning_none(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["TWO_WORKSPACES"] = True
                namespace["psycopg"].connect.side_effect = ConnectionError("compute is paused")
                connect = load_function(notebook, "connect", namespace)
                with self.assertRaises(ConnectionError):
                    if notebook == NOTEBOOKS[0]:
                        connect("new", "production")
                    else:
                        connect("production", ws=namespace["w_new"])
                self.assertEqual(namespace["psycopg"].connect.call_count, 6)
                namespace["public_address"].assert_not_called()

    def test_cached_public_route_is_reused(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["TWO_WORKSPACES"] = True
                namespace["ROUTES"][HOST] = "203.0.113.10"
                connect = load_function(notebook, "connect", namespace)
                if notebook == NOTEBOOKS[0]:
                    connect("new", "production")
                else:
                    connect("production", ws=namespace["w_new"])
                namespace["public_address"].assert_not_called()
                self.assertEqual(namespace["psycopg"].connect.call_args.kwargs["hostaddr"], "203.0.113.10")
                self.assertEqual(namespace["psycopg"].connect.call_args.kwargs["sslmode"], "verify-full")

    def test_successful_normal_route_is_cached_without_an_ip(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["TWO_WORKSPACES"] = True
                connect = load_function(notebook, "connect", namespace)
                if notebook == NOTEBOOKS[0]:
                    connect("new", "production")
                else:
                    connect("production", ws=namespace["w_new"])
                self.assertIn(HOST, namespace["ROUTES"])
                self.assertIsNone(namespace["ROUTES"][HOST])
                namespace["psycopg"].connect.side_effect = ConnectionError(ROUTE_ERRORS[0])
                with self.assertRaises(ConnectionError):
                    if notebook == NOTEBOOKS[0]:
                        connect("new", "production")
                    else:
                        connect("production", ws=namespace["w_new"])
                namespace["public_address"].assert_not_called()

    def test_preflight_explicit_source_client_does_not_switch_routes(self):
        namespace = self.namespace()
        namespace["psycopg"].connect.side_effect = ConnectionError(ROUTE_ERRORS[0])
        connect = load_function(NOTEBOOKS[1], "connect", namespace)
        with self.assertRaises(ConnectionError):
            connect("production", ws=namespace["w"])
        namespace["public_address"].assert_not_called()

    def test_preflight_source_pg_tool_uses_the_source_identity(self):
        namespace = self.namespace()
        namespace["NEW_USER"] = "other-learner"
        namespace["connect"] = MagicMock()
        namespace["subprocess"].run.return_value = types.SimpleNamespace(returncode=0, stderr="")
        run_pg = load_function(NOTEBOOKS[1], "run_pg", namespace)
        run_pg("pg_dump", "production", ["--schema-only"], ws=namespace["w"])
        namespace["connect"].assert_not_called()
        self.assertEqual(namespace["subprocess"].run.call_args.kwargs["env"]["PGUSER"], namespace["USER"])

    def test_postgres_commands_use_the_same_tls_settings(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                namespace = self.namespace()
                namespace["subprocess"].run.return_value = types.SimpleNamespace(returncode=0, stderr="")
                namespace["time"].time.return_value = 0
                namespace["ROUTES"][HOST] = "203.0.113.10"
                run_pg = load_function(notebook, "run_pg", namespace)
                if notebook == NOTEBOOKS[0]:
                    run_pg("pg_dump", "old", "production", ["--schema-only"])
                else:
                    run_pg("pg_dump", "production", ["--schema-only"])
                env = namespace["subprocess"].run.call_args.kwargs["env"]
                self.assertEqual(env["PGHOST"], HOST)
                self.assertEqual(env["PGHOSTADDR"], "203.0.113.10")
                self.assertEqual(env["PGSSLMODE"], "verify-full")
                self.assertEqual(env["PGSSLROOTCERT"], "system")
                self.assertEqual(env["PGPASSWORD"], "test-token")


if __name__ == "__main__":
    unittest.main()

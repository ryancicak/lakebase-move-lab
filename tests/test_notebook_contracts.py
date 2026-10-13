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


class CliTransportTests(unittest.TestCase):
    def run_cli(self, notebook, host, source_host=AWS, authorization="Bearer notebook-token", returncode=0,
                extra=None):
        client = lambda address: types.SimpleNamespace(config=types.SimpleNamespace(
            host=address, authenticate=lambda: {"Authorization": authorization}))
        process = MagicMock()
        process.run.return_value = types.SimpleNamespace(
            returncode=returncode, stdout="command output\n", stderr="command detail\n")
        namespace = {
            "w": client(source_host), "w_new": client(host),
            "CLI": Path("/test/cli/databricks"), "CLI_DIR": Path("/test/cli"),
            "BUNDLE_DIR": Path("/test/bundle"), "urlsplit": urlsplit,
            "os": types.SimpleNamespace(environ={
                "PATH": "/usr/bin", "DATABRICKS_HOST": "https://unrelated.example.com",
                "DATABRICKS_TOKEN": "unrelated-token", "GODEBUG": "unrelated=1",
                "DATABRICKS_INSECURE_SKIP_VERIFY": "true",
            }),
            "subprocess": process,
            "TEMPORARY": ("INTERNAL_ERROR", "TEMPORARILY_UNAVAILABLE", "try again later", "timed out"),
            **(extra or {}),
        }
        invoke = load_function(notebook, "cli", namespace)
        kwargs = {"cwd": Path("/test/bundle")}
        if notebook == NOTEBOOKS[1]:
            kwargs["ws"] = client(host)
        return process, lambda: invoke("bundle", "deploy", **kwargs)

    def test_azure_cli_uses_http1_in_both_notebooks(self):
        for notebook in NOTEBOOKS:
            for host in (AZURE, AZURE + "/"):
                with self.subTest(notebook=notebook, host=host):
                    process, invoke = self.run_cli(notebook, host)
                    self.assertEqual(invoke(), (0, "command output\ncommand detail"))
                    env = process.run.call_args.kwargs["env"]
                    self.assertEqual(env["GODEBUG"], "http2client=0")
                    self.assertEqual(env["DATABRICKS_HOST"], host)
                    self.assertEqual(env["DATABRICKS_TOKEN"], "notebook-token")
                    self.assertNotIn("DATABRICKS_INSECURE_SKIP_VERIFY", env)
                    self.assertEqual(process.run.call_args.kwargs["timeout"], 900)
                    process.run.assert_called_once()

    def test_aws_cli_keeps_default_transport_even_from_azure(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, invoke = self.run_cli(notebook, AWS, source_host=AZURE)
                invoke()
                env = process.run.call_args.kwargs["env"]
                self.assertNotIn("GODEBUG", env)
                self.assertEqual(env["DATABRICKS_HOST"], AWS)

    def test_gcp_cli_keeps_default_transport(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, invoke = self.run_cli(notebook, "https://example.1.gcp.databricks.com")
                invoke()
                self.assertNotIn("GODEBUG", process.run.call_args.kwargs["env"])

    def test_preflight_default_client_uses_its_own_host(self):
        process, invoke = self.run_cli(NOTEBOOKS[1], AZURE)
        workspace = types.SimpleNamespace(config=types.SimpleNamespace(
            host=AZURE, authenticate=lambda: {"Authorization": "Bearer notebook-token"}))
        namespace = {
            "w": workspace, "CLI": Path("/test/cli/databricks"), "CLI_DIR": Path("/test/cli"),
            "os": types.SimpleNamespace(environ={"PATH": "/usr/bin"}),
            "subprocess": process, "urlsplit": urlsplit,
        }
        load_function(NOTEBOOKS[1], "cli", namespace)("current-user", "me")
        self.assertEqual(process.run.call_args.kwargs["env"]["GODEBUG"], "http2client=0")
        process.run.assert_called_once()

    def test_failed_bundle_command_is_not_replayed(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, invoke = self.run_cli(notebook, AZURE, returncode=1)
                self.assertEqual(invoke(), (1, "command output\ncommand detail"))
                process.run.assert_called_once()

    def run_with_results(self, notebook, results):
        clock = MagicMock()
        process, invoke = self.run_cli(notebook, AWS, extra={"time": clock})
        process.run.side_effect = [types.SimpleNamespace(returncode=code, stdout=out, stderr="")
                                   for code, out in results]
        with contextlib.redirect_stdout(io.StringIO()):
            result = invoke()
        return process, clock, result

    def test_retry_markers_match_the_notebooks(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                tree = ast.parse(source(notebook))
                value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == "TEMPORARY" for t in node.targets))
                self.assertEqual(ast.literal_eval(value),
                                 ("INTERNAL_ERROR", "TEMPORARILY_UNAVAILABLE", "try again later", "timed out"))

    def test_temporary_error_gets_two_more_tries(self):
        failure = ("Error: cannot create resources.postgres_branches.development: The request could not be "
                   "processed. Please try again later ... (500 INTERNAL_ERROR)")
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, clock, result = self.run_with_results(notebook, [(1, failure), (0, "Deployment complete!")])
                self.assertEqual(result, (0, "Deployment complete!"))
                self.assertEqual(process.run.call_count, 2)
                clock.sleep.assert_called_once_with(15)

    def test_temporary_errors_stop_after_three_tries(self):
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, clock, result = self.run_with_results(
                    notebook, [(1, "Error: request timed out after 1m30s of inactivity")] * 3)
                self.assertEqual(result[0], 1)
                self.assertEqual(process.run.call_count, 3)
                self.assertEqual(clock.sleep.call_count, 2)

    def test_destroy_guard_refusal_is_not_retried(self):
        guard = ("Error: resources.postgres_projects.app has lifecycle.prevent_destroy set, but the plan calls "
                 "for this resource to be recreated or destroyed.")
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook):
                process, clock, result = self.run_with_results(notebook, [(1, guard)])
                self.assertEqual(result, (1, guard))
                process.run.assert_called_once()
                clock.sleep.assert_not_called()

    def test_missing_bearer_token_fails_before_starting_cli(self):
        for notebook in NOTEBOOKS:
            for authorization in ("", "Basic notebook-token"):
                with self.subTest(notebook=notebook, authorization=authorization):
                    process, invoke = self.run_cli(notebook, AZURE, authorization=authorization)
                    with self.assertRaises(RuntimeError):
                        invoke()
                    process.run.assert_not_called()


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


class BundleFileTests(unittest.TestCase):
    def bundle_text(self, notebook, folder):
        workspace = types.SimpleNamespace(config=types.SimpleNamespace(host=AWS))
        namespace = {"BUNDLE_NAME": "lb-move-lab", "PRE_BUNDLE": "lb-move-lab-preflight-1", "w_new": workspace,
                     "w": workspace, "NEW_ID": "lb-move-new-sam-42", "PRE_ID": "lb-move-pre-sam-42-1",
                     "NEW_LABEL": "Lakebase move lab: new home", "PG_VERSION": 17, "BUNDLE_DIR": folder}
        load_function(notebook, "write_bundle", namespace)(guard=True)
        return (folder / "databricks.yml").read_text()

    def test_a_retried_deploy_can_adopt_the_development_branch(self):
        import tempfile
        for notebook in NOTEBOOKS:
            with self.subTest(notebook=notebook), tempfile.TemporaryDirectory() as folder:
                text = self.bundle_text(notebook, Path(folder))
                block = text.split("    development:\n", 1)[1].split("\n\n", 1)[0]
                self.assertIn("replace_existing: true", block)
                self.assertIn("no_expiry: true", block)


class Recorder:
    """Stands in for an SDK dataclass and remembers its arguments."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class PointInTimeTests(unittest.TestCase):
    WHOLE_MINUTE = 1791909960  # 2026-10-13 16:46:00 UTC

    def lab_moment(self, seconds):
        from datetime import datetime, timezone
        cell = next(cell for cell in source(NOTEBOOKS[0]).split("# COMMAND ----------")
                    if "# DBTITLE 1,Try to restore the new home to before the move" in cell)
        projects = MagicMock()
        namespace = {"RESTORE_STARTED": datetime.fromtimestamp(seconds, timezone.utc), "NEW_ID": "new",
                     "client": lambda pid: projects, "project_path": lambda pid: f"projects/{pid}",
                     "branch_path": lambda pid, branch: f"projects/{pid}/branches/{branch}",
                     "Branch": Recorder, "BranchSpec": Recorder, "Timestamp": Recorder, "Duration": Recorder,
                     "show": MagicMock(), "query": MagicMock()}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(cell, NOTEBOOKS[0], "exec"), namespace)
        return projects.postgres.create_branch.call_args.kwargs["branch"].spec.source_branch_time.seconds

    def test_lab_avoids_a_whole_minute(self):
        self.assertEqual(self.lab_moment(self.WHOLE_MINUTE), self.WHOLE_MINUTE - 1)
        self.assertEqual(self.lab_moment(self.WHOLE_MINUTE + 7), self.WHOLE_MINUTE + 7)

    def preflight_moment(self, now):
        tree = ast.parse(source(NOTEBOOKS[1]))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and any(isinstance(decorator, ast.Call) and isinstance(decorator.args[0], ast.Constant)
                                and decorator.args[0].value == "Point-in-time branch"
                                for decorator in node.decorator_list))
        function.decorator_list = []
        workspace = MagicMock()
        namespace = {"time": types.SimpleNamespace(time=lambda: now, sleep=lambda seconds: None),
                     "DEPLOYED_AT": now - 600, "w": workspace, "PRE_ID": "pre", "connect": MagicMock(),
                     "Branch": Recorder, "BranchSpec": Recorder, "Timestamp": Recorder, "Duration": Recorder}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     NOTEBOOKS[1], "exec"), namespace)
        namespace["_"]()
        return workspace.postgres.create_branch.call_args.kwargs["branch"].spec.source_branch_time.seconds

    def test_preflight_avoids_a_whole_minute(self):
        self.assertEqual(self.preflight_moment(self.WHOLE_MINUTE + 3), self.WHOLE_MINUTE - 1)
        self.assertEqual(self.preflight_moment(self.WHOLE_MINUTE + 10), self.WHOLE_MINUTE + 7)


class WorkspaceCheckTests(unittest.TestCase):
    """The lab's Check this workspace cell, with every cloud call mocked."""

    def workspace(self, projects=(), create_error=None, has_postgres=True):
        workspace = MagicMock()
        workspace.current_user.me.return_value = types.SimpleNamespace(user_name="sam.learner@example.com", id="42")
        workspace.postgres.list_projects.return_value = [
            types.SimpleNamespace(name=f"projects/{pid}", status=types.SimpleNamespace(display_name=label))
            for pid, label in projects]
        if create_error:
            workspace.postgres.create_project.side_effect = create_error
        workspace.metastores.current.return_value = types.SimpleNamespace(metastore_id="one")
        if not has_postgres:
            return types.SimpleNamespace(current_user=workspace.current_user)
        return workspace

    def run_check(self, workspace, values=None, other=None, reachable=True, catalog_error=None, secrets=None):
        values = {"where": "This workspace", "other_url": "", "catalog": "main", **(values or {})}
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = MagicMock(side_effect=lambda **kwargs: other if kwargs else workspace)
        postgres = types.ModuleType("databricks.sdk.service.postgres")
        postgres.Project, postgres.ProjectSpec = Recorder, Recorder
        spark = MagicMock()
        spark.sql.return_value.count.return_value = 0
        if catalog_error:
            spark.sql.side_effect = catalog_error
        dbutils = types.SimpleNamespace(widgets=FakeWidgets(values), secrets=types.SimpleNamespace(
            get=lambda scope, key: (secrets or {})[key]))
        cell = next(cell for cell in source(NOTEBOOKS[0]).split("# COMMAND ----------")
                    if "# DBTITLE 1,Check this workspace" in cell)
        namespace = {"dbutils": dbutils, "spark": spark}
        opened = MagicMock() if reachable else MagicMock(side_effect=OSError("no route to host"))
        output, error = io.StringIO(), None
        with patch.dict(sys.modules, {"databricks.sdk": sdk, "databricks.sdk.service.postgres": postgres}), \
                patch.dict("os.environ", {"IS_SERVERLESS": "TRUE", "DATABRICKS_RUNTIME_VERSION": "client.5.12"}), \
                patch("urllib.request.urlopen", opened), contextlib.redirect_stdout(output):
            try:
                exec(compile(cell, NOTEBOOKS[0], "exec"), namespace)
            except RuntimeError as caught:
                error = caught
        return output.getvalue(), error

    def test_a_ready_workspace_creates_and_deletes_one_test_project(self):
        workspace = self.workspace()
        output, error = self.run_check(workspace)
        self.assertIsNone(error)
        self.assertIn("Ready. Go on to the next cell.", output)
        self.assertNotIn("❌", output)
        self.assertEqual(workspace.postgres.create_project.call_args.kwargs["project_id"], "lb-move-chk-sam-learner-42")
        workspace.postgres.delete_project.assert_called_once_with(
            name="projects/lb-move-chk-sam-learner-42", purge=True)

    def test_no_permission_to_create_projects_stops_with_the_fix(self):
        error_type = type("PermissionDenied", (Exception,), {})
        output, error = self.run_check(self.workspace(create_error=error_type("PERMISSION_DENIED: not allowed")))
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("Not ready", str(error))
        self.assertIn("Ask your workspace admin for permission to create Lakebase projects", output)

    def test_blocked_downloads_stop_with_the_fix(self):
        output, error = self.run_check(self.workspace(), reachable=False)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("reach apt.postgresql.org over HTTPS", output)
        self.assertIn("reach github.com over HTTPS", output)

    def test_an_old_sdk_stops_before_anything_else(self):
        output, error = self.run_check(self.workspace(has_postgres=False))
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("Run the %pip cell and the restart cell", output)

    def test_leftovers_point_to_module_7_without_stopping_the_cleanup_path(self):
        workspace = self.workspace(projects=[("lb-move-old-sam-learner-42", "Lakebase move lab: old home")])
        output, error = self.run_check(workspace)
        self.assertIsNone(error)
        self.assertIn("left over from an earlier run", output)
        self.assertIn("Clean up first", output)

    def test_someone_elses_project_with_the_lab_name_stops(self):
        workspace = self.workspace(projects=[("lb-move-new-sam-learner-42", "Production orders")])
        output, error = self.run_check(workspace)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("this lab didn't make it", output)

    def test_no_create_schema_is_only_a_warning(self):
        output, error = self.run_check(self.workspace(), catalog_error=Exception(
            "(com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException) PERMISSION_DENIED: User does not "
            "have CREATE SCHEMA on Catalog 'main'."))
        self.assertIsNone(error)
        self.assertIn("⚠️ Catalog main", output)
        self.assertNotIn("com.databricks", output)
        self.assertIn("Ready. Go on to the next cell.", output)

    def test_other_workspace_sign_in_failure_stops_with_the_fix(self):
        workspace = self.workspace()
        workspace.secrets.list_secrets.return_value = [types.SimpleNamespace(key="host")]
        output, error = self.run_check(workspace, values={"where": "Another workspace", "other_url": AZURE},
                                       secrets={"host": AZURE})
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("paste a fresh personal access token", output)

    def test_other_workspace_is_checked_too(self):
        workspace, other = self.workspace(), self.workspace()
        other.metastores.current.return_value = types.SimpleNamespace(metastore_id="two")
        workspace.secrets.list_secrets.return_value = [types.SimpleNamespace(key=k) for k in ("host", "token")]
        output, error = self.run_check(workspace, values={"where": "Another workspace", "other_url": AZURE},
                                       other=other, secrets={"host": AZURE, "token": "test-token"})
        self.assertIsNone(error)
        self.assertIn("Lakebase in the other workspace", output)
        self.assertIn("Create a Lakebase project in the other workspace", output)
        self.assertIn("its own metastore", output)
        other.postgres.delete_project.assert_called_once()


if __name__ == "__main__":
    unittest.main()

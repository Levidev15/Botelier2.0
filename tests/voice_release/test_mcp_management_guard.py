"""Portable policy tests for the separate synthetic MCP management boundary."""

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "examples/features/botelier-flow-trial"


class MCPManagementGuardPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "mcp_management_policy_under_test", TRIAL / "mcp_management_guard.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(TRIAL))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(TRIAL))
        cls.module = module

    def assert_denied(self, category, operation):
        before = len(self.module.BLOCKED)
        with self.assertRaises(self.module.GuardError):
            operation()
        self.assertEqual(len(self.module.BLOCKED), before + 1)
        self.assertEqual(self.module.BLOCKED[-1], category)

    def test_only_the_management_route_is_admitted(self):
        policy = self.module.MCPManagementImportsOnly()
        self.assertIsNone(policy.find_spec("botelier.api.mcp_connections"))
        for route in (
            "botelier.api.auth", "botelier.api.simulation",
            "botelier.api.flow_versions", "botelier.api.mcp_connections.extra",
        ):
            with self.subTest(route=route):
                self.assert_denied(
                    "unapproved_application_route_import",
                    lambda route=route: policy.find_spec(route),
                )

    def test_root_bootstrap_and_real_database_imports_remain_forbidden(self):
        policy = self.module.MCPManagementImportsOnly()
        for name in (
            "main", "database", "botelier.database", "botelier.app",
            "botelier.startup", "botelier.bootstrap", "psycopg", "psycopg2",
            "asyncpg", "aiosqlite", "pg8000",
        ):
            category = (
                "application_bootstrap_import"
                if name in {"main", "botelier.app", "botelier.startup", "botelier.bootstrap"}
                else "live_database_or_driver_import"
            )
            with self.subTest(name=name):
                self.assert_denied(category, lambda name=name: policy.find_spec(name))

    def test_even_in_memory_database_connections_are_forbidden(self):
        self.assert_denied(
            "database_connection",
            lambda: self.module.management_audit("sqlite3.connect", (":memory:",)),
        )
        self.assert_denied(
            "network_or_subprocess",
            lambda: self.module.management_audit(
                "socket.connect", (None, ("127.0.0.1", 5432)),
            ),
        )

    def test_only_one_exact_management_suite_can_be_requested(self):
        expected = TRIAL / "test_mcp_native_policy.py"
        self.assertEqual(self.module.validate_targets([expected]), (expected.resolve(),))
        for targets in (
            [], [expected, expected], [TRIAL / "test_native_actions.py"],
        ):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                self.module.validate_targets(targets)

    def test_the_default_fake_database_never_connects(self):
        before = len(self.module.BLOCKED)
        with self.assertRaises(self.module.GuardError):
            self.module.reject_database()
        self.assertEqual(len(self.module.BLOCKED), before)


if __name__ == "__main__":
    unittest.main()

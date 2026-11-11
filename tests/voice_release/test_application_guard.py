"""Exercise the application-test launcher's safety boundaries as a real process."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "examples/features/botelier-flow-trial"


class ApplicationGuardTests(unittest.TestCase):
    def run_guard(self, script="application_guard.py", extra_env=None):
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        env.update(extra_env or {})
        args = [sys.executable, "-B", str(TRIAL / script)]
        if script in {"application_guard.py", "lifecycle_guard.py", "callback_guard.py", "recovery_guard.py"}:
            args += ["--backend-root", str(ROOT / "botelier/backend")]
        else:
            args += ["--target", "wheel"]
        args += ["--package-root", "/tmp/not-installed/pipecat", "--self-test"]
        return subprocess.run(
            args, env=env, text=True, capture_output=True, timeout=20, check=False
        )

    def test_application_mode_denies_network_process_secrets_and_database(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["guard_self_test"], "passed")
        self.assertEqual(observed["expected_denials"], 6)

    def test_inherited_unknown_credentials_are_rejected_before_application_import(self):
        marker = "synthetic-value-not-a-credential"
        result = self.run_guard(
            extra_env={"UNEXPECTED_COMPATIBILITY_CREDENTIAL": marker}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env -i", result.stderr)
        self.assertNotIn(marker, result.stderr + result.stdout)

    def test_framework_mode_still_denies_all_application_imports(self):
        result = self.run_guard(script="guard.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["expected_denials"], 4)

    def test_lifecycle_mode_keeps_network_process_secrets_and_server_database_denied(self):
        result = self.run_guard(script="lifecycle_guard.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["expected_denials"], 6)

    def test_lifecycle_mode_rejects_inherited_credentials_before_import(self):
        marker = "synthetic-value-not-a-credential"
        result = self.run_guard(
            script="lifecycle_guard.py",
            extra_env={"UNEXPECTED_COMPATIBILITY_CREDENTIAL": marker},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env -i", result.stderr)
        self.assertNotIn(marker, result.stderr + result.stdout)

    def test_callback_mode_keeps_network_process_secrets_server_and_database_denied(self):
        result = self.run_guard(script="callback_guard.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["expected_denials"], 6)

    def test_callback_mode_rejects_inherited_credentials_before_import(self):
        marker = "synthetic-value-not-a-credential"
        result = self.run_guard(
            script="callback_guard.py",
            extra_env={"UNEXPECTED_COMPATIBILITY_CREDENTIAL": marker},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env -i", result.stderr)
        self.assertNotIn(marker, result.stderr + result.stdout)

    def test_recovery_mode_keeps_network_process_secrets_and_live_startup_denied(self):
        result = self.run_guard(script="recovery_guard.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["expected_denials"], 6)

    def test_recovery_mode_rejects_inherited_credentials_before_import(self):
        marker = "synthetic-value-not-a-credential"
        result = self.run_guard(
            script="recovery_guard.py", extra_env={"NEON_DATABASE_URL": marker},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("env -i", result.stderr)
        self.assertNotIn(marker, result.stderr + result.stdout)

    def test_recovery_connection_policy_denies_dsns_and_non_fixture_destinations(self):
        program = (
            "from recovery_guard import FIXTURE_CONNECTION,validate_fixture_connection\n"
            "from guard import TrialSafetyError\n"
            "validate_fixture_connection((),dict(FIXTURE_CONNECTION))\n"
            "bad=[(('postgresql://customer.invalid/live',),{}),"
            "((),{**FIXTURE_CONNECTION,'host':'127.0.0.1'}),"
            "((),{**FIXTURE_CONNECTION,'dbname':'customer'}),"
            "((),{**FIXTURE_CONNECTION,'password':'not-a-credential'})]\n"
            "for args,kwargs in bad:\n"
            " try: validate_fixture_connection(args,kwargs)\n"
            " except TrialSafetyError: continue\n"
            " raise AssertionError('Non-fixture connection was admitted')\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", program],
            env={"PATH": os.environ["PATH"], "PYTHONPATH": str(TRIAL)},
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_callback_fixture_namespace_does_not_admit_other_api_modules_or_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "pipecat"
            package.mkdir()
            (package / "__init__.py").write_text("# Guard-unit fixture, not runtime evidence.\n")
            for target in ("main", "botelier.database", "botelier.api.websockets"):
                with self.subTest(target=target):
                    program = (
                        "import sys, types\n"
                        "from application_guard import main\n"
                        "from callback_guard import CallbackServices\n"
                        "def prepare():\n"
                        "    namespace = types.ModuleType('botelier.api')\n"
                        f"    namespace.__path__ = [{str(ROOT / 'botelier/backend/botelier/api')!r}]\n"
                        "    sys.modules['botelier.api'] = namespace\n"
                        f"    __import__({target!r})\n"
                        "main(import_policy=CallbackServices, prepare_tests=prepare)\n"
                    )
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", program,
                         "--backend-root", str(ROOT / "botelier/backend"),
                         "--package-root", str(package), "--tests", "unused.py"],
                        env={
                            "PATH": os.environ["PATH"], "PYTHONPATH": str(TRIAL),
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        text=True, capture_output=True, timeout=20, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "OFFLINE TRIAL GUARD: live_application_or_database_import",
                        result.stderr,
                    )

    def test_fixture_preparation_runs_under_database_and_server_import_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "pipecat"
            package.mkdir()
            (package / "__init__.py").write_text("# Guard-unit fixture, not runtime evidence.\n")
            for target in ("botelier.database", "botelier.api"):
                with self.subTest(target=target):
                    program = (
                        "from application_guard import main\n"
                        "from lifecycle_guard import LifecycleServices\n"
                        "def prepare():\n"
                        f"    __import__({target!r})\n"
                        "main(import_policy=LifecycleServices, prepare_tests=prepare)\n"
                    )
                    result = subprocess.run(
                        [
                            sys.executable, "-B", "-c", program,
                            "--backend-root", str(ROOT / "botelier/backend"),
                            "--package-root", str(package), "--tests", "unused.py",
                        ],
                        env={
                            "PATH": os.environ["PATH"],
                            "PYTHONPATH": str(TRIAL),
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        text=True, capture_output=True, timeout=20, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "OFFLINE TRIAL GUARD: live_application_or_database_import",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()

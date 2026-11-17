"""Caught audit refusals must remain diagnosable after test-output capture."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "examples/features/botelier-flow-trial/auth_guard.py"
PAYLOAD = "synthetic-private-input-must-not-be-logged"
PROGRAM = """
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types

spec = importlib.util.spec_from_file_location("auth_diagnostic_subject", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
backend = sys.argv[2]
attempts = int(sys.argv[3])
depth = int(sys.argv[4])
diagnose = sys.argv[5] == "yes"
crash = sys.argv[6] == "yes"
interleave = sys.argv[7] == "yes"

# Database construction is outside this standard-library diagnostic unit.
# Keep the real environment validation, import policy and installed audit hook.
guard._install_database = lambda postgres: None

def refused_operation(remaining):
    if remaining:
        return refused_operation(remaining - 1)
    try:
        # Dispatch a real interpreter audit event, never a DNS/network request.
        sys.audit("socket.getaddrinfo",
                  "synthetic-private-input-must-not-be-logged", 443, 0, 0, 0)
    except guard.AuthGuardError:
        return
    raise AssertionError("The real audit hook failed to refuse the operation")

class RunnerFailure(Exception):
    pass

def captured_test_driver(arguments):
    if arguments[-1] != "synthetic_trial.py":
        raise AssertionError("Unexpected test-driver arguments")
    with contextlib.redirect_stderr(io.StringIO()):
        for _ in range(attempts):
            refused_operation(depth)
    print("TEST_DRIVER_CAPTURE_FINISHED")
    if interleave:
        class ReportingOutput:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.triggered = False

            def write(self, text):
                if text.startswith("AUTH_GUARD_TRACE=") and not self.triggered:
                    self.triggered = True
                    refused_operation(0)
                return self.wrapped.write(text)

            def flush(self):
                self.wrapped.flush()

        sys.stdout = ReportingOutput(sys.stdout)
    if crash:
        raise RunnerFailure()
    return 0

# Only replace the external test-driver boundary that captures passing output.
# Assertions below concern the real guard's diagnostics, refusal and exit code.
sys.modules["pytest"] = types.SimpleNamespace(main=captured_test_driver)
sys.argv = ["auth_guard.py", "--backend-root", backend]
if diagnose:
    sys.argv.append("--diagnose")
sys.argv += ["--tests", "synthetic_trial.py"]
try:
    result = guard.main()
except RunnerFailure:
    print("ORIGINAL_RUNNER_FAILURE_PRESERVED")
    raise SystemExit(17)
raise SystemExit(result)
"""


class AuthGuardDiagnosticsTests(unittest.TestCase):
    def launch(self, *, attempts=1, depth=0, diagnose=True, crash=False, interleave=False):
        with tempfile.TemporaryDirectory(prefix="auth-diagnostic-unit-") as tmp:
            fixture = Path(tmp) / "diagnostic_fixture.py"
            fixture.write_text(textwrap.dedent(PROGRAM))
            return subprocess.run(
                [
                    sys.executable, "-B", str(fixture), str(GUARD),
                    str(ROOT / "botelier/backend"), str(attempts), str(depth),
                    "yes" if diagnose else "no", "yes" if crash else "no",
                    "yes" if interleave else "no",
                ],
                capture_output=True, text=True, timeout=15,
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": "/tmp",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "NEXTAUTH_SECRET": "botelier-auth-trial-only-synthetic-nextauth-secret-v1",
                    "INTEGRATION_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                },
            )

    def records(self, result):
        return [
            json.loads(line.removeprefix("AUTH_GUARD_TRACE="))
            for line in result.stdout.splitlines()
            if line.startswith("AUTH_GUARD_TRACE=")
        ]

    def test_caught_refusal_survives_passing_test_capture_without_logging_input(self):
        result = self.launch()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("AUTH_GUARD_BLOCKED_ATTEMPTS=1", result.stdout)
        records = self.records(result)
        self.assertEqual(len(records), 1, result.stdout)
        record = records[0]
        self.assertEqual(set(record), {"category", "event", "frames"})
        self.assertEqual(record["category"], "network_or_subprocess")
        self.assertEqual(record["event"], "socket.getaddrinfo")
        self.assertTrue(any(
            frame["function"] == "refused_operation" for frame in record["frames"]
        ))
        self.assertGreater(
            result.stdout.index("AUTH_GUARD_TRACE="),
            result.stdout.index("TEST_DRIVER_CAPTURE_FINISHED"),
        )
        for frame in record["frames"]:
            self.assertEqual(set(frame), {"file", "function", "line"})
            self.assertIsInstance(frame["line"], int)
        self.assertNotIn(PAYLOAD, result.stdout + result.stderr)

    def test_deep_repeated_refusals_have_bounded_diagnostics_but_all_still_count(self):
        result = self.launch(attempts=20, depth=100)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("AUTH_GUARD_BLOCKED_ATTEMPTS=20", result.stdout)
        records = self.records(result)
        self.assertGreater(len(records), 0, result.stdout)
        self.assertLessEqual(len(records), 8)
        self.assertTrue(all(0 < len(record["frames"]) <= 24 for record in records))
        self.assertLess(len(result.stdout.encode()), 65536)
        self.assertNotIn(PAYLOAD, result.stdout + result.stderr)

    def test_disabled_diagnostics_do_not_change_refusal_or_produce_traces(self):
        result = self.launch(diagnose=False)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("AUTH_GUARD_BLOCKED_ATTEMPTS=1", result.stdout)
        self.assertEqual(self.records(result), [])
        self.assertNotIn(PAYLOAD, result.stdout + result.stderr)

    def test_runner_exception_does_not_hide_the_refusal_or_get_replaced(self):
        result = self.launch(crash=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertIn("ORIGINAL_RUNNER_FAILURE_PRESERVED", result.stdout)
        self.assertEqual(len(self.records(result)), 1, result.stdout)
        self.assertNotIn(PAYLOAD, result.stdout + result.stderr)

    def test_another_refusal_during_reporting_keeps_diagnostics_and_failure_intact(self):
        result = self.launch(interleave=True)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("AUTH_GUARD_BLOCKED_ATTEMPTS=2", result.stdout)
        self.assertGreater(len(self.records(result)), 0, result.stdout)
        self.assertNotIn(PAYLOAD, result.stdout + result.stderr)

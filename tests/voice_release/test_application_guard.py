"""Exercise the application-test launcher's safety boundaries as a real process."""

import json
import os
from pathlib import Path
import subprocess
import sys
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
        if script == "application_guard.py":
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


if __name__ == "__main__":
    unittest.main()

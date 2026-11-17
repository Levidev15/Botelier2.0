"""The auth launcher must refuse real configuration before importing the app."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "examples/features/botelier-flow-trial/auth_guard.py"


class AuthGuardPolicyTests(unittest.TestCase):
    def launch(self, extra):
        return subprocess.run(
            [
                sys.executable, "-B", str(GUARD),
                "--backend-root", str(ROOT / "botelier/backend"),
                "--self-test",
            ],
            capture_output=True, text=True, timeout=15,
            env={
                "PATH": os.environ["PATH"],
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
                "NEXTAUTH_SECRET": "botelier-auth-trial-only-synthetic-nextauth-secret-v1",
                "INTEGRATION_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                **extra,
            },
        )

    def test_database_configuration_is_refused_before_database_initialization(self):
        marker = "postgresql://not-a-real-credential@customer.invalid/customer"
        result = self.launch({"DATABASE_URL": marker})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("documented env -i", result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_arbitrary_signing_secret_is_refused_without_printing_its_value(self):
        marker = "not-an-actual-secret-do-not-print"
        result = self.launch({"NEXTAUTH_SECRET": marker})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixed synthetic test signing key", result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_arbitrary_cipher_key_is_refused_without_printing_its_value(self):
        marker = "not-an-actual-cipher-key-do-not-print"
        result = self.launch({"INTEGRATION_ENCRYPTION_KEY": marker})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixed synthetic test encryption key", result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

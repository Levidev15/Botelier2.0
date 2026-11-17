"""Locked packages must be fetchable by the isolated GitHub/Azure builders."""

import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit


LOCK = Path(__file__).resolve().parents[2] / "botelier/frontend/package-lock.json"


class FrontendLockPortabilityTests(unittest.TestCase):
    def test_locked_registry_artifacts_use_the_public_https_registry(self):
        packages = json.loads(LOCK.read_text())["packages"]
        invalid = []
        for name, package in packages.items():
            if "resolved" not in package:
                continue
            url = urlsplit(package["resolved"])
            if (url.scheme != "https" or url.hostname != "registry.npmjs.org"
                    or url.username is not None or url.password is not None):
                invalid.append(name)
        self.assertEqual(invalid, [], "Builder package URLs must not rely on Replit-private DNS")

    def test_all_downloaded_packages_retain_their_integrity_checks(self):
        packages = json.loads(LOCK.read_text())["packages"]
        missing = [
            name for name, package in packages.items()
            if "resolved" in package and not package.get("integrity")
        ]
        self.assertEqual(missing, [], "Portable URLs must not remove npm's artifact verification")

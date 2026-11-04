"""Supplement the executable policy tests with workflow privilege invariants."""

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )


class WorkflowIsolationTests(unittest.TestCase):
    def test_production_has_no_automatic_release_trigger(self):
        production = load("deploy-voice.yml")
        self.assertEqual(
            set(production["on"]), {"workflow_dispatch"},
            "A push or PR must not start a production release",
        )

    def test_candidate_has_no_deployment_credentials_or_write_token(self):
        path = ROOT / ".github/workflows/voice-flow-candidate.yml"
        self.assertTrue(path.is_file(), "The credential-free candidate workflow is missing")
        candidate = load(path.name)
        self.assertEqual(candidate.get("permissions"), {"contents": "read"})
        for job in candidate["jobs"].values():
            self.assertNotIn("environment", job)
            self.assertNotIn("permissions", job)
            for step in job.get("steps", []):
                self.assertNotIn("azure/", step.get("uses", "").lower())
        # Neither environment nor repo credentials may enter the candidate job.
        self.assertNotRegex(
            json.dumps(candidate), r"\$\{\{[^}]*\bsecrets\b",
            "Candidate workflow expressions must not access the secrets context",
        )

    def test_production_authentication_requires_successful_build_and_policy(self):
        production = load("deploy-voice.yml")
        release = production["jobs"].get("release")
        self.assertIsNotNone(release, "Separate the credential-free build from release")
        self.assertEqual(release["environment"], "voice-production")
        self.assertIn("build", release["needs"])
        steps = release["steps"]
        guard = next(
            (i for i, step in enumerate(steps) if step.get("id") == "authorize_release"), None
        )
        self.assertIsNotNone(guard, "Production must execute the release policy")
        self.assertNotIn("continue-on-error", steps[guard])
        auth = [
            i for i, step in enumerate(steps)
            if step.get("uses", "").startswith(("azure/login@", "azure/docker-login@"))
        ]
        self.assertTrue(auth, "The release job must contain the explicit Azure boundary")
        self.assertTrue(all(i > guard for i in auth))
        build = production["jobs"]["build"]
        self.assertNotIn("environment", build)
        self.assertFalse(any(
            step.get("uses", "").startswith("azure/") for step in build["steps"]
        ))

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

    def test_actual_application_checks_cannot_be_ignored_or_access_network(self):
        candidate = load("voice-flow-candidate.yml")
        steps = candidate["jobs"]["candidate"]["steps"]
        check = next(step for step in steps
                     if step.get("id") == "application_compatibility")
        self.assertNotIn("continue-on-error", check)
        for required in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "application_guard.py", "--backend-root /app",
            "test_application_terminal.py",
        ):
            self.assertIn(required, check["run"])
        export = next(i for i, step in enumerate(steps)
                      if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

    def test_application_failure_evidence_is_retained_without_weakening_gate(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        evidence = next(step for step in steps
                        if step.get("name", "").startswith("Retain application compatibility"))
        self.assertEqual(evidence["if"], "always()")
        self.assertTrue(evidence["uses"].startswith("actions/upload-artifact@"))

    def test_transfer_and_recording_checks_are_required_before_image_export(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        check = next(step for step in steps if step.get("id") == "application_lifecycle")
        self.assertNotIn("continue-on-error", check)
        for required in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "lifecycle_guard.py", "test_application_transfers.py",
            "test_application_recordings.py",
            "test_application_transfer_retries.py",
        ):
            self.assertIn(required, check["run"])
        export = next(i for i, step in enumerate(steps)
                      if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

    def test_callback_checks_are_isolated_and_required_before_image_export(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        check = next(step for step in steps if step.get("id") == "application_callbacks")
        self.assertNotIn("continue-on-error", check)
        for required in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "callback_guard.py", "--backend-root /app",
            "test_application_callbacks.py", "test_application_callback_delivery.py",
            "test_application_callback_lifecycle.py",
            "test_application_transfer_recovery.py",
        ):
            self.assertIn(required, check["run"])
        export = next(i for i, step in enumerate(steps)
                      if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

    def test_api_and_mcp_contract_checks_are_required_before_image_export(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        check = next((step for step in steps if step.get("id") == "node_contracts"), None)
        self.assertIsNotNone(check, "The API/MCP node-contract gate is missing")
        self.assertNotIn("continue-on-error", check)
        self.assertNotIn("if", check)
        for required in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "lifecycle_guard.py", "--backend-root /app",
            "test_application_api_contracts.py", "test_application_mcp_contracts.py",
            "test_action_boundary_contracts.py",
        ):
            self.assertIn(required, check["run"])
        export = next(i for i, step in enumerate(steps)
                      if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

    def test_postgresql_recovery_is_mandatory_before_image_export(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        check = next((step for step in steps if step.get("id") == "transfer_recovery"), None)
        self.assertIsNotNone(check, "The real PostgreSQL recovery gate is missing")
        self.assertNotIn("continue-on-error", check)
        self.assertIn("bash scripts/voice_release/check_transfer_recovery.sh", check["run"])
        export = next(i for i, step in enumerate(steps) if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

    def test_native_adapter_gate_is_mandatory_and_offline_before_image_export(self):
        steps = load("voice-flow-candidate.yml")["jobs"]["candidate"]["steps"]
        check = next((step for step in steps if step.get("id") == "native_pilot_adapter"), None)
        self.assertIsNotNone(check, "The saved-flow native adapter gate is missing")
        self.assertNotIn("continue-on-error", check)
        self.assertNotIn("if", check)
        for required in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "lifecycle_guard.py", "--backend-root /app",
            "test_pilot_contract.py", "test_pilot_pipeline.py", "test_pilot_mcp.py",
            "test_pilot_interruption_order.py", "test_pilot_reentry.py",
            "test_pilot_revisions.py",
            'tee "$EVIDENCE/native-pilot-adapter.log"',
        ):
            self.assertIn(required, check["run"])
        export = next(i for i, step in enumerate(steps)
                      if step.get("id") == "export_candidate_image")
        self.assertLess(steps.index(check), export)

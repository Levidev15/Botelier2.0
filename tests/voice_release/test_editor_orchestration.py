"""The editor checkpoint must consume the same isolated candidate as voice."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class EditorOrchestrationTests(unittest.TestCase):
    def setUp(self):
        workflow = yaml.load(
            (ROOT / ".github/workflows/voice-flow-candidate.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.steps = workflow["jobs"]["candidate"]["steps"]

    def test_browser_checks_use_the_verified_image_not_an_unrelated_backend(self):
        browser = next(step for step in self.steps if step.get("id") == "frontend_alignment")
        image_build = next(
            step for step in self.steps
            if "docker build -f botelier/backend/Dockerfile.flow-pilot" in step.get("run", "")
        )
        provenance = next(
            step for step in self.steps
            if "--manifest /opt/voice-runtime/pilot-runtime.json" in step.get("run", "")
        )
        self.assertGreater(self.steps.index(browser), self.steps.index(image_build))
        self.assertGreater(self.steps.index(browser), self.steps.index(provenance))
        self.assertEqual(
            browser["env"]["EDITOR_CANDIDATE_IMAGE"],
            "voice-flow-candidate:${{ github.sha }}",
        )
        self.assertIn("--browser --native-editor", browser["run"])
        self.assertNotIn("continue-on-error", browser)

    def test_editor_auth_publisher_and_native_contracts_are_a_required_offline_gate(self):
        editor = next(
            (step for step in self.steps if step.get("id") == "editor_contracts"),
            None,
        )
        self.assertIsNotNone(editor, "The combined editor contract gate is missing")
        self.assertNotIn("continue-on-error", editor)
        for fragment in (
            "--network none", "--read-only", '--entrypoint env "$IMAGE" -i',
            "editor_guard.py", "--self-test", "test_editor_fixture.py",
            "--backend-root /app",
            "--package-root /usr/local/lib/python3.11/site-packages/pipecat",
            ':/ci/examples/features/botelier-flow-trial:ro"',
            "python -B /ci/examples/features/botelier-flow-trial/editor_guard.py",
            "--tests /ci/examples/features/botelier-flow-trial/test_editor_fixture.py",
        ):
            self.assertIn(fragment, editor["run"])
        export = next(
            step for step in self.steps if step.get("id") == "export_candidate_image"
        )
        self.assertLess(self.steps.index(editor), self.steps.index(export))


if __name__ == "__main__":
    unittest.main()

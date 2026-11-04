"""Execute the workflow's Python checks with only Docker inspect faked.

This tests image promotion logic, not a Docker build or a GitHub Actions runner.
No workflow shell command, Azure client or credential is executed.
"""

import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
IMAGE_ID = "sha256:" + "1" * 64
DIGEST = "sha256:" + "2" * 64


class ImagePromotionTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(
            (ROOT / ".github/workflows/deploy-voice.yml").read_text(), Loader=yaml.BaseLoader
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.image = "voice-legacy:" + SHA
        self.remote = "registry.invalid/botelier-voice:" + SHA
        self.inspection = {
            "Id": IMAGE_ID, "RepoTags": [self.image], "RepoDigests": [],
            "Config": {"Labels": {
                "org.opencontainers.image.revision": SHA,
                "botelier.runtime.profile": "legacy",
            }},
        }
        self.metadata = {"image_id": IMAGE_ID, "commit": SHA, "profile": "legacy"}
        self.responses = {self.image: [copy.deepcopy(self.inspection)]}
        fake = self.directory / "docker"
        fake.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, pathlib, sys\n"
            "if sys.argv[1:3] != ['image', 'inspect']: raise SystemExit(12)\n"
            "responses = json.loads(pathlib.Path(os.environ['DOCKER_RESPONSES']).read_text())\n"
            "if sys.argv[3] not in responses: raise SystemExit(13)\n"
            "print(json.dumps(responses[sys.argv[3]]))\n"
        )
        fake.chmod(0o700)

    def step(self, job, identifier):
        return next(
            step for step in self.workflow["jobs"][job]["steps"]
            if step.get("id") == identifier
        )

    def run_python(self, step):
        scripts = re.findall(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", step["run"], re.S)
        self.assertEqual(len(scripts), 1, "Expected one actual workflow Python check")
        (self.directory / "responses.json").write_text(json.dumps(self.responses))
        result = subprocess.run(
            [sys.executable, "-B", "-c", scripts[0]],
            env={
                "PATH": str(self.directory),
                "IMAGE": self.image, "GITHUB_SHA": SHA,
                "OUTPUT_DIR": str(self.directory),
                "REGISTRY": "registry.invalid",
                "GITHUB_OUTPUT": str(self.directory / "github-output"),
                "DOCKER_RESPONSES": str(self.directory / "responses.json"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True, text=True, timeout=10,
        )
        return result

    def validate_loaded_image(self):
        (self.directory / "image-meta.json").write_text(json.dumps(self.metadata))
        return self.run_python(self.step("release", "verify_checked_image"))

    def test_export_records_the_actual_checked_image_identity(self):
        result = self.run_python(self.step("build", "export_checked_image"))
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads((self.directory / "image-meta.json").read_text())
        self.assertEqual(actual, self.metadata)

    def test_exact_loaded_legacy_image_is_accepted(self):
        result = self.validate_loaded_image()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_different_binary_is_rejected_even_with_the_same_commit(self):
        self.responses[self.image][0]["Id"] = "sha256:" + "3" * 64
        self.assertNotEqual(self.validate_loaded_image().returncode, 0)

    def test_a_different_commit_is_rejected_even_with_the_same_image_name(self):
        self.metadata["commit"] = "b" * 40
        self.assertNotEqual(self.validate_loaded_image().returncode, 0)

    def test_candidate_profile_and_wrong_revision_labels_cannot_be_promoted(self):
        for label, value in (
            ("botelier.runtime.profile", "native-flows-pilot"),
            ("org.opencontainers.image.revision", "b" * 40),
        ):
            with self.subTest(label=label):
                self.responses[self.image][0] = copy.deepcopy(self.inspection)
                self.responses[self.image][0]["Config"]["Labels"][label] = value
                self.assertNotEqual(self.validate_loaded_image().returncode, 0)

    def test_registry_reference_is_content_addressed_not_a_mutable_tag(self):
        pushed = copy.deepcopy(self.inspection)
        pushed["RepoDigests"] = ["registry.invalid/botelier-voice@" + DIGEST]
        self.responses[self.remote] = [pushed]
        result = self.run_python(self.step("release", "image"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.directory / "github-output").read_text(),
            "reference=registry.invalid/botelier-voice@" + DIGEST + "\n",
        )

    def test_missing_ambiguous_foreign_and_invalid_digests_are_rejected(self):
        for digests in (
            [], ["foreign.invalid/botelier-voice@" + DIGEST],
            ["registry.invalid/botelier-voice:latest"],
            ["registry.invalid/botelier-voice@sha256:bad"],
            ["registry.invalid/botelier-voice@" + DIGEST,
             "registry.invalid/botelier-voice@sha256:" + "4" * 64],
        ):
            with self.subTest(digests=digests):
                pushed = copy.deepcopy(self.inspection)
                pushed["RepoDigests"] = digests
                self.responses[self.remote] = [pushed]
                result = self.run_python(self.step("release", "image"))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.directory / "github-output").exists())

    def test_a_pushed_image_with_different_content_is_rejected(self):
        pushed = copy.deepcopy(self.inspection)
        pushed["Id"] = "sha256:" + "3" * 64
        pushed["RepoDigests"] = ["registry.invalid/botelier-voice@" + DIGEST]
        self.responses[self.remote] = [pushed]
        result = self.run_python(self.step("release", "image"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "github-output").exists())

    def candidate_export_step(self):
        workflow = yaml.load(
            (ROOT / ".github/workflows/voice-flow-candidate.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        return next(
            step for step in workflow["jobs"]["candidate"]["steps"]
            if step.get("id") == "export_candidate_image"
        )

    def test_retained_candidate_is_explicitly_ineligible_for_production(self):
        labels = self.responses[self.image][0]["Config"]["Labels"]
        labels["botelier.runtime.profile"] = "native-flows-pilot"
        labels["botelier.runtime.production-eligible"] = "false"
        result = self.run_python(self.candidate_export_step())
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads((self.directory / "image-meta.json").read_text())
        self.assertEqual(actual["image_id"], IMAGE_ID)
        self.assertEqual(actual["profile"], "native-flows-pilot")
        self.assertIs(actual["production_eligible"], False)

    def test_candidate_export_rejects_wrong_or_production_eligible_labels(self):
        for labels in (
            {"botelier.runtime.profile": "legacy"},
            {"botelier.runtime.profile": "native-flows-pilot",
             "botelier.runtime.production-eligible": "true"},
        ):
            with self.subTest(labels=labels):
                self.responses[self.image][0]["Config"]["Labels"] = {
                    "org.opencontainers.image.revision": SHA, **labels,
                }
                result = self.run_python(self.candidate_export_step())
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.directory / "image-meta.json").exists())

    def test_all_inline_python_is_syntactically_valid(self):
        count = 0
        for job in self.workflow["jobs"].values():
            for step in job["steps"]:
                for script in re.findall(
                    r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", step.get("run", ""), re.S
                ):
                    compile(script, "<workflow-python>", "exec")
                    count += 1
        self.assertGreaterEqual(count, 4)

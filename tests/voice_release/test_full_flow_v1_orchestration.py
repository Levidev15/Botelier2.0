"""Exercise candidate-only full-flow CI with a Docker command double."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/voice_release/check_full_flow_v1.sh"
REVISION = "a" * 40


class FullFlowV1OrchestrationTests(unittest.TestCase):
    def launch(
        self, *, actions="true", image=None, revision=REVISION,
        fail_guard="", stale_checkpoint=False,
        mcp_self_test_denials="12", mcp_blocked_attempts="0",
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "docker.jsonl"
            if stale_checkpoint:
                (root / "evidence").mkdir()
                (root / "evidence/full-flow-v1-checkpoint.json").write_text(
                    json.dumps({"commit": "c" * 40, "result": "passed"})
                )
            binary = root / "docker"
            binary.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "args=sys.argv[1:]\n"
                "with open(os.environ['FIXTURE_DOCKER_LOG'],'a') as out:\n"
                " out.write(json.dumps(args)+'\\n')\n"
                "target=os.environ.get('FIXTURE_FAIL_GUARD')\n"
                "self_test_denials=os.environ.get('FIXTURE_MCP_SELF_TEST_DENIALS','12')\n"
                "blocked_attempts=os.environ.get('FIXTURE_MCP_BLOCKED_ATTEMPTS','0')\n"
                "matched=any(a.endswith('/'+target) for a in args) if target else False\n"
                "mcp_guard=any(a.endswith('/mcp_management_guard.py') for a in args)\n"
                "if target=='mcp_management_self_test':\n"
                " matched=mcp_guard and '--self-test' in args\n"
                "if target=='mcp_management_tests':\n"
                " matched=mcp_guard and any(a.endswith('/test_mcp_native_policy.py') "
                "for a in args)\n"
                "if matched:\n"
                " print('synthetic guarded-suite failure',file=sys.stderr)\n"
                " sys.exit(19)\n"
                "if mcp_guard and '--self-test' in args:\n"
                " print('{\"guard_self_test\":\"passed\",\"expected_denials\":'+"
                "self_test_denials+'}')\n"
                "elif mcp_guard:\n"
                " print('MCP_MANAGEMENT_GUARD_BLOCKED_ATTEMPTS='+blocked_attempts)\n"
                "print('synthetic command enumeration only, not test evidence')\n"
            )
            binary.chmod(0o700)
            result = subprocess.run(
                ["bash", str(SCRIPT)], text=True, capture_output=True, timeout=15,
                env={
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "GITHUB_ACTIONS": actions,
                    "IMAGE": image or "voice-flow-candidate:" + REVISION,
                    "GITHUB_SHA": revision,
                    "RUNNER_TEMP": str(root),
                    "GITHUB_WORKSPACE": str(ROOT),
                    "EVIDENCE": str(root / "evidence"),
                    "FIXTURE_DOCKER_LOG": str(log),
                    "FIXTURE_FAIL_GUARD": fail_guard,
                    "FIXTURE_MCP_SELF_TEST_DENIALS": mcp_self_test_denials,
                    "FIXTURE_MCP_BLOCKED_ATTEMPTS": mcp_blocked_attempts,
                },
            )
            calls = [
                json.loads(line) for line in log.read_text().splitlines()
            ] if log.exists() else []
            checkpoints = list((root / "evidence").glob("*checkpoint.json"))
            evidence = json.loads(checkpoints[0].read_text()) if checkpoints else None
            return result, calls, evidence

    def test_runs_all_profiles_on_the_exact_revision_without_network(self):
        result, calls, evidence = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 5)
        guards = []
        exercised = set()
        for call in calls:
            self.assertEqual(call[:2], ["run", "--rm"])
            self.assertEqual(call[call.index("--network") + 1], "none")
            self.assertIn("--read-only", call)
            self.assertIn("voice-flow-candidate:" + REVISION, call)
            self.assertNotIn("-p", call)
            self.assertNotIn("--publish", call)
            self.assertNotIn("--env-file", call)
            self.assertIn("-i", call)
            self.assertIn("PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", call)
            self.assertTrue(any(item.endswith(":/test-tools:ro") for item in call))
            self.assertTrue(any(
                item.endswith(":/ci/examples/features/botelier-flow-trial:ro")
                for item in call
            ))
            guards.extend(
                item.rsplit("/", 1)[-1] for item in call
                if item.endswith("_guard.py")
            )
            exercised.update(
                item.rsplit("/", 1)[-1] for item in call
                if item.endswith(".py") and "/test_" in item
            )
        self.assertEqual(guards, [
            "application_guard.py", "lifecycle_guard.py", "editor_guard.py",
            "mcp_management_guard.py", "mcp_management_guard.py",
        ])
        self.assertIn(
            "/ci/examples/features/botelier-flow-trial/test_native_prepared_transport.py",
            calls[1],
        )
        for name in (
            "test_native_effect_ledger.py", "test_native_record_actions.py",
            "test_native_flow_recovery.py", "test_flow_response_preview_routes.py",
        ):
            self.assertIn("/ci/examples/features/botelier-flow-trial/" + name, calls[2])
            self.assertNotIn("/ci/examples/features/botelier-flow-trial/" + name, calls[0])
            self.assertNotIn("/ci/examples/features/botelier-flow-trial/" + name, calls[1])
        self.assertTrue({
            "test_native_graph.py", "test_native_graph_imports.py",
            "test_native_values.py", "test_native_output_values.py",
            "test_native_request_templates.py", "test_native_prepared_transport.py",
            "test_reservation_quote_contract.py", "test_native_quote_actions.py",
            "test_native_quote_graph.py",
            "test_native_graph_runtime.py", "test_native_graph_corrections.py",
            "test_native_graph_text_host.py", "test_native_graph_host_selection.py",
            "test_native_actions.py", "test_native_effect_ledger.py",
            "test_native_effect_actions.py", "test_native_capabilities.py",
            "test_native_messaging.py", "test_native_tool_sources.py",
            "test_native_record_actions.py", "test_native_integration_binding.py",
            "test_native_integration_resolution.py", "test_native_quote_bridge.py",
            "test_native_quote_delivery.py",
            "test_flow_response_preview.py", "test_flow_response_preview_routes.py",
            "test_native_flow_recovery.py",
        }.issubset(exercised), exercised)
        self.assertIn(
            "/ci/examples/features/botelier-flow-trial/test_native_quote_actions.py",
            calls[0],
        )
        self.assertIn(
            "/ci/examples/features/botelier-flow-trial/test_native_quote_graph.py",
            calls[0],
        )
        editor = set(
            item.rsplit("/", 1)[-1] for item in calls[2]
            if item.endswith(".py") and "/test_" in item
        )
        for name in (
            "test_native_actions.py", "test_native_capabilities.py",
            "test_native_tool_sources.py", "test_native_integration_resolution.py",
            "test_native_quote_bridge.py", "test_native_quote_delivery.py",
        ):
            self.assertIn(name, editor)
            self.assertNotIn(
                "/ci/examples/features/botelier-flow-trial/" + name, calls[1],
            )
        self.assertIn("--self-test", calls[3])
        self.assertNotIn("--tests", calls[3])
        self.assertIn("NEXTAUTH_SECRET=botelier-editor-trial-only-synthetic-nextauth-secret-v1", calls[3])
        self.assertIn("NEXTAUTH_SECRET=botelier-editor-trial-only-synthetic-nextauth-secret-v1", calls[4])
        self.assertIn(
            "INTEGRATION_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            calls[3],
        )
        self.assertIn(
            "INTEGRATION_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            calls[4],
        )
        self.assertIn("BOTELIER_NATIVE_FLOWS_DEV=1", calls[3])
        self.assertIn("BOTELIER_NATIVE_FLOWS_DEV=1", calls[4])
        self.assertIn("NEXTAUTH_URL=http://127.0.0.1:5011", calls[3])
        self.assertIn("NEXTAUTH_URL=http://127.0.0.1:5011", calls[4])
        self.assertIn("--tests", calls[4])
        self.assertEqual(
            [
                item for item in calls[4]
                if item.endswith(".py") and "/test_" in item
            ],
            ["/ci/examples/features/botelier-flow-trial/test_mcp_native_policy.py"],
        )
        self.assertNotIn("test_mcp_native_policy.py", calls[0])
        self.assertNotIn("test_mcp_native_policy.py", calls[1])
        self.assertNotIn("test_mcp_native_policy.py", calls[2])
        self.assertIn(
            "/ci/examples/features/botelier-flow-trial/test_mcp_native_policy.py",
            calls[4],
        )
        self.assertEqual(evidence["commit"], REVISION)
        self.assertFalse(evidence["production_activation"])
        self.assertFalse(evidence["manual_audio_certified"])
        self.assertEqual(evidence["providers"], "synthetic")
        self.assertEqual(evidence["result"], "passed")
        self.assertEqual(evidence["completed_boundaries"], [
            "application_guard", "lifecycle_guard", "editor_guard",
            "mcp_management_self_test", "mcp_management_guard",
        ])

    def test_refuses_local_execution_before_any_docker_invocation(self):
        result, calls, _ = self.launch(actions="false")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_refuses_a_non_candidate_image_before_any_docker_invocation(self):
        result, calls, _ = self.launch(image="production:latest")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_refuses_a_mismatched_revision_before_any_docker_invocation(self):
        result, calls, _ = self.launch(revision="b" * 40)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_preserves_suite_failure_and_stops_before_later_boundaries(self):
        for count, guard in enumerate(
            (
                "application_guard.py", "lifecycle_guard.py", "editor_guard.py",
                "mcp_management_self_test", "mcp_management_tests",
            ), 1,
        ):
            with self.subTest(guard=guard):
                result, calls, evidence = self.launch(
                    fail_guard=guard, stale_checkpoint=True,
                )
                self.assertEqual(result.returncode, 19, result.stderr)
                self.assertEqual(len(calls), count)
                self.assertIsNone(
                    evidence, "A failed rerun must not leave a completed checkpoint.",
                )

    def test_mcp_self_test_must_report_all_twelve_denials_before_suite(self):
        result, calls, evidence = self.launch(
            mcp_self_test_denials="11", stale_checkpoint=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(calls), 4)
        self.assertIn("--self-test", calls[3])
        self.assertIsNone(evidence)

    def test_mcp_suite_must_report_zero_guard_blocks_before_completion(self):
        result, calls, evidence = self.launch(
            mcp_blocked_attempts="1", stale_checkpoint=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 5)
        self.assertIn("/test_mcp_native_policy.py", calls[4][-1])
        self.assertIsNone(evidence)

    def test_the_real_workflow_invokes_the_full_v1_gate_without_replacing_old_checks(self):
        source = (ROOT / ".github/workflows/voice-flow-candidate.yml").read_text()
        self.assertTrue(
            "bash scripts/voice_release/check_full_flow_v1.sh" in source,
            "The candidate workflow must run the full V1 gate.",
        )
        self.assertIn("test_pilot_handoff_input.py", source)
        self.assertIn("test_application_mcp_contracts.py", source)
        self.assertIn("test_native_simulation_api.py", source)

    def test_the_full_v1_step_is_mandatory_before_image_export(self):
        source = yaml.safe_load(
            (ROOT / ".github/workflows/voice-flow-candidate.yml").read_text()
        )
        steps = source["jobs"]["candidate"]["steps"]
        matches = [
            (index, step) for index, step in enumerate(steps)
            if step.get("id") == "full_flow_v1"
        ]
        self.assertEqual(len(matches), 1)
        index, step = matches[0]
        self.assertEqual(step["run"], "bash scripts/voice_release/check_full_flow_v1.sh")
        self.assertNotIn("if", step)
        self.assertNotIn("continue-on-error", step)
        self.assertEqual(step["env"]["IMAGE"], "voice-flow-candidate:${{ github.sha }}")
        exports = [
            order for order, value in enumerate(steps)
            if "docker save " in value.get("run", "")
        ]
        self.assertTrue(exports, "The candidate workflow should retain its image export.")
        self.assertLess(index, min(exports))

    def test_mcp_portable_guard_policy_is_in_existing_release_test_discovery(self):
        workflow = (ROOT / ".github/workflows/voice-flow-candidate.yml").read_text()
        self.assertIn(
            "python -B -m unittest discover -s tests/voice_release -v", workflow,
        )
        self.assertTrue(
            (ROOT / "tests/voice_release/test_mcp_management_guard.py").is_file(),
        )
        script = SCRIPT.read_text()
        self.assertIn('"expected_denials"[[:space:]]*:[[:space:]]*12', script)
        self.assertIn("MCP_MANAGEMENT_GUARD_BLOCKED_ATTEMPTS=0", script)

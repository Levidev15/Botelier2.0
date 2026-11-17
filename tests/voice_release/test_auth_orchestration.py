"""Execute the auth CI runner with controlled process I/O, never a live DB."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/voice_release/check_auth_alignment.sh"
IMAGE = "voice-flow-candidate:" + "b" * 40


class AuthOrchestrationTests(unittest.TestCase):
    def launch(self, *, image=IMAGE, actions="true", fail=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "botelier/frontend").mkdir(parents=True)
            (root / "deps/node_modules/next-auth").mkdir(parents=True)
            binary = root / "docker"
            binary.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "from pathlib import Path\n"
                "args=sys.argv[1:]\n"
                "with open(os.environ['FIXTURE_DOCKER_LOG'],'a') as f: f.write(json.dumps(args)+'\\n')\n"
                "probes=Path(os.environ['FIXTURE_DOCKER_LOG']+'.probes')\n"
                "if args[0]=='exec' and '/proc/1/comm' in ' '.join(args):\n"
                " n=int(probes.read_text())+1 if probes.exists() else 1\n"
                " probes.write_text(str(n)); sys.exit(0 if n>=2 else 1)\n"
                "if args[:2]==['run','-d']:\n"
                " if 'POSTGRES_HOST_AUTH_METHOD=trust' not in args: sys.exit(23)\n"
                " if 'unix_socket_directories=/var/run/postgresql,/tmp/botelier-auth-fixture' not in args: sys.exit(25)\n"
                " print('synthetic-auth-fixture')\n"
                "if args[:2]==['run','--rm'] and 'auth_guard.py' in ' '.join(args):\n"
                " if not probes.exists() or int(probes.read_text())<2: sys.exit(24)\n"
                " if os.environ.get('FAIL_CHECK') and os.environ['FAIL_CHECK'] in ' '.join(args): sys.exit(19)\n"
            )
            binary.chmod(0o700)
            log = root / "docker.jsonl"
            result = subprocess.run(
                ["bash", str(SCRIPT)], text=True, capture_output=True, timeout=15,
                env={
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "GITHUB_ACTIONS": actions, "IMAGE": image,
                    "RUNNER_TEMP": str(root), "GITHUB_WORKSPACE": str(root),
                    "EVIDENCE": str(root / "evidence"),
                    "FRONTEND_DEPENDENCIES": str(root / "deps/node_modules"),
                    "FIXTURE_DOCKER_LOG": str(log), "FAIL_CHECK": fail,
                },
            )
            calls = (
                [json.loads(line) for line in log.read_text().splitlines()]
                if log.exists() else []
            )
            return result, calls, list(root.glob("voice-auth-socket.*"))

    def test_checks_real_auth_and_legacy_upgrade_in_isolated_processes_then_cleans_up(self):
        result, calls, remaining = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in calls if call[0] == "run"]
        self.assertEqual(len(runs), 4)
        self.assertIn("POSTGRES_DB=voice_auth_fixture", runs[0])
        self.assertIn("listen_addresses=", runs[0])
        for call in runs:
            self.assertEqual(call[call.index("--network") + 1], "none")
            self.assertIn("--read-only", call)
            self.assertNotIn("-p", call)
            self.assertNotIn("--publish", call)
        checks = runs[1:]
        self.assertIn("--self-test", checks[0])
        self.assertIn("/app/tests/test_authenticator_mfa.py", checks[1])
        self.assertNotIn("--postgres", checks[1])
        self.assertIn("--postgres", checks[2])
        self.assertIn("/app/tests/test_mfa_postgres_races.py", checks[2])
        self.assertIn(
            "/ci/examples/features/botelier-flow-trial/test_mfa_schema_upgrade.py",
            checks[2],
        )
        for call in checks:
            self.assertIn("-i", call)
            self.assertIn("env", call)
            mounts = [call[i + 1] for i, value in enumerate(call) if value == "-v"]
            self.assertTrue(any(m.endswith(":/frontend:ro") for m in mounts))
            self.assertTrue(any(m.endswith(":/frontend/node_modules:ro") for m in mounts))
            self.assertTrue(any(m.endswith(":/test-node/node:ro") for m in mounts))
            self.assertTrue(any(m.endswith(":/tmp/botelier-auth-fixture:ro") for m in mounts))
        self.assertEqual(calls[-1], ["rm", "-f", "synthetic-auth-fixture"])
        self.assertTrue(any(call[0] == "logs" for call in calls))
        self.assertTrue(any(call[0] == "inspect" for call in calls))
        self.assertEqual(remaining, [])

    def test_failed_auth_stops_before_postgres_tests_and_still_cleans_up(self):
        result, calls, remaining = self.launch(fail="test_authenticator_mfa.py")
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertFalse(any("test_mfa_postgres_races.py" in " ".join(c) for c in calls))
        self.assertEqual(calls[-1], ["rm", "-f", "synthetic-auth-fixture"])
        self.assertEqual(remaining, [])

    def test_rejects_non_candidate_image_before_any_process_io(self):
        result, calls, _ = self.launch(image="production:latest")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_rejects_local_docker_invocation_before_any_process_io(self):
        result, calls, _ = self.launch(actions="false")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

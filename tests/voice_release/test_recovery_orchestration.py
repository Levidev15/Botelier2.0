"""Execute CI orchestration with an enumerated Docker I/O double, never a DB."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/voice_release/check_transfer_recovery.sh"
IMAGE = "voice-flow-candidate:" + "a" * 40


class RecoveryOrchestrationTests(unittest.TestCase):
    def launch(self, *, image=IMAGE, actions="true", fail_suite=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "docker"
            binary.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "args=sys.argv[1:]\n"
                "with open(os.environ['FIXTURE_DOCKER_LOG'],'a') as f: f.write(json.dumps(args)+'\\n')\n"
                "probes=os.environ['FIXTURE_DOCKER_LOG']+'.probes'\n"
                "if args[0]=='exec' and '/proc/1/comm' in ' '.join(args):\n"
                " from pathlib import Path\n"
                " p=Path(probes); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n))\n"
                " sys.exit(0 if n>=2 else 1)\n"
                "if args[:2]==['run','-d']:\n"
                " if 'POSTGRES_HOST_AUTH_METHOD=trust' not in args:\n"
                "  print('Synthetic official-image password-free initialization refusal',file=sys.stderr); sys.exit(23)\n"
                " print('synthetic-fixture-container')\n"
                "if args[:2]==['run','--rm']:\n"
                " from pathlib import Path\n"
                " p=Path(probes)\n"
                " if not p.exists() or int(p.read_text())<2:\n"
                "  print('Synthetic temporary-server readiness false positive',file=sys.stderr); sys.exit(24)\n"
                "if os.environ.get('FAIL_SUITE') and any(os.environ['FAIL_SUITE'] in a for a in args): sys.exit(19)\n"
            )
            binary.chmod(0o700)
            log = root / "docker.jsonl"
            result = subprocess.run(
                ["bash", str(SCRIPT)], text=True, capture_output=True, timeout=15,
                env={
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "GITHUB_ACTIONS": actions, "IMAGE": image,
                    "RUNNER_TEMP": str(root), "GITHUB_WORKSPACE": str(ROOT),
                    "EVIDENCE": str(root / "evidence"),
                    "FIXTURE_DOCKER_LOG": str(log), "FAIL_SUITE": fail_suite,
                },
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls, list(root.glob("voice-recovery-socket.*"))

    def test_runs_three_isolated_processes_and_removes_the_disposable_database(self):
        result, calls, remaining = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in calls if call[0] == "run"]
        self.assertEqual(len(runs), 4)
        self.assertIn("listen_addresses=", runs[0])
        for call in runs:
            self.assertEqual(call[call.index("--network") + 1], "none")
            self.assertIn("--read-only", call)
            self.assertNotIn("-p", call)
            self.assertNotIn("--publish", call)
        actual = [call[-1].rsplit("/", 1)[-1] for call in runs[1:]]
        self.assertEqual(actual, [
            "test_transfer_attempts_postgres.py",
            "test_recovery_process_seed.py", "test_recovery_process_resume.py",
        ])
        for call in runs[1:]:
            self.assertIn("-i", call)
            self.assertIn("env", call)
            self.assertTrue(call[call.index("-v") + 1].endswith(":/offline-db:ro"))
        self.assertEqual(calls[-1], ["rm", "-f", "synthetic-fixture-container"])
        self.assertTrue(any(call[0] == "logs" for call in calls[:-1]))
        self.assertTrue(any(call[0] == "inspect" for call in calls[:-1]))
        self.assertEqual(remaining, [])
        probes = [i for i, call in enumerate(calls) if "/proc/1/comm" in " ".join(call)]
        first_client = next(i for i, call in enumerate(calls) if call[:2] == ["run", "--rm"])
        self.assertEqual(len(probes), 2)
        self.assertLess(probes[-1], first_client)

    def test_failed_suite_stops_recovery_and_still_cleans_up(self):
        result, calls, remaining = self.launch(fail_suite="test_transfer_attempts_postgres.py")
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertFalse(any("test_recovery_process_seed.py" in " ".join(call) for call in calls))
        self.assertEqual(calls[-1], ["rm", "-f", "synthetic-fixture-container"])
        diagnostic = next(call for call in calls if call[:2] == ["run", "--rm"] and "stat" in call)
        self.assertEqual(diagnostic[diagnostic.index("--network") + 1], "none")
        self.assertTrue(diagnostic[diagnostic.index("-v") + 1].endswith(":/offline-db:ro"))
        self.assertEqual(remaining, [])

    def test_a_non_candidate_image_is_rejected_before_docker(self):
        result, calls, _ = self.launch(image="production:latest")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_local_invocation_is_rejected_before_docker(self):
        result, calls, _ = self.launch(actions="false")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

"""Exercise the real release CLI without credentials, GitHub or Azure access."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts/voice_release/authorize.py"
SHA = "a" * 40


def approved_request():
    return {
        "target": "production",
        "event_name": "workflow_dispatch",
        "ref": "refs/heads/main",
        "sha": SHA,
        "approved_sha": SHA,
        "calls_drained": True,
        "checks_passed": True,
        "environment": {
            "id": 12,
            "name": "voice-production",
            "protection_rules": [
                {
                    "id": 13,
                    "type": "required_reviewers",
                    "prevent_self_review": True,
                    "reviewers": [
                        {"type": "Team", "reviewer": {"id": 42, "slug": "release-reviewers"}}
                    ],
                }
            ],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        },
        "branch_policies": {
            "total_count": 1,
            "branch_policies": [{"id": 14, "name": "main", "type": "branch"}],
        },
    }


class ReleaseAuthorizationTests(unittest.TestCase):
    def run_cli(self, request=None, raw=None):
        self.assertTrue(POLICY.is_file(), "The release-authorization CLI is not implemented")
        result = subprocess.run(
            [sys.executable, "-B", str(POLICY)],
            input=raw if raw is not None else json.dumps(request),
            capture_output=True,
            text=True,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=10,
        )
        self.assertTrue(result.stdout.strip(), "Policy must return a structured decision")
        decision = json.loads(result.stdout)
        self.assertEqual(set(decision), {"allowed", "reason"})
        self.assertEqual(result.stderr, "")
        return result.returncode, decision

    def assert_denied(self, request, reason):
        code, decision = self.run_cli(request)
        self.assertEqual(code, 2)
        self.assertEqual(decision, {"allowed": False, "reason": reason})

    def test_manual_main_commit_requires_all_gates(self):
        code, decision = self.run_cli(approved_request())
        self.assertEqual(code, 0)
        self.assertEqual(decision, {"allowed": True, "reason": "approved_production_release"})

    def test_push_and_pull_request_never_authorize_release(self):
        for event in ("push", "pull_request", "workflow_run", "", None):
            with self.subTest(event=event):
                request = approved_request()
                request["event_name"] = event
                self.assert_denied(request, "manual_dispatch_required")

    def test_candidate_branches_and_tags_cannot_release_production(self):
        for ref in ("refs/heads/candidate/pilot", "refs/tags/main", "main", None):
            with self.subTest(ref=ref):
                request = approved_request()
                request["ref"] = ref
                self.assert_denied(request, "production_main_ref_required")

    def test_staging_or_user_selected_targets_cannot_reach_production(self):
        for target in ("staging", "candidate", "", None, "production;echo unsafe"):
            with self.subTest(target=target):
                request = approved_request()
                request["target"] = target
                self.assert_denied(request, "production_target_required")

    def test_exact_commit_must_be_approved(self):
        for approved in ("b" * 40, SHA[:7], "", None, True):
            with self.subTest(approved=approved):
                request = approved_request()
                request["approved_sha"] = approved
                self.assert_denied(request, "exact_commit_approval_required")

    def test_commit_must_be_full_hex_not_a_shell_or_ref_expression(self):
        for sha in ("a" * 39, "g" * 40, "main", "$(echo unsafe)", 123, None):
            with self.subTest(sha=sha):
                request = approved_request()
                request["sha"] = sha
                request["approved_sha"] = sha
                self.assert_denied(request, "invalid_commit")

    def test_calls_drained_requires_a_real_boolean(self):
        for value in (False, "true", "false", 1, "", None):
            with self.subTest(value=value):
                request = approved_request()
                request["calls_drained"] = value
                self.assert_denied(request, "call_drain_acknowledgement_required")

    def test_failed_or_skipped_checks_cannot_authorize_release(self):
        for value in (False, "success", "true", 1, None):
            with self.subTest(value=value):
                request = approved_request()
                request["checks_passed"] = value
                self.assert_denied(request, "checks_not_passed")

    def test_missing_unprotected_or_wrong_environment_is_rejected(self):
        for env in (None, {}, {"name": "voice-production"}, {"name": "staging"}):
            with self.subTest(environment=env):
                request = approved_request()
                request["environment"] = env
                self.assert_denied(request, "protected_environment_required")

    def test_required_reviewers_must_be_present_and_cannot_self_approve(self):
        for patch in ({"reviewers": []}, {"prevent_self_review": False},
                      {"prevent_self_review": "true"}, {"reviewers": None}):
            with self.subTest(patch=patch):
                request = approved_request()
                request["environment"]["protection_rules"][0].update(patch)
                self.assert_denied(request, "independent_review_required")

    def test_timer_or_other_rules_do_not_substitute_for_review(self):
        request = approved_request()
        request["environment"]["protection_rules"] = [{"type": "wait_timer", "wait_timer": 30}]
        self.assert_denied(request, "independent_review_required")

    def test_malformed_reviewer_metadata_is_denied_without_crashing(self):
        for reviewer_type in ([], {}, None):
            with self.subTest(reviewer_type=reviewer_type):
                request = approved_request()
                request["environment"]["protection_rules"][0]["reviewers"][0]["type"] = reviewer_type
                self.assert_denied(request, "independent_review_required")

    def test_wildcard_tag_and_extra_branch_policies_are_denied(self):
        for policies in (
            [{"name": "*", "type": "branch"}],
            [{"name": "main", "type": "tag"}],
            [{"name": "main", "type": "branch"}, {"name": "candidate/*", "type": "branch"}],
            [],
        ):
            with self.subTest(policies=policies):
                request = approved_request()
                request["branch_policies"] = {
                    "total_count": len(policies), "branch_policies": policies
                }
                self.assert_denied(request, "main_only_environment_required")

    def test_incomplete_or_unrestricted_branch_metadata_is_denied(self):
        for change in ("missing", "incomplete", "unrestricted"):
            with self.subTest(change=change):
                request = approved_request()
                if change == "missing":
                    request["branch_policies"] = None
                elif change == "incomplete":
                    request["branch_policies"]["total_count"] = 2
                else:
                    request["environment"]["deployment_branch_policy"] = None
                self.assert_denied(request, "main_only_environment_required")

    def test_missing_approval_fields_are_not_silently_defaulted(self):
        for key in ("approved_sha", "calls_drained", "checks_passed"):
            with self.subTest(key=key):
                request = approved_request()
                request.pop(key)
                expected = {
                    "approved_sha": "exact_commit_approval_required",
                    "calls_drained": "call_drain_acknowledgement_required",
                    "checks_passed": "checks_not_passed",
                }[key]
                self.assert_denied(request, expected)

    def test_malformed_oversized_and_non_object_input_is_structurally_denied(self):
        for raw in ("{", "[]", "null", '"text"', " " * 65537,
                    "[" * 1100 + "0" + "]" * 1100):
            with self.subTest(raw=raw[:20]):
                code, decision = self.run_cli(raw=raw)
                self.assertEqual(code, 2)
                self.assertEqual(decision, {"allowed": False, "reason": "invalid_request"})

    def test_denial_does_not_echo_untrusted_data(self):
        request = approved_request()
        request["approved_sha"] = "DO_NOT_LOG_PRIVATE_INPUT"
        code, decision = self.run_cli(request)
        self.assertEqual(code, 2)
        self.assertNotIn("DO_NOT_LOG_PRIVATE_INPUT", json.dumps(decision))

    def test_input_metadata_is_not_modified(self):
        # Exercise the importable decision function as well as its CLI wrapper.
        self.assertTrue(POLICY.is_file(), "The release-authorization module is not implemented")
        import importlib.util

        spec = importlib.util.spec_from_file_location("voice_release_policy", POLICY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        request = approved_request()
        before = copy.deepcopy(request)
        self.assertTrue(module.authorize(request)["allowed"])
        self.assertEqual(request, before)


if __name__ == "__main__":
    unittest.main()

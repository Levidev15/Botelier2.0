"""Fail-closed, credential-free authorization for the manual voice release job.

GitHub enforces the environment review before the job starts. This additional
check rejects missing protection metadata, wrong revisions and accidental pushes;
it does not query GitHub, drain calls or perform a deployment itself.
"""

import json
import re
import sys


MAX_REQUEST_BYTES = 65536


def deny(reason):
    return {"allowed": False, "reason": reason}


def _independent_review(environment):
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_reviewers":
            continue
        reviewers = rule.get("reviewers")
        if rule.get("prevent_self_review") is not True or not isinstance(reviewers, list):
            continue
        if reviewers and all(
            isinstance(entry, dict)
            and isinstance(entry.get("type"), str)
            and entry.get("type") in {"User", "Team"}
            and isinstance(entry.get("reviewer"), dict)
            and type(entry["reviewer"].get("id")) is int
            and entry["reviewer"]["id"] > 0
            for entry in reviewers
        ):
            return True
    return False


def _main_only(environment, metadata):
    policy = environment.get("deployment_branch_policy")
    if not isinstance(policy, dict):
        return False
    if policy.get("protected_branches") is not False:
        return False
    if policy.get("custom_branch_policies") is not True:
        return False
    if not isinstance(metadata, dict):
        return False
    entries = metadata.get("branch_policies")
    return (
        type(metadata.get("total_count")) is int
        and metadata["total_count"] == 1
        and isinstance(entries, list)
        and len(entries) == 1
        and isinstance(entries[0], dict)
        and entries[0].get("name") == "main"
        and entries[0].get("type") == "branch"
    )


def authorize(request):
    """Decide from verified workflow inputs and GitHub's real environment data."""
    if not isinstance(request, dict):
        return deny("invalid_request")
    if request.get("target") != "production":
        return deny("production_target_required")
    if request.get("event_name") != "workflow_dispatch":
        return deny("manual_dispatch_required")
    if request.get("ref") != "refs/heads/main":
        return deny("production_main_ref_required")
    sha = request.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        return deny("invalid_commit")
    if request.get("approved_sha") != sha:
        return deny("exact_commit_approval_required")
    if request.get("calls_drained") is not True:
        return deny("call_drain_acknowledgement_required")
    if request.get("checks_passed") is not True:
        return deny("checks_not_passed")
    environment = request.get("environment")
    if (
        not isinstance(environment, dict)
        or environment.get("name") != "voice-production"
        or not isinstance(environment.get("protection_rules"), list)
    ):
        return deny("protected_environment_required")
    if not _independent_review(environment):
        return deny("independent_review_required")
    if not _main_only(environment, request.get("branch_policies")):
        return deny("main_only_environment_required")
    return {"allowed": True, "reason": "approved_production_release"}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        request = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        decision = deny("invalid_request")
    else:
        decision = authorize(request)
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

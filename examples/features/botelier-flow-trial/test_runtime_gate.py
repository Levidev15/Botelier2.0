"""Acceptance tests for the isolated trial gate; no application imports."""

import importlib.util
from pathlib import Path

import pytest


def gate_module():
    """Load only the trial gate, not Botelier or a voice service."""
    path = Path(__file__).with_name("runtime_probe.py")
    assert path.is_file(), "Runtime gate is not implemented"
    spec = importlib.util.spec_from_file_location("trial_runtime_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("observed", "status", "exit_code"),
    [
        (
            {
                "import_root_matches": True,
                "flows_available": True,
                "handler_schemas": True,
                "base_schema_accepts_handler": True,
                "node_configs": True,
                "package_version": "1.5.0",
            },
            "compatible_for_isolated_trial",
            0,
        ),
        (
            {
                "import_root_matches": True,
                "flows_available": False,
                "package_version": "1.5.0",
            },
            "blocked_missing_flows",
            2,
        ),
        (
            {
                "import_root_matches": False,
                "flows_available": True,
                "handler_schemas": True,
                "node_configs": True,
                "package_version": "1.5.0",
            },
            "blocked_wrong_import_target",
            2,
        ),
        (
            {
                "import_root_matches": True,
                "flows_available": True,
                "handler_schemas": False,
                "node_configs": True,
                "package_version": "1.5.0",
            },
            "blocked_incompatible_api",
            2,
        ),
        ({}, "blocked_wrong_import_target", 2),
        (
            {
                "import_root_matches": True,
                "flows_available": True,
                "handler_schemas": True,
                "node_configs": True,
                "package_version": "999.0",
            },
            "blocked_unpinned_version",
            2,
        ),
    ],
)
def test_gate_rejects_incomplete_or_wrong_runtime(observed, status, exit_code):
    result = gate_module().classify(observed)
    assert result["status"] == status
    assert result["exit_code"] == exit_code


def test_runtime_gate_does_not_treat_dependency_failure_as_missing_flows():
    error = ModuleNotFoundError("missing unrelated dependency")
    error.name = "unrelated_dependency"
    assert gate_module().import_failure_code(error) == "dependency_import_failure"


def test_runtime_gate_recognizes_missing_flows_module():
    error = ModuleNotFoundError("No module named pipecat.flows")
    error.name = "pipecat.flows"
    assert gate_module().import_failure_code(error) == "missing_flows"


def test_runtime_gate_rejects_non_import_failures_as_missing_flows():
    assert gate_module().import_failure_code(RuntimeError("broken API")) == "runtime_import_failure"


def test_gate_requires_handler_support_in_selected_base_runtime():
    result = gate_module().classify({
        "import_root_matches": True,
        "flows_available": True,
        "handler_schemas": True,
        "base_schema_accepts_handler": False,
        "node_configs": True,
        "package_version": "1.5.0",
    })
    assert result == {"status": "blocked_incompatible_api", "exit_code": 2}


def guard_module():
    path = Path(__file__).with_name("guard.py")
    spec = importlib.util.spec_from_file_location("trial_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "keys",
    [
        {"PATH", "HOME", "LD_LIBRARY_PATH", "LC_CTYPE"},
        {"PATH", "HOME", "NLTK_DATA"},
    ],
)
def test_clean_nix_environment_is_accepted_without_reading_values(keys):
    module = guard_module()
    assert module.validate_environment_keys(keys) is None


@pytest.mark.parametrize("unexpected", ["OPENAI_API_KEY", "UNRECOGNIZED_TRIAL_SETTING"])
def test_secret_or_unrecognized_environment_is_rejected(unexpected):
    module = guard_module()
    with pytest.raises(module.TrialSafetyError):
        module.validate_environment_keys({"PATH", "HOME", unexpected})

"""Read-only runtime compatibility probe; it never initializes Botelier."""

import importlib
import inspect
from importlib.metadata import version
from pathlib import Path


PINNED_VERSION = "1.5.0"


def classify(observed, *, require_flows=True):
    """Fail closed on the exact runtime/API prerequisites of this trial."""
    if observed.get("import_root_matches") is not True:
        status = "blocked_wrong_import_target"
    elif observed.get("package_version") != PINNED_VERSION:
        status = "blocked_unpinned_version"
    elif not require_flows:
        status = "legacy_runtime_import_verified"
    elif observed.get("flows_available") is not True:
        status = "blocked_missing_flows"
    elif not (
        observed.get("handler_schemas") is True
        and observed.get("base_schema_accepts_handler") is True
        and observed.get("node_configs") is True
    ):
        status = "blocked_incompatible_api"
    else:
        status = "compatible_for_isolated_trial"
    passed = status in {"compatible_for_isolated_trial", "legacy_runtime_import_verified"}
    return {"status": status, "exit_code": 0 if passed else 2}


def import_failure_code(error):
    """Do not mislabel an unrelated dependency crash as missing Flows."""
    if isinstance(error, ModuleNotFoundError):
        return "missing_flows" if error.name == "pipecat.flows" else "dependency_import_failure"
    return "runtime_import_failure"


def observe(expected_root, *, require_flows=True):
    """Import actual selected packages and report their capabilities."""
    import pipecat
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.frames.frames import TTSSpeakFrame

    actual_root = Path(pipecat.__file__).resolve().parent
    observed = {
        "package_version": version("pipecat-ai"),
        "actual_package_root": str(actual_root),
        "import_root_matches": actual_root == Path(expected_root).resolve(),
        "tts_append_to_context_default": inspect.signature(TTSSpeakFrame).parameters[
            "append_to_context"
        ].default,
        "flows_available": False,
        "base_schema_accepts_handler": "handler" in inspect.signature(
            FunctionSchema
        ).parameters,
    }
    if not require_flows:
        observed["flows_available"] = None
        observed["flows_probe_skipped"] = True
        observed.update(classify(observed, require_flows=False))
        return observed
    try:
        flows = importlib.import_module("pipecat.flows")
    except Exception as error:
        code = import_failure_code(error)
        observed["import_failure"] = code
        observed["failure_type"] = type(error).__name__
        if code != "missing_flows":
            observed.update(status="blocked_" + code, exit_code=2)
            return observed
    else:
        observed.update(
            flows_available=True,
            flow_manager_file=inspect.getfile(flows.FlowManager),
            handler_schemas="handler" in inspect.signature(
                flows.FlowsFunctionSchema
            ).parameters,
            node_configs=all(
                key in flows.NodeConfig.__annotations__
                for key in ("task_messages", "functions", "context_strategy")
            ),
            declarative_flow_export=hasattr(flows, "Flow"),
        )
    observed.update(classify(observed))
    return observed

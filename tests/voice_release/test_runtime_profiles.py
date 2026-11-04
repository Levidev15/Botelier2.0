"""The legacy release gate must not misrepresent or require native Flows."""

import importlib.util
import inspect
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "runtime_probe", ROOT / "examples/features/botelier-flow-trial/runtime_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.assertIn(
            "require_flows", inspect.signature(probe.classify).parameters,
            "Image checks need an explicit legacy/native capability requirement",
        )

    def test_legacy_import_gate_does_not_require_flows_or_handler_schema(self):
        observed = {
            "import_root_matches": True, "package_version": "1.5.0",
            "flows_available": False, "base_schema_accepts_handler": False,
        }
        self.assertEqual(
            probe.classify(observed, require_flows=False),
            {"status": "legacy_runtime_import_verified", "exit_code": 0},
        )
        self.assertEqual(
            probe.classify(observed),
            {"status": "blocked_missing_flows", "exit_code": 2},
        )

    def test_both_profiles_reject_the_wrong_import_source(self):
        for require_flows in (True, False):
            with self.subTest(native=require_flows):
                result = probe.classify(
                    {"import_root_matches": False, "package_version": "1.5.0"},
                    require_flows=require_flows,
                )
                self.assertEqual(result, {"status": "blocked_wrong_import_target", "exit_code": 2})

    def test_both_profiles_reject_unpinned_distribution_versions(self):
        for require_flows in (True, False):
            with self.subTest(native=require_flows):
                result = probe.classify(
                    {"import_root_matches": True, "package_version": "1.4.0"},
                    require_flows=require_flows,
                )
                self.assertEqual(result, {"status": "blocked_unpinned_version", "exit_code": 2})

    def test_native_profile_still_requires_real_handler_and_node_apis(self):
        result = probe.classify({
            "import_root_matches": True, "package_version": "1.5.0",
            "flows_available": True, "handler_schemas": True,
            "base_schema_accepts_handler": False, "node_configs": True,
        })
        self.assertEqual(result, {"status": "blocked_incompatible_api", "exit_code": 2})

    def test_legacy_success_is_not_labelled_as_native_compatibility(self):
        result = probe.classify(
            {"import_root_matches": True, "package_version": "1.5.0"},
            require_flows=False,
        )
        self.assertNotIn("compatible_for_isolated_trial", result.values())
        self.assertIn("legacy", result["status"])

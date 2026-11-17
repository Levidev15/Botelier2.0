"""Guarded regressions for pure package import boundaries."""

import ast
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace


def _backend_root_from_package():
    package = importlib.import_module("botelier")
    package_paths = getattr(package, "__path__", ())
    candidates = list(package_paths) if package_paths is not None else []
    spec = getattr(package, "__spec__", None)
    spec_paths = getattr(spec, "submodule_search_locations", None)
    if spec_paths is not None:
        candidates.extend(spec_paths)
    for package_path in candidates:
        package_dir = Path(package_path).resolve()
        if package_dir.name != "botelier":
            continue
        backend = package_dir.parent
        if (
            (package_dir / "voice" / "__init__.py").is_file()
            and (package_dir / "services" / "__init__.py").is_file()
        ):
            return backend
    raise AssertionError("Could not locate the loaded botelier package source")


def test_voice_public_exports_are_lazy_before_compiler_import():
    backend = _backend_root_from_package()
    initializer = backend / "botelier" / "voice" / "__init__.py"
    source = initializer.read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager_modules = {
        alias.name for statement in tree.body if isinstance(statement, ast.ImportFrom)
        for alias in statement.names
    }
    assert "CallHandler" not in eager_modules
    assert "call_handler" in source


def test_services_exports_are_lazy_before_importing_pure_submodules():
    backend = _backend_root_from_package()
    initializer = backend / "botelier" / "services" / "__init__.py"
    source = initializer.read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager_modules = {
        alias.name for statement in tree.body if isinstance(statement, ast.ImportFrom)
        for alias in statement.names
    }
    assert not {"CallLogger", "MCPClient", "mcp_client_pool"} & eager_modules
    assert "_PUBLIC_EXPORTS" in source


def test_native_graph_and_pure_projection_import_normally_under_component_guard():
    voice = importlib.import_module("botelier.voice")
    compiler = importlib.import_module("botelier.voice.flows.native_graph")
    from botelier.voice.flows import FlowTemplates
    from botelier.services import response_projection
    services = importlib.import_module("botelier.services")

    assert {"VoiceAgent", "CallHandler"} <= set(voice.__all__)
    assert "VoiceAgent" in dir(voice) and "CallHandler" in dir(voice)
    assert compiler.__file__.endswith("/botelier/voice/flows/native_graph.py")
    assert callable(FlowTemplates.list_templates)
    assert callable(response_projection.validate_mapped_projection)
    assert set(services.__all__) == set(services._PUBLIC_EXPORTS)
    assert "botelier.voice.call_handler" not in sys.modules
    assert "botelier.services.call_logger" not in sys.modules
    assert "botelier.services.mcp_client" not in sys.modules


def test_voice_agent_public_import_remains_available_lazily():
    from botelier.voice import VoiceAgent

    assert callable(VoiceAgent)
    assert "botelier.voice.call_handler" not in sys.modules


def test_call_handler_public_export_remains_lazy_without_loading_guarded_component(monkeypatch):
    voice = importlib.import_module("botelier.voice")
    fake_handler = object()
    requests = []

    def fake_import(module_name, package_name):
        requests.append((module_name, package_name))
        return SimpleNamespace(CallHandler=fake_handler)

    monkeypatch.setattr(voice, "import_module", fake_import)
    try:
        assert voice.__getattr__("CallHandler") is fake_handler
        assert voice.CallHandler is fake_handler
        assert requests == [(".call_handler", "botelier.voice")]
    finally:
        voice.__dict__.pop("CallHandler", None)
    assert "botelier.voice.call_handler" not in sys.modules


def test_legacy_service_exports_resolve_lazily_without_service_startup(monkeypatch):
    services = importlib.import_module("botelier.services")
    for public_name, (module_name, attribute) in services._PUBLIC_EXPORTS.items():
        marker = object()
        requests = []

        def fake_import(module, package, attribute=attribute, marker=marker):
            requests.append((module, package))
            return SimpleNamespace(**{attribute: marker})

        monkeypatch.setattr(services, "import_module", fake_import)
        try:
            assert getattr(services, public_name) is marker
            assert requests == [(module_name, "botelier.services")]
        finally:
            services.__dict__.pop(public_name, None)

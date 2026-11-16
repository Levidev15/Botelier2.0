"""Offline guard for the real simulation router and native text host.

Only ``botelier.api.simulation`` is admitted. The API/database package
initializers are replaced with inert namespaces before import; the simulator,
auth middleware, ORM models, FlowManager, adapters, host, and workers stay real.
"""

import argparse
import importlib.abc
from importlib.machinery import ModuleSpec
import json
import os
from pathlib import Path
import sys
import types

import application_guard
import guard


TEST_NEXTAUTH_SECRET = (
    "botelier-flow-trial-only-synthetic-nextauth-secret-v1-not-a-credential"
)
_EXTRA_ENV = {
    "NEXTAUTH_SECRET",
    "BOTELIER_ENV",
    "BOTELIER_NATIVE_FLOWS_DEV",
}


class SimulationServices(application_guard.NoLiveApplicationServices):
    """Allow only the actual simulator route, not API package side imports."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"botelier.api", "botelier.api.simulation"}:
            return None
        return super().find_spec(fullname, path, target)


def install_test_namespaces(backend: Path):
    """Provide inert package boundaries without importing server/database boot."""
    from sqlalchemy.orm import declarative_base

    database = types.ModuleType("botelier.database")
    database.__package__ = "botelier"
    database.__spec__ = ModuleSpec("botelier.database", loader=None)
    database.Base = declarative_base()
    database._session_factory = None

    def bind_session_factory(factory):
        database._session_factory = factory

    def forbidden_database_factory(*args, **kwargs):
        guard.deny("live_database_session_requested")

    def get_db():
        factory = database._session_factory
        if factory is None:
            guard.deny("synthetic_database_session_not_configured")
        session = factory()
        try:
            yield session
        finally:
            session.close()

    database.bind_session_factory = bind_session_factory
    database.SessionLocal = forbidden_database_factory
    database.get_db = get_db
    sys.modules["botelier.database"] = database

    # botelier.api.__init__ imports every route. Install only a namespace path,
    # then let the import gate load the one real simulation.py module.
    api_path = backend / "botelier" / "api"
    api_namespace = types.ModuleType("botelier.api")
    api_namespace.__package__ = "botelier.api"
    api_namespace.__path__ = [str(api_path)]
    api_namespace.__spec__ = ModuleSpec(
        "botelier.api", loader=None, is_package=True,
    )
    sys.modules["botelier.api"] = api_namespace

    from application_support import load_voice_engine

    load_voice_engine()
    return database


def _validate_environment():
    keys = set(os.environ)
    if keys - guard.ALLOWED_ENV - _EXTRA_ENV:
        raise guard.TrialSafetyError(
            "Run simulation_guard with only the documented env -i values"
        )
    if os.environ.get("NEXTAUTH_SECRET") != TEST_NEXTAUTH_SECRET:
        raise guard.TrialSafetyError(
            "NEXTAUTH_SECRET must be the fixed simulation-trial-only synthetic value"
        )
    if (
        os.environ.get("BOTELIER_ENV") != "development"
        or os.environ.get("BOTELIER_NATIVE_FLOWS_DEV") != "1"
    ):
        raise guard.TrialSafetyError(
            "Native API tests require the explicit synthetic development opt-in"
        )
    # Reuse the existing allowlist unchanged for every non-synthetic variable.
    guard.validate_environment_keys(keys - _EXTRA_ENV)


def _self_test(backend: Path):
    install_test_namespaces(backend)
    try:
        __import__("botelier.api.websockets")
    except guard.TrialSafetyError:
        pass
    else:
        raise AssertionError("A non-simulation API route was importable")
    assert guard.BLOCKED == ["live_application_or_database_import"]
    print(json.dumps({
        "simulation_guard": "passed",
        "forbidden_route_imports": len(guard.BLOCKED),
    }))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--diagnose", action="store_true")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args()

    _validate_environment()
    backend = args.backend_root.resolve()
    package = args.package_root.resolve()
    if not (backend / "botelier" / "voice" / "engine.py").is_file():
        parser.error("--backend-root must contain the actual voice engine")
    if package.name != "pipecat" or not args.package_root.is_absolute():
        parser.error("--package-root must be an absolute pipecat directory")

    sys.dont_write_bytecode = True
    guard.DIAGNOSTICS = args.diagnose
    sys.addaudithook(application_guard.application_audit)
    sys.meta_path.insert(0, SimulationServices())
    sys.path[:0] = [str(package.parent), str(backend)]

    if args.self_test:
        _self_test(backend)
        return 0

    import pipecat

    if Path(pipecat.__file__).resolve().parent != package:
        raise RuntimeError("Tests did not load the approved Pipecat source")
    install_test_namespaces(backend)

    import pytest

    print(json.dumps({
        "application_backend": str(backend),
        "pipecat_package": str(package),
        "scope": "actual_simulation_router_and_native_text_host_only",
    }, sort_keys=True))
    result = pytest.main([
        "-q",
        "--tb=short",
        "--noconftest",
        "-p",
        "no:cacheprovider",
        *(["-s"] if args.diagnose else []),
        "-c",
        str(Path(__file__).with_name("pytest.ini")),
        "--basetemp=/tmp/botelier-native-simulation-api/pytest-temp",
        "-o",
        "log_file=/tmp/botelier-native-simulation-api/pytest.log",
        *[str(path) for path in args.tests],
    ])
    print("SIMULATION_GUARD_BLOCKED_ATTEMPTS=" + str(len(guard.BLOCKED)))
    return 3 if guard.BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

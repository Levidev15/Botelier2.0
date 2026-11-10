"""Run actual voice-component tests without credentials, databases or networking.

This is a Python audit guard, not an OS sandbox. CI additionally uses Docker's
network-disabled, read-only filesystem. The normal framework guard is unchanged.
"""

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import guard


FORBIDDEN_IMPORTS = (
    "main", "database", "botelier.database", "botelier.api",
    "botelier.voice.call_handler", "psycopg", "psycopg2", "asyncpg",
)


class NoLiveApplicationServices(importlib.abc.MetaPathFinder):
    forbidden_imports = FORBIDDEN_IMPORTS

    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == name or fullname.startswith(name + ".")
            for name in self.forbidden_imports
        ):
            guard.deny("live_application_or_database_import")
        return None


def application_audit(event, args):
    if event.startswith("sqlite3.connect"):
        guard.deny("database_connect")
    guard.audit(event, args)


def self_test(backend, forbidden_import="botelier.voice.call_handler"):
    import socket

    # Keep the pure-stdlib guard test from running the eager voice initializer.
    voice = types.ModuleType("botelier.voice")
    voice.__path__ = [str(backend / "botelier/voice")]
    sys.modules["botelier.voice"] = voice
    checks = (
        lambda: socket.getaddrinfo("offline-compatibility.invalid", 443),
        lambda: open(Path("/tmp") / ".env", "r"),
        lambda: open(backend / "unsafe-compatibility-output", "w"),
        lambda: subprocess.Popen([sys.executable, "-c", "raise SystemExit(99)"]),
        lambda: __import__("botelier.database"),
        lambda: __import__(forbidden_import),
    )
    for operation in checks:
        try:
            operation()
        except guard.TrialSafetyError:
            continue
        raise AssertionError("A forbidden compatibility operation was allowed")
    assert len(guard.BLOCKED) == 6
    print(json.dumps({"guard_self_test": "passed", "expected_denials": 6}))


def main(
    *,
    import_policy=NoLiveApplicationServices,
    scope="actual_components_not_server_or_live_provider_startup",
    self_test_import="botelier.voice.call_handler",
    prepare_tests=None,
):
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--diagnose", action="store_true")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args()

    guard.validate_environment_keys(os.environ.keys())
    backend = args.backend_root.resolve()
    package = args.package_root.resolve()
    if not (backend / "botelier/voice/engine.py").is_file():
        parser.error("--backend-root must contain the actual voice engine")
    if package.name != "pipecat" or not args.package_root.is_absolute():
        parser.error("--package-root must be an absolute pipecat directory")

    sys.dont_write_bytecode = True
    guard.DIAGNOSTICS = args.diagnose
    sys.addaudithook(application_audit)
    sys.meta_path.insert(0, import_policy())
    sys.path[:0] = [str(package.parent), str(backend)]

    if args.self_test:
        self_test(backend, self_test_import)
        return 0

    import pipecat
    if Path(pipecat.__file__).resolve().parent != package:
        raise RuntimeError("The voice tests loaded a different Pipecat source")
    # Trusted fixture setup runs under the already-installed I/O/import guards,
    # after environment/source validation and before pytest can import tests.
    if prepare_tests is not None:
        prepare_tests()
    import pytest

    print(json.dumps({
        "application_backend": str(backend),
        "pipecat_package": str(package),
        "scope": scope,
    }, sort_keys=True))
    result = pytest.main([
        "-q", "--tb=short", "--noconftest", "-p", "no:cacheprovider",
        *(["-s"] if args.diagnose else []),
        "-c", str(Path(__file__).with_name("pytest.ini")),
        "--basetemp=/tmp/botelier-voice-compatibility/pytest-temp",
        "-o", "log_file=/tmp/botelier-voice-compatibility/pytest.log",
        *[str(path) for path in args.tests],
    ])
    print("APPLICATION_GUARD_BLOCKED_ATTEMPTS=" + str(len(guard.BLOCKED)))
    return 3 if guard.BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline trial launcher with Python-level safety checks, not an OS sandbox."""

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[3]
OUT = Path("/tmp/botelier-native-flow-trial")
ALLOWED_ENV = {
    "PATH", "HOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
    "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK", "LOGURU_LEVEL", "LC_CTYPE",
    "LD_LIBRARY_PATH",  # Injected by the Nix interpreter even under env -i.
    "NLTK_DATA",  # Explicit existing public tokenizer cache; never downloaded.
}
BLOCKED = []
DIAGNOSTICS = False


class TrialSafetyError(RuntimeError):
    """An operation is outside the approved offline trial."""


def deny(category):
    BLOCKED.append(category)
    if DIAGNOSTICS:
        print("TRIAL_GUARD_CATEGORY=" + category, file=sys.stderr)
        traceback.print_stack(limit=10, file=sys.stderr)
    raise TrialSafetyError("OFFLINE TRIAL GUARD: " + category)


def check_path(raw, *, writing=False):
    if not isinstance(raw, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(raw)).resolve()
    if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".key", ".pem"}:
        deny("secret_file")
    if writing and not path.is_relative_to(Path("/tmp")):
        deny("write_outside_tmp")


def audit(event, args):
    if event in {
        "socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo",
        "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
        "subprocess.Popen", "os.system", "os.posix_spawn",
    }:
        deny("network_or_subprocess")
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (
            isinstance(mode, str) and any(char in mode for char in "wax+")
        ) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        check_path(args[0], writing=writing)
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
        check_path(args[0], writing=True)
    if event in {"os.rename", "os.link", "os.symlink"}:
        check_path(args[0], writing=True)
        check_path(args[1], writing=True)


class NoApplicationServices(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"botelier", "psycopg", "psycopg2", "asyncpg", "sqlalchemy"}:
            deny("application_or_database_import")
        return None


def validate_environment_keys(keys):
    if set(keys) - ALLOWED_ENV:
        raise TrialSafetyError("Run with the documented env -i command before importing packages")


def install_guard():
    validate_environment_keys(os.environ.keys())
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoApplicationServices())


def self_test():
    """Deliberately exercise four denied boundaries without completing them."""
    import socket

    checks = (
        lambda: socket.getaddrinfo("offline-trial.invalid", 443),
        lambda: open(OUT / ".env", "r"),
        lambda: open(ROOT / ".local" / "unsafe-trial-output", "w"),
        lambda: __import__("botelier"),
    )
    for operation in checks:
        try:
            operation()
        except TrialSafetyError:
            continue
        raise AssertionError("A forbidden trial operation was allowed")
    assert len(BLOCKED) == 4
    print(json.dumps({"guard_self_test": "passed", "expected_denials": len(BLOCKED)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("wheel", "vendored"), required=True)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--profile", choices=("native", "legacy"), default="native")
    parser.add_argument("--diagnose", action="store_true")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args()
    global DIAGNOSTICS
    DIAGNOSTICS = args.diagnose
    wheel = ROOT / ".pythonlibs/lib/python3.11/site-packages"
    selected = wheel if args.target == "wheel" else ROOT / "src"
    expected_root = selected / "pipecat"
    if args.package_root is not None:
        if not args.package_root.is_absolute() or args.package_root.name != "pipecat":
            parser.error("--package-root must be an absolute pipecat package directory")
        expected_root = args.package_root
        selected = expected_root.parent
    sys.path.insert(0, str(selected))
    install_guard()

    if args.self_test:
        self_test()
        return 0

    if args.probe:
        from runtime_probe import observe

        observation = observe(expected_root, require_flows=args.profile == "native")
        print(json.dumps(observation, sort_keys=True))
        result = observation["exit_code"]
    else:
        import pytest

        result = pytest.main([
            "-q", "--tb=short", "--noconftest", "-p", "no:cacheprovider",
            "-c", str(Path(__file__).with_name("pytest.ini")),
            "--basetemp=" + str(OUT / "pytest-temp"),
            "-o", "log_file=" + str(OUT / "pytest.log"),
            *[str(path) for path in args.tests],
        ])
    print("TRIAL_GUARD_BLOCKED_ATTEMPTS=" + str(len(BLOCKED)))
    return 3 if BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

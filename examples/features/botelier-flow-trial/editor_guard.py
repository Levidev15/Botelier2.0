"""Separate audited launcher for the bounded native editor ASGI fixture.

The guard is Python-level defense in depth, not an OS sandbox. It deliberately
admits only four real API leaf routers and a single in-memory SQLite database.
"""

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import types

TRIAL = Path(__file__).resolve().parent
TEST_SECRET = "botelier-editor-trial-only-synthetic-nextauth-secret-v1"
TEST_FERNET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
TOTP_SECRET = "JBSWY3DPEHPK3PXP"
ALLOWED_ENV = {
    "PATH", "HOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "NEXTAUTH_SECRET",
    "INTEGRATION_ENCRYPTION_KEY", "BOTELIER_ENV",
    "BOTELIER_NATIVE_FLOWS_DEV", "NEXTAUTH_URL", "LOGURU_LEVEL", "LC_CTYPE",
    "LD_LIBRARY_PATH", "NLTK_DATA",
}
APPROVED_ROUTES = {
    "botelier.api.auth", "botelier.api.mfa",
    "botelier.api.flow_versions", "botelier.api.simulation",
}
BLOCKED = []
BACKEND_ROOT = None
PACKAGE_ROOT = None


class EditorSafetyError(RuntimeError):
    """The editor trial exceeded its independently reviewed boundary."""


def deny(category):
    BLOCKED.append(category)
    raise EditorSafetyError("EDITOR TRIAL GUARD: " + category)


def validate_environment():
    unexpected = set(os.environ) - ALLOWED_ENV
    if unexpected:
        raise EditorSafetyError("Use the documented env -i launcher environment")
    if os.environ.get("NEXTAUTH_SECRET") != TEST_SECRET:
        raise EditorSafetyError("NEXTAUTH_SECRET must be the fixed synthetic value")
    if os.environ.get("INTEGRATION_ENCRYPTION_KEY") != TEST_FERNET_KEY:
        raise EditorSafetyError("INTEGRATION_ENCRYPTION_KEY must be the fixed synthetic value")
    if (
        os.environ.get("BOTELIER_ENV") != "development"
        or os.environ.get("BOTELIER_NATIVE_FLOWS_DEV") != "1"
    ):
        raise EditorSafetyError("Explicit synthetic native-development opt-ins are required")
    if os.environ.get("NEXTAUTH_URL") != "http://127.0.0.1:5011":
        raise EditorSafetyError("NEXTAUTH_URL must be the fixed synthetic browser origin")
    if os.environ.get("NLTK_DATA") not in (
        None, "/home/runner/nltk_data", "/opt/nltk_data",
    ):
        raise EditorSafetyError("NLTK_DATA must name an explicitly approved read-only cache")


def _check_path(raw, *, writing=False):
    if not isinstance(raw, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(raw)).resolve()
    if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".key", ".pem"}:
        deny("secret_file_access")
    if writing and not path.is_relative_to(Path("/tmp")):
        deny("write_outside_tmp")


def _audit(event, args):
    if event in {
        "socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo",
        "socket.getnameinfo", "socket.gethostbyname", "socket.gethostbyaddr",
        "socket.sendto", "socket.listen", "socket.accept",
        "socket.send", "socket.sendall", "socket.recv", "socket.recvfrom",
        "socket.shutdown", "subprocess.Popen", "os.system", "os.posix_spawn",
        "os.posix_spawnp", "os.fork", "os.forkpty", "os.exec", "os.spawn",
    }:
        deny("network_or_subprocess")
    if event == "socket.__new__":
        family = args[1] if len(args) > 1 else None
        if family != socket.AF_UNIX:
            deny("network_or_subprocess")
    if event == "sqlite3.connect":
        database = args[0] if args else None
        if database not in (":memory:", "sqlite://", "file::memory:?cache=shared"):
            deny("non_fixture_database_connection")
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (
            isinstance(mode, str) and any(char in mode for char in "wax+")
        ) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        _check_path(args[0], writing=writing)
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
        _check_path(args[0], writing=True)
    if event in {"os.rename", "os.link", "os.symlink"}:
        _check_path(args[0], writing=True)
        if len(args) > 1:
            _check_path(args[1], writing=True)


class _EditorImportsOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"botelier.api", "botelier.models", "botelier.auth",
                        "botelier.services", "botelier.voice"}:
            return None
        if fullname in {
            "main", "botelier.main", "botelier.app", "botelier.server",
            "botelier.startup", "botelier.bootstrap",
        }:
            deny("application_bootstrap_import")
        if fullname.startswith("botelier.api."):
            if fullname not in APPROVED_ROUTES:
                deny("unapproved_application_route_import")
        if fullname in {"botelier.database", "psycopg", "psycopg2", "asyncpg"}:
            deny("live_database_or_driver_import")
        if fullname.split(".", 1)[0] in {"psycopg", "psycopg2", "asyncpg"}:
            deny("live_database_or_driver_import")
        return None


def install(backend_root, package_root):
    global BACKEND_ROOT, PACKAGE_ROOT
    validate_environment()
    backend = Path(backend_root).resolve()
    package = Path(package_root)
    if not package.is_absolute() or package.name != "pipecat" or not (
        package / "__init__.py"
    ).is_file():
        raise EditorSafetyError("package-root must name the approved Pipecat source package")
    package = package.resolve()
    if not (backend / "botelier" / "api" / "auth.py").is_file():
        raise EditorSafetyError("Backend root does not contain actual Botelier auth route")
    if not (backend / "botelier" / "api" / "flow_versions.py").is_file():
        raise EditorSafetyError("Backend root does not contain actual flow-version route")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(package.parent), str(TRIAL), str(backend)]
    BACKEND_ROOT = backend
    PACKAGE_ROOT = package
    sys.addaudithook(_audit)
    sys.meta_path.insert(0, _EditorImportsOnly())


def verify_sdk_source():
    import pipecat

    if Path(pipecat.__file__).resolve().parent != PACKAGE_ROOT:
        raise EditorSafetyError("Loaded Pipecat source differs from --package-root")


def self_test():
    import socket
    import subprocess

    def construct_socket():
        sock = socket.socket()
        sock.close()

    checks = (
        ("network_or_subprocess", lambda: socket.getaddrinfo("editor-fixture.invalid", 443)),
        ("network_or_subprocess", construct_socket),
        ("network_or_subprocess", lambda: subprocess.Popen([sys.executable, "-c", "pass"])),
        ("secret_file_access", lambda: open(Path("/tmp") / ".env", "r")),
        ("secret_file_access", lambda: open(Path("/tmp") / "editor-fixture.key", "r")),
        ("non_fixture_database_connection", lambda: sqlite3.connect(
            "/tmp/editor-fixture-forbidden.sqlite",
        )),
        ("live_database_or_driver_import", lambda: __import__("botelier.database")),
        ("live_database_or_driver_import", lambda: __import__("psycopg")),
        ("unapproved_application_route_import", lambda: __import__("botelier.api.websockets")),
        ("application_bootstrap_import", lambda: __import__("botelier.main")),
        ("application_bootstrap_import", lambda: __import__("main")),
        ("write_outside_tmp", lambda: open(TRIAL / "editor-guard-forbidden-output", "w")),
        ("write_outside_tmp", lambda: _audit(
            "os.rename", ("/tmp/editor-guard-source", str(TRIAL / "editor-guard-destination")),
        )),
        ("write_outside_tmp", lambda: _audit(
            "os.symlink", ("/tmp/editor-guard-source", str(TRIAL / "editor-guard-destination")),
        )),
    )
    for category, operation in checks:
        before = len(BLOCKED)
        try:
            operation()
        except EditorSafetyError:
            if len(BLOCKED) != before + 1 or BLOCKED[-1] != category:
                raise AssertionError("An editor guard self-test hit the wrong denial")
        else:
            raise AssertionError("A forbidden editor-fixture operation was allowed")
    expected = {
        "network_or_subprocess", "secret_file_access",
        "non_fixture_database_connection", "live_database_or_driver_import",
        "unapproved_application_route_import", "application_bootstrap_import",
        "write_outside_tmp",
    }
    if not expected.issubset(BLOCKED):
        raise AssertionError("Editor guard self-refusal coverage was incomplete")
    print(json.dumps({
        "type": "guard_self_test",
        "result": "passed",
        "denial_attempts": len(BLOCKED),
        "denial_categories": sorted(set(BLOCKED)),
    }, separators=(",", ":")))


async def _jsonl_lines():
    import asyncio
    import os

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    buffer = bytearray()
    discarding = False
    fd = sys.stdin.fileno()

    def readable():
        nonlocal discarding
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            queue.put_nowait(None)
            return
        if not chunk:
            queue.put_nowait(None)
            return
        buffer.extend(chunk)
        while b"\n" in buffer:
            line, _, remainder = buffer.partition(b"\n")
            buffer[:] = remainder
            if discarding or len(line) > 64 * 1024:
                queue.put_nowait(b"\x00EDITOR_LINE_TOO_LARGE")
            else:
                queue.put_nowait(line)
            discarding = False
        if len(buffer) > 64 * 1024:
            buffer.clear()
            discarding = True

    loop.add_reader(fd, readable)
    try:
        while True:
            line = await queue.get()
            if line is None:
                if discarding:
                    yield b"\x00EDITOR_LINE_TOO_LARGE"
                elif buffer:
                    yield bytes(buffer)
                return
            yield line
    finally:
        loop.remove_reader(fd)


async def _serve_jsonl():
    from editor_fixture import EditorASGIFixture, EditorFixtureError

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON field")
            value[key] = item
        return value

    fixture = EditorASGIFixture()
    async with fixture:
        print(json.dumps(fixture.ready_record(), separators=(",", ":")), flush=True)
        async for line in _jsonl_lines():
            request_id = None
            if line == b"\x00EDITOR_LINE_TOO_LARGE" or len(line) > 64 * 1024:
                output = {"type": "error", "status": 413, "body": {"detail": "IPC line too large"}}
            else:
                try:
                    request = json.loads(line, object_pairs_hook=unique_object)
                    if isinstance(request, dict):
                        request_id = request.get("id")
                    if not isinstance(request, dict):
                        raise EditorFixtureError("Unsupported IPC action")
                    action = request.get("action")
                    if action == "request":
                        output = await fixture.forward(request)
                    elif (
                        action == "totp" and set(request) == {"action", "id"}
                        and isinstance(request.get("id"), (str, int))
                        and not isinstance(request.get("id"), bool)
                        and len(str(request["id"])) <= 128
                    ):
                        code = fixture.ready_record()["totp"]
                        output = {"type": "totp", "id": request["id"], "code": code}
                    elif (
                        action == "shutdown" and set(request) == {"action", "id"}
                        and isinstance(request.get("id"), (str, int))
                        and not isinstance(request.get("id"), bool)
                        and len(str(request["id"])) <= 128
                    ):
                        output = {
                            "type": "shutdown", "id": request["id"],
                            "blocked_attempts": len(BLOCKED),
                        }
                        print(json.dumps(output, separators=(",", ":")), flush=True)
                        break
                    else:
                        raise EditorFixtureError("Unsupported IPC action")
                except EditorFixtureError:
                    output = {"type": "response", "id": request_id, "status": 404,
                              "body": {"detail": "Not found"}, "headers": []}
                except (json.JSONDecodeError, UnicodeError):
                    output = {"type": "error", "id": request_id, "status": 400,
                              "body": {"detail": "Invalid JSON-lines request"}}
                except Exception:
                    # No exception text, body, token, or credentials are written.
                    output = {"type": "error", "id": request_id, "status": 500,
                              "body": {"detail": "Editor fixture request failed"}}
            print(json.dumps(output, separators=(",", ":")), flush=True)
        print(json.dumps({
            "type": "guard_counters",
            "blocked_attempts": len(BLOCKED),
        }, separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--stdio", action="store_true")
    group.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args()
    sys.modules["editor_guard"] = sys.modules[__name__]
    install(args.backend_root, args.package_root)
    verify_sdk_source()
    if args.self_test:
        self_test()
        return 0
    if args.stdio:
        import asyncio

        asyncio.run(_serve_jsonl())
        if BLOCKED:
            return 3
        return 0
    import pytest

    result = pytest.main([
        "-q", "--tb=short", "--noconftest", "-p", "no:cacheprovider",
        "-p", "pytest_asyncio.plugin", "-c", str(TRIAL / "pytest.ini"),
        "--basetemp=/tmp/botelier-editor-fixture/pytest-temp",
        "-o", "log_file=/tmp/botelier-editor-fixture/pytest.log",
        *(str(path) for path in args.tests),
    ])
    print(json.dumps({
        "type": "guard_counters", "blocked_attempts": len(BLOCKED),
    }, separators=(",", ":")))
    return 3 if BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

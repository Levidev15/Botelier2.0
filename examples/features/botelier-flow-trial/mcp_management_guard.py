"""Narrow offline boundary for the real MCP management API leaf.

This guard admits the MCP connection management route and its real SQLAlchemy
model/auth mappings, but supplies an inert database namespace and rejects every
database connection. It is a Python-level guard, not an OS sandbox.
"""

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import types

import editor_guard


TRIAL = Path(__file__).resolve().parent
APPROVED_ROUTE = "botelier.api.mcp_connections"
BLOCKED = []
BACKEND_ROOT = None
PACKAGE_ROOT = None


class GuardError(RuntimeError):
    """The MCP management trial exceeded its bounded offline scope."""


def deny(category):
    BLOCKED.append(category)
    raise GuardError("MCP MANAGEMENT GUARD: " + category)


def validate_environment():
    """Reuse the editor profile's exact synthetic-only environment contract."""
    try:
        editor_guard.validate_environment()
    except editor_guard.EditorSafetyError as error:
        raise GuardError(str(error)) from None


def validate_roots(backend_root, package_root):
    backend = Path(backend_root).resolve()
    package_arg = Path(package_root)
    if not package_arg.is_absolute() or package_arg.name != "pipecat":
        raise GuardError("package-root must be an absolute Pipecat package path")
    package = package_arg.resolve()
    if not (package / "__init__.py").is_file():
        raise GuardError("package-root must contain the pinned Pipecat package")
    if not (backend / "botelier" / "api" / "mcp_connections.py").is_file():
        raise GuardError("backend-root must contain the actual MCP management route")
    if not (backend / "botelier" / "auth" / "middleware.py").is_file():
        raise GuardError("backend-root must contain the actual auth middleware")
    return backend, package


def validate_targets(targets):
    expected = (TRIAL / "test_mcp_native_policy.py").resolve()
    resolved = tuple(Path(target).resolve() for target in targets)
    if resolved != (expected,):
        raise ValueError("Only the exact test_mcp_native_policy.py suite is admitted")
    return resolved


class MCPManagementImportsOnly(importlib.abc.MetaPathFinder):
    """Admit precisely one route leaf, not the eager API package initializer."""

    _BOOTSTRAP = frozenset({
        "main", "botelier.main", "botelier.app", "botelier.server",
        "botelier.startup", "botelier.bootstrap", "botelier.asgi",
        "botelier.application", "botelier.factory", "botelier.worker",
    })
    _DRIVERS = frozenset({
        "psycopg", "psycopg2", "asyncpg", "aiosqlite", "pg8000",
        "pymysql", "MySQLdb", "cx_Oracle", "oracledb", "pyodbc",
    })

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self._BOOTSTRAP:
            deny("application_bootstrap_import")
        if fullname == "database" or fullname.startswith("database."):
            deny("live_database_or_driver_import")
        if fullname == "botelier.database" or fullname.startswith("botelier.database."):
            deny("live_database_or_driver_import")
        root = fullname.split(".", 1)[0]
        if root in self._DRIVERS:
            deny("live_database_or_driver_import")
        if fullname == "botelier.api":
            # A synthetic namespace package is seeded before test imports; never
            # execute botelier/api/__init__.py (which imports unrelated routes).
            return None
        if fullname.startswith("botelier.api."):
            if fullname != APPROVED_ROUTE:
                deny("unapproved_application_route_import")
        return None


def management_audit(event, args):
    """Reuse strict editor I/O boundaries and prohibit every DB connection."""
    if event in {
        "socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo",
        "socket.getnameinfo", "socket.gethostbyname", "socket.gethostbyaddr",
        "socket.sendto", "socket.listen", "socket.accept", "socket.send",
        "socket.sendall", "socket.recv", "socket.recvfrom", "socket.shutdown",
        "subprocess.Popen", "os.system", "os.posix_spawn", "os.posix_spawnp",
        "os.fork", "os.forkpty", "os.exec", "os.spawn",
    }:
        deny("network_or_subprocess")
    if event == "socket.__new__":
        family = args[1] if len(args) > 1 else None
        if family != socket.AF_UNIX:
            deny("network_or_subprocess")
    if event.startswith("sqlite3.connect"):
        # Unlike the editor guard, this profile permits no SQLite connection,
        # including :memory: and shared-cache in-memory databases.
        deny("database_connection")
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (
            isinstance(mode, str) and any(char in mode for char in "wax+")
        ) or bool(flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ))
        _check_path(args[0], writing=writing)
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
        _check_path(args[0], writing=True)
    if event in {"os.rename", "os.link", "os.symlink"}:
        _check_path(args[0], writing=True)
        if len(args) > 1:
            _check_path(args[1], writing=True)


def _check_path(raw, *, writing=False):
    if not isinstance(raw, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(raw)).resolve()
    if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {
        ".key", ".pem",
    }:
        deny("secret_file_access")
    if writing and not path.is_relative_to(Path("/tmp")):
        deny("write_outside_tmp")


def reject_database():
    """Fail closed when a dependency override is missing; never make a session."""
    raise GuardError("A synthetic get_db dependency override is required")


def seed_inert_namespaces(backend_root):
    """Install only the dependency surface needed by the actual leaf route."""
    if "botelier.api" in sys.modules or "botelier.database" in sys.modules:
        raise GuardError("Application API/database modules loaded before MCP guard")

    from sqlalchemy.orm import declarative_base

    database = types.ModuleType("botelier.database")
    database.__package__ = "botelier"
    database.Base = declarative_base()
    database.get_db = reject_database
    sys.modules["botelier.database"] = database

    api = types.ModuleType("botelier.api")
    api.__package__ = "botelier.api"
    api.__path__ = [str(Path(backend_root).resolve() / "botelier" / "api")]
    sys.modules["botelier.api"] = api


def install(backend_root, package_root):
    global BACKEND_ROOT, PACKAGE_ROOT

    validate_environment()
    backend, package = validate_roots(backend_root, package_root)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(package.parent), str(TRIAL), str(backend)]
    BACKEND_ROOT, PACKAGE_ROOT = backend, package
    sys.addaudithook(management_audit)
    sys.meta_path.insert(0, MCPManagementImportsOnly())
    seed_inert_namespaces(backend)


def verify_package_source():
    import pipecat

    if Path(pipecat.__file__).resolve().parent != PACKAGE_ROOT:
        raise GuardError("Loaded Pipecat source differs from --package-root")


def verify_route_source():
    module = sys.modules.get(APPROVED_ROUTE)
    expected = (BACKEND_ROOT / "botelier" / "api" / "mcp_connections.py").resolve()
    if module is None or Path(module.__file__).resolve() != expected:
        raise GuardError("MCP tests did not load the pinned management route")


def self_test():
    expected = (
        ("network_or_subprocess", lambda: socket.getaddrinfo(
            "mcp-management-fixture.invalid", 443,
        )),
        ("network_or_subprocess", socket.socket),
        ("network_or_subprocess", lambda: subprocess.Popen(
            [sys.executable, "-c", "pass"],
        )),
        ("secret_file_access", lambda: open(Path("/tmp") / ".env", "r")),
        ("secret_file_access", lambda: open(Path("/tmp") / "mcp-management.pem", "r")),
        ("database_connection", lambda: sqlite3.connect(":memory:")),
        ("write_outside_tmp", lambda: open(TRIAL / "mcp-management-forbidden", "w")),
        ("application_bootstrap_import", lambda: __import__("main")),
        ("unapproved_application_route_import", lambda: __import__(
            "botelier.api.simulation",
        )),
        ("unapproved_application_route_import", lambda: MCPManagementImportsOnly().find_spec(
            "botelier.api.mcp_connections.extra",
        )),
        ("live_database_or_driver_import", lambda: MCPManagementImportsOnly().find_spec(
            "botelier.database",
        )),
        ("live_database_or_driver_import", lambda: __import__("psycopg")),
    )
    start = len(BLOCKED)
    for category, operation in expected:
        before = len(BLOCKED)
        try:
            operation()
        except GuardError:
            if len(BLOCKED) != before + 1 or BLOCKED[-1] != category:
                raise AssertionError("MCP guard self-test hit the wrong denial")
        else:
            raise AssertionError("A forbidden MCP-management operation was allowed")
    # A missing dependency override is a normal fail-closed error, not an audit
    # boundary bypass and not a reason to connect to a real database.
    try:
        reject_database()
    except GuardError:
        pass
    else:
        raise AssertionError("The synthetic get_db namespace must reject access")
    observed = BLOCKED[start:]
    if len(observed) != len(expected):
        raise AssertionError("MCP guard self-test denial accounting was incomplete")
    print(json.dumps({
        "guard_self_test": "passed",
        "expected_denials": len(expected),
        "denial_categories": sorted(set(observed)),
        "database_override": "required-and-inert",
    }, separators=(",", ":")))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args(argv)

    # Validate target shape before installing imports or loading application code.
    targets = None if args.self_test else validate_targets(args.tests)
    install(args.backend_root, args.package_root)
    verify_package_source()
    if args.self_test:
        self_test()
        return 0

    import pytest

    result = 1
    try:
        result = pytest.main([
            "-q", "--tb=short", "--noconftest", "-p", "no:cacheprovider",
            "-c", str(TRIAL / "pytest.ini"),
            "--basetemp=/tmp/botelier-mcp-management/pytest-temp",
            "-o", "log_file=/tmp/botelier-mcp-management/pytest.log",
            *(str(target) for target in targets),
        ])
        verify_route_source()
    finally:
        print("MCP_MANAGEMENT_GUARD_BLOCKED_ATTEMPTS=" + str(len(BLOCKED)))
    return 3 if BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

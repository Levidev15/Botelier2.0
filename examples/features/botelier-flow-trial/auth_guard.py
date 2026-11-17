"""Isolated auth/MFA test launcher: real auth modules, disposable SQLite only."""
import argparse
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import types


TRIAL = Path(__file__).resolve().parent
TEST_SECRET = "botelier-auth-trial-only-synthetic-nextauth-secret-v1"
TEST_FERNET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
ALLOWED_ENV = {
    "PATH", "HOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "NEXTAUTH_SECRET",
    "INTEGRATION_ENCRYPTION_KEY", "LOGURU_LEVEL",
    "LC_CTYPE", "LD_LIBRARY_PATH",
}
BLOCKED = []
DIAGNOSTICS = False
ALLOWED_BOTELIER_MODULES = {
    "botelier.database",
    "botelier.api.auth",
    "botelier.api.mfa",
    "botelier.api.sms_pkg._auth",
    "botelier.api.sms_pkg.webhook",
    "botelier.auth.middleware",
    "botelier.auth.permissions",
    "botelier.auth.features",
    "botelier.crypto",
    "botelier.models.account",
    "botelier.models.assistant",
    "botelier.models.disposition",
    "botelier.models.integration",
    "botelier.models.invitation",
    "botelier.models.knowledge_base",
    "botelier.models.knowledge_entry",
    "botelier.models.mfa",
    "botelier.models.phone_number",
    "botelier.models.property",
    "botelier.models.mcp_connection",
    "botelier.models.role",
    "botelier.models.sms_conversation",
    "botelier.models.tool",
    "botelier.models.tool_set",
    "botelier.models.user",
    "botelier.mfa_schema",
    "botelier.services.notification_broadcaster",
    "botelier.services.mfa_service",
    "botelier.services.property_scope",
    "botelier.services.sms_service",
    "botelier.voice.knowledge_handler",
}
FIXTURE_CONNECTION = {
    "host": "/tmp/botelier-auth-fixture",
    "dbname": "voice_auth_fixture",
    "user": "postgres",
    "connect_timeout": 3,
    "options": "-c statement_timeout=5000 -c lock_timeout=3000",
}


class AuthGuardError(RuntimeError):
    """An operation outside this isolated auth/MFA test scope."""


def deny(category):
    BLOCKED.append(category)
    if DIAGNOSTICS:
        print("AUTH_GUARD_CATEGORY=" + category, file=sys.stderr)
        traceback.print_stack(limit=10, file=sys.stderr)
    raise AuthGuardError("AUTH TRIAL GUARD: " + category)


def _check_path(raw, *, writing=False):
    if not isinstance(raw, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(raw)).resolve()
    if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".key", ".pem"}:
        deny("credential_file_access")
    if writing and not path.is_relative_to(Path("/tmp")):
        deny("write_outside_tmp")


def _audit(event, args):
    if event == "subprocess.Popen":
        _validate_nextauth_encoder(args)
        return
    if event in {
        "socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo",
        "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
        "os.system", "os.posix_spawn",
    }:
        deny("network_or_subprocess")
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
        _check_path(args[1], writing=True)


def _validate_nextauth_encoder(args):
    """Permit only the root tests' exact synthetic NextAuth JWE encoder."""
    if len(args) != 4:
        deny("unapproved_subprocess")
    executable, argv, cwd, _env = args
    frontend = _FRONTEND_ROOT
    resolved_node = Path(shutil.which("node") or "/nonexistent").resolve()
    executable_path = Path(os.fsdecode(executable)) if executable is not None else None
    resolved_executable = (
        executable_path.resolve() if executable_path and executable_path.is_absolute()
        else Path(shutil.which(str(executable_path)) or "/nonexistent").resolve()
        if executable_path else resolved_node
    )
    if (
        _NODE_BINARY is None or resolved_node != _NODE_BINARY
        or resolved_executable != _NODE_BINARY
        or Path(os.fsdecode(cwd)).resolve() != frontend
    ):
        deny("unapproved_subprocess")
    if (
        not isinstance(argv, (list, tuple))
        or len(argv) != 3 or argv[0] != "node" or argv[1] != "-e"
    ):
        deny("unapproved_subprocess")
    script = argv[2]
    expired = (
        "require('next-auth/jwt').encode({token:{sub:'real-nextauth-subject',auth_time:123},"
        "secret:process.env.NEXTAUTH_SECRET,maxAge:-60"
        "}).then(t=>process.stdout.write(t));"
    )
    valid = (
        "require('next-auth/jwt').encode({token:{sub:'real-nextauth-subject',auth_time:123},"
        "secret:process.env.NEXTAUTH_SECRET,maxAge:3600"
        "}).then(t=>process.stdout.write(t));"
    )
    if script in {expired, valid}:
        return
    if not isinstance(script, str):
        deny("unapproved_subprocess")
    prefix = "require('next-auth/jwt').encode({token:"
    suffix = ",secret:process.env.NEXTAUTH_SECRET,maxAge:3600}).then(t=>process.stdout.write(t));"
    if not script.startswith(prefix) or not script.endswith(suffix):
        deny("unapproved_subprocess")
    import json

    encoded = script[len(prefix):-len(suffix)]
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError):
        deny("unapproved_subprocess")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"sub", "auth_time"}
        or not isinstance(payload["sub"], str)
        or not isinstance(payload["auth_time"], (int, float))
        or not 0 <= payload["auth_time"] < 10_000_000_000
    ):
        deny("unapproved_subprocess")
    import uuid

    try:
        if uuid.UUID(payload["sub"]).version != 4:
            deny("unapproved_subprocess")
    except (AttributeError, ValueError):
        deny("unapproved_subprocess")
def _namespace(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    sys.modules[name] = module


class _AuthModulesOnly(importlib.abc.MetaPathFinder):
    _NAMESPACE_PARENTS = {
        "botelier", "botelier.api", "botelier.api.sms_pkg", "botelier.auth",
        "botelier.models", "botelier.services", "botelier.voice",
    }

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("botelier.") and (
            fullname not in ALLOWED_BOTELIER_MODULES
            and fullname not in self._NAMESPACE_PARENTS
        ):
            deny("unapproved_application_import")
        driver = fullname.split(".")[0]
        if driver == "psycopg" or (driver == "psycopg2" and not _POSTGRES):
            deny("non_sqlite_database_driver")
        return None


def _install_database(postgres):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    from sqlalchemy.pool import StaticPool

    module = types.ModuleType("botelier.database")
    module.Base = declarative_base()
    if postgres:
        if not Path("/tmp/botelier-auth-fixture/.s.PGSQL.5432").exists():
            raise AuthGuardError("Disposable PostgreSQL fixture socket is unavailable")
        import psycopg2

        original_connect = psycopg2.connect

        def fixture_connect(*args, **kwargs):
            if args or kwargs != FIXTURE_CONNECTION:
                deny("non_fixture_database_connection")
            return original_connect(**FIXTURE_CONNECTION)

        psycopg2.connect = fixture_connect
        module.engine = create_engine(
            "postgresql+psycopg2://",
            creator=lambda: psycopg2.connect(**FIXTURE_CONNECTION),
            pool_pre_ping=False,
        )
    else:
        module.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    module.SessionLocal = sessionmaker(bind=module.engine, expire_on_commit=False)

    def get_db():
        db = module.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    module.get_db = get_db
    module.init_db = lambda: deny("application_database_initialization")
    module.run_stuck_call_sweeper = lambda: deny("application_database_initialization")
    sys.modules["botelier.database"] = module
    try:
        import asyncpg
    except ImportError:
        return

    asyncpg.connect = lambda *args, **kwargs: deny("non_fixture_database_connection")
    if hasattr(asyncpg, "create_pool"):
        asyncpg.create_pool = lambda *args, **kwargs: deny("non_fixture_database_connection")


_BACKEND_ROOT = None
_FRONTEND_ROOT = None
_NODE_BINARY = None


def _install(backend_root, *, postgres=False, frontend_root=None, node_binary=None):
    global _BACKEND_ROOT, _FRONTEND_ROOT, _NODE_BINARY
    unknown = set(os.environ) - ALLOWED_ENV
    if unknown:
        raise AuthGuardError("Run with the documented env -i command")
    if os.environ.get("NEXTAUTH_SECRET") != TEST_SECRET:
        raise AuthGuardError("Use only the fixed synthetic test signing key")
    if os.environ.get("INTEGRATION_ENCRYPTION_KEY") != TEST_FERNET_KEY:
        raise AuthGuardError("Use only the fixed synthetic test encryption key")
    # Imported only because the actual SMS SSE module shares its file with
    # SMSService; no model/provider invocation is allowed by this harness.
    os.environ["OPENAI_API_KEY"] = "offline-auth-guard-not-a-credential"
    backend_root = backend_root.resolve()
    if not (backend_root / "botelier" / "api" / "auth.py").is_file():
        raise AuthGuardError("Backend root does not contain botelier/api/auth.py")
    sys.path.insert(0, str(backend_root))
    sys.path.insert(0, str(TRIAL))
    _BACKEND_ROOT = backend_root
    _FRONTEND_ROOT = (
        frontend_root.resolve() if frontend_root else (backend_root.parent / "frontend").resolve()
    )
    candidate_node = node_binary or (Path(shutil.which("node")) if shutil.which("node") else None)
    _NODE_BINARY = candidate_node.resolve() if candidate_node else None
    if _NODE_BINARY and not _NODE_BINARY.is_file():
        raise AuthGuardError("The configured Node executable is unavailable")
    os.environ["AUTH_TEST_FRONTEND"] = str(_FRONTEND_ROOT)
    _namespace("botelier", backend_root / "botelier")
    for name, suffix in (
        ("botelier.api", "api"),
        ("botelier.api.sms_pkg", "api/sms_pkg"),
        ("botelier.auth", "auth"),
        ("botelier.models", "models"),
        ("botelier.services", "services"),
        ("botelier.voice", "voice"),
    ):
        _namespace(name, backend_root / "botelier" / suffix)
    sys.dont_write_bytecode = True
    sys.addaudithook(_audit)
    sys.meta_path.insert(0, _AuthModulesOnly())
    _install_database(postgres)


def _self_test():
    try:
        __import__("botelier.api.websockets")
    except AuthGuardError:
        if BLOCKED != ["unapproved_application_import"]:
            raise AssertionError("Unexpected auth guard self-test result")
    else:
        raise AssertionError("Non-auth API route import was allowed")
    print(json.dumps({
        "auth_guard": "passed",
        "blocked_non_auth_route_imports": len(BLOCKED),
        "database": "disposable_postgres" if _POSTGRES else "sqlite",
    }))


_POSTGRES = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path)
    parser.add_argument("--node-binary", type=Path)
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--tests", nargs="+", type=Path)
    args = parser.parse_args()
    if not args.self_test and not args.tests:
        parser.error("supply --self-test or --tests")
    global DIAGNOSTICS
    global _POSTGRES
    DIAGNOSTICS = args.diagnose
    _POSTGRES = args.postgres
    _install(
        args.backend_root,
        postgres=args.postgres,
        frontend_root=args.frontend_root,
        node_binary=args.node_binary,
    )
    if args.self_test:
        _self_test()
        return 0
    import pytest

    out = Path("/tmp/botelier-auth-trial")
    result = pytest.main([
        "-q", "--tb=short", "--noconftest", "-p", "no:cacheprovider",
        "-p", "pytest_asyncio.plugin",
        "--basetemp=" + str(out / "pytest-temp"),
        "-o", "log_file=" + str(out / "pytest.log"),
        *[str(path) for path in args.tests],
    ])
    print("AUTH_GUARD_BLOCKED_ATTEMPTS=" + str(len(BLOCKED)))
    if BLOCKED:
        print("AUTH_GUARD_BLOCKED_CATEGORIES=" + ",".join(BLOCKED))
    return 3 if BLOCKED else int(result)


if __name__ == "__main__":
    raise SystemExit(main())

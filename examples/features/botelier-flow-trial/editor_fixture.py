"""Bounded ASGI checkpoint for real editor/auth/version/native leaf routes.

This is test-only infrastructure. It is intentionally not a replacement for
the application startup path or the browser's real sign-in flow.
"""

import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ACCOUNT_ID = "00000000-0000-0000-0000-000000000101"
PROPERTY_ID = "00000000-0000-0000-0000-000000000102"
ASSISTANT_ID = "00000000-0000-0000-0000-000000000104"
TOOL_SET_ID = "00000000-0000-0000-0000-000000000105"
TOOL_ID = "offline-flow"
USER_ID = "00000000-0000-0000-0000-000000000106"
EMAIL = "editor-pilot@botelier-test.org"
PASSWORD = "EditorPilot-Only!2026"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"
MAX_BODY_BYTES = 48 * 1024
_SIM_SESSION = re.compile(r"^/api/simulate/session/([A-Za-z0-9_-]{1,128})(?:/state)?$")
_SAFE_HEADERS = {"content-type", "origin", "x-mfa-csrf", "cookie", "authorization"}


class EditorFixtureError(RuntimeError):
    """An invalid request or setup for this scoped test fixture."""


def _json_size(value):
    try:
        return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as error:
        raise EditorFixtureError("Request body must be bounded JSON") from error


def _validate_json_shape(value, *, depth=0):
    if depth > 12:
        raise EditorFixtureError("Request JSON nesting exceeds the fixture limit")
    if isinstance(value, dict):
        if len(value) > 256 or not all(isinstance(key, str) and len(key) <= 128 for key in value):
            raise EditorFixtureError("Request object exceeds the fixture limits")
        for child in value.values():
            _validate_json_shape(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 2048:
            raise EditorFixtureError("Request array exceeds the fixture limit")
        for child in value:
            _validate_json_shape(child, depth=depth + 1)
    elif isinstance(value, str) and len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise EditorFixtureError("Request string exceeds the fixture limit")
    elif isinstance(value, float) and not math.isfinite(value):
        raise EditorFixtureError("Non-finite JSON number is not allowed")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise EditorFixtureError("Unsupported JSON value")


class EditorASGIFixture:
    """Direct async pytest fixture and allowlisted JSON-lines ASGI endpoint."""

    account_id = ACCOUNT_ID
    property_id = PROPERTY_ID
    assistant_id = ASSISTANT_ID
    tool_id = TOOL_ID
    user_id = USER_ID
    email = EMAIL
    password = PASSWORD
    totp_secret = TOTP_SECRET

    def __init__(self):
        self.app = None
        self.client = None
        self.engine = None
        self.factory = None
        self._lifespan = None
        self._native_fixture = None
        self._patches = None
        self._issued_simulation_sessions = set()
        self.models = None

    def ready_record(self):
        import pyotp

        return {
            "type": "ready",
            "scope": "test_only_editor_leaf_routes_not_main_app_startup",
            "account_id": self.account_id,
            "property_id": self.property_id,
            "assistant_id": self.assistant_id,
            "tool_id": self.tool_id,
            "tool_set_id": TOOL_SET_ID,
            "user_id": self.user_id,
            "email": self.email,
            "password": self.password,
            "totp": pyotp.TOTP(self.totp_secret).now(),
            "browser_fixtures": {
                "account": {
                    "id": self.account_id, "name": "Synthetic editor checkpoint",
                    "status": "active",
                },
                "property": {
                    "id": self.property_id, "account_id": self.account_id,
                    "name": "Synthetic Property", "timezone": "UTC",
                },
                "tool_set": {
                    "id": TOOL_SET_ID, "account_id": self.account_id,
                    "name": "Synthetic flow toolset",
                    "assistant_ids": [self.assistant_id], "tool_ids": [self.tool_id],
                },
                "assistant": {
                    "id": self.assistant_id, "account_id": self.account_id,
                    "property_id": self.property_id, "tool_set_id": TOOL_SET_ID,
                    "name": "Synthetic editor assistant",
                    "business_name": "Synthetic editor property", "is_active": True,
                    "call_settings": {"native_flow_tool_id": self.tool_id},
                },
                "user": {
                    "id": self.user_id, "email": self.email,
                    "first_name": "Synthetic", "last_name": "Editor",
                    "is_active": True,
                },
                "tool": {
                    "id": self.tool_id, "tool_set_id": TOOL_SET_ID,
                    "name": "Synthetic native flow", "tool_type": "FLOW",
                    "is_active": True, "published_version_number": 1,
                },
                "permissions": {
                    "flows.view": True, "flows.edit": True, "flows.publish": True,
                    "tools.view": True, "assistants.view": True,
                },
                "features": {"native_flow_editor": True, "flow_versioning": True},
            },
        }

    def allowed_request(self, method, path, body=None):
        """Validate the complete bridge route and bounded route-specific body."""
        if not isinstance(method, str) or not isinstance(path, str):
            return False
        if len(path) > 2048 or not path.startswith("/") or path.startswith("//"):
            return False
        verb = method.upper()
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            return False
        route = parsed.path
        try:
            query = parse_qs(parsed.query, strict_parsing=True, max_num_fields=4)
        except ValueError:
            return False

        def query_is(expected):
            return query == expected

        if route == "/api/auth/login":
            return (
                verb == "POST" and query_is({})
                and self._body_keys(body, {"email", "password"})
                and isinstance(body.get("email"), str) and len(body["email"]) <= 320
                and isinstance(body.get("password"), str) and len(body["password"]) <= 1024
            )
        if route == "/api/auth/mfa/status":
            return verb == "GET" and query_is({}) and body is None
        if route in {"/api/auth/mfa/verify", "/api/auth/mfa/logout"}:
            return verb == "POST" and query_is({}) and (
                (
                    self._body_keys(body, {"code"})
                    and isinstance(body.get("code"), str)
                    and re.fullmatch(r"[0-9]{6}", body["code"]) is not None
                ) if route.endswith("/verify")
                else body in (None, {})
            )
        if route == f"/api/tools/{TOOL_ID}/flow":
            return (
                verb == "GET" and body is None
                and query in (
                    {"account_id": [self.account_id]},
                    {"account_id": [self.account_id], "source": ["draft"]},
                    {"account_id": [self.account_id], "source": ["published"]},
                )
            )
        if route == f"/api/tools/{TOOL_ID}/flow/draft":
            return query == {"account_id": [self.account_id]} and (
                (
                    verb == "PUT"
                    and self._body_keys(body, {"flow_config"}, optional={"description"})
                ) or (verb == "DELETE" and body in (None, {}))
            )
        if route == f"/api/tools/{TOOL_ID}/flow/publish":
            return query == {"account_id": [self.account_id]} and verb == "POST" and (
                body is None or self._body_keys(body, set(), optional={"description"})
            )
        if route == f"/api/tools/{TOOL_ID}/flow/versions":
            return query == {"account_id": [self.account_id]} and verb == "GET" and body is None
        if re.fullmatch(rf"/api/tools/{re.escape(TOOL_ID)}/flow/versions/[1-9][0-9]{{0,8}}", route):
            return query == {"account_id": [self.account_id]} and verb == "GET" and body is None
        if route == "/api/simulate/start":
            return (
                verb == "POST" and query_is({})
                and self._body_keys(
                    body, {"tool_id", "assistant_id", "engine", "source", "source_version"}
                )
                and body.get("tool_id") == TOOL_ID
                and body.get("assistant_id") == self.assistant_id
                and body.get("engine") == "native_pilot"
                and body.get("source") == "published"
                and type(body.get("source_version")) is int
                and 1 <= body["source_version"] <= 2_147_483_647
            )
        if route == "/api/simulate/message":
            return (
                verb == "POST" and query_is({})
                and self._body_keys(body, {"session_id", "message"})
                and isinstance(body.get("session_id"), str)
                and body.get("session_id") in self._issued_simulation_sessions
                and isinstance(body.get("message"), str)
                and len(body["message"].encode("utf-8")) <= 4096
            )
        if _SIM_SESSION.fullmatch(route):
            if not query_is({}):
                return False
            match = _SIM_SESSION.fullmatch(route)
            session_id = match.group(1)
            if session_id not in self._issued_simulation_sessions:
                return False
            if route.endswith("/state"):
                return verb == "GET" and body is None
            return verb == "DELETE" and body in (None, {})
        return False

    @staticmethod
    def _body_keys(body, required, optional=frozenset()):
        if not isinstance(body, dict) or not required.issubset(body):
            return False
        if not set(body).issubset(required | set(optional)):
            return False
        try:
            _validate_json_shape(body)
            return _json_size(body) <= MAX_BODY_BYTES
        except EditorFixtureError:
            return False

    async def __aenter__(self):
        import importlib
        import os
        from contextlib import ExitStack
        from pathlib import Path
        from unittest.mock import patch

        import httpx
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.dialects.postgresql import JSONB, UUID
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import editor_guard

        self._patches = ExitStack()
        backend = editor_guard.BACKEND_ROOT
        if backend is None:
            raise EditorFixtureError("Use editor_guard to initialize the approved source scope")
        backend = Path(backend).resolve()
        if Path(importlib.import_module("botelier").__file__).resolve().parent.parent != backend:
            raise EditorFixtureError("Loaded application package does not match approved backend")

        from simulation_guard import install_test_namespaces

        database = install_test_namespaces(backend)

        @compiles(JSONB, "sqlite")
        def _jsonb_sqlite(type_, compiler, **kw):
            return "JSON"

        @compiles(UUID, "sqlite")
        def _uuid_sqlite(type_, compiler, **kw):
            return "CHAR(32)"

        original_uuid_bind_processor = UUID.bind_processor

        def _sqlite_uuid_bind_processor(type_, dialect):
            if dialect.name == "sqlite" and type_.as_uuid:
                import uuid

                def bind(value):
                    if isinstance(value, uuid.UUID):
                        return value.hex
                    if isinstance(value, str):
                        return uuid.UUID(value).hex
                    return value

                return bind
            return original_uuid_bind_processor(type_, dialect)

        self._patches.enter_context(patch.object(
            UUID, "bind_processor", _sqlite_uuid_bind_processor,
        ))

        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        database.bind_session_factory(self.factory)

        from botelier.models.account import Account, AccountStatus, SubscriptionTier
        from botelier.models.assistant import Assistant
        from botelier.models.flow_version import FlowVersion, FlowVersionStatus
        from botelier.models.mfa import MFAAudit, MFARecoveryCode, MFARateLimit, MFASession
        from botelier.models.property import Property
        from botelier.models.role import AccountMembership, Role
        from botelier.models.tool import Tool, ToolType
        from botelier.models.tool_set import ToolSet
        from botelier.models.user import AuthProvider, User, UserType

        self.models = {
            "Account": Account, "AccountMembership": AccountMembership,
            "Assistant": Assistant, "FlowVersion": FlowVersion, "MFAAudit": MFAAudit,
            "MFARecoveryCode": MFARecoveryCode, "MFARateLimit": MFARateLimit,
            "MFASession": MFASession, "Property": Property, "Role": Role,
            "Tool": Tool, "ToolSet": ToolSet, "User": User,
        }
        for index in FlowVersion.__table__.indexes:
            if index.name == "ix_flow_versions_single_draft":
                index.dialect_options["sqlite"]["where"] = (
                    index.dialect_options["postgresql"]["where"]
                )
        tables = [model.__table__ for model in self.models.values()]
        database.Base.metadata.create_all(self.engine, tables=tables)

        import uuid
        from botelier.api.auth import hash_password
        from botelier.crypto import reset_cipher_cache
        from botelier.services import mfa_service
        import pyotp

        reset_cipher_cache()
        account_id = uuid.UUID(self.account_id)
        property_id = uuid.UUID(self.property_id)
        assistant_id = uuid.UUID(self.assistant_id)
        tool_set_id = uuid.UUID(TOOL_SET_ID)
        user_id = uuid.UUID(self.user_id)
        encrypted_secret = mfa_service.secret_cipher().encrypt(self.totp_secret.encode()).decode()

        db = self.factory()
        account = Account(
            id=account_id, name="Synthetic editor checkpoint", slug="editor-checkpoint",
            email=self.email, status=AccountStatus.ACTIVE,
            subscription_tier=SubscriptionTier.FREE, require_mfa=True,
        )
        prop = Property(
            id=property_id, account_id=account_id, name="Synthetic Property",
            timezone="UTC", is_default=True, is_active=True,
        )
        role = Role(
            id=uuid.UUID("00000000-0000-0000-0000-000000000107"),
            name="Editor pilot", slug="editor-pilot", account_id=account_id,
            permissions={
                "flows": {"view": True, "edit": True, "publish": True},
                "tools": {"view": True}, "assistants": {"view": True},
            },
        )
        user = User(
            id=user_id, email=self.email, password_hash=hash_password(self.password),
            first_name="Synthetic", last_name="Editor", auth_provider=AuthProvider.EMAIL,
            user_type=UserType.ACCOUNT_USER, is_active=True, email_verified=True,
            mfa_enabled=True, mfa_secret_encrypted=encrypted_secret, mfa_version=1,
        )
        membership = AccountMembership(
            id=uuid.UUID("00000000-0000-0000-0000-000000000108"),
            user_id=user_id, account_id=account_id, role_id=role.id, is_active=True,
            is_owner=True,
        )
        tool_set = ToolSet(
            id=tool_set_id, account_id=account_id, name="Synthetic flow toolset",
        )
        assistant = Assistant(
            id=assistant_id, account_id=account_id, property_id=property_id,
            tool_set_id=tool_set_id, name="Synthetic editor assistant",
            business_name="Synthetic editor property",
            system_prompt="Use only the pilot flow and its fixture results.",
            llm_provider="openai", llm_model="gpt-4.1-mini", temperature=0.25,
            max_tokens=231, stt_provider="deepgram", tts_provider="deepgram",
            stt_model="flux-general-en", tts_model="flux", tts_voice="aura-asteria-en",
            stt_config={}, llm_config={}, tts_config={}, vad_config={},
            allowed_connection_ids=[], call_settings={"native_flow_tool_id": TOOL_ID},
            is_active=True,
        )
        from pilot_io import pilot_config

        initial_config = pilot_config()
        # UI positions are saved editor metadata, not native runtime semantics.
        positions = {
            "start": (40, 0), "query": (40, 190), "lookup": (40, 390),
            "response": (40, 610), "choice": (40, 810), "failure": (370, 610),
        }
        for node in initial_config["nodes"]:
            x, y = positions[node["id"]]
            node["position"] = {"x": x, "y": y}
            if node["type"] == "collect_slot":
                node["data"]["slot"].update(type="text", required=True)
        api_node = next(node for node in initial_config["nodes"] if node["id"] == "lookup")
        api_node["data"]["api"]["endpointId"] = "editor-fixture-endpoint"
        initial_config["variables"].extend([
            {"key": "rooms", "type": "array", "description": "Synthetic room results"},
            {"key": "price", "type": "number", "description": "Synthetic result price"},
        ])
        tool = Tool(
            id=TOOL_ID, name="Synthetic native flow", description="Bounded editor checkpoint",
            tool_type=ToolType.FLOW, config=initial_config, tool_set_id=tool_set_id,
            is_active="true",
        )
        version_id = uuid.UUID("00000000-0000-0000-0000-000000000109")
        version = FlowVersion(
            id=version_id, tool_id=TOOL_ID, version_number=1,
            status=FlowVersionStatus.PUBLISHED,
            description="Synthetic published pilot baseline", flow_config=initial_config,
        )
        tool.published_version_id = version_id
        tool.published_version_number = 1
        db.add_all([account, prop, role, user, membership, tool_set, assistant, tool, version])
        db.commit()
        db.close()
        assert pyotp.TOTP(self.totp_secret).now()
        self.models.update({"version_id": version_id})

        from application_support import API_KEYS
        from native_text_io import NativeTextFixture

        replies = [
            {"tool_calls": [{"index": 0, "id": "editor-query", "type": "function",
                             "function": {"name": "collect_query",
                                          "arguments": '{"query":"standard"}'}}]},
            {"tool_calls": [{"index": 0, "id": "editor-choice", "type": "function",
                             "function": {"name": "collect_choice",
                                          "arguments": '{"choice":"standard"}'}}]},
            "The synthetic standard option is selected.",
        ]
        self._native_fixture = NativeTextFixture(replies)
        await self._native_fixture.__aenter__()
        from botelier.services import native_simulation

        expected_native_service = backend / "botelier" / "services" / "native_simulation.py"
        if Path(native_simulation.__file__).resolve() != expected_native_service.resolve():
            raise EditorFixtureError("Native simulation service source identity mismatch")
        self._patches.enter_context(patch.object(
            native_simulation, "native_model_api_keys", return_value=API_KEYS,
        ))
        self._patches.enter_context(patch.object(
            native_simulation, "native_action_session_factory",
            return_value=self._native_fixture.actions.session,
        ))
        from botelier.voice.flows.native_text_host import NativeTextHost

        expected_host = backend / "botelier" / "voice" / "flows" / "native_text_host.py"
        host_module = sys.modules[NativeTextHost.__module__]
        if Path(host_module.__file__).resolve() != expected_host.resolve():
            raise EditorFixtureError("Native text host source identity mismatch")
        from botelier.voice.flows.pilot_adapter import NativePilotAdapter

        adapter_module = sys.modules[NativePilotAdapter.__module__]
        expected_adapter = backend / "botelier" / "voice" / "flows" / "pilot_adapter.py"
        if Path(adapter_module.__file__).resolve() != expected_adapter.resolve():
            raise EditorFixtureError("Native pilot adapter source identity mismatch")

        self.app = FastAPI()
        # Avoid botelier.api.__init__ importing the whole server route catalogue.
        api_modules = ("botelier.api.auth", "botelier.api.mfa",
                       "botelier.api.flow_versions", "botelier.api.simulation")
        for name in api_modules:
            module = importlib.import_module(name)
            if Path(module.__file__).resolve() != (backend / (name.replace(".", "/") + ".py")).resolve():
                raise EditorFixtureError(f"Application source identity mismatch: {name}")
            self.app.include_router(module.router)
        from botelier.api import simulation

        simulation.SimulationSession.sessions = {}
        simulation.SimulationSession.native_registry = None
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://127.0.0.1:5011",
        )
        return self

    async def forward(self, request):
        if (
            not isinstance(request, dict)
            or set(request) - {"action", "id", "method", "path", "headers", "body"}
            or request.get("action") != "request"
            or not isinstance(request.get("id"), (str, int))
            or isinstance(request.get("id"), bool)
            or len(str(request.get("id"))) > 128
        ):
            raise EditorFixtureError("Unsupported IPC action")
        method = request.get("method")
        path = request.get("path")
        body = request.get("body")
        if not self.allowed_request(method, path, body):
            raise EditorFixtureError("Request is outside the editor fixture allowlist")
        headers = request.get("headers") or {}
        if not isinstance(headers, dict) or len(headers) > 8:
            raise EditorFixtureError("Unsupported request headers")
        safe_headers = {}
        for key, value in headers.items():
            normalized = key.lower() if isinstance(key, str) else ""
            if normalized not in _SAFE_HEADERS or not isinstance(value, str) or len(value) > 8192:
                raise EditorFixtureError("Unsupported request headers")
            if normalized == "cookie" and not re.fullmatch(
                r"botelier_mfa_session=[A-Za-z0-9_-]{32,256}", value
            ):
                raise EditorFixtureError("Only the synthetic MFA session cookie is accepted")
            if normalized == "origin" and value != "http://127.0.0.1:5011":
                raise EditorFixtureError("Only the fixed synthetic browser origin is accepted")
            if normalized == "authorization" and not re.fullmatch(
                r"Bearer [A-Za-z0-9._~-]{1,4096}", value
            ):
                raise EditorFixtureError("Only a bounded issued bearer token is accepted")
            if normalized == "content-type" and value.lower() not in {
                "application/json", "application/json; charset=utf-8",
            }:
                raise EditorFixtureError("Only JSON request bodies are accepted")
            safe_headers[normalized] = value
        encoded = None if body is None else json.dumps(body, separators=(",", ":"))
        if encoded is not None and len(encoded.encode()) > MAX_BODY_BYTES:
            raise EditorFixtureError("Request body exceeds fixture limit")
        self.client.cookies.clear()
        try:
            response = await self.client.request(
                method.upper(), path, headers=safe_headers, content=encoded,
            )
        finally:
            # Browser cookies must be explicitly forwarded on every RPC call.
            self.client.cookies.clear()
        payload = None
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:MAX_BODY_BYTES]
        if urlsplit(path).path == "/api/simulate/start" and response.status_code == 200:
            session_id = payload.get("session_id") if isinstance(payload, dict) else None
            if isinstance(session_id, str) and len(session_id) <= 128:
                self._issued_simulation_sessions.add(session_id)
        session_match = _SIM_SESSION.fullmatch(urlsplit(path).path)
        if (
            session_match and not urlsplit(path).path.endswith("/state")
            and method.upper() == "DELETE" and response.status_code < 400
        ):
            self._issued_simulation_sessions.discard(session_match.group(1))
        return {
            "type": "response",
            "id": request["id"],
            "status": response.status_code,
            "body": payload,
            "headers": list(response.headers.multi_items()),
        }

    async def __aexit__(self, exc_type, exc, traceback):
        if self.client is not None:
            await self.client.aclose()
        if self._lifespan is not None:
            await self._lifespan.__aexit__(exc_type, exc, traceback)
        if self._native_fixture is not None:
            await self._native_fixture.__aexit__(exc_type, exc, traceback)
        if self._patches is not None:
            self._patches.close()
        if self.engine is not None:
            self.engine.dispose()
        if self.factory is not None:
            from botelier.crypto import reset_cipher_cache

            reset_cipher_cache()
        from sqlalchemy.dialects.postgresql import JSONB, UUID
        from sqlalchemy.ext.compiler import deregister

        deregister(JSONB)
        deregister(UUID)

"""Synthetic persistence/auth metadata and transport for actual simulator API tests."""

from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import guard


class SimulationDBQuery:
    """Strict evaluator for the actual simulator's SQLAlchemy filter expressions."""

    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.filters = []

    def filter(self, *criteria):
        for criterion in criteria:
            operator = getattr(getattr(criterion, "operator", None), "__name__", "")
            if operator != "eq":
                guard.deny("unsupported_simulation_metadata_filter")
            field = getattr(getattr(criterion, "left", None), "key", None)
            right = getattr(criterion, "right", None)
            expected = getattr(right, "value", right)
            if type(right).__name__ == "True_":
                expected = True
            elif type(right).__name__ == "False_":
                expected = False
            elif type(right).__name__ == "Null":
                expected = None
            if not field or not isinstance(
                expected, (str, int, float, bool, uuid.UUID, type(None)),
            ):
                raise AssertionError(
                    "Synthetic session received an unsupported filter "
                    f"field={field!r}, left={type(getattr(criterion, 'left', None)).__name__}, "
                    f"right={type(right).__name__}, value={type(expected).__name__}"
                )
            self.filters.append((field, expected))
        return self

    def order_by(self, *ordering):
        return self

    def _rows(self):
        rows = self.session.records.rows_for(self.model)
        matched = []
        for row in rows:
            if all(_equal(getattr(row, field, None), expected) for field, expected in self.filters):
                matched.append(row)
        return matched

    def first(self):
        self.session._assert_open()
        rows = self._rows()
        return rows[0] if rows else None

    def all(self):
        self.session._assert_open()
        return self._rows()


def _equal(actual, expected):
    if hasattr(actual, "value"):
        actual = actual.value
    if hasattr(expected, "value"):
        expected = expected.value
    if isinstance(actual, (uuid.UUID, str)) or isinstance(expected, (uuid.UUID, str)):
        return str(actual) == str(expected)
    return actual == expected


class SimulationDBSession:
    """No-connection session with only explicit auth and flow metadata reads."""

    def __init__(self, records):
        self.records = records
        self.closed = False
        self.events = records.events
        self.events.append(("db.open", id(self)))

    def _assert_open(self):
        if self.closed:
            guard.deny("simulation_db_used_after_close")

    def query(self, model):
        self._assert_open()
        self.events.append(("db.query", model.__name__))
        if model.__name__ not in self.records.allowed_models:
            guard.deny("unexpected_simulation_metadata_query")
        return SimulationDBQuery(self, model)

    def get(self, model, identity):
        self._assert_open()
        if model.__name__ not in {"User", "MFASession"}:
            guard.deny("unexpected_simulation_assurance_lookup")
        self.events.append(("db.get", model.__name__))
        return next(
            (
                row for row in self.records.rows_for(model)
                if _equal(row.id, identity)
            ),
            None,
        )

    def commit(self):
        self._assert_open()
        self.events.append(("db.commit", id(self)))

    def rollback(self):
        self.events.append(("db.rollback", id(self)))

    def close(self):
        if not self.closed:
            self.closed = True
            self.events.append(("db.close", id(self)))

    def add(self, row):
        self._assert_open()
        guard.deny("unexpected_simulation_metadata_write")

    def refresh(self, row):
        self._assert_open()
        guard.deny("unexpected_simulation_metadata_refresh")

    def __getattr__(self, name):
        guard.deny("unexpected_simulation_metadata_operation")


class NativeSimulationRecords:
    """Real NativeDevRecords plus in-memory, explicitly routed auth metadata."""

    allowed_models = {
        "Account", "AccountMembership", "Assistant", "FlowVersion", "Property",
        "Role", "Tool", "ToolSet", "User", "MFASession",
    }

    def __init__(self, *, stale_tool_config=True, bad_contract=False, events=None):
        from native_dev_voice_io import NativeDevRecords
        from botelier.models.role import AccountMembership, Role
        from botelier.models.user import User, UserType
        from botelier.models.mfa import MFASession
        from node_contract_io import ACCOUNT

        self.metadata = NativeDevRecords(bad_contract=bad_contract)
        self.metadata.rows["FlowVersion"].version_number = 1
        self.metadata.assistant.knowledge_base_id = None
        self.metadata.assistant.mcp_connection_id = None
        self.metadata.assistant.mcp_enabled_tools = []
        if stale_tool_config:
            # The native route must compile FlowVersion, never this stale editor.
            self.metadata.rows["Tool"][0].config = {}

        self.events = events if events is not None else []
        self.sessions = []
        self._rows = self.metadata.rows
        self.admin = _user(User, UserType.PLATFORM_ADMIN, "native-admin")
        self.other_admin = _user(User, UserType.PLATFORM_ADMIN, "other-admin")
        self.denied_user = _user(User, UserType.ACCOUNT_USER, "denied-user")
        role = Role(
            id=uuid.uuid4(),
            name="Synthetic no-access role",
            slug="simulation-no-access",
            permissions={
                "tools": {"view": False},
                "assistants": {"view": False},
            },
        )
        membership = AccountMembership(
            id=uuid.uuid4(),
            user_id=self.denied_user.id,
            account_id=ACCOUNT,
            role_id=role.id,
            role=role,
            permission_overrides={},
            is_active=True,
        )
        self.denied_user.account_memberships = [membership]
        self.users = [self.admin, self.other_admin, self.denied_user]
        # Represent completed factor verification in the synthetic persistence
        # boundary; the real middleware must still resolve/check every session.
        # Actual enrollment and factor/recovery behavior has a separate real
        # SQLite/PostgreSQL HTTP suite, not a middleware dependency override.
        now = datetime.utcnow()
        self.assurance_sessions = [
            MFASession(
                id=hashlib.sha256(
                    f"native-simulation-fixture:{user.id}".encode()
                ).hexdigest(),
                user_id=user.id,
                version=0,
                primary_at=now,
                verified_at=now,
                expires_at=now + timedelta(minutes=10),
                restricted=False,
                recovery_grant=False,
                revoked=False,
                pending_secret_encrypted=None,
                pending_expires_at=None,
                attempts=0,
                created_at=now,
            )
            for user in self.users
        ]
        self.memberships = [membership]
        self.roles = [role]

        self.account = SimpleNamespace(id=ACCOUNT, name="Synthetic test account")

    @property
    def assistant(self):
        return self.metadata.assistant

    @property
    def tool(self):
        return self.metadata.rows["Tool"][0]

    @property
    def version(self):
        return self.metadata.rows["FlowVersion"]

    def rows_for(self, model):
        name = model.__name__
        if name == "User":
            return self.users
        if name == "MFASession":
            return self.assurance_sessions
        if name == "AccountMembership":
            return self.memberships
        if name == "Role":
            return self.roles
        if name == "Account":
            return [self.account]
        if name in self._rows:
            row = self._rows[name]
            if row is None:
                return []
            return row if isinstance(row, list) else [row]
        if name in self.allowed_models:
            return []
        guard.deny("unexpected_simulation_metadata_model")

    def session(self):
        session = SimulationDBSession(self)
        self.sessions.append(session)
        return session

    def assurance_for(self, user):
        return next(row for row in self.assurance_sessions if row.user_id == user.id)


def _user(model, user_type, replit_id):
    return model(
        id=uuid.uuid4(),
        replit_id=replit_id,
        email=f"{replit_id}@fixture.invalid",
        first_name="Synthetic",
        last_name="Simulator",
        user_type=user_type,
        is_active=True,
        mfa_enabled=True,
        mfa_version=0,
        mfa_recovery_required=False,
        primary_credentials_revoked_at=None,
        account_memberships=[],
        last_login_at=None,
    )


def auth_header(user, secret, *, assurance=None):
    from jose import jwt

    now = int(datetime.utcnow().timestamp())
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + 600,
            "email": user.email,
            **(
                {
                    "sid": assurance.id,
                    "purpose": "botelier_session",
                    "auth_time": now,
                }
                if assurance is not None else {}
            ),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class NativeSimulationAPIHarness:
    """Run the actual API router through HTTPX ASGI with real native workers."""

    def __init__(
        self,
        *,
        replies=None,
        payload=None,
        stale_tool_config=True,
        bad_contract=False,
        environment=None,
        native_enabled="1",
    ):
        from simulation_guard import TEST_NEXTAUTH_SECRET

        self.events = []
        self.records = NativeSimulationRecords(
            stale_tool_config=stale_tool_config,
            bad_contract=bad_contract,
            events=self.events,
        )
        self.secret = TEST_NEXTAUTH_SECRET
        self.replies = replies or [
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "native-api-query",
                    "type": "function",
                    "function": {
                        "name": "collect_query",
                        "arguments": '{"query":"standard"}',
                    },
                }],
            },
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "native-api-choice",
                    "type": "function",
                    "function": {
                        "name": "collect_choice",
                        "arguments": '{"choice":"standard"}',
                    },
                }],
            },
            "Your choice is paused for this pilot.",
        ]
        self.payload = payload
        self.environment = environment
        self.native_enabled = native_enabled
        self.fixture = None
        self.client = None
        self.app = None
        self.api = None
        self.database = None
        self.registry = None
        self.active_sessions = []
        self._patches = ExitStack()
        self._lifespan = None
        self._native_simulation_module = None
        self.shutdown_active_count = None

    async def __aenter__(self):
        import botelier
        import httpx
        from fastapi import FastAPI

        from application_support import API_KEYS
        from native_text_io import NativeTextFixture
        from simulation_guard import install_test_namespaces

        # CI mounts trial code separately from the installed app. Keep the
        # exact router identity check against the loaded backend, not /ci.
        backend = Path(botelier.__file__).resolve().parent.parent
        self.database = sys.modules.get("botelier.database")
        if self.database is None:
            self.database = install_test_namespaces(backend)
        self.database.bind_session_factory(self.records.session)

        if self.environment is not None:
            self._patches.enter_context(patch.dict(
                os.environ,
                {
                    "BOTELIER_ENV": self.environment,
                    "BOTELIER_NATIVE_FLOWS_DEV": self.native_enabled,
                },
            ))

        self.fixture = NativeTextFixture(self.replies, payload=self.payload)
        await self.fixture.__aenter__()

        async def observe_provider(request):
            self.events.append(("provider", str(request.url)))
            return await self._provider_http(request)

        self._provider_http = self.fixture.providers.http
        self._patches.enter_context(patch.object(
            self.fixture.providers, "http", observe_provider,
        ))

        from botelier.services import native_simulation

        self._native_simulation_module = native_simulation
        if hasattr(native_simulation, "native_model_api_keys"):
            self._patches.enter_context(patch.object(
                native_simulation,
                "native_model_api_keys",
                return_value=API_KEYS,
            ))
        if hasattr(native_simulation, "native_action_session_factory"):
            self._patches.enter_context(patch.object(
                native_simulation,
                "native_action_session_factory",
                return_value=self.fixture.actions.session,
            ))

        import importlib
        self.api = importlib.import_module("botelier.api.simulation")
        actual_route = Path(self.api.__file__).resolve()
        expected_route = backend / "botelier" / "api" / "simulation.py"
        if actual_route != expected_route.resolve():
            raise RuntimeError("The actual simulation API route was not loaded")

        self.api.SimulationSession.sessions = {}
        self.api.SimulationSession.native_registry = None
        self.app = FastAPI()
        self.app.include_router(self.api.router)
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://simulation.test",
        )
        return self

    def headers(self, user=None):
        return (
            auth_header(
                user, self.secret, assurance=self.records.assurance_for(user),
            )
            if user is not None else {}
        )

    def start_payload(
        self, *, engine="native_pilot", source="published", source_version=1,
        tool_config=None,
    ):
        return {
            "tool_id": self.records.tool.id,
            "assistant_id": str(self.records.assistant.id),
            "engine": engine,
            "source": source,
            "source_version": source_version,
            **({"ignored_tool_config": tool_config} if tool_config is not None else {}),
        }

    def track_session(self, session_id):
        session = self.api.SimulationSession.sessions.get(session_id)
        if session is not None and hasattr(session, "host"):
            self.active_sessions.append(session)
            if session.host not in self.fixture.hosts:
                self.fixture.hosts.append(session.host)
            self.registry = getattr(
                self.api.SimulationSession, "native_registry", None,
            )
        return session

    async def start(self, *, user=None, **overrides):
        response = await self.client.post(
            "/api/simulate/start",
            json=self.start_payload(**overrides),
            headers=self.headers(user or self.records.admin),
        )
        body = response.json()
        if response.status_code == 200 and isinstance(body, dict):
            self.track_session(body.get("session_id"))
        if self.registry is None:
            self.registry = getattr(
                self.api.SimulationSession, "native_registry", None,
            )
        return response

    async def message(self, session_id, message, *, user=None, **extra):
        return await self.client.post(
            "/api/simulate/message",
            json={"session_id": session_id, "message": message, **extra},
            headers=self.headers(user or self.records.admin),
        )

    async def state(self, session_id, *, user=None):
        return await self.client.get(
            f"/api/simulate/session/{session_id}/state",
            headers=self.headers(user or self.records.admin),
        )

    async def delete(self, session_id, *, user=None):
        return await self.client.delete(
            f"/api/simulate/session/{session_id}",
            headers=self.headers(user or self.records.admin),
        )

    async def __aexit__(self, exc_type, exc, traceback):
        if self.client is not None:
            await self.client.aclose()
        if self._lifespan is not None:
            await self._lifespan.__aexit__(exc_type, exc, traceback)
        registry = getattr(self.api.SimulationSession, "native_registry", None)
        if registry is not None:
            self.shutdown_active_count = registry.active_count
        await self.fixture.__aexit__(exc_type, exc, traceback)
        self._patches.close()
        if exc_type is None and self.shutdown_active_count not in (None, 0):
            raise AssertionError(
                "API lifespan left native simulation sessions active"
            )

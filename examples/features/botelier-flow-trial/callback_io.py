"""Real callback router and signature code, synthetic records and external I/O."""

from contextlib import ExitStack
import importlib
from importlib.machinery import ModuleSpec
from pathlib import Path
import sys
import types
from unittest.mock import patch

import guard

from application_support import load_function_mapper
from callback_store import CallbackStore, TOKEN_A
from transfer_storage import MemoryTransferStorage


# Matches the synthetic origin in the actual SDK-generated transfer TwiML.
BASE_URL = "https://offline.invalid"


def load_callbacks():
    load_function_mapper()
    import botelier

    root = Path(botelier.__file__).resolve().parent
    database = sys.modules["botelier.database"]

    def unavailable(*args, **kwargs):
        guard.deny("unexpected_callback_database_or_dashboard_auth")

    database.get_db = unavailable
    # Dashboard JWT initialization requires a real secret and is not used by
    # these public, Twilio-authenticated callbacks. Its test-only replacement
    # always denies; it cannot authenticate anybody or bypass Twilio validation.
    for name, location in (("botelier.auth", "auth"), ("botelier.api", "api")):
        if name not in sys.modules:
            namespace = types.ModuleType(name)
            namespace.__path__ = [str(root / location)]
            namespace.__package__ = name
            namespace.__spec__ = ModuleSpec(name, loader=None, is_package=True)
            sys.modules[name] = namespace
    if "botelier.auth.middleware" not in sys.modules:
        middleware = types.ModuleType("botelier.auth.middleware")
        middleware.get_current_user = unavailable
        middleware.check_account_permission = unavailable
        sys.modules[middleware.__name__] = middleware
    module = importlib.import_module("botelier.api.calls")
    if Path(module.__file__).resolve() != root / "api/calls.py":
        raise RuntimeError("Callback checks did not load the real route module")
    return module


class CallbackHarness:
    def __init__(self, *, store=None, handler=None, expected_errors=(), expected_rollbacks=0):
        self.module = load_callbacks()
        self.store = store or CallbackStore()
        self.handler = handler
        self.patches = ExitStack()
        self.errors, self.jobs, self.billing = [], [], []
        self.expected_errors = expected_errors
        self.expected_rollbacks = expected_rollbacks

    async def __aenter__(self):
        import httpx
        from fastapi import FastAPI
        from loguru import logger
        from botelier.config import domain
        from botelier.services.call_logger import CallLogger
        from botelier.voice.call_handler import CallHandler

        self.handler = self.handler or CallHandler()

        async def fixture_db():
            yield self.store

        self.app = FastAPI()
        self.app.include_router(self.module.router)
        self.app.dependency_overrides[self.module.get_db] = fixture_db
        self.patches.enter_context(patch.object(
            domain, "get_public_base_url", lambda **kwargs: BASE_URL,
        ))
        self.patches.enter_context(patch.object(
            self.module, "_get_call_handler", lambda: self.handler,
        ))
        from botelier.services.transfer_attempts import TransferAttempts
        storage = vars(self.store).get("transfer_storage") or MemoryTransferStorage()
        self.patches.enter_context(patch.object(
            self.module, "_transfer_attempts_for_db",
            lambda db: TransferAttempts(storage),
        ))
        # Keep callback routing and eligibility helpers real. Only external
        # business jobs and billing persistence are out of this checkpoint.
        for name in (
            "run_acw_background", "run_record_extraction_for_call_background",
            "run_billing_alert_background",
        ):
            def record_job(*args, _name=name, **kwargs):
                assert not self.store.locked, "Callback held an update lock across background work"
                self.jobs.append((_name, args))
            self.patches.enter_context(patch.object(self.module, name, record_job))
        for name in ("_upsert_inbound_billing", "_write_transfer_billing"):
            def billing_io(logger, *args, _name=name, **kwargs):
                self.billing.append((_name, args))
            self.patches.enter_context(patch.object(CallLogger, name, billing_io))
        self.sink = logger.add(
            lambda message: self.errors.append(message.record["message"]), level="ERROR",
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=BASE_URL,
        )
        return self

    async def post(self, path, fields, *, token=TOKEN_A, signature=None):
        from twilio.request_validator import RequestValidator

        if signature is None:
            signature = RequestValidator(token).compute_signature(BASE_URL + path, fields)
        return await self.client.post(
            path, data=fields, headers={"X-Twilio-Signature": signature},
        )

    async def __aexit__(self, *exc):
        from loguru import logger

        await self.client.aclose()
        logger.remove(self.sink)
        self.patches.close()
        self.store.close()
        if exc[0] is None:
            assert self.errors == list(self.expected_errors), self.errors
            assert self.store.rollbacks == self.expected_rollbacks

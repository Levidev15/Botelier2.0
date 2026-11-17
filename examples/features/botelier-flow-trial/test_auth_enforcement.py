"""TDD smoke check for actual password-login/MFA protocol enforcement."""
import asyncio
import base64
import hashlib
import hmac
import importlib
import os
import sys
import types
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


def test_required_platform_admin_login_does_not_issue_application_bearer():
    from botelier.api.auth import router as auth_router, hash_password
    from botelier.auth.middleware import get_current_user
    from botelier.database import Base, get_db
    from botelier.models.user import User, UserType
    from fastapi import Depends

    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from botelier.models.account import Account
    from botelier.models.role import AccountMembership, Role
    from botelier.models.invitation import AccountInvitation
    from botelier.models.mfa import MFAAudit, MFARecoveryCode, MFARateLimit, MFASession
    Base.metadata.create_all(engine, tables=[
        Account.__table__, User.__table__, Role.__table__, AccountMembership.__table__,
        AccountInvitation.__table__, MFASession.__table__, MFARecoveryCode.__table__,
        MFARateLimit.__table__, MFAAudit.__table__,
    ])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add(User(
        id=uuid.uuid4(), email="admin@example.com",
        password_hash=hash_password("TestPassword123!"),
        user_type=UserType.PLATFORM_ADMIN, is_active=True,
    ))
    db.commit()
    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/auth-trial-protected")
    def protected(user=Depends(get_current_user)):
        return {"id": str(user.id)}

    def dependency():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    with TestClient(app, headers={
        "X-MFA-CSRF": "1", "Origin": "http://testserver",
    }) as client:
        response = client.post("/api/auth/login", json={
            "email": "admin@example.com",
            "password": "TestPassword123!",
        })
        assert response.status_code == 200, response.text
        assert response.json()["mfa_required"] is True
        assert response.json()["access_token"] is None
        assert client.get("/auth-trial-protected").status_code == 403
    db.close()
    engine.dispose()


def test_stream_auth_import_does_not_initialize_messaging_providers():
    importlib.import_module("botelier.api.sms_pkg.webhook")

    assert "botelier.services.sms_service" not in sys.modules
    assert "botelier.voice.knowledge_handler" not in sys.modules
    assert "OPENAI_API_KEY" not in os.environ


@pytest.fixture
def sms_webhook_trial(monkeypatch):
    """Real routing, form parsing and signature checks; no SMS/AI execution."""
    from botelier.database import get_db

    state = types.SimpleNamespace(events=[], calls=[], fail=False)
    state.db = MagicMock(name="disposable_sms_lookup")
    state.db.query.return_value.filter.return_value.first.return_value = None
    state.url = "https://offline.invalid/api/sms/webhook"
    token = "offline-sms-signature-fixture-not-a-credential"
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)

    class OfflineSMSService:
        def __init__(self, db):
            self.db = db

        def process_incoming_sms(self, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running = False
            else:
                loop_running = True
            state.calls.append({"db": self.db, "loop_running": loop_running, **kwargs})
            if state.fail:
                raise RuntimeError("offline SMS processing failure")
            return None, None, False

    def sender_attribute(name):
        if name == "SMSService":
            state.events.append("provider_import")
            return OfflineSMSService
        raise AttributeError(name)

    sender = types.ModuleType("botelier.services.sms_service")
    sender.__getattr__ = sender_attribute
    monkeypatch.setitem(sys.modules, sender.__name__, sender)

    # Reload the actual router, and restore both its cache entry and package
    # attribute afterward so these boundary doubles cannot leak to other tests.
    package = importlib.import_module("botelier.api.sms_pkg")
    monkeypatch.setattr(package, "webhook", None, raising=False)
    monkeypatch.delitem(sys.modules, "botelier.api.sms_pkg.webhook", raising=False)
    webhook = importlib.import_module("botelier.api.sms_pkg.webhook")
    monkeypatch.setattr(webhook, "_build_webhook_url", lambda request, path: state.url)
    validate = webhook._validate_twilio_signature

    def tracked_validation(*args, **kwargs):
        valid, url = validate(*args, **kwargs)
        state.events.append("signature_valid" if valid else "signature_invalid")
        return valid, url

    monkeypatch.setattr(webhook, "_validate_twilio_signature", tracked_validation)

    def signed_headers(form):
        payload = state.url + "".join(key + form[key] for key in sorted(form))
        signature = base64.b64encode(
            hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
        ).decode()
        return {"X-Twilio-Signature": signature}

    state.signed_headers = signed_headers
    app = FastAPI()
    app.include_router(webhook.router)

    def fixture_db():
        yield state.db

    app.dependency_overrides[get_db] = fixture_db
    with TestClient(app) as state.client:
        yield state


@pytest.mark.parametrize(("media_fields", "expected_media"), [
    ({}, None),
    ({
        "NumMedia": "2",
        "MediaUrl0": "https://example.invalid/first.png",
        "MediaUrl1": "https://example.invalid/second.png",
    }, [
        "https://example.invalid/first.png",
        "https://example.invalid/second.png",
    ]),
])
def test_valid_sms_loads_provider_after_signature_and_preserves_worker_dispatch(
    sms_webhook_trial, media_fields, expected_media,
):
    trial = sms_webhook_trial
    assert trial.events == []
    form = {
        "From": "+15550001111", "To": "+15550002222",
        "Body": "Offline reservation request", "MessageSid": "SM" + "0" * 32,
        **media_fields,
    }
    response = trial.client.post(
        "/api/sms/webhook", data=form, headers=trial.signed_headers(form),
    )

    assert response.status_code == 200
    assert response.text == '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    assert response.headers["content-type"].startswith("text/xml")
    assert trial.events[0] == "signature_valid"
    assert "provider_import" in trial.events[1:]
    assert trial.calls == [{
        "db": trial.db, "loop_running": False,
        "from_number": "+15550001111", "to_number": "+15550002222",
        "body": "Offline reservation request", "twilio_sid": "SM" + "0" * 32,
        "media_urls": expected_media,
    }]


@pytest.mark.parametrize("rejection", ["invalid_signature", "missing_signature", "missing_token"])
def test_rejected_sms_never_loads_or_dispatches_provider(sms_webhook_trial, monkeypatch, rejection):
    trial = sms_webhook_trial
    assert trial.events == []
    form = {
        "From": "+15550001111", "To": "+15550002222",
        "Body": "Offline rejection check", "MessageSid": "SM" + "1" * 32,
    }
    headers = trial.signed_headers(form)
    if rejection == "invalid_signature":
        headers["X-Twilio-Signature"] = "invalid-fixture-signature"
    elif rejection == "missing_signature":
        headers = {}
    else:
        monkeypatch.delenv("TWILIO_AUTH_TOKEN")
    response = trial.client.post("/api/sms/webhook", data=form, headers=headers)

    assert response.status_code == 403
    assert trial.events == ["signature_invalid"]
    assert trial.calls == []


def test_sms_processing_failure_preserves_empty_twiml_acknowledgment(sms_webhook_trial):
    trial = sms_webhook_trial
    assert trial.events == []
    trial.fail = True
    form = {
        "From": "+15550001111", "To": "+15550002222",
        "Body": "Offline failure check", "MessageSid": "SM" + "2" * 32,
    }
    response = trial.client.post(
        "/api/sms/webhook", data=form, headers=trial.signed_headers(form),
    )

    assert response.status_code == 200
    assert response.text == '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    assert trial.events[0] == "signature_valid"
    assert "provider_import" in trial.events[1:]
    assert len(trial.calls) == 1
    assert trial.calls[0]["loop_running"] is False

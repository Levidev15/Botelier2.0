"""MFA protocol regression tests using an isolated SQLite database."""
import time
import uuid

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from botelier.database import Base, get_db
from botelier.api.auth import router as auth_router, hash_password, create_jwt_token
from botelier.api.mfa import router as mfa_router
from botelier.auth.middleware import get_current_user
from botelier.models.user import User, UserType
from botelier.models.account import Account
from botelier.models.role import Role, AccountMembership
from botelier.models.disposition import AssistantDisposition
from botelier.models.knowledge_base import KnowledgeBase
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.mfa import MFASession, MFARecoveryCode, MFARateLimit, MFAAudit
from botelier.models.invitation import AccountInvitation, InvitationStatus
from botelier.crypto import reset_cipher_cache


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_cipher_cache()
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    tables = [Account.__table__, User.__table__, Role.__table__, AccountMembership.__table__,
              MFASession.__table__, MFARecoveryCode.__table__, MFARateLimit.__table__, MFAAudit.__table__,
              AccountInvitation.__table__]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    user = User(id=uuid.uuid4(), email="mfa@example.com", password_hash=hash_password("TestPassword123!"),
                first_name="MFA", user_type=UserType.PLATFORM_ADMIN, is_active=True)
    db.add(user)
    db.commit()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(mfa_router)

    from fastapi import Depends
    @app.get("/protected")
    @app.post("/protected")
    def protected(current=Depends(get_current_user)):
        return {"id": str(current.id)}

    def dependency():
        session = factory()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = dependency
    client = TestClient(app, headers={"X-MFA-CSRF": "1", "Origin": "http://testserver"})
    yield client, db, user
    db.close()
    engine.dispose()
    reset_cipher_cache()


def login(client):
    result = client.post("/api/auth/login", json={"email": "mfa@example.com", "password": "TestPassword123!"})
    assert result.status_code == 200, result.text
    return result


def enroll(client):
    reply = client.post("/api/auth/mfa/enroll", json={})
    assert reply.status_code == 200, reply.text
    secret = reply.json()["secret"]
    reply = client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert reply.status_code == 200, reply.text
    return secret, reply.json()


def test_admin_primary_session_cannot_access_application(env):
    client, db, user = env
    result = login(client)
    assert result.status_code == 200
    assert result.json()["access_token"] is None
    assert result.json()["enrollment_required"] is True
    assert client.get("/protected").status_code == 403
    assert "HttpOnly" in result.headers["set-cookie"]


def test_enrollment_full_session_and_legacy_token_rejection(env):
    client, db, user = env
    legacy = create_jwt_token(user)
    login(client)
    secret, data = enroll(client)
    assert len(data["recovery_codes"]) == 10
    assert client.get("/protected").status_code == 200
    assert client.get("/protected", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401
    db.expire_all()
    assert secret not in db.get(User, user.id).mfa_secret_encrypted
    assert db.query(MFARecoveryCode).count() == 10
    assert db.query(MFARecoveryCode).first().code_hash not in data["recovery_codes"]


def test_code_replay_and_recovery_force_reenrollment(env):
    client, db, user = env
    login(client)
    secret, data = enroll(client)
    old = data["access_token"]
    login(client)
    db.expire_all()
    replay_code = pyotp.TOTP(secret).at(db.get(User, user.id).mfa_last_step * 30)
    assert client.post("/api/auth/mfa/verify", json={"code": replay_code}).status_code == 400
    recovered = client.post("/api/auth/mfa/verify", json={"code": data["recovery_codes"][0]})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["access_token"] is None
    assert recovered.json()["enrollment_required"] is True
    assert client.get("/protected", headers={"Authorization": f"Bearer {old}"}).status_code in (401, 403)
    assert client.get("/protected").status_code == 403
    _, new_data = enroll(client)
    assert len(new_data["recovery_codes"]) == 10
    assert client.get("/protected").status_code == 200


def test_required_admin_cannot_disable_mfa(env):
    client, _, _ = env
    login(client)
    enroll(client)
    assert client.post("/api/auth/mfa/disable", json={}).status_code == 403


def test_mutation_csrf_and_challenge_rate_limit(env):
    client, _, _ = env
    login(client)
    assert client.post("/api/auth/mfa/enroll", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    enroll(client)
    login(client)
    codes = [client.post("/api/auth/mfa/verify", json={"code": "wrong"}).status_code for _ in range(8)]
    assert 429 in codes


def test_logout_revokes_bearer(env):
    client, _, _ = env
    login(client)
    _, data = enroll(client)
    assert client.post("/api/auth/mfa/logout", json={}).status_code == 200
    assert client.get("/protected", headers={"Authorization": f"Bearer {data['access_token']}"}).status_code == 401


def test_account_policy_applies_across_memberships(env):
    client, db, user = env
    user.user_type = UserType.ACCOUNT_USER
    account = Account(name="Protected", slug="protected", email="account@example.invalid", require_mfa=True)
    optional = Account(name="Optional", slug="optional", email="optional@example.invalid")
    db.add_all([account, optional])
    db.flush()
    role = Role(name="Admin", slug="admin", permissions={"settings": {"edit": True}})
    db.add(role)
    db.flush()
    db.add_all([AccountMembership(user_id=user.id, account_id=a.id, role_id=role.id) for a in (account, optional)])
    db.commit()
    assert login(client).json()["mfa_required"] is True
    assert client.get("/protected").status_code == 403


def test_legacy_validate_rejects_admin(env):
    client, _, user = env
    assert client.post("/api/auth/validate", json={"token": create_jwt_token(user)}).json()["valid"] is False


def test_stale_primary_cannot_be_refreshed_with_rolling_iat(env):
    from datetime import datetime, timedelta
    from jose import jwt
    import os
    client, _, user = env
    token = jwt.encode({"sub": str(user.id), "iat": datetime.utcnow(),
                        "auth_time": time.time() - 3600,
                        "exp": datetime.utcnow() + timedelta(hours=1)},
                       os.environ["NEXTAUTH_SECRET"], algorithm="HS256")
    reply = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert reply.status_code == 200
    assert reply.json()["primary_fresh"] is False
    assert client.post("/api/auth/mfa/enroll", json={}).json()["detail"]["code"] == "primary_auth_required"
    assert client.post("/api/auth/mfa/reauthenticate", json={"password": "TestPassword123!"}).status_code == 200
    enroll(client)
    assert client.get("/protected").status_code == 200


def test_expired_challenge_cannot_enroll(env):
    from datetime import datetime, timedelta
    client, db, _ = env
    login(client)
    db.query(MFASession).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
    db.commit()
    assert client.post("/api/auth/mfa/enroll", json={}).status_code == 401


def test_persisted_user_limit_survives_new_login_challenges(env):
    client, db, user = env
    from botelier.services import mfa_service as service
    from fastapi import HTTPException
    for _ in range(20):
        service.rate_limit(db, user.id, "test-source", "test")
    with pytest.raises(HTTPException) as exc:
        service.rate_limit(db, user.id, "test-source", "test")
    assert exc.value.status_code == 429
    assert db.query(MFARateLimit).count() == 2


def test_recovery_regeneration_revokes_prior_sessions_and_codes(env):
    client, db, _ = env
    login(client)
    _, first = enroll(client)
    reply = client.post("/api/auth/mfa/recovery-codes", json={})
    assert reply.status_code == 200
    assert set(reply.json()["recovery_codes"]).isdisjoint(first["recovery_codes"])
    assert client.get("/protected", headers={"Authorization": f"Bearer {first['access_token']}"}).status_code == 401
    login(client)
    assert client.post("/api/auth/mfa/verify", json={"code": first["recovery_codes"][0]}).status_code == 400


def test_optional_user_can_disable_but_prior_bearers_are_revoked(env):
    client, db, user = env
    user.user_type = UserType.ACCOUNT_USER
    db.commit()
    assert login(client).json()["access_token"]
    _, first = enroll(client)
    result = client.post("/api/auth/mfa/disable", json={})
    assert result.status_code == 200, result.text
    assert result.json()["access_token"]
    assert client.get("/protected", headers={"Authorization": f"Bearer {first['access_token']}"}).status_code == 401
    assert client.get("/protected").status_code == 200


def test_enrollment_rejects_ephemeral_cipher(env, monkeypatch):
    client, _, _ = env
    login(client)
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    assert client.post("/api/auth/mfa/enroll", json={}).status_code == 503


def test_replacement_invalidates_old_authenticator_and_recovery(env):
    client, _, _ = env
    login(client)
    old_secret, original = enroll(client)
    new_secret, replacement = enroll(client)
    assert old_secret != new_secret
    assert client.get("/protected", headers={"Authorization": f"Bearer {original['access_token']}"}).status_code == 401
    login(client)
    assert client.post("/api/auth/mfa/verify", json={"code": pyotp.TOTP(old_secret).now()}).status_code == 400
    assert client.post("/api/auth/mfa/verify", json={"code": original["recovery_codes"][0]}).status_code == 400


def test_replit_identity_bootstraps_only_restricted_session(env):
    from datetime import datetime, timedelta
    from jose import jwt
    import os
    client, db, user = env
    user.replit_id = "replit_test_identity"
    db.commit()
    token = jwt.encode({"sub": user.replit_id, "auth_time": time.time(),
                        "exp": datetime.utcnow() + timedelta(hours=1)},
                       os.environ["NEXTAUTH_SECRET"], algorithm="HS256")
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    reply = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert reply.status_code == 200
    assert reply.json()["mfa_required"] is True
    assert client.get("/protected").status_code == 403
    enroll(client)
    assert client.get("/protected").status_code == 200


def test_cookie_authenticated_writes_require_csrf(env):
    client, _, _ = env
    login(client)
    enroll(client)
    assert client.post("/protected", headers={"X-MFA-CSRF": ""}).status_code == 403
    assert client.post("/protected").status_code == 200


def test_invitation_registration_is_restricted_for_required_account(env):
    from datetime import datetime, timedelta
    client, db, user = env
    account = Account(name="Invitation account", slug="invite-account", email="account@example.com", require_mfa=True)
    role = Role(name="Staff", slug="invite-staff")
    db.add_all([account, role])
    db.flush()
    invitation = AccountInvitation(
        account_id=account.id, role_id=role.id, token="invitation-test",
        invitee_email="invited@example.com", invited_by_id=user.id,
        expires_at=datetime.utcnow() + timedelta(hours=1), status=InvitationStatus.PENDING,
    )
    db.add(invitation)
    db.commit()
    result = client.post("/api/auth/register", json={
        "email": "invited@example.com", "password": "TestPassword123!",
        "first_name": "Invited", "last_name": "Member", "invitation_token": invitation.token,
    })
    assert result.status_code == 200, result.text
    assert result.json()["access_token"] is None
    assert result.json()["enrollment_required"] is True
    assert client.get("/protected").status_code == 403
    db.expire_all()
    assert db.get(AccountInvitation, invitation.id).status == InvitationStatus.ACCEPTED


def test_policy_change_requires_fresh_mfa_and_is_immediate(env):
    client, db, user = env
    login(client)
    _, full = enroll(client)
    account = Account(name="Policy", slug="policy-account", email="policy@example.com")
    db.add(account)
    db.commit()
    result = client.patch(f"/api/auth/mfa/policy/{account.id}", json={"require_mfa": True})
    assert result.status_code == 200, result.text
    db.expire_all()
    assert db.get(Account, account.id).require_mfa is True
    login(client)
    assert client.patch(f"/api/auth/mfa/policy/{account.id}", json={"require_mfa": False}).status_code == 403


@pytest.mark.asyncio
async def test_sse_rechecks_revocation_before_delivering_next_event(env, monkeypatch):
    from starlette.requests import Request
    from botelier.api.sms_pkg import webhook
    from botelier.services import mfa_service as service
    client, db, _ = env
    login(client)
    enroll(client)
    raw = client.cookies.get(service.COOKIE_NAME)
    monkeypatch.setattr(webhook, "SessionLocal", sessionmaker(bind=db.bind))
    monkeypatch.setattr(webhook, "assert_sms_account_access", lambda *args: None)

    async def events(**kwargs):
        yield {"event": "keepalive", "data": ""}
        db.query(MFASession).update({"revoked": True})
        db.commit()
        yield {"event": "new_message", "data": "must not be disclosed"}
    monkeypatch.setattr(webhook.broadcaster, "event_generator", events)
    request = Request({"type": "http", "method": "GET", "path": "/api/sms/stream",
                       "headers": [(b"cookie", f"{service.COOKIE_NAME}={raw}".encode())], "query_string": b""})
    response = await webhook.sms_event_stream(request, str(uuid.uuid4()))
    received = [event async for event in response.body_iterator]
    assert len(received) == 1
    assert received[0]["event"] == "keepalive"


def test_first_replit_login_preserves_optional_mfa_and_returns_revocable_session(env):
    from datetime import datetime, timedelta
    from jose import jwt
    import os
    client, db, _ = env
    token = jwt.encode({"sub": "brand_new_replit_subject", "email": "new-replit@example.com",
                        "name": "New Replit User", "auth_time": time.time(),
                        "exp": datetime.utcnow() + timedelta(hours=1)},
                       os.environ["NEXTAUTH_SECRET"], algorithm="HS256")
    reply = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["mfa_required"] is False
    assert reply.json()["access_token"]
    new_user = db.query(User).filter(User.replit_id == "brand_new_replit_subject").one()
    assert reply.json()["user"]["id"] == str(new_user.id)
    assert client.get("/protected").status_code == 200
    client.post("/api/auth/mfa/logout", json={})
    assert client.get("/protected", headers={"Authorization": f"Bearer {reply.json()['access_token']}"}).status_code == 401


def test_optional_password_reauthentication_returns_replacement_token(env):
    client, db, user = env
    user.user_type = UserType.ACCOUNT_USER
    db.commit()
    old = login(client).json()["access_token"]
    reply = client.post("/api/auth/mfa/reauthenticate", json={"password": "TestPassword123!"})
    assert reply.status_code == 200
    assert reply.json()["access_token"]
    assert client.get("/protected", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_password_only_attacker_cannot_take_over_recovery_enrollment(env):
    client, db, user = env
    login(client)
    _, original = enroll(client)
    login(client)
    recovered = client.post("/api/auth/mfa/verify", json={"code": original["recovery_codes"][0]})
    assert recovered.status_code == 200
    attacker = TestClient(client.app, headers={"X-MFA-CSRF": "1", "Origin": "http://testserver"})
    login(attacker)
    denied = attacker.post("/api/auth/mfa/enroll", json={})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "recovery_session_required"
    assert attacker.post("/api/auth/mfa/confirm", json={"code": "123456"}).status_code == 403
    assert client.post("/api/auth/mfa/reauthenticate", json={"password": "TestPassword123!"}).status_code == 200
    enroll(client)
    assert client.get("/protected").status_code == 200
    assert attacker.get("/protected").status_code == 401


def test_foreign_origin_cannot_read_cookie_authenticated_data(env):
    client, _, _ = env
    login(client)
    enroll(client)
    for path in ("/protected", "/api/auth/mfa/status"):
        assert client.get(path, headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.get("/protected").status_code == 200


def test_credentialed_cors_has_explicit_origins(monkeypatch):
    from fastapi.middleware.cors import CORSMiddleware
    from botelier.api.mfa import configured_origins
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=sorted(configured_origins()),
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.get("/cors")
    def cors():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/cors", headers={"Origin": "https://app.example.com"}).headers["access-control-allow-origin"] == "https://app.example.com"
    assert "access-control-allow-origin" not in client.get("/cors", headers={"Origin": "https://evil.example.com"}).headers


@pytest.mark.parametrize("max_age,valid", [(3600, True), (-60, False)])
def test_actual_nextauth_generated_jwe_is_compatible(max_age, valid):
    import subprocess
    from pathlib import Path
    from botelier.auth.middleware import decode_jwt_token
    frontend = Path(__import__("os").environ["AUTH_TEST_FRONTEND"])
    result = subprocess.run(
        ["node", "-e",
         "require('next-auth/jwt').encode({token:{sub:'real-nextauth-subject',auth_time:123},"
         f"secret:process.env.NEXTAUTH_SECRET,maxAge:{max_age}"
         "}).then(t=>process.stdout.write(t));"],
        cwd=frontend, capture_output=True, text=True, check=True,
    )
    payload = decode_jwt_token(result.stdout)
    if valid:
        assert payload["sub"] == "real-nextauth-subject"
        assert payload["auth_time"] == 123
    else:
        assert payload is None


def nextauth_identity(user, authenticated_at=None):
    import json
    import os
    import subprocess
    from pathlib import Path
    payload = {"sub": str(user.id), "auth_time": authenticated_at or time.time()}
    return subprocess.run(
        ["node", "-e", "require('next-auth/jwt').encode({token:" + json.dumps(payload)
         + ",secret:process.env.NEXTAUTH_SECRET,maxAge:3600}).then(t=>process.stdout.write(t));"],
        cwd=Path(os.environ["AUTH_TEST_FRONTEND"]), capture_output=True, text=True, check=True,
    ).stdout


@pytest.mark.parametrize("operation", ["disable", "logout", "reset"])
def test_fresh_nextauth_jwe_cannot_replay_after_primary_revocation(env, operation):
    from botelier.services import mfa_service as service
    client, db, user = env
    user.user_type = UserType.ACCOUNT_USER
    db.commit()
    login(client)
    if operation == "disable":
        enroll(client)
    token = nextauth_identity(user)
    if operation == "reset":
        db.expire_all()
        locked = service.lock_user(db, db.get(User, user.id))
        service.revoke_all(db, locked)
        db.commit()
    else:
        assert client.post(f"/api/auth/mfa/{operation}", json={}).status_code == 200
    denied = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 401, denied.text
    assert denied.json()["detail"]["code"] == "primary_auth_required"
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code in (401, 403)
    fresh = nextauth_identity(user)
    reply = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {fresh}"})
    assert reply.status_code == 200, reply.text


def test_replit_primary_refresh_preserves_only_same_browser_recovery_grant(env):
    from datetime import timedelta
    from botelier.services import mfa_service as service
    client, db, user = env
    login(client)
    _, original = enroll(client)
    login(client)
    assert client.post("/api/auth/mfa/verify", json={"code": original["recovery_codes"][0]}).status_code == 200
    original_session = db.get(MFASession, service.digest(client.cookies.get(service.COOKIE_NAME)))
    original_session.primary_at = service.utcnow() - timedelta(minutes=6)
    expiry = original_session.expires_at
    db.commit()
    assert client.post("/api/auth/mfa/enroll", json={}).status_code == 403
    fresh = nextauth_identity(user)
    attacker = TestClient(client.app, headers={"X-MFA-CSRF": "1", "Origin": "http://testserver"})
    attacker.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {fresh}"})
    assert attacker.post("/api/auth/mfa/enroll", json={}).status_code == 403
    reply = client.post("/api/auth/mfa/bootstrap", headers={"Authorization": f"Bearer {fresh}"})
    assert reply.status_code == 200, reply.text
    db.expire_all()
    current = db.get(MFASession, service.digest(client.cookies.get(service.COOKIE_NAME)))
    assert current.recovery_grant is True
    assert current.expires_at == expiry
    assert db.get(MFASession, original_session.id).revoked is True
    enroll(client)


def test_legacy_logout_revokes_identity_and_expired_logout_clears_cookie(env):
    from datetime import timedelta
    from botelier.services import mfa_service as service
    client, db, user = env
    user.user_type = UserType.ACCOUNT_USER
    db.commit()
    legacy = create_jwt_token(user)
    assert client.get("/protected", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200
    assert client.post("/api/auth/mfa/logout", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200
    assert client.get("/protected", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401
    login(client)
    db.query(MFASession).update({"expires_at": service.utcnow() - timedelta(seconds=1)})
    db.commit()
    result = client.post("/api/auth/mfa/logout", json={})
    assert result.status_code == 200
    assert "Max-Age=0" in result.headers["set-cookie"]
    assert service.COOKIE_NAME not in client.cookies


def test_logout_does_not_hide_database_failure(env):
    client, _, _ = env
    login(client)

    def broken():
        raise RuntimeError("database unavailable")

    client.app.dependency_overrides[get_db] = broken
    failing = TestClient(client.app, raise_server_exceptions=False,
                         headers={"X-MFA-CSRF": "1", "Origin": "http://testserver"})
    assert failing.post("/api/auth/mfa/logout", json={}).status_code == 500


def test_user_limited_attempts_do_not_drain_shared_source(env):
    from botelier.services import mfa_service as service
    from fastapi import HTTPException
    _, db, user = env
    for _ in range(110):
        try:
            service.rate_limit(db, user.id, "shared-proxy", "quota-test")
        except HTTPException as exc:
            assert exc.status_code == 429
    row = db.get(MFARateLimit, service.digest("quota-test:source:shared-proxy"))
    assert row.attempts == 20
    service.rate_limit(db, uuid.uuid4(), "shared-proxy", "quota-test")


def test_internal_exchange_source_requires_token_bound_hmac():
    import os
    import hmac
    import hashlib
    from starlette.requests import Request
    from botelier.api.mfa import bootstrap_source
    token = "opaque-primary-token-for-protocol-test"
    marker = hmac.new(os.environ["NEXTAUTH_SECRET"].encode(),
                      ("botelier-mfa-exchange-v1\n" + token).encode(), hashlib.sha256).hexdigest()
    request = Request({"type": "http", "method": "POST", "path": "/", "client": ("proxy", 80),
                       "headers": [(b"x-botelier-auth-exchange", marker.encode()),
                                   (b"x-forwarded-for", b"untrusted-attacker-input")]})
    assert bootstrap_source(request, token, "user-a") != bootstrap_source(request, token, "user-b")
    assert bootstrap_source(request, "different-token", "user-a") == "proxy"


def test_admin_mutation_requires_a_fresh_verified_session(env):
    from datetime import timedelta
    from fastapi import HTTPException
    from botelier.services import mfa_service as service

    client, db, user = env
    target = User(id=uuid.uuid4(), email="target@example.com", user_type=UserType.ACCOUNT_USER)
    db.add(target)
    db.commit()
    with pytest.raises(HTTPException) as missing:
        service.lock_admin_mutation(db, db.get(User, user.id), target.id)
    assert missing.value.status_code == 403

    login(client)
    enroll(client)
    session_id = service.digest(client.cookies.get(service.COOKIE_NAME))
    actor = db.get(User, user.id)
    actor._mfa_session_id = session_id
    assert service.lock_admin_mutation(db, actor, target.id)[1].id == target.id

    session = db.get(MFASession, session_id)
    session.verified_at = service.utcnow() - timedelta(minutes=6)
    db.commit()
    db.expire_all()
    actor = db.get(User, user.id)
    actor._mfa_session_id = session_id
    with pytest.raises(HTTPException) as stale:
        service.lock_admin_mutation(db, actor, target.id)
    assert stale.value.status_code == 403


def test_mfa_secret_rotation_is_successful_or_fails_closed(monkeypatch):
    from datetime import datetime, timedelta
    from botelier.crypto import re_encrypt_all
    from botelier.models.integration import (
        AccountIntegration, AccountSecret, IntegrationType,
    )
    from botelier.models.mcp_connection import MCPConnection
    from botelier.models.property import Property

    old_key, new_key = Fernet.generate_key(), Fernet.generate_key()
    old_cipher, new_cipher = Fernet(old_key), Fernet(new_key)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    tables = [
        Account.__table__, Property.__table__, IntegrationType.__table__,
        AccountIntegration.__table__, AccountSecret.__table__, MCPConnection.__table__,
        User.__table__, MFASession.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    user = User(
        id=uuid.uuid4(), email="rotate@example.com", user_type=UserType.ACCOUNT_USER,
        mfa_secret_encrypted=old_cipher.encrypt(b"enrolled-secret").decode(),
    )
    pending = MFASession(
        id="pending-rotation-session", user_id=user.id, version=0,
        primary_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(minutes=5),
        pending_secret_encrypted=old_cipher.encrypt(b"pending-secret").decode(),
    )
    db.add_all([user, pending])
    db.commit()
    try:
        monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", f"{new_key.decode()},{old_key.decode()}")
        reset_cipher_cache()
        summary = re_encrypt_all(db)
        db.expire_all()
        stored_user = db.get(User, user.id)
        stored_pending = db.get(MFASession, pending.id)
        assert summary["UserMFA"] == summary["PendingMFA"] == 1
        assert new_cipher.decrypt(stored_user.mfa_secret_encrypted.encode()) == b"enrolled-secret"
        assert new_cipher.decrypt(stored_pending.pending_secret_encrypted.encode()) == b"pending-secret"

        stored_user.mfa_secret_encrypted = old_cipher.encrypt(b"unreadable-under-new-key").decode()
        stored_pending.pending_secret_encrypted = old_cipher.encrypt(b"also-unreadable").decode()
        db.commit()
        monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", new_key.decode())
        reset_cipher_cache()
        with pytest.raises(RuntimeError, match="MFA key rotation failed"):
            re_encrypt_all(db)
        db.expire_all()
        assert old_cipher.decrypt(db.get(User, user.id).mfa_secret_encrypted.encode()) == b"unreadable-under-new-key"
        assert old_cipher.decrypt(db.get(MFASession, pending.id).pending_secret_encrypted.encode()) == b"also-unreadable"

        # A pending factor can fail only after the enrolled factor was changed
        # earlier in the transaction. Neither change may survive that failure.
        stored_user = db.get(User, user.id)
        stored_pending = db.get(MFASession, pending.id)
        stored_user.mfa_secret_encrypted = new_cipher.encrypt(b"valid-enrolled-secret").decode()
        before = (stored_user.mfa_secret_encrypted, stored_pending.pending_secret_encrypted)
        db.commit()
        with pytest.raises(RuntimeError, match="MFA key rotation failed"):
            re_encrypt_all(db)
        db.expire_all()
        assert (
            db.get(User, user.id).mfa_secret_encrypted,
            db.get(MFASession, pending.id).pending_secret_encrypted,
        ) == before
    finally:
        db.close()
        engine.dispose()
        reset_cipher_cache()

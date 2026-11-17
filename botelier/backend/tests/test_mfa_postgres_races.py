"""PostgreSQL-only auth races on the auth_guard disposable fixture database."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Response
from sqlalchemy import inspect
from starlette.requests import Request

from botelier.api import mfa as api
from botelier.crypto import reset_cipher_cache
from botelier.database import Base, SessionLocal
from botelier.models.mfa import MFAAudit, MFARecoveryCode, MFARateLimit, MFASession
from botelier.models.user import User, UserType
from botelier.services import mfa_service as service

AUTH_TABLES = [
    User.__table__, MFASession.__table__, MFARecoveryCode.__table__,
    MFARateLimit.__table__, MFAAudit.__table__,
]


@pytest.fixture
def pg_env(monkeypatch):
    engine = SessionLocal.kw["bind"]
    db = SessionLocal()
    if db.bind.dialect.name != "postgresql":
        db.close()
        pytest.skip("Run auth_guard.py with --postgres to exercise fixture PostgreSQL row-lock races")
    existing = set(inspect(engine).get_table_names())
    created_tables = [table for table in AUTH_TABLES if table.name not in existing]
    Base.metadata.create_all(engine, tables=AUTH_TABLES)
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    reset_cipher_cache()
    ids = [uuid.uuid4(), uuid.uuid4()]
    source = f"mfa-test-{uuid.uuid4().hex}"
    secret = pyotp.random_base32()
    for user_id in ids:
        db.add(User(id=user_id, email=f"mfa-race-{user_id}@example.invalid",
                    user_type=UserType.PLATFORM_ADMIN, is_active=True, mfa_enabled=True,
                    mfa_secret_encrypted=service.secret_cipher().encrypt(secret.encode()).decode()))
    db.commit()

    def make_session(user_id=ids[0], verified=False):
        user = db.get(User, user_id)
        row, raw = service.new_session(db, user, primary_at=service.utcnow(),
                                      verified_at=service.utcnow() if verified else None)
        db.commit()
        return row.id, raw, service.token_for(user, row)

    def request(token=None):
        headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
        return Request({"type": "http", "method": "POST", "path": "/api/auth/mfa",
                        "headers": headers, "client": (source, 1234), "query_string": b""})
    try:
        yield db, ids, secret, make_session, request
    finally:
        db.rollback()
        for model in (MFAAudit, MFARecoveryCode, MFASession):
            db.query(model).filter(model.user_id.in_(ids)).delete(synchronize_session=False)
        for action in ("factor", "bootstrap", "primary"):
            keys = [service.digest(f"{action}:user:{u}") for u in ids]
            keys.append(service.digest(f"{action}:source:{source}"))
            db.query(MFARateLimit).filter(MFARateLimit.key.in_(keys)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
        if created_tables:
            Base.metadata.drop_all(engine, tables=created_tables)
        reset_cipher_cache()


def race_verify(session_ids, code, request):
    barrier = threading.Barrier(2)

    def attempt(session_id):
        db = SessionLocal()
        try:
            ctx = service.resolve_session(db, session_id)
            barrier.wait(timeout=10)
            api.verify(api.CodeBody(code=code), request(), Response(), ctx, db)
            return 200
        except HTTPException as exc:
            return exc.status_code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(attempt, session_ids))


def test_postgres_totp_can_only_be_consumed_once(pg_env):
    db, ids, secret, make_session, request = pg_env
    sessions = [make_session()[0], make_session()[0]]
    assert sorted(race_verify(sessions, pyotp.TOTP(secret).now(), request)) == [200, 400]
    db.expire_all()
    assert db.get(User, ids[0]).mfa_last_step is not None
    assert db.query(MFAAudit).filter(MFAAudit.user_id == ids[0], MFAAudit.event == "factor_verified").count() == 1


def test_postgres_recovery_code_has_one_session_bound_winner(pg_env):
    db, ids, _, make_session, request = pg_env
    codes = service.generate_recovery_codes(db, db.get(User, ids[0]))
    db.commit()
    sessions = [make_session()[0], make_session()[0]]
    results = race_verify(sessions, codes[0], request)
    assert results.count(200) == 1
    assert results.count(401) == 1
    assert db.query(MFASession).filter(
        MFASession.user_id == ids[0], MFASession.recovery_grant.is_(True),
        MFASession.revoked.is_(False),
    ).count() == 1


def test_postgres_bootstrap_cannot_resurrect_concurrent_logout(pg_env, monkeypatch):
    _, ids, _, make_session, request = pg_env
    session_id, _, token = make_session(verified=True)
    read_original = threading.Event()
    logout_done = threading.Event()
    original_lock = service.lock_user

    def delayed_lock(db, user):
        if threading.current_thread().name == "mfa-bootstrap-race":
            read_original.set()
            assert logout_done.wait(timeout=10)
        return original_lock(db, user)
    monkeypatch.setattr(service, "lock_user", delayed_lock)
    result = []

    def bootstrap():
        db = SessionLocal()
        try:
            api.bootstrap(request(token), Response(), db)
            result.append(200)
        except HTTPException as exc:
            result.append(exc.status_code)
        finally:
            db.close()

    worker = threading.Thread(target=bootstrap, name="mfa-bootstrap-race")
    worker.start()
    try:
        assert read_original.wait(timeout=10)
        db = SessionLocal()
        try:
            api.logout(request(token), Response(), db)
        finally:
            db.close()
    finally:
        logout_done.set()
        worker.join(timeout=15)
    assert not worker.is_alive()
    assert result == [401]


def test_postgres_stale_admin_context_cannot_promote_after_demotion(pg_env):
    db, ids, _, make_session, _ = pg_env
    session_id, _, _ = make_session(verified=True)
    stale_db = SessionLocal()
    try:
        actor = stale_db.get(User, ids[0])
        actor._mfa_session_id = session_id
        live_actor = service.lock_user(db, db.get(User, ids[0]))
        live_actor.user_type = UserType.ACCOUNT_USER
        service.revoke_all(db, live_actor)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            service.lock_admin_mutation(stale_db, actor, ids[1])
        assert exc.value.status_code == 403
        assert db.get(User, ids[1]).user_type == UserType.PLATFORM_ADMIN
    finally:
        stale_db.close()

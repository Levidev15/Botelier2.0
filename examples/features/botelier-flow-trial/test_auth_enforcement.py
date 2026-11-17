"""TDD smoke check for actual password-login/MFA protocol enforcement."""
import uuid

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

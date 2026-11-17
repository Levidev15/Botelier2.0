"""Authenticator enrollment, restricted challenge sessions and account policy."""
import base64
import io
import os
import time
import hashlib
import hmac
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from botelier.auth.middleware import decode_jwt_token, resolve_primary_identity
from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.mfa import MFARecoveryCode, MFASession
from botelier.models.role import AccountMembership
from botelier.models.user import User
from botelier.services import mfa_service as mfa

router = APIRouter(prefix="/api/auth/mfa", tags=["Security"])


def configured_origins():
    """Explicit browser origins, shared by CORS and cookie authentication."""
    allowed = set()
    for name in ("PUBLIC_BASE_URL", "FRONTEND_URL", "NEXTAUTH_URL"):
        value = os.environ.get(name, "").rstrip("/")
        if value:
            parsed = urlsplit(value)
            if parsed.scheme in ("http", "https") and parsed.netloc and "*" not in parsed.netloc:
                allowed.add(f"{parsed.scheme}://{parsed.netloc}")
    for domain in os.environ.get("REPLIT_DOMAINS", "").split(","):
        if domain.strip():
            allowed.add("https://" + domain.strip())
    domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
    if domain:
        allowed.add("https://" + domain)
    environment = (os.environ.get("BOTELIER_ENV") or os.environ.get("APP_ENV")
                   or os.environ.get("ENVIRONMENT") or "").lower()
    if environment not in ("production", "prod") and os.environ.get("REPLIT_DEPLOYMENT") != "1":
        allowed.update({"http://localhost:5000", "http://127.0.0.1:5000",
                        "http://localhost:3000", "http://127.0.0.1:3000"})
    return allowed


def validate_cookie_origin(request: Request, require_origin=False):
    origin = request.headers.get("origin", "").rstrip("/")
    allowed = configured_origins() | {str(request.base_url).rstrip("/")}
    if (require_origin and not origin) or (origin and origin not in allowed):
        mfa.error("csrf_origin", "Cross-origin security request rejected.")


def csrf(request: Request):
    if request.headers.get("X-MFA-CSRF") != "1":
        mfa.error("csrf_required", "Security request header missing.")
    validate_cookie_origin(request, require_origin=True)


def set_session_cookie(response: Response, request: Request, session, raw):
    secure = (request.url.scheme == "https"
              or os.environ.get("BOTELIER_ENV", "").lower() in ("production", "prod")
              or request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        mfa.COOKIE_NAME, raw, httponly=True, secure=secure, samesite="strict",
        path="/", max_age=max(0, int((session.expires_at - mfa.utcnow()).total_seconds())),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def context(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    # Security endpoints prefer the purpose-bound cookie. The general auth gate
    # deliberately prefers explicit bearer credentials instead.
    raw = request.cookies.get(mfa.COOKIE_NAME)
    if raw:
        validate_cookie_origin(request)
        return mfa.resolve_session(db, mfa.digest(raw))
    auth = request.headers.get("authorization", "")
    payload = decode_jwt_token(auth[7:]) if auth.startswith("Bearer ") else None
    if payload and payload.get("sid") and payload.get("purpose") == "botelier_session":
        return mfa.resolve_session(db, payload["sid"], payload.get("sub"))
    mfa.error("session_required", "Sign in again to manage security.", 401)


def source(request):
    return request.client.host if request.client else "unknown"


def bootstrap_source(request, token, subject):
    """Isolate server-to-server exchanges without trusting caller XFF values."""
    expected = hmac.new(
        os.environ["NEXTAUTH_SECRET"].encode(),
        ("botelier-mfa-exchange-v1\n" + token).encode(),
        hashlib.sha256,
    ).hexdigest()
    marker = request.headers.get("X-Botelier-Auth-Exchange", "")
    if marker and hmac.compare_digest(marker, expected):
        return f"internal-exchange:{subject}:{source(request)}"
    return source(request)


@router.post("/bootstrap", dependencies=[Depends(csrf)])
def bootstrap(request: Request, response: Response, db: Session = Depends(get_db)):
    auth = request.headers.get("authorization", "")
    payload = decode_jwt_token(auth[7:]) if auth.startswith("Bearer ") else None
    if not payload or not payload.get("sub"):
        mfa.error("invalid_identity", "Please sign in again.", 401)
    mfa.rate_limit(db, payload["sub"], bootstrap_source(request, auth[7:], payload["sub"]), "bootstrap")
    user = resolve_primary_identity(db, payload)
    if not user or not user.is_active:
        mfa.error("invalid_identity", "Please sign in again.", 401)
    if payload.get("sid"):
        # A revoked MFA token must never bootstrap a new first-factor session.
        _, original = mfa.resolve_session(db, payload["sid"], user.id)
        primary = original.primary_at
    else:
        try:
            # Only explicitly captured primary auth time is accepted, never iat:
            # NextAuth routinely reissues JWTs without authenticating the person.
            seconds = float(payload.get("auth_time", 0))
            primary = datetime.utcfromtimestamp(seconds)
            if seconds > time.time() + 30:
                raise ValueError()
        except (ValueError, TypeError, OverflowError, OSError):
            primary = datetime(1970, 1, 1)
    user = mfa.lock_user(db, user)
    if payload.get("sid"):
        # Recheck after locking the user: logout/reset may have happened while
        # this request waited for the lock. Expire identity-map state first.
        db.expire(original)
        _, original = mfa.resolve_session(db, payload["sid"], user.id)
        primary = original.primary_at
    else:
        mfa.enforce_primary_cutoff(user, payload)
    recovery_session = None
    incoming_cookie = request.cookies.get(mfa.COOKIE_NAME)
    if incoming_cookie and user.mfa_recovery_required:
        # The same-user, same-browser grant is reloaded under the user lock.
        # A fresh provider identity alone never confers enrollment authority.
        candidate = db.get(MFASession, mfa.digest(incoming_cookie), populate_existing=True)
        if (candidate and candidate.user_id == user.id and candidate.recovery_grant
                and not candidate.revoked and candidate.version == user.mfa_version
                and candidate.expires_at > mfa.utcnow()):
            recovery_session = candidate
    session, raw = mfa.new_session(
        db, user, primary_at=primary, force_restricted=not mfa.fresh(primary),
        recovery_grant=recovery_session is not None,
    )
    if recovery_session:
        session.expires_at = min(session.expires_at, recovery_session.expires_at)
        recovery_session.revoked = True
    mfa.audit(db, user, "bootstrap")
    db.commit()
    set_session_cookie(response, request, session, raw)
    return {**mfa.status_response(db, user, session), **mfa.auth_response(db, user, session)}


@router.get("/status")
def status(ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    return mfa.status_response(db, user, session)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/reauthenticate", dependencies=[Depends(csrf)])
def reauthenticate(body: PasswordBody, request: Request, response: Response,
                   ctx=Depends(context), db: Session = Depends(get_db)):
    from botelier.api.auth import verify_password
    user, session = ctx
    mfa.rate_limit(db, user.id, source(request), "primary")
    user, session = mfa.begin_attempt(db, user, session)
    if not user.password_hash:
        mfa.error("provider_reauthentication_required", "Sign in with Replit again, then return to Security.")
    if not verify_password(body.password, user.password_hash):
        mfa.failed_attempt(db, user, session)
    session.revoked = True
    new, raw = mfa.new_session(db, user, primary_at=mfa.utcnow(),
                              recovery_grant=session.recovery_grant)
    if session.recovery_grant:
        # Reauthentication must not extend the absolute recovery-grant window.
        new.expires_at = min(new.expires_at, session.expires_at)
    mfa.audit(db, user, "primary_verified")
    db.commit()
    set_session_cookie(response, request, new, raw)
    return {**mfa.status_response(db, user, new), **mfa.auth_response(db, user, new)}


@router.post("/enroll", dependencies=[Depends(csrf)])
def enroll(request: Request, ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    mfa.rate_limit(db, user.id, source(request))
    user, session = mfa.begin_attempt(db, user, session)
    mfa.require_recovery_grant(user, session)
    mfa.require_fresh(session, mfa=user.mfa_enabled and not user.mfa_recovery_required)
    secret = pyotp.random_base32()
    session.pending_secret_encrypted = mfa.secret_cipher().encrypt(secret.encode()).decode()
    session.pending_expires_at = mfa.utcnow() + timedelta(seconds=mfa.CHALLENGE_SECONDS)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Botelier")
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    mfa.audit(db, user, "enrollment_started")
    db.commit()
    return {"secret": secret, "provisioning_uri": uri,
            "qr_data_url": "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode()}


class CodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=128)


def complete_enrollment(db, user, session, code):
    mfa.require_recovery_grant(user, session)
    mfa.require_fresh(session, mfa=user.mfa_enabled and not user.mfa_recovery_required)
    if not session.pending_secret_encrypted or not session.pending_expires_at or session.pending_expires_at <= mfa.utcnow():
        mfa.error("enrollment_expired", "Start authenticator setup again.", 400)
    secret = mfa.secret_cipher().decrypt(session.pending_secret_encrypted.encode()).decode()
    step = mfa.matched_step(secret, code)
    if step is None:
        mfa.failed_attempt(db, user, session)
    user.mfa_secret_encrypted = session.pending_secret_encrypted
    user.mfa_enabled = True
    user.mfa_recovery_required = False
    user.mfa_last_step = step
    primary = session.primary_at
    mfa.revoke_all(db, user)
    codes = mfa.generate_recovery_codes(db, user)
    new, raw = mfa.new_session(db, user, primary_at=primary, verified_at=mfa.utcnow())
    mfa.audit(db, user, "enrollment_confirmed")
    db.commit()
    return new, raw, codes


@router.post("/confirm", dependencies=[Depends(csrf)])
def confirm(body: CodeBody, request: Request, response: Response,
            ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    mfa.rate_limit(db, user.id, source(request))
    user, session = mfa.begin_attempt(db, user, session)
    new, raw, codes = complete_enrollment(db, user, session, body.code.strip())
    set_session_cookie(response, request, new, raw)
    return {**mfa.auth_response(db, user, new), "recovery_codes": codes}


@router.post("/verify", dependencies=[Depends(csrf)])
def verify(body: CodeBody, request: Request, response: Response,
           ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    mfa.rate_limit(db, user.id, source(request))
    user, session = mfa.begin_attempt(db, user, session)
    mfa.require_fresh(session)
    code = body.code.strip()
    step = None
    if user.mfa_enabled and user.mfa_secret_encrypted and not user.mfa_recovery_required:
        secret = mfa.secret_cipher().decrypt(user.mfa_secret_encrypted.encode()).decode()
        step = mfa.matched_step(secret, code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        session.revoked = True
        new, raw = mfa.new_session(db, user, primary_at=session.primary_at, verified_at=mfa.utcnow())
        mfa.audit(db, user, "factor_verified")
    else:
        recovery = db.query(MFARecoveryCode).filter(
            MFARecoveryCode.code_hash == mfa.recovery_digest(user, code),
            MFARecoveryCode.user_id == user.id,
            MFARecoveryCode.consumed_at.is_(None),
        ).with_for_update().first()
        if not recovery or user.mfa_recovery_required:
            mfa.failed_attempt(db, user, session)
        recovery.consumed_at = mfa.utcnow()
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_last_step = None
        user.mfa_recovery_required = True
        primary = session.primary_at
        mfa.revoke_all(db, user)
        db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete(synchronize_session=False)
        new, raw = mfa.new_session(db, user, primary_at=primary, force_restricted=True, recovery_grant=True)
        mfa.audit(db, user, "recovery_used")
    db.commit()
    set_session_cookie(response, request, new, raw)
    return mfa.auth_response(db, user, new)


@router.post("/recovery-codes", dependencies=[Depends(csrf)])
def regenerate(request: Request, response: Response, ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    user, session = mfa.begin_attempt(db, user, session)
    mfa.require_fresh(session, mfa=True)
    if not user.mfa_enabled or user.mfa_recovery_required:
        mfa.error("enrollment_required", "Enroll an authenticator first.")
    primary, verified = session.primary_at, session.verified_at
    mfa.revoke_all(db, user)
    codes = mfa.generate_recovery_codes(db, user)
    new, raw = mfa.new_session(db, user, primary_at=primary, verified_at=verified)
    mfa.audit(db, user, "recovery_codes_regenerated")
    db.commit()
    set_session_cookie(response, request, new, raw)
    return {**mfa.auth_response(db, user, new), "recovery_codes": codes}


@router.post("/disable", dependencies=[Depends(csrf)])
def disable(request: Request, response: Response, ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    user, session = mfa.begin_attempt(db, user, session)
    mfa.require_fresh(session, mfa=True)
    if mfa.policy_required(db, user):
        mfa.error("policy_requires_mfa", "Your administrator requires MFA; it cannot be disabled.")
    primary = session.primary_at
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_last_step = None
    mfa.revoke_all(db, user)
    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete(synchronize_session=False)
    new, raw = mfa.new_session(db, user, primary_at=primary)
    mfa.audit(db, user, "mfa_disabled")
    db.commit()
    set_session_cookie(response, request, new, raw)
    return mfa.auth_response(db, user, new)


@router.post("/logout", dependencies=[Depends(csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Idempotent clearing is deliberately independent of the usual live-session
    # dependency: expired/revoked cookies must not strand the browser.
    raw = request.cookies.get(mfa.COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    payload = decode_jwt_token(auth[7:]) if auth.startswith("Bearer ") else None
    session_id = mfa.digest(raw) if raw else (payload.get("sid") if payload else None)
    session = db.get(MFASession, session_id) if session_id else None
    if not session and payload and payload.get("sid") and payload.get("purpose") == "botelier_session":
        session = db.get(MFASession, payload["sid"])
    user = db.get(User, session.user_id) if session else None
    if not user and payload and not payload.get("sid"):
        sub = payload.get("sub")
        from botelier.auth.middleware import is_valid_uuid
        import uuid
        if isinstance(sub, str):
            user = db.query(User).filter(
                User.id == uuid.UUID(sub) if is_valid_uuid(sub) else User.replit_id == sub
            ).first()
    if user:
        user = mfa.lock_user(db, user)
        live = False
        if session:
            session = db.get(MFASession, session.id, populate_existing=True)
            live = not session.revoked and session.expires_at > mfa.utcnow() and session.version == user.mfa_version
            if live:
                session.revoked = True
                session.pending_secret_encrypted = None
        elif payload:
            try:
                mfa.enforce_primary_cutoff(user, payload)
                live = True
            except HTTPException as exc:
                if exc.status_code != 401:
                    raise
        if live:
            user.primary_credentials_revoked_at = mfa.utcnow()
            mfa.audit(db, user, "logout")
        db.commit()
    response.delete_cookie(mfa.COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"success": True}


def policy_account(db, user, session, account_id, permission):
    mfa.enforce_payload(db, user, {"sid": session.id, "purpose": "botelier_session"})
    try:
        import uuid
        aid = uuid.UUID(account_id)
    except ValueError:
        mfa.error("invalid_account", "Invalid account ID.", 400)
    from botelier.auth.middleware import check_account_permission
    check_account_permission(user, aid, permission, db)
    account = db.get(Account, aid)
    if not account:
        mfa.error("account_not_found", "Account not found.", 404)
    return account


@router.get("/policy/{account_id}")
def get_policy(account_id: str, ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    account = policy_account(db, user, session, account_id, "settings.view")
    return {"require_mfa": account.require_mfa}


class PolicyBody(BaseModel):
    require_mfa: bool


@router.patch("/policy/{account_id}", dependencies=[Depends(csrf)])
def update_policy(account_id: str, body: PolicyBody, ctx=Depends(context), db: Session = Depends(get_db)):
    user, session = ctx
    user, session = mfa.begin_attempt(db, user, session)
    mfa.require_fresh(session, mfa=True)
    if not user.mfa_enabled or user.mfa_recovery_required:
        mfa.error("enrollment_required", "Enroll and verify MFA before changing policy.")
    account = policy_account(db, user, session, account_id, "settings.edit")
    account.require_mfa = body.require_mfa
    mfa.audit(db, user, "policy_enabled" if body.require_mfa else "policy_disabled", account.id)
    db.commit()
    return {"require_mfa": account.require_mfa}

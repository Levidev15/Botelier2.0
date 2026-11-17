"""Authentication assurance shared by REST, MFA and human-user event streams.

No process-local security state: sessions, attempts and replay guards survive
worker changes. User-row locks serialize factor and session mutations.
"""
import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from botelier.crypto import get_cipher
from botelier.models.account import Account
from botelier.models.mfa import MFAAudit, MFARecoveryCode, MFARateLimit, MFASession
from botelier.models.role import AccountMembership
from botelier.models.user import User

COOKIE_NAME = "botelier_mfa_session"
FRESH_SECONDS = 300
CHALLENGE_SECONDS = 600
SESSION_SECONDS = 86400
MAX_ATTEMPTS = 5


def error(code, message, status=403):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utcnow():
    return datetime.utcnow()


def secret_cipher():
    # A dev ephemeral key is acceptable for disposable integration demos, never MFA.
    if not (os.environ.get("INTEGRATION_ENCRYPTION_KEY", "").strip()
            or os.environ.get("AZURE_KEY_VAULT_URL", "").strip()):
        error("mfa_key_unavailable", "Persistent encryption key is required for MFA.", 503)
    return get_cipher()


def audit(db, user, event, account_id=None):
    db.add(MFAAudit(user_id=user.id, event=event, account_id=account_id))


def policy_required(db, user):
    if user.is_platform_admin or user.mfa_recovery_required is True:
        return True
    return db.query(AccountMembership.id).join(Account, AccountMembership.account_id == Account.id).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.is_active.is_(True),
        Account.require_mfa.is_(True),
    ).first() is not None


def needs_mfa(db, user):
    return user.mfa_enabled is True or policy_required(db, user)


def user_info(user):
    return {
        "id": str(user.id), "email": user.email,
        "first_name": user.first_name, "last_name": user.last_name,
        "display_name": user.display_name, "user_type": user.user_type.value,
        "profile_image_url": user.profile_image_url, "mfa_enabled": user.mfa_enabled is True,
    }


def fresh(value):
    return value is not None and 0 <= (utcnow() - value).total_seconds() <= FRESH_SECONDS


def require_fresh(session, mfa=False):
    if not fresh(session.primary_at):
        error("primary_auth_required", "Sign in again to confirm your identity.")
    if mfa and not fresh(session.verified_at):
        error("mfa_verification_required", "Verify a current authenticator code first.")


def lock_user(db, user):
    return db.query(User).filter(User.id == user.id).populate_existing().with_for_update().one()


def lock_admin_mutation(db, actor, target_id):
    """Serialize role changes with both actor revocation and target mutations."""
    sid = getattr(actor, "_mfa_session_id", None)
    if not sid:
        error("mfa_verification_required", "Verify MFA before changing administrators.")
    try:
        target_id = uuid.UUID(str(target_id))
    except ValueError:
        error("invalid_user", "Invalid user ID.", 400)
    actor_id = actor.id
    rows = db.query(User).filter(User.id.in_([actor_id, target_id])).order_by(User.id).populate_existing().with_for_update().all()
    users = {row.id: row for row in rows}
    actor = users.get(actor_id)
    target = users.get(target_id)
    if not actor or not actor.is_active or not actor.is_platform_admin:
        error("admin_required", "Platform administrator access required.")
    if not target:
        error("user_not_found", "User not found.", 404)
    cached = db.get(MFASession, sid)
    if cached:
        db.expire(cached)
    _, session = resolve_session(db, sid, actor_id)
    enforce_payload(db, actor, {"sid": sid, "purpose": "botelier_session"})
    require_fresh(session, mfa=True)
    return actor, target


def new_session(db, user, primary_at=None, verified_at=None, force_restricted=False, recovery_grant=False):
    now = utcnow()
    restricted = force_restricted or (needs_mfa(db, user) and verified_at is None)
    raw = secrets.token_urlsafe(32)
    row = MFASession(
        id=digest(raw), user_id=user.id, version=user.mfa_version or 0,
        primary_at=primary_at or datetime(1970, 1, 1),
        verified_at=verified_at, restricted=restricted, revoked=False,
        recovery_grant=recovery_grant,
        expires_at=now + timedelta(seconds=CHALLENGE_SECONDS if restricted else SESSION_SECONDS),
    )
    db.add(row)
    db.flush()
    return row, raw


def revoke_all(db, user):
    user.mfa_version = (user.mfa_version or 0) + 1
    user.primary_credentials_revoked_at = utcnow()
    db.query(MFASession).filter(MFASession.user_id == user.id).update(
        {"revoked": True, "pending_secret_encrypted": None}, synchronize_session=False)
    db.flush()


def token_for(user, session):
    now = utcnow()
    return jwt.encode({
        "sub": str(user.id), "email": user.email, "user_type": user.user_type.value,
        "sid": session.id, "auth_time": int(session.primary_at.replace(tzinfo=timezone.utc).timestamp()),
        "iat": now, "exp": session.expires_at,
        "purpose": "botelier_session",
    }, os.environ["NEXTAUTH_SECRET"], algorithm="HS256")


def auth_response(db, user, session):
    restricted = session.restricted or (needs_mfa(db, user) and session.verified_at is None)
    return {
        "access_token": None if restricted else token_for(user, session),
        "token_type": "bearer", "user": user_info(user),
        "mfa_required": restricted,
        "enrollment_required": restricted and (not user.mfa_enabled or user.mfa_recovery_required),
    }


def resolve_session(db, session_id, user_id=None):
    row = db.get(MFASession, session_id)
    if not row or row.revoked or row.expires_at <= utcnow():
        error("session_expired", "Session expired. Please sign in again.", 401)
    user = db.get(User, row.user_id)
    if not user or not user.is_active or row.version != user.mfa_version:
        error("session_revoked", "Session revoked. Please sign in again.", 401)
    if user_id is not None and str(user.id) != str(user_id):
        error("invalid_session", "Session identity mismatch.", 401)
    return user, row


def enforce_payload(db, user, payload):
    """Gate all existing bearer paths, including legacy JWT and NextAuth."""
    if payload.get("sid"):
        _, row = resolve_session(db, payload["sid"], user.id)
        if payload.get("purpose") != "botelier_session" or row.restricted:
            error("mfa_required", "Complete MFA before accessing the application.")
        if needs_mfa(db, user) and (not row.verified_at or not user.mfa_enabled or user.mfa_recovery_required):
            error("mfa_required", "Complete MFA before accessing the application.")
        user._mfa_session_id = row.id
        return row
    enforce_primary_cutoff(user, payload)
    # Changed factors revoke ALL legacy tokens. Legacy optional-MFA users keep
    # access until enrollment; mandatory/enrolled users must use the MFA flow.
    if needs_mfa(db, user) or (user.mfa_version or 0) != 0:
        error("mfa_required", "Complete MFA before accessing the application.")
    return None


def enforce_primary_cutoff(user, payload):
    """A rolling provider JWT must never resurrect a revoked primary login."""
    cutoff = user.primary_credentials_revoked_at
    if cutoff is None:
        return
    try:
        authenticated_at = datetime.utcfromtimestamp(float(payload["auth_time"]))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        error("primary_auth_required", "Sign in again; this primary credential was revoked.", 401)
    if authenticated_at <= cutoff or authenticated_at > utcnow() + timedelta(seconds=30):
        error("primary_auth_required", "Sign in again; this primary credential was revoked.", 401)


def full_cookie_user(db, raw):
    user, row = resolve_session(db, digest(raw))
    enforce_payload(db, user, {"sid": row.id, "purpose": "botelier_session"})
    return user


def rate_limit(db, user_id, source, action="factor"):
    """Atomic upsert + lock; limits are persisted even when verification fails.

    Source is request.client.host only: do not trust caller-supplied XFF.
    When behind an unconfigured proxy this deliberately limits the proxy as
    one source, rather than letting clients spoof their own rate-limit bucket.
    """
    now = utcnow()
    keys = [(f"{action}:user:{user_id}", 20), (f"{action}:source:{source}", 100)]
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    # Always charge the user first. Rejected user attempts must not exhaust the
    # shared source bucket and deny other users behind the same proxy.
    for raw, maximum in keys:
        key = digest(raw)
        db.execute(insert(MFARateLimit).values(key=key, window_started_at=now, attempts=0).on_conflict_do_nothing())
        row = db.execute(select(MFARateLimit).where(MFARateLimit.key == key).with_for_update()).scalar_one()
        if (now - row.window_started_at).total_seconds() >= 300:
            row.window_started_at = now
            row.attempts = 0
        row.attempts += 1
        if row.attempts > maximum:
            db.commit()
            error("rate_limited", "Too many attempts. Wait five minutes and try again.", 429)
    db.commit()


def begin_attempt(db, user, session):
    user = lock_user(db, user)
    # Locking the user serializes all challenge/factor mutations for them.
    session = db.query(MFASession).filter(MFASession.id == session.id).populate_existing().one()
    if session.revoked or session.version != user.mfa_version or session.expires_at <= utcnow():
        error("session_expired", "Session expired. Please sign in again.", 401)
    if session.attempts >= MAX_ATTEMPTS:
        error("challenge_exhausted", "Too many attempts. Sign in again.", 429)
    return user, session


def require_recovery_grant(user, session):
    if user.mfa_recovery_required and not session.recovery_grant:
        error("recovery_session_required", "Continue in the browser where you used your recovery code, or contact your security operator.")


def failed_attempt(db, user, session):
    session.attempts += 1
    audit(db, user, "factor_failed")
    db.commit()
    error("invalid_code", "Invalid, expired, or previously used code.", 400)


def matched_step(secret, code, last_step=None):
    if not code.isascii() or len(code) != 6 or not code.isdigit():
        return None
    current = int(time.time() // 30)
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    for step in (current, current - 1, current + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(totp.at(step * 30), code):
            return step
    return None


def recovery_digest(user, code):
    normalized = code.strip().replace("-", "").upper()
    return digest(f"{user.id}:{normalized}")


def generate_recovery_codes(db, user):
    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete(synchronize_session=False)
    codes = []
    for _ in range(10):
        raw = secrets.token_hex(10).upper()
        code = "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))
        codes.append(code)
        db.add(MFARecoveryCode(user_id=user.id, code_hash=recovery_digest(user, code)))
    db.flush()
    return codes


def status_response(db, user, session):
    required = policy_required(db, user)
    need = session.restricted or ((user.mfa_enabled or required) and not session.verified_at)
    return {
        "user": user_info(user), "mfa_enabled": user.mfa_enabled,
        "mfa_required": bool(need), "policy_required": required,
        "enrollment_required": bool(need and (not user.mfa_enabled or user.mfa_recovery_required)),
        "primary_fresh": fresh(session.primary_at), "mfa_fresh": fresh(session.verified_at),
        # One-way row identifier, not a credential. Allows a dual-approved
        # operator to bind total-loss recovery to this exact browser session.
        "recovery_session_reference": session.id if user.mfa_recovery_required and session.restricted else None,
        "recovery_codes_remaining": db.query(MFARecoveryCode).filter(
            MFARecoveryCode.user_id == user.id, MFARecoveryCode.consumed_at.is_(None)).count(),
    }

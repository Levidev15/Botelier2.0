"""Authentication Middleware for FastAPI.

Validates JWT tokens from NextAuth and provides current user context.
"""

import base64
import hashlib
import json
import os
from datetime import datetime
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.role import AccountMembership
from botelier.models.user import SupportSession, User, UserType

security = HTTPBearer(auto_error=False)

NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "")
if not NEXTAUTH_SECRET:
    raise RuntimeError(
        "NEXTAUTH_SECRET environment variable is not set. "
        "Authentication cannot function without a configured secret."
    )


def derive_encryption_key(secret: str) -> bytes:
    """Derive encryption key matching NextAuth's key derivation."""
    salt = b""
    info = b"NextAuth.js Generated Encryption Key"

    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=info, backend=default_backend()
    )
    return hkdf.derive(secret.encode())


def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode a JWT token.

    Supports:
    1. Plain HS256 tokens (from email/password auth)
    2. NextAuth signed (JWS) tokens
    3. NextAuth encrypted (JWE) tokens

    Only tokens signed with the configured NEXTAUTH_SECRET are accepted.
    """
    for secret in [NEXTAUTH_SECRET]:
        try:
            payload = jwt.decode(
                token, secret, algorithms=["HS256"],
                options={"verify_aud": False, "require_exp": True},
            )
            return payload
        except JWTError:
            continue

    # Try JWE decryption with current secret
    try:
        from jose import jwe

        key = derive_encryption_key(NEXTAUTH_SECRET)
        decrypted = jwe.decrypt(token, key)
        payload = json.loads(decrypted)
        import time
        if not isinstance(payload, dict) or not isinstance(payload.get("exp"), (int, float)):
            return None
        if payload["exp"] <= time.time():
            return None
        return payload
    except Exception:
        pass

    return None


def decode_nextauth_token(token: str) -> Optional[dict]:
    """Alias for backward compatibility."""
    return decode_jwt_token(token)


def is_valid_uuid(val: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        import uuid

        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False


def resolve_primary_identity(db: Session, payload: dict) -> Optional[User]:
    """Resolve a verified identity without linking by email or granting access."""
    from botelier.models.user import AuthProvider
    import uuid

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        return None
    if is_valid_uuid(sub):
        return db.query(User).filter(User.id == uuid.UUID(sub)).first()
    user = db.query(User).filter(User.replit_id == sub).first()
    if not user:
        email = payload.get("email") or f"{sub}@replit.user"
        if db.query(User.id).filter(User.email == email).first():
            raise HTTPException(
                status_code=409,
                detail="An account already uses this email. Sign in using its existing method.",
            )
        parts = (payload.get("name") or "").split()
        user = User(
            replit_id=sub, email=email,
            first_name=payload.get("first_name") or (parts[0] if parts else None),
            last_name=payload.get("last_name") or (" ".join(parts[1:]) if len(parts) > 1 else None),
            profile_image_url=payload.get("picture") or payload.get("image"),
            auth_provider=AuthProvider.REPLIT, user_type=UserType.ACCOUNT_USER,
            last_login_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()
        user._primary_identity_created = True
    return user


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Get current user from JWT token (optional - returns None if not authenticated).

    Supports both:
    - Email/password JWT tokens (sub = user UUID)
    - NextAuth tokens (sub = Replit ID)
    """
    from botelier.services import mfa_service as mfa
    if not credentials:
        raw = request.cookies.get(mfa.COOKIE_NAME)
        if raw:
            from botelier.api.mfa import validate_cookie_origin
            validate_cookie_origin(request)
        if raw and request.method not in ("GET", "HEAD", "OPTIONS"):
            from botelier.api.mfa import csrf
            csrf(request)
        return mfa.full_cookie_user(db, raw) if raw else None

    token = credentials.credentials
    payload = decode_nextauth_token(token)

    if not payload:
        return None

    if not payload.get("sub"):
        return None

    _LOGIN_COOLDOWN_SECONDS = 300
    user = resolve_primary_identity(db, payload)
    if not user:
        return None
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    mfa.enforce_payload(db, user, payload)
    now = datetime.utcnow()
    needs_commit = getattr(user, "_primary_identity_created", False)
    if user.last_login_at is None or (now - user.last_login_at).total_seconds() > _LOGIN_COOLDOWN_SECONDS:
        user.last_login_at = now
        needs_commit = True
    if not is_valid_uuid(payload["sub"]):
        new_pic = payload.get("picture") or payload.get("image")
        if new_pic and user.profile_image_url != new_pic:
            user.profile_image_url = new_pic
            needs_commit = True
    if needs_commit:
        db.commit()

    return user


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Get current user from JWT token (required - raises 401 if not authenticated)."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


async def get_platform_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Get current user and verify they are a platform admin."""
    if user.user_type != UserType.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user


def validate_support_session(
    session_token: str,
    account_id: str,
    db: Session,
) -> Optional[SupportSession]:
    """Validate a support session token.

    Returns the SupportSession if valid, None otherwise.
    """
    support_session = (
        db.query(SupportSession)
        .filter(
            SupportSession.session_token == session_token,
            SupportSession.account_id == account_id,
            SupportSession.is_active == True,
        )
        .first()
    )

    if support_session and support_session.is_valid:
        print(
            f"[AUDIT] Support session used: admin_id={support_session.admin_id}, account_id={account_id}"
        )
        return support_session

    return None


class AccountContext:
    """Context object containing user and their account membership."""

    def __init__(
        self,
        user: User,
        account: Account,
        membership: Optional[AccountMembership] = None,
    ):
        self.user = user
        self.account = account
        self.membership = membership

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission in this account."""
        if self.user.is_platform_admin:
            return True

        if self.membership:
            return self.membership.has_permission(permission)

        return False

    def require_permission(self, permission: str):
        """Raise 403 if user doesn't have the permission."""
        if not self.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )


def get_account_context(account_id_param: str = "account_id"):
    """Factory function to create account context dependency.

    Usage:
        @router.get("/accounts/{account_id}/assistants")
        async def list_assistants(
            ctx: AccountContext = Depends(get_account_context("account_id")),
        ):
            ctx.require_permission("assistants.view")
            ...
    """

    async def _get_account_context(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AccountContext:
        account_id = request.path_params.get(account_id_param)

        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account ID is required",
            )

        account = db.query(Account).filter(Account.id == account_id).first()

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if user.is_platform_admin:
            return AccountContext(user=user, account=account)

        membership = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == user.id,
                AccountMembership.account_id == account.id,
                AccountMembership.is_active == True,
            )
            .first()
        )

        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this account",
            )

        return AccountContext(user=user, account=account, membership=membership)

    return _get_account_context


async def get_account_from_support_session(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Account]:
    """Get account from support session headers if present.

    Checks X-Support-Session and X-Account-Id headers.
    Returns the account if the support session is valid, None otherwise.
    """
    session_token = request.headers.get("X-Support-Session")
    account_id = request.headers.get("X-Account-Id")

    if not session_token or not account_id:
        return None

    if not user.is_platform_admin:
        return None

    support_session = validate_support_session(session_token, account_id, db)

    if not support_session:
        return None

    account = db.query(Account).filter(Account.id == account_id).first()
    return account


def check_account_permission(
    user: User,
    account_id: str,
    permission: str,
    db: Session,
) -> None:
    """Verify the user has the given permission for the specified account.
    Platform admins bypass all checks.
    Raises HTTP 403 if access is denied.
    """
    if user.is_platform_admin:
        return

    membership = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.user_id == user.id,
            AccountMembership.account_id == account_id,
            AccountMembership.is_active == True,
        )
        .first()
    )

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this account",
        )

    if not membership.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {permission}",
        )


def get_hotel_context(permission: str):
    """Reusable FastAPI dependency factory for query-param scoped account endpoints.

    Accepts ``account_id`` from the query string (``hotel_id`` is accepted as a
    deprecated alias for backward compatibility), validates the UUID, loads the
    membership, performs a permission check, and returns a fully-populated
    ``AccountContext`` with platform-admin bypass support.

    Usage::

        @router.get("/my-resource")
        async def my_endpoint(
            ctx: AccountContext = Depends(get_hotel_context("resource.view")),
        ):
            ctx.require_permission("resource.edit")  # optional extra check
            account_id = str(ctx.account.id)
            ...
    """
    from typing import Optional as _Optional
    from uuid import UUID as _UUID

    from fastapi import Query as _Query

    async def _dependency(
        account_id: _Optional[str] = _Query(None, description="Account UUID"),
        hotel_id: _Optional[str] = _Query(
            None,
            description="Deprecated: use account_id instead. Will be removed in a future release.",
        ),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AccountContext:
        raw_id = account_id or hotel_id
        if not raw_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id is required",
            )
        try:
            _UUID(raw_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account_id — must be a valid UUID",
            )

        account = db.query(Account).filter(Account.id == raw_id).first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if user.is_platform_admin:
            return AccountContext(user=user, account=account)

        membership = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == user.id,
                AccountMembership.account_id == account.id,
                AccountMembership.is_active == True,
            )
            .first()
        )

        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this account",
            )

        if permission and not membership.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )

        return AccountContext(user=user, account=account, membership=membership)

    return _dependency


async def get_current_account_id(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[str]:
    """Get the current account ID from support session headers or user's default account.

    Priority:
    1. Support session headers (X-Support-Session + X-Account-Id)
    2. User's first account membership
    """
    session_token = request.headers.get("X-Support-Session")
    account_id = request.headers.get("X-Account-Id")

    if session_token and account_id and user.is_platform_admin:
        support_session = validate_support_session(session_token, account_id, db)
        if support_session:
            return account_id

    if user.account_memberships:
        first_membership = next((m for m in user.account_memberships if m.is_active), None)
        if first_membership:
            return str(first_membership.account_id)

    return None

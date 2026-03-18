"""
Authentication Middleware for FastAPI.

Validates JWT tokens from NextAuth and provides current user context.
"""

import os
import json
import base64
import hashlib
from typing import Optional, Annotated
from datetime import datetime

from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from botelier.database import get_db
from botelier.models.user import User, UserType, SupportSession
from botelier.models.account import Account
from botelier.models.role import AccountMembership

security = HTTPBearer(auto_error=False)

NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "")


def derive_encryption_key(secret: str) -> bytes:
    """Derive encryption key matching NextAuth's key derivation."""
    salt = b"NextAuth.js Generated Encryption Key"
    info = b""
    
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.backends import default_backend
    
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
        backend=default_backend()
    )
    return hkdf.derive(secret.encode())


def decode_jwt_token(token: str) -> Optional[dict]:
    """
    Decode a JWT token.
    
    Supports:
    1. Plain HS256 tokens (from email/password auth)
    2. NextAuth signed (JWS) tokens
    3. NextAuth encrypted (JWE) tokens
    
    Tries all known secrets so tokens issued before/after secret rotation still work.
    """
    # Build list of secrets to try (current env secret + fallback default)
    secrets_to_try = []
    if NEXTAUTH_SECRET:
        secrets_to_try.append(NEXTAUTH_SECRET)
    fallback = "botelier-secret-key"
    if fallback not in secrets_to_try:
        secrets_to_try.append(fallback)

    for secret in secrets_to_try:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                options={"verify_aud": False}
            )
            return payload
        except JWTError:
            continue

    # Try JWE decryption with current secret
    if NEXTAUTH_SECRET:
        try:
            from jose import jwe
            key = derive_encryption_key(NEXTAUTH_SECRET)
            decrypted = jwe.decrypt(token, key)
            return json.loads(decrypted)
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


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Get current user from JWT token (optional - returns None if not authenticated).
    
    Supports both:
    - Email/password JWT tokens (sub = user UUID)
    - NextAuth tokens (sub = Replit ID)
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = decode_nextauth_token(token)
    
    if not payload:
        return None
    
    sub = payload.get("sub")
    if not sub:
        return None
    
    if is_valid_uuid(sub):
        user = db.query(User).filter(User.id == sub).first()
        
        if user:
            user.last_login_at = datetime.utcnow()
            db.commit()
        
        return user
    
    user = db.query(User).filter(User.replit_id == sub).first()
    
    if not user:
        email = payload.get("email")
        if email:
            user = db.query(User).filter(User.email == email).first()
        
        if not user:
            from botelier.models.user import AuthProvider
            user = User(
                replit_id=sub,
                email=payload.get("email") or f"{sub}@replit.user",
                first_name=payload.get("first_name") or payload.get("name", "").split()[0] if payload.get("name") else None,
                last_name=payload.get("last_name") or " ".join(payload.get("name", "").split()[1:]) if payload.get("name") else None,
                profile_image_url=payload.get("picture") or payload.get("image"),
                auth_provider=AuthProvider.REPLIT,
                user_type=UserType.ACCOUNT_USER,
                last_login_at=datetime.utcnow(),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            if not user.replit_id:
                user.replit_id = sub
            user.last_login_at = datetime.utcnow()
            if payload.get("picture") or payload.get("image"):
                user.profile_image_url = payload.get("picture") or payload.get("image")
            db.commit()
    else:
        user.last_login_at = datetime.utcnow()
        if payload.get("email") and user.email != payload.get("email"):
            pass
        if payload.get("picture") or payload.get("image"):
            user.profile_image_url = payload.get("picture") or payload.get("image")
        db.commit()
    
    return user


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """
    Get current user from JWT token (required - raises 401 if not authenticated).
    """
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
    """
    Get current user and verify they are a platform admin.
    """
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
    """
    Validate a support session token.
    
    Returns the SupportSession if valid, None otherwise.
    """
    support_session = db.query(SupportSession).filter(
        SupportSession.session_token == session_token,
        SupportSession.account_id == account_id,
        SupportSession.is_active == True,
    ).first()
    
    if support_session and support_session.is_valid:
        print(f"[AUDIT] Support session used: admin_id={support_session.admin_id}, account_id={account_id}")
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
    """
    Factory function to create account context dependency.
    
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
        
        membership = db.query(AccountMembership).filter(
            AccountMembership.user_id == user.id,
            AccountMembership.account_id == account.id,
            AccountMembership.is_active == True,
        ).first()
        
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
    """
    Get account from support session headers if present.
    
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
    """
    Verify the user has the given permission for the specified account.
    Platform admins bypass all checks.
    Raises HTTP 403 if access is denied.
    """
    if user.is_platform_admin:
        return

    membership = db.query(AccountMembership).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.account_id == account_id,
        AccountMembership.is_active == True,
    ).first()

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
    """
    Reusable FastAPI dependency factory for query-param scoped hotel endpoints.

    Reads `hotel_id` from the query string, verifies the user is authenticated
    and holds the given permission for that account, then returns the hotel_id
    as a plain string.

    Usage::

        @router.get("/my-resource")
        async def my_endpoint(
            hotel_id: str = Depends(get_hotel_context("resource.view")),
        ):
            ...
    """
    from uuid import UUID as _UUID
    from fastapi import Query as _Query

    async def _dependency(
        hotel_id: str = _Query(..., description="Hotel/account ID for multi-tenant isolation"),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> str:
        try:
            _UUID(hotel_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid hotel_id — must be a valid UUID",
            )
        check_account_permission(user, hotel_id, permission, db)
        return hotel_id

    return _dependency


async def get_current_account_id(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[str]:
    """
    Get the current account ID from support session headers or user's default account.
    
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
        first_membership = next(
            (m for m in user.account_memberships if m.is_active),
            None
        )
        if first_membership:
            return str(first_membership.account_id)
    
    return None

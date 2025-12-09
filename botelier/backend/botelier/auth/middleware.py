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
from botelier.models.user import User, UserType
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


def decode_nextauth_token(token: str) -> Optional[dict]:
    """
    Decode a NextAuth JWT token.
    
    NextAuth can use either signed (JWS) or encrypted (JWE) tokens.
    This handles both cases.
    """
    if not NEXTAUTH_SECRET:
        return None
    
    try:
        payload = jwt.decode(
            token,
            NEXTAUTH_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return payload
    except JWTError:
        try:
            from jose import jwe
            key = derive_encryption_key(NEXTAUTH_SECRET)
            decrypted = jwe.decrypt(token, key)
            return json.loads(decrypted)
        except Exception:
            return None


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Get current user from JWT token (optional - returns None if not authenticated).
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = decode_nextauth_token(token)
    
    if not payload:
        return None
    
    replit_id = payload.get("sub")
    if not replit_id:
        return None
    
    user = db.query(User).filter(User.replit_id == replit_id).first()
    
    if not user:
        user = User(
            replit_id=replit_id,
            email=payload.get("email"),
            first_name=payload.get("first_name") or payload.get("name", "").split()[0] if payload.get("name") else None,
            last_name=payload.get("last_name") or " ".join(payload.get("name", "").split()[1:]) if payload.get("name") else None,
            profile_image_url=payload.get("picture") or payload.get("image"),
            user_type=UserType.ACCOUNT_USER,
            last_login_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.last_login_at = datetime.utcnow()
        if payload.get("email"):
            user.email = payload.get("email")
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

"""
Account Secrets API — encrypted key-value store for sensitive credentials.

Secrets are stored Fernet-encrypted and referenced in flow/tool configs as
{{secrets.key_name}}. Secret VALUES are never returned by any endpoint.

All routes are scoped under /api/secrets/account/{account_id} so that the
caller's account is explicit and validated against current_user memberships,
preventing cross-account access for users who belong to multiple accounts.
"""

import re
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.integration import AccountSecret
from botelier.auth.middleware import get_current_user


router = APIRouter(prefix="/api/secrets", tags=["secrets"])

_KEY_RE = re.compile(r"^[a-z0-9_]{1,100}$")


def _assert_account_access(current_user, account_id: str) -> None:
    """
    Raise 403 if the authenticated user does not have an active membership
    for the requested account_id.  Platform admins bypass this check.
    """
    if getattr(current_user, "user_type", None) == "platform_admin":
        return
    memberships = getattr(current_user, "account_memberships", None) or []
    allowed = {str(getattr(m, "account_id", "")) for m in memberships if getattr(m, "is_active", False)}
    if account_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this account",
        )


class SecretMetadata(BaseModel):
    id: str
    name: str
    key: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreateSecretRequest(BaseModel):
    name: str
    key: str
    value: str
    description: Optional[str] = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not _KEY_RE.match(v):
            raise ValueError("Secret key must be lowercase letters, digits, and underscores only (max 100 chars)")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Secret name cannot be empty")
        return v

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str) -> str:
        if not v:
            raise ValueError("Secret value cannot be empty")
        return v


class UpdateSecretRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None


@router.get("/account/{account_id}", response_model=List[SecretMetadata])
async def list_secrets(
    account_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id)
    secrets = (
        db.query(AccountSecret)
        .filter(AccountSecret.account_id == account_id)
        .order_by(AccountSecret.created_at.asc())
        .all()
    )
    return [
        SecretMetadata(
            id=str(s.id),
            name=s.name,
            key=s.key,
            description=s.description,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in secrets
    ]


@router.post("/account/{account_id}", response_model=SecretMetadata, status_code=201)
async def create_secret(
    account_id: str,
    body: CreateSecretRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id)

    existing = (
        db.query(AccountSecret)
        .filter(AccountSecret.account_id == account_id, AccountSecret.key == body.key)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A secret with key '{body.key}' already exists for this account",
        )

    secret = AccountSecret(
        account_id=account_id,
        name=body.name,
        key=body.key,
        description=body.description,
        value_encrypted="",
    )
    secret.set_value(body.value)
    db.add(secret)
    db.commit()
    db.refresh(secret)

    logger.info(f"Created secret '{body.key}' for account {account_id}")

    return SecretMetadata(
        id=str(secret.id),
        name=secret.name,
        key=secret.key,
        description=secret.description,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.patch("/account/{account_id}/{secret_id}", response_model=SecretMetadata)
async def update_secret(
    account_id: str,
    secret_id: str,
    body: UpdateSecretRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id)

    secret = (
        db.query(AccountSecret)
        .filter(AccountSecret.id == secret_id, AccountSecret.account_id == account_id)
        .first()
    )
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    if body.name is not None:
        secret.name = body.name.strip()
    if body.description is not None:
        secret.description = body.description
    if body.value is not None and body.value.strip():
        secret.set_value(body.value)

    db.commit()
    db.refresh(secret)

    logger.info(f"Updated secret '{secret.key}' for account {account_id}")

    return SecretMetadata(
        id=str(secret.id),
        name=secret.name,
        key=secret.key,
        description=secret.description,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.delete("/account/{account_id}/{secret_id}", status_code=204)
async def delete_secret(
    account_id: str,
    secret_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id)

    secret = (
        db.query(AccountSecret)
        .filter(AccountSecret.id == secret_id, AccountSecret.account_id == account_id)
        .first()
    )
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    key = secret.key
    db.delete(secret)
    db.commit()

    logger.info(f"Deleted secret '{key}' for account {account_id}")

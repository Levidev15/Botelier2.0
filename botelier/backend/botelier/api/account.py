"""Account-Level Client API Endpoints.

Authenticated endpoints for account members (not platform-admin-only).
These are scoped to a single account and require the caller to be
an active member or a platform admin.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from botelier.api.assistants import _validate_iana_timezone
from botelier.auth.features import get_account_features
from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.role import AccountMembership
from botelier.models.user import User

router = APIRouter(prefix="/api/account", tags=["Account"])


class AccountBasicInfoResponse(BaseModel):
    id: str
    name: str
    business_type: Optional[str] = None
    email: str
    phone: Optional[str] = None
    timezone: str

    class Config:
        from_attributes = True


class AccountBasicInfoUpdate(BaseModel):
    # "name" doubles as the business/company name shown to callers and on
    # SMS ({account_name} template variable) — not limited to hotels.
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    business_type: Optional[str] = Field(None, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    timezone: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip() if v else v

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v):
        return _validate_iana_timezone(v) if v is not None else v


def _to_basic_info_response(account: Account) -> AccountBasicInfoResponse:
    return AccountBasicInfoResponse(
        id=str(account.id),
        name=account.name,
        business_type=account.business_type,
        email=account.email,
        phone=account.phone,
        timezone=account.timezone or "UTC",
    )


@router.get("/features")
async def get_account_features_client(
    account_id: str = Query(..., description="Account ID to retrieve features for"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the resolved feature map for an account.

    Platform admins may query any account.  Regular users must be an active
    member of the requested account.

    Response: ``{"call_recording": true, "qa_scoring": false, ...}``
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not user.is_platform_admin:
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
                status_code=403,
                detail="You don't have access to this account",
            )

    return get_account_features(
        subscription_tier=account.subscription_tier.value,
        feature_flags_override=account.feature_flags or {},
    )


@router.get("/basic-info", response_model=AccountBasicInfoResponse)
async def get_account_basic_info(
    account_id: str = Query(..., description="Account ID to retrieve basic info for"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the account's basic profile: business name, type, contact info, timezone.

    The "name" field is a generic business/company name (not limited to
    hotels) — it's what callers hear referenced and what SMS templates
    interpolate via {account_name}. "timezone" is the account-wide IANA
    timezone, used as the default for newly created assistants.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    check_account_permission(user, account_id, "settings.view", db)

    return _to_basic_info_response(account)


@router.patch("/basic-info", response_model=AccountBasicInfoResponse)
async def update_account_basic_info(
    data: AccountBasicInfoUpdate,
    account_id: str = Query(..., description="Account ID to update basic info for"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the account's basic profile (business name, type, contact, timezone)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    check_account_permission(user, account_id, "settings.edit", db)

    if data.name is not None:
        account.name = data.name
    if data.business_type is not None:
        account.business_type = data.business_type
    if data.email is not None:
        account.email = data.email
    if data.phone is not None:
        account.phone = data.phone
    if data.timezone is not None:
        account.timezone = data.timezone

    db.commit()
    db.refresh(account)

    return _to_basic_info_response(account)

"""
Account-Level Client API Endpoints.

Authenticated endpoints for account members (not platform-admin-only).
These are scoped to a single account and require the caller to be
an active member or a platform admin.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.role import AccountMembership
from botelier.models.user import User
from botelier.auth.middleware import get_current_user
from botelier.auth.features import get_account_features


router = APIRouter(prefix="/api/account", tags=["Account"])


@router.get("/features")
async def get_account_features_client(
    account_id: str = Query(..., description="Account ID to retrieve features for"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the resolved feature map for an account.

    Platform admins may query any account.  Regular users must be an active
    member of the requested account.

    Response: ``{"call_recording": true, "qa_scoring": false, ...}``
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not user.is_platform_admin:
        membership = db.query(AccountMembership).filter(
            AccountMembership.user_id == user.id,
            AccountMembership.account_id == account_id,
            AccountMembership.is_active == True,
        ).first()
        if not membership:
            raise HTTPException(
                status_code=403,
                detail="You don't have access to this account",
            )

    return get_account_features(
        subscription_tier=account.subscription_tier.value,
        feature_flags_override=account.feature_flags or {},
    )

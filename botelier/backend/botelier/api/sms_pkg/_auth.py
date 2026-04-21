"""
Shared authentication / tenant-isolation helpers for the SMS package.

Task #137 — every SMS endpoint must:
  1. Require a valid JWT (HTTPBearer via `get_current_user`).
  2. Verify the authenticated user is either a platform admin or has an
     active membership in the `account_id` they claim in the request.

Granular SMS-level RBAC permissions (e.g. "messages.view",
"messages.reply") are intentionally NOT introduced here — they would
expand the permission catalog and require a coordinated role-template
migration. The security task is scoped to closing the
"any caller can pass any account_id" hole, which a membership check
fully resolves. Granular SMS permissions can be layered on later by
swapping `assert_sms_account_access` for a permission-aware helper
without touching call sites.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from botelier.auth.middleware import get_current_user
from botelier.database import get_db
from botelier.models.role import AccountMembership
from botelier.models.user import User


def assert_sms_account_access(
    user: User,
    account_id: str,
    db: Session,
) -> None:
    """
    Raise 403 unless `user` is a platform admin or has an active
    membership in `account_id`. Raise 400 if account_id is not a UUID.
    """
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account_id is required",
        )

    try:
        UUID(str(account_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account_id — must be a valid UUID",
        )

    if user.is_platform_admin:
        return

    membership = db.query(AccountMembership).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.account_id == account_id,
        AccountMembership.is_active == True,  # noqa: E712
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this account",
        )


def require_sms_query_account():
    """
    FastAPI dependency: authenticates the caller, asserts they have
    access to the `account_id` query parameter, and returns it as a
    string. Use this for GET routes that accept `?account_id=...`.

    Usage:
        @router.get("/templates")
        async def list_templates(
            account_id: str = Depends(require_sms_query_account()),
            db: Session = Depends(get_db),
        ):
            ...
    """

    async def _dep(
        account_id: Optional[str] = Query(
            None, description="Account ID for multi-tenant isolation"
        ),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> str:
        assert_sms_account_access(user, account_id or "", db)
        return account_id  # type: ignore[return-value]

    return _dep

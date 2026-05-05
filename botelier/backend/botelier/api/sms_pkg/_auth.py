"""Shared authentication / tenant-isolation helpers for the SMS package.

Every SMS endpoint must:
  1. Require a valid JWT (HTTPBearer via `get_current_user`).
  2. Verify the authenticated user is either a platform admin or has an
     active membership in the `account_id` they claim in the request.
  3. Verify the caller's role grants the required `messages.*` permission.

Read-only endpoints call `assert_sms_account_access` (checks `messages.view`).
Mutating endpoints call `assert_sms_permission` with the specific permission:
  - `messages.manage_conversations` — take-over, return-to-ai, close
  - `messages.reply`               — reply, upload (MMS attachment)
  - `messages.manage_settings`     — template CRUD, notification settings
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.user import User


def _validate_account_id(account_id: str) -> None:
    """Raise 400 if account_id is missing or not a valid UUID."""
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


def assert_sms_account_access(
    user: User,
    account_id: str,
    db: Session,
) -> None:
    """Raise 403 unless `user` is a platform admin or has an active membership
    in `account_id` with the `messages.view` permission.
    Raise 400 if account_id is missing or not a valid UUID.

    Use this for read-only SMS endpoints. Mutating endpoints should call
    `assert_sms_permission` with the appropriate permission string instead.
    """
    _validate_account_id(account_id)
    check_account_permission(user, account_id, "messages.view", db)


def assert_sms_permission(
    user: User,
    account_id: str,
    permission: str,
    db: Session,
) -> None:
    """Raise 403 unless `user` is a platform admin or has an active membership
    in `account_id` with the given `permission` (e.g. ``messages.reply``).
    Raise 400 if account_id is missing or not a valid UUID.

    Valid SMS permissions:
      - ``messages.view``                 — read-only access
      - ``messages.reply``                — send replies / upload MMS files
      - ``messages.manage_conversations`` — take-over, return-to-ai, close
      - ``messages.manage_settings``      — template CRUD, notification settings
    """
    _validate_account_id(account_id)
    check_account_permission(user, account_id, permission, db)


def require_sms_query_account():
    """FastAPI dependency: authenticates the caller, asserts they have
    `messages.view` access to the `account_id` query parameter, and
    returns it as a string. Use this for GET routes that accept
    `?account_id=...`.

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

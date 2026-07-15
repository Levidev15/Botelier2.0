"""Payment Page Templates API — per-property review+pay page design (Task #339).

Operators design the public review+pay page (branding, which reservation
sections/fields show, whether each field is editable, and the Privacy/Terms
footer) per property. The design is stored as one structured ``design`` JSONB
blob shared by the dashboard designer and the public renderer.

ACCOUNT/PROPERTY-scoped: every query filters by ``account_id`` for multi-tenant
isolation, enforces the ``properties.*`` permission family (consistent with the
per-property config surface), and validates that a supplied ``property_id``
belongs to the account (fail closed / HTTP 400 on cross-account).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..models.payment_page_template import (
    PaymentPageTemplate,
    default_page_design,
    validate_design,
)
from ..models.user import User
from ..services.property_scope import property_belongs_to_account

router = APIRouter(prefix="/api/payment-pages", tags=["Payment Pages"])


class PaymentPageUpdate(BaseModel):
    design: dict


def _validate_property(db: Session, account_id: UUID, property_id: Optional[UUID]) -> None:
    """Fail closed if a supplied property does not belong to the account."""
    if property_id is None:
        return
    if not property_belongs_to_account(db, account_id, property_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Property does not belong to this account",
        )


def _load(db: Session, account_id: UUID, property_id: Optional[UUID]) -> Optional[PaymentPageTemplate]:
    q = db.query(PaymentPageTemplate).filter(
        PaymentPageTemplate.account_id == account_id
    )
    if property_id is None:
        q = q.filter(PaymentPageTemplate.property_id.is_(None))
    else:
        q = q.filter(PaymentPageTemplate.property_id == property_id)
    return q.first()


@router.get("")
async def get_payment_page(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    property_id: Optional[UUID] = Query(None, description="Property scope (NULL = account default)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the effective review+pay page design for a property.

    Falls back to the platform default when the property has no saved design, so
    the designer and renderer always have a complete contract to work with.
    """
    check_account_permission(user, str(account_id), "properties.view", db)
    _validate_property(db, account_id, property_id)

    row = _load(db, account_id, property_id)
    if row is not None:
        return {"design": row.design or default_page_design(), "is_custom": True}
    return {"design": default_page_design(), "is_custom": False}


@router.put("")
async def upsert_payment_page(
    payload: PaymentPageUpdate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    property_id: Optional[UUID] = Query(None, description="Property scope (NULL = account default)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create or update the review+pay page design for a property."""
    check_account_permission(user, str(account_id), "properties.manage", db)
    _validate_property(db, account_id, property_id)

    if not isinstance(payload.design, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="design must be an object",
        )

    # Branding/footer values reach the public page's CSS + href/src sinks — reject
    # unsafe colors/URLs at write time (renderer additionally coerces).
    try:
        validate_design(payload.design)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    row = _load(db, account_id, property_id)
    if row is None:
        row = PaymentPageTemplate(
            account_id=account_id,
            property_id=property_id,
            design=payload.design,
        )
        db.add(row)
    else:
        row.design = payload.design

    db.commit()
    db.refresh(row)
    logger.info(
        f"Payment page template saved (account {account_id}, property {property_id})"
    )
    return row.to_dict()


@router.delete("")
async def reset_payment_page(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    property_id: Optional[UUID] = Query(None, description="Property scope (NULL = account default)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reset a property's page to the platform default by deleting its row."""
    check_account_permission(user, str(account_id), "properties.manage", db)
    _validate_property(db, account_id, property_id)

    row = _load(db, account_id, property_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"success": True}

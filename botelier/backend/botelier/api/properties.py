"""Properties API — list, create, edit, and delete properties within an account.

A property represents a distinct location/business unit under an Account (e.g.
Hotel A, Hotel B). Phone numbers, assistants, and integration connections may be
bound to a property so one property can never receive another property's data —
see Task #327 (Per-Property Data Isolation).

Properties are ACCOUNT-scoped: every query filters by ``account_id`` for
multi-tenant isolation and enforces the ``properties.*`` permission family.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..models.assistant import Assistant
from ..models.integration import AccountIntegration
from ..models.phone_number import PhoneNumber
from ..models.property import Property
from ..models.user import User

router = APIRouter(prefix="/api/properties", tags=["Properties"])


class PropertyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    address: Optional[str] = None
    timezone: Optional[str] = Field(None, max_length=50)


class PropertyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    address: Optional[str] = None
    timezone: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


def _get_owned_property(db: Session, account_id: UUID, property_id: UUID) -> Property:
    """Load a property, failing closed if it does not belong to ``account_id``.

    Filtering on both the id AND the account_id prevents cross-tenant access via a
    guessed/leaked property id.
    """
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.account_id == account_id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


@router.get("")
async def list_properties(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List properties for an account (default property first, then by name)."""
    check_account_permission(user, str(account_id), "properties.view", db)

    query = db.query(Property).filter(Property.account_id == account_id)
    if not include_inactive:
        query = query.filter(Property.is_active == True)

    rows = query.order_by(Property.is_default.desc(), Property.name.asc()).all()
    return {"properties": [p.to_dict() for p in rows], "total": len(rows)}


@router.get("/{property_id}")
async def get_property(
    property_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fetch a single property by id (account-scoped)."""
    check_account_permission(user, str(account_id), "properties.view", db)
    return _get_owned_property(db, account_id, property_id).to_dict()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_property(
    payload: PropertyCreate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new property under the account."""
    check_account_permission(user, str(account_id), "properties.manage", db)

    prop = Property(
        account_id=account_id,
        name=payload.name.strip(),
        description=payload.description,
        address=payload.address,
        timezone=payload.timezone,
        is_default=False,
        is_active=True,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    logger.info(f"Property created: {prop.id} (account {account_id})")
    return prop.to_dict()


@router.patch("/{property_id}")
async def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a property's editable fields (account-scoped)."""
    check_account_permission(user, str(account_id), "properties.manage", db)

    prop = _get_owned_property(db, account_id, property_id)

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        prop.name = updates["name"].strip()
    if "description" in updates:
        prop.description = updates["description"]
    if "address" in updates:
        prop.address = updates["address"]
    if "timezone" in updates:
        prop.timezone = updates["timezone"]
    if "is_active" in updates and updates["is_active"] is not None:
        prop.is_active = updates["is_active"]

    db.commit()
    db.refresh(prop)
    return prop.to_dict()


@router.delete("/{property_id}")
async def delete_property(
    property_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a property.

    The default property cannot be deleted (it is the account's fallback scope).

    Deletion is refused while any phone number, assistant, or integration is still
    bound to this property. The FK is ``ON DELETE SET NULL``, so a raw delete would
    silently promote a property-PRIVATE integration to account-GLOBAL scope —
    exposing this property's data to every other property under the account. That
    would invert the fail-closed isolation guarantee (Task #327), so we require the
    operator to first reassign or disconnect the bound resources.
    """
    check_account_permission(user, str(account_id), "properties.manage", db)

    prop = _get_owned_property(db, account_id, property_id)
    if prop.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the account's default property",
        )

    bound = {
        "integrations": db.query(AccountIntegration)
        .filter(AccountIntegration.property_id == property_id)
        .count(),
        "phone_numbers": db.query(PhoneNumber)
        .filter(PhoneNumber.property_id == property_id)
        .count(),
        "assistants": db.query(Assistant)
        .filter(Assistant.property_id == property_id)
        .count(),
    }
    if any(bound.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Cannot delete a property while resources are still bound to "
                    "it. Reassign or disconnect them first."
                ),
                "bound": bound,
            },
        )

    db.delete(prop)
    db.commit()
    logger.info(f"Property deleted: {property_id} (account {account_id})")
    return {"success": True, "id": str(property_id)}

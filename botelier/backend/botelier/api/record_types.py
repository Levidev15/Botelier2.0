"""Record Types API - CRUD for account-scoped structured output table definitions.

Record types are ACCOUNT-scoped (shared across all assistants in the account).
All endpoints require an ``account_id`` query parameter for multi-tenant
isolation and enforce the ``records.*`` permission family.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..models.record import Record
from ..models.record_type import RecordType
from ..models.user import User

router = APIRouter(prefix="/api/record-types", tags=["Record Types"])

_VALID_FIELD_TYPES = {
    "text",
    "number",
    "date",
    "datetime",
    "boolean",
    "select",
    "phone",
    "email",
}


class FieldDef(BaseModel):
    key: str
    label: str
    type: str = "text"
    required: bool = False
    options: Optional[List[str]] = None


class StatusOption(BaseModel):
    value: str
    label: str
    color: Optional[str] = None


class RecordTypeCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = "#6366f1"
    fields: List[FieldDef] = []
    status_options: List[StatusOption] = []
    auto_extract: bool = False
    extraction_instructions: Optional[str] = None
    assistant_ids: Optional[List[str]] = None
    is_active: bool = True
    display_order: Optional[int] = None


class RecordTypeUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    fields: Optional[List[FieldDef]] = None
    status_options: Optional[List[StatusOption]] = None
    auto_extract: Optional[bool] = None
    extraction_instructions: Optional[str] = None
    assistant_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "record-type"


def _unique_slug(db: Session, account_id: UUID, base: str, exclude_id: Optional[UUID] = None) -> str:
    """Return a slug unique within the account, appending -2, -3, ... if needed."""
    base = _slugify(base)
    candidate = base
    suffix = 1
    while True:
        q = db.query(RecordType).filter(
            RecordType.account_id == account_id, RecordType.slug == candidate
        )
        if exclude_id is not None:
            q = q.filter(RecordType.id != exclude_id)
        if q.first() is None:
            return candidate
        suffix += 1
        candidate = f"{base}-{suffix}"


def _validate_fields(fields: List[FieldDef]) -> None:
    seen = set()
    for f in fields:
        if not f.key or not f.key.strip():
            raise HTTPException(status_code=400, detail="Every field must have a non-empty key")
        if f.key in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate field key: {f.key}")
        seen.add(f.key)
        if f.type not in _VALID_FIELD_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid field type '{f.type}' for field '{f.key}'",
            )


@router.get("")
async def list_record_types(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all record types for an account, with record counts."""
    check_account_permission(user, str(account_id), "records.view", db)

    query = db.query(RecordType).filter(RecordType.account_id == account_id)
    if not include_inactive:
        query = query.filter(RecordType.is_active == True)
    record_types = query.order_by(RecordType.display_order, RecordType.created_at).all()

    counts: Dict[UUID, int] = dict(
        db.query(Record.record_type_id, func.count(Record.id))
        .filter(Record.account_id == account_id)
        .group_by(Record.record_type_id)
        .all()
    )

    return [
        rt.to_dict(include_counts=True, record_count=counts.get(rt.id, 0)) for rt in record_types
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_record_type(
    data: RecordTypeCreate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new record type (table definition)."""
    check_account_permission(user, str(account_id), "records.manage_types", db)

    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    _validate_fields(data.fields)

    slug = _unique_slug(db, account_id, data.slug or data.name)

    max_order = db.query(RecordType).filter(RecordType.account_id == account_id).count()

    record_type = RecordType(
        account_id=account_id,
        name=data.name.strip(),
        slug=slug,
        description=data.description,
        icon=data.icon,
        color=data.color,
        fields=[f.model_dump() for f in data.fields],
        status_options=[s.model_dump() for s in data.status_options],
        auto_extract=data.auto_extract,
        extraction_instructions=data.extraction_instructions,
        assistant_ids=data.assistant_ids or None,
        is_active=data.is_active,
        display_order=data.display_order if data.display_order is not None else max_order,
    )

    db.add(record_type)
    db.commit()
    db.refresh(record_type)

    logger.info(f"Created record type '{record_type.name}' for account {account_id}")
    return record_type.to_dict()


@router.get("/{record_type_id}")
async def get_record_type(
    record_type_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single record type."""
    check_account_permission(user, str(account_id), "records.view", db)

    record_type = (
        db.query(RecordType)
        .filter(RecordType.id == record_type_id, RecordType.account_id == account_id)
        .first()
    )
    if not record_type:
        raise HTTPException(status_code=404, detail="Record type not found")

    count = (
        db.query(func.count(Record.id))
        .filter(Record.account_id == account_id, Record.record_type_id == record_type_id)
        .scalar()
    )
    return record_type.to_dict(include_counts=True, record_count=count or 0)


@router.patch("/{record_type_id}")
async def update_record_type(
    record_type_id: UUID,
    data: RecordTypeUpdate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a record type."""
    check_account_permission(user, str(account_id), "records.manage_types", db)

    record_type = (
        db.query(RecordType)
        .filter(RecordType.id == record_type_id, RecordType.account_id == account_id)
        .first()
    )
    if not record_type:
        raise HTTPException(status_code=404, detail="Record type not found")

    update_data: Dict[str, Any] = data.model_dump(exclude_unset=True)

    if "fields" in update_data and update_data["fields"] is not None:
        _validate_fields([FieldDef(**f) for f in update_data["fields"]])

    if "slug" in update_data and update_data["slug"]:
        update_data["slug"] = _unique_slug(
            db, account_id, update_data["slug"], exclude_id=record_type_id
        )

    if "assistant_ids" in update_data and not update_data["assistant_ids"]:
        update_data["assistant_ids"] = None

    for key, value in update_data.items():
        setattr(record_type, key, value)

    record_type.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record_type)

    logger.info(f"Updated record type {record_type_id}")
    return record_type.to_dict()


@router.delete("/{record_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record_type(
    record_type_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a record type and all its records (cascade)."""
    check_account_permission(user, str(account_id), "records.manage_types", db)

    record_type = (
        db.query(RecordType)
        .filter(RecordType.id == record_type_id, RecordType.account_id == account_id)
        .first()
    )
    if not record_type:
        raise HTTPException(status_code=404, detail="Record type not found")

    db.delete(record_type)
    db.commit()

    logger.info(f"Deleted record type {record_type_id}")
    return None

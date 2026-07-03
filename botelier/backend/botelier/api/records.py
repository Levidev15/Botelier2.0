"""Records API - list, view, edit, delete, export, and manual-create structured records.

Records are ACCOUNT-scoped. Every query filters by ``account_id`` for
multi-tenant isolation and enforces the ``records.*`` permission family.
"""

import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..models.record import CaptureMethod, Record, SourceChannel
from ..models.record_type import RecordType
from ..models.user import User

router = APIRouter(prefix="/api/records", tags=["Records"])


class RecordCreate(BaseModel):
    record_type_id: UUID
    data: Dict[str, Any] = {}
    status: Optional[str] = None


class RecordUpdate(BaseModel):
    data: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


@router.get("")
async def list_records(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    record_type_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    source_channel: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List records for an account with optional filters (paginated)."""
    check_account_permission(user, str(account_id), "records.view", db)

    query = db.query(Record).filter(Record.account_id == account_id)
    if record_type_id:
        query = query.filter(Record.record_type_id == record_type_id)
    if status_filter:
        query = query.filter(Record.status == status_filter)
    if source_channel:
        query = query.filter(Record.source_channel == source_channel)
    if date_from:
        query = query.filter(Record.created_at >= date_from.replace(tzinfo=None))
    if date_to:
        query = query.filter(Record.created_at <= date_to.replace(tzinfo=None))

    total = query.count()
    rows = (
        query.order_by(Record.created_at.desc()).offset(offset).limit(limit).all()
    )

    return {
        "records": [r.to_dict(include_type=True) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/export")
async def export_records(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    record_type_id: Optional[UUID] = Query(
        None, description="Export a single record type (columns from its fields)."
    ),
    status_filter: Optional[str] = Query(None, alias="status"),
    source_channel: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export records to CSV.

    When ``record_type_id`` is provided, one column is emitted per field of that
    record type. Otherwise a generic ``Data (JSON)`` column is used.
    """
    check_account_permission(user, str(account_id), "records.export", db)

    record_type: Optional[RecordType] = None
    if record_type_id:
        record_type = (
            db.query(RecordType)
            .filter(RecordType.id == record_type_id, RecordType.account_id == account_id)
            .first()
        )
        if not record_type:
            raise HTTPException(status_code=404, detail="Record type not found")

    query = db.query(Record).filter(Record.account_id == account_id)
    if record_type_id:
        query = query.filter(Record.record_type_id == record_type_id)
    if status_filter:
        query = query.filter(Record.status == status_filter)
    if source_channel:
        query = query.filter(Record.source_channel == source_channel)
    if date_from:
        query = query.filter(Record.created_at >= date_from.replace(tzinfo=None))
    if date_to:
        query = query.filter(Record.created_at <= date_to.replace(tzinfo=None))

    rows = query.order_by(Record.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    base_headers = [
        "Created At (UTC)",
        "Record Type",
        "Status",
        "Source Channel",
        "Capture Method",
    ]

    if record_type is not None:
        fields = record_type.fields or []
        field_headers = [f.get("label") or f.get("key") for f in fields]
        field_keys = [f.get("key") for f in fields]
        writer.writerow(base_headers + field_headers)
        type_name_by_id = {str(record_type.id): record_type.name}
    else:
        writer.writerow(base_headers + ["Data (JSON)"])
        field_keys = None
        # Preload type names for mixed export.
        type_name_by_id = {
            str(rt.id): rt.name
            for rt in db.query(RecordType).filter(RecordType.account_id == account_id).all()
        }

    for r in rows:
        data = r.data or {}
        base = [
            r.created_at.isoformat() + "Z" if r.created_at else "",
            type_name_by_id.get(str(r.record_type_id), ""),
            r.status or "",
            r.source_channel or "",
            r.capture_method or "",
        ]
        if field_keys is not None:
            values = [_fmt_cell(data.get(k)) for k in field_keys]
            writer.writerow(base + values)
        else:
            import json as _json

            writer.writerow(base + [_json.dumps(data, ensure_ascii=False)])

    output.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    slug = record_type.slug if record_type is not None else "records"
    filename = f"{slug}_{ts}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _fmt_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, dict)):
        import json as _json

        return _json.dumps(value, ensure_ascii=False)
    return str(value)


@router.get("/{record_id}")
async def get_record(
    record_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single record."""
    check_account_permission(user, str(account_id), "records.view", db)

    record = (
        db.query(Record)
        .filter(Record.id == record_id, Record.account_id == account_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record.to_dict(include_type=True)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_record(
    data: RecordCreate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually create a record in the dashboard."""
    check_account_permission(user, str(account_id), "records.create", db)

    record_type = (
        db.query(RecordType)
        .filter(RecordType.id == data.record_type_id, RecordType.account_id == account_id)
        .first()
    )
    if not record_type:
        raise HTTPException(status_code=404, detail="Record type not found")

    record = Record(
        account_id=account_id,
        record_type_id=record_type.id,
        status=data.status,
        data=data.data or {},
        source_channel=SourceChannel.MANUAL.value,
        capture_method=CaptureMethod.MANUAL.value,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(f"Manually created record {record.id} (type {record_type.id})")
    return record.to_dict(include_type=True)


@router.patch("/{record_id}")
async def update_record(
    record_id: UUID,
    data: RecordUpdate,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a record's data and/or status."""
    check_account_permission(user, str(account_id), "records.edit", db)

    record = (
        db.query(Record)
        .filter(Record.id == record_id, Record.account_id == account_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    update_data = data.model_dump(exclude_unset=True)
    if "data" in update_data and update_data["data"] is not None:
        record.data = update_data["data"]
    if "status" in update_data:
        record.status = update_data["status"]

    record.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(record)

    logger.info(f"Updated record {record_id}")
    return record.to_dict(include_type=True)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a record."""
    check_account_permission(user, str(account_id), "records.delete", db)

    record = (
        db.query(Record)
        .filter(Record.id == record_id, Record.account_id == account_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    db.delete(record)
    db.commit()

    logger.info(f"Deleted record {record_id}")
    return None

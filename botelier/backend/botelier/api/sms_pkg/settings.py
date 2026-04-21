"""
SMS Settings endpoints.

  GET    /api/sms/templates              — List templates
  POST   /api/sms/templates              — Create template
  PUT    /api/sms/templates/{id}         — Update template
  DELETE /api/sms/templates/{id}         — Delete template
  GET    /api/sms/settings/notifications — Get notification settings
  PUT    /api/sms/settings/notifications — Save notification settings
  POST   /api/sms/upload                 — Upload file attachment (MMS)
"""

import os
import uuid as uuid_mod
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from botelier.auth.middleware import get_current_user
from botelier.database import get_db
from botelier.models.sms_template import SMSTemplate, SMSNotificationSettings
from botelier.models.user import User

from ._auth import assert_sms_account_access

router = APIRouter(prefix="/api/sms", tags=["SMS"])

# Strict allowlist: maps a vetted content-type to the *server-chosen*
# extension that will be written to disk. We never trust the user-supplied
# filename for the on-disk extension — that is how a caller could write
# .html / .js / .svg files into a publicly-served directory and turn the
# upload endpoint into a stored-XSS vector. (Task #137 V2)
ALLOWED_UPLOAD_EXT_BY_CONTENT_TYPE = {
    "image/jpeg":      "jpg",
    "image/jpg":       "jpg",  # tolerate the non-standard alias some clients send
    "image/png":       "png",
    "image/gif":       "gif",
    "image/webp":      "webp",
    "application/pdf": "pdf",
}


def _sniff_matches_content_type(payload: bytes, content_type: str) -> bool:
    """
    Defense-in-depth: verify the file's leading bytes are consistent with
    the declared content_type. content_type is client-supplied and cannot
    be trusted on its own; this catches a caller that uploads HTML/SVG/JS
    with a forged `Content-Type: image/png` header.
    """
    if len(payload) < 4:
        return False
    ct = (content_type or "").lower()
    if ct in ("image/jpeg", "image/jpg"):
        return payload[:3] == b"\xff\xd8\xff"
    if ct == "image/png":
        return payload[:8] == b"\x89PNG\r\n\x1a\n"
    if ct == "image/gif":
        return payload[:6] in (b"GIF87a", b"GIF89a")
    if ct == "image/webp":
        return payload[:4] == b"RIFF" and len(payload) >= 12 and payload[8:12] == b"WEBP"
    if ct == "application/pdf":
        return payload[:4] == b"%PDF"
    return False


MAX_FILE_SIZE = 5 * 1024 * 1024
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "uploads",
)


@router.get("/templates")
async def list_templates(
    account_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, account_id, db)
    templates = db.query(SMSTemplate).filter(
        SMSTemplate.account_id == UUID(account_id),
    ).order_by(SMSTemplate.category, SMSTemplate.name).all()
    return [t.to_dict() for t in templates]


class TemplateRequest(BaseModel):
    account_id: str
    name: str
    content: str
    category: Optional[str] = None
    is_active: bool = True


@router.post("/templates")
async def create_template(
    request: TemplateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, request.account_id, db)
    template = SMSTemplate(
        account_id=UUID(request.account_id),
        name=request.name,
        content=request.content,
        category=request.category,
        is_active=request.is_active,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template.to_dict()


@router.put("/templates/{template_id}")
async def update_template(
    template_id: UUID,
    request: TemplateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, request.account_id, db)
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.account_id == UUID(request.account_id),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.name       = request.name
    template.content    = request.content
    template.category   = request.category
    template.is_active  = request.is_active
    template.updated_at = datetime.utcnow()
    db.commit()
    return template.to_dict()


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    account_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, account_id, db)
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.account_id == UUID(account_id),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"success": True}


@router.get("/settings/notifications")
async def get_notification_settings(
    account_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, account_id, db)
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.account_id == UUID(account_id),
    ).first()
    if not settings:
        return {"sound_enabled": True, "visual_enabled": True, "threshold": 1, "sound_type": "chime"}
    return settings.to_dict()


class NotificationSettingsRequest(BaseModel):
    account_id: str
    sound_enabled: bool = True
    visual_enabled: bool = True
    threshold: int = 1
    sound_type: str = "chime"


@router.put("/settings/notifications")
async def update_notification_settings(
    request: NotificationSettingsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_sms_account_access(user, request.account_id, db)
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.account_id == UUID(request.account_id),
    ).first()

    if not settings:
        settings = SMSNotificationSettings(
            account_id=UUID(request.account_id),
            sound_enabled=request.sound_enabled,
            visual_enabled=request.visual_enabled,
            threshold=str(request.threshold),
            sound_type=request.sound_type,
        )
        db.add(settings)
    else:
        settings.sound_enabled  = request.sound_enabled
        settings.visual_enabled = request.visual_enabled
        settings.threshold      = str(request.threshold)
        settings.sound_type     = request.sound_type
        settings.updated_at     = datetime.utcnow()

    db.commit()
    db.refresh(settings)
    return settings.to_dict()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    account_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Upload a file attachment for MMS sending (images + PDF, max 5 MB).

    Security (Task #137 V2):
      • Authenticated — JWT required.
      • Tenant-scoped — caller must be a member of `account_id`.
      • Extension is server-chosen from a content-type allowlist; the
        attacker-controlled `file.filename` is NEVER used to decide what
        extension to write to disk. This blocks stored-XSS via .html /
        .svg / .js uploads served from /uploads/*.
    """
    assert_sms_account_access(user, account_id, db)

    ext = ALLOWED_UPLOAD_EXT_BY_CONTENT_TYPE.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type!r} not allowed",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5MB limit")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Defense-in-depth: confirm the leading bytes match the declared
    # content_type. Without this, a caller could POST malicious
    # HTML/SVG/JS bytes with a forged `Content-Type: image/png` header
    # — the file would still be served from /uploads/<uuid>.png, but
    # browsers can sniff it and execute scripts in some configurations.
    if not _sniff_matches_content_type(contents, file.content_type or ""):
        raise HTTPException(
            status_code=400,
            detail="File contents do not match the declared content_type",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_name = f"{uuid_mod.uuid4().hex}.{ext}"
    file_path   = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if replit_domain:
        base_url = f"https://{replit_domain}"
    elif request:
        forwarded_host = request.headers.get("x-forwarded-host", "")
        base_url = f"https://{forwarded_host}" if forwarded_host else str(request.base_url).rstrip("/")
    else:
        base_url = "http://localhost:3001"

    public_url = f"{base_url}/uploads/{unique_name}"
    logger.info(
        f"SMS upload: account={account_id} user={user.id} "
        f"content_type={file.content_type} size={len(contents)} stored={unique_name}"
    )
    return {
        "success": True,
        "url": public_url,
        # Echo back the original filename for the UI, but this value is
        # NOT used server-side for any path decision.
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(contents),
    }

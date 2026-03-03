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

from botelier.database import get_db
from botelier.models.sms_template import SMSTemplate, SMSNotificationSettings

router = APIRouter(prefix="/api/sms", tags=["SMS"])

ALLOWED_UPLOAD_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
}
MAX_FILE_SIZE = 5 * 1024 * 1024
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "uploads",
)


@router.get("/templates")
async def list_templates(
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    templates = db.query(SMSTemplate).filter(
        SMSTemplate.hotel_id == UUID(hotel_id),
    ).order_by(SMSTemplate.category, SMSTemplate.name).all()
    return [t.to_dict() for t in templates]


class TemplateRequest(BaseModel):
    hotel_id: str
    name: str
    content: str
    category: Optional[str] = None
    is_active: bool = True


@router.post("/templates")
async def create_template(
    request: TemplateRequest,
    db: Session = Depends(get_db),
):
    template = SMSTemplate(
        hotel_id=UUID(request.hotel_id),
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
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.hotel_id == UUID(request.hotel_id),
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
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.hotel_id == UUID(hotel_id),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"success": True}


@router.get("/settings/notifications")
async def get_notification_settings(
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.hotel_id == UUID(hotel_id),
    ).first()
    if not settings:
        return {"sound_enabled": True, "visual_enabled": True, "threshold": 1, "sound_type": "chime"}
    return settings.to_dict()


class NotificationSettingsRequest(BaseModel):
    hotel_id: str
    sound_enabled: bool = True
    visual_enabled: bool = True
    threshold: int = 1
    sound_type: str = "chime"


@router.put("/settings/notifications")
async def update_notification_settings(
    request: NotificationSettingsRequest,
    db: Session = Depends(get_db),
):
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.hotel_id == UUID(request.hotel_id),
    ).first()

    if not settings:
        settings = SMSNotificationSettings(
            hotel_id=UUID(request.hotel_id),
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
    hotel_id: str = Form(...),
    request: Request = None,
):
    """Upload a file attachment for MMS sending (images + PDF, max 5 MB)."""
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail=f"File type {file.content_type} not allowed")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5MB limit")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
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
    return {
        "success": True,
        "url": public_url,
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(contents),
    }

from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from ..database import get_db
from ..models import AssistantResolutionOption, Assistant
from ..models.user import User
from ..auth.middleware import get_current_user, check_account_permission


router = APIRouter(prefix="/api/assistants", tags=["Resolution Options"])


class ResolutionOptionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    display_order: Optional[int] = 0
    is_active: Optional[bool] = True


class ResolutionOptionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/{assistant_id}/resolution-options")
async def list_resolution_options(
    assistant_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(hotel_id), "assistants.view", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()

    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    options = db.query(AssistantResolutionOption).filter(
        AssistantResolutionOption.assistant_id == assistant_id
    ).order_by(AssistantResolutionOption.display_order, AssistantResolutionOption.created_at).all()

    return [o.to_dict() for o in options]


@router.post("/{assistant_id}/resolution-options", status_code=status.HTTP_201_CREATED)
async def create_resolution_option(
    assistant_id: UUID,
    data: ResolutionOptionCreate,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(hotel_id), "assistants.edit", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()

    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    max_order = db.query(AssistantResolutionOption).filter(
        AssistantResolutionOption.assistant_id == assistant_id
    ).count()

    option = AssistantResolutionOption(
        assistant_id=assistant_id,
        name=data.name,
        description=data.description,
        display_order=data.display_order if data.display_order else max_order,
        is_active=data.is_active,
    )

    db.add(option)
    db.commit()
    db.refresh(option)

    logger.info(f"Created resolution option '{data.name}' for assistant {assistant_id}")
    return option.to_dict()


@router.patch("/{assistant_id}/resolution-options/{option_id}")
async def update_resolution_option(
    assistant_id: UUID,
    option_id: UUID,
    data: ResolutionOptionUpdate,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(hotel_id), "assistants.edit", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()

    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    option = db.query(AssistantResolutionOption).filter(
        AssistantResolutionOption.id == option_id,
        AssistantResolutionOption.assistant_id == assistant_id
    ).first()

    if not option:
        raise HTTPException(status_code=404, detail="Resolution option not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(option, key, value)

    option.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(option)

    logger.info(f"Updated resolution option {option_id}")
    return option.to_dict()


@router.delete("/{assistant_id}/resolution-options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resolution_option(
    assistant_id: UUID,
    option_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(hotel_id), "assistants.edit", db)
    assistant = db.query(Assistant).filter(
        Assistant.id == assistant_id,
        Assistant.hotel_id == hotel_id
    ).first()

    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")

    option = db.query(AssistantResolutionOption).filter(
        AssistantResolutionOption.id == option_id,
        AssistantResolutionOption.assistant_id == assistant_id
    ).first()

    if not option:
        raise HTTPException(status_code=404, detail="Resolution option not found")

    db.delete(option)
    db.commit()

    logger.info(f"Deleted resolution option {option_id}")
    return None

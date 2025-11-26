"""
Flow Versions API endpoints.

Provides endpoints for managing versioned flow configurations:
- Save drafts
- Publish versions
- List version history
- Revert to previous versions
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timezone
import uuid

from botelier.database import get_db
from botelier.models.tool import Tool, ToolType as DBToolType
from botelier.models.flow_version import FlowVersion, FlowVersionStatus

router = APIRouter(prefix="/api/tools", tags=["flow-versions"])


@router.get("/{tool_id}/flow")
def get_tool_flow(
    tool_id: str,
    hotel_id: str,
    source: Optional[str] = None,
    version: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get flow configuration for a flow-type tool.
    
    Query Parameters:
        - source: 'draft', 'published', or omit for auto-select (draft if exists, else published)
        - version: Specific version number to fetch (overrides source)
    
    Returns the visual flow editor data (nodes, edges, variables).
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    flow_version = None
    
    if version is not None:
        flow_version = db.query(FlowVersion).filter(
            FlowVersion.tool_id == tool_id,
            FlowVersion.version_number == version
        ).first()
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} not found for this flow"
            )
    elif source == "draft":
        if tool.draft_version_id:
            flow_version = db.query(FlowVersion).filter(
                FlowVersion.id == tool.draft_version_id
            ).first()
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No draft exists for this flow"
            )
    elif source == "published":
        if tool.published_version_id:
            flow_version = db.query(FlowVersion).filter(
                FlowVersion.id == tool.published_version_id
            ).first()
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No published version exists for this flow"
            )
    else:
        if tool.draft_version_id:
            flow_version = db.query(FlowVersion).filter(
                FlowVersion.id == tool.draft_version_id
            ).first()
        elif tool.published_version_id:
            flow_version = db.query(FlowVersion).filter(
                FlowVersion.id == tool.published_version_id
            ).first()
        else:
            flow_config = tool.config or {}
            return {
                "tool_id": tool.id,
                "hotel_id": str(tool.hotel_id),
                "name": tool.name,
                "source": "legacy",
                "version_number": 0,
                "has_draft": False,
                "has_published": False,
                "flow_config": {
                    "initial_node": flow_config.get("initial_node"),
                    "nodes": flow_config.get("nodes", []),
                    "edges": flow_config.get("edges", []),
                    "variables": flow_config.get("variables", [])
                }
            }
    
    return {
        "tool_id": tool.id,
        "hotel_id": str(tool.hotel_id),
        "name": tool.name,
        "source": flow_version.status.value,
        "version_number": flow_version.version_number,
        "version_id": str(flow_version.id),
        "description": flow_version.description,
        "has_draft": tool.draft_version_id is not None,
        "has_published": tool.published_version_id is not None,
        "published_version_number": tool.published_version_number or 0,
        "flow_config": flow_version.flow_config
    }


@router.put("/{tool_id}/flow/draft")
def save_flow_draft(
    tool_id: str,
    hotel_id: str,
    draft_data: dict,
    db: Session = Depends(get_db)
):
    """
    Save flow as a draft.
    
    Creates or updates the draft version. Drafts can be tested in the simulator
    before publishing to production.
    
    Body:
        - flow_config: The flow configuration (nodes, edges, variables)
        - description: Optional description for this version
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    flow_config = draft_data.get("flow_config", {})
    description = draft_data.get("description")
    
    next_version = (tool.published_version_number or 0) + 1
    
    if tool.draft_version_id:
        draft = db.query(FlowVersion).filter(
            FlowVersion.id == tool.draft_version_id
        ).first()
        if draft:
            draft.flow_config = flow_config
            draft.description = description
            draft.version_number = next_version
    else:
        draft = FlowVersion(
            id=uuid.uuid4(),
            tool_id=tool_id,
            version_number=next_version,
            status=FlowVersionStatus.DRAFT,
            description=description,
            flow_config=flow_config,
        )
        db.add(draft)
        db.flush()
        tool.draft_version_id = draft.id
    
    db.commit()
    db.refresh(draft)
    
    return {
        "tool_id": tool_id,
        "version_id": str(draft.id),
        "version_number": draft.version_number,
        "status": "draft",
        "description": draft.description,
        "message": "Draft saved successfully"
    }


@router.post("/{tool_id}/flow/publish")
def publish_flow(
    tool_id: str,
    hotel_id: str,
    publish_data: Optional[dict] = None,
    db: Session = Depends(get_db)
):
    """
    Publish the current draft as a new version.
    
    The draft becomes immutable and is used for live calls.
    A new draft can be created for future edits.
    
    Body (optional):
        - description: Override or set the version description
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    if not tool.draft_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No draft to publish. Save a draft first."
        )
    
    draft = db.query(FlowVersion).filter(
        FlowVersion.id == tool.draft_version_id
    ).first()
    
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft version not found"
        )
    
    if publish_data and publish_data.get("description"):
        draft.description = publish_data["description"]
    
    draft.status = FlowVersionStatus.PUBLISHED
    draft.published_at = datetime.now(timezone.utc)
    
    tool.published_version_id = draft.id
    tool.published_version_number = draft.version_number
    tool.draft_version_id = None
    
    tool.config = draft.flow_config
    
    db.commit()
    db.refresh(draft)
    
    return {
        "tool_id": tool_id,
        "version_id": str(draft.id),
        "version_number": draft.version_number,
        "status": "published",
        "description": draft.description,
        "published_at": draft.published_at.isoformat(),
        "message": f"Version {draft.version_number} published successfully"
    }


@router.delete("/{tool_id}/flow/draft")
def discard_draft(
    tool_id: str,
    hotel_id: str,
    db: Session = Depends(get_db)
):
    """
    Discard the current draft.
    
    Reverts to the last published version for editing.
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if not tool.draft_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No draft to discard"
        )
    
    draft = db.query(FlowVersion).filter(
        FlowVersion.id == tool.draft_version_id
    ).first()
    
    if draft:
        db.delete(draft)
    
    tool.draft_version_id = None
    db.commit()
    
    return {
        "tool_id": tool_id,
        "message": "Draft discarded successfully"
    }


@router.get("/{tool_id}/flow/versions")
def list_flow_versions(
    tool_id: str,
    hotel_id: str,
    db: Session = Depends(get_db)
):
    """
    List all versions of a flow.
    
    Returns version history without full flow_config (for performance).
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    versions = db.query(FlowVersion).filter(
        FlowVersion.tool_id == tool_id
    ).order_by(desc(FlowVersion.version_number)).all()
    
    return {
        "tool_id": tool_id,
        "published_version_number": tool.published_version_number or 0,
        "has_draft": tool.draft_version_id is not None,
        "versions": [v.to_summary_dict() for v in versions]
    }


@router.get("/{tool_id}/flow/versions/{version_number}")
def get_flow_version(
    tool_id: str,
    version_number: int,
    hotel_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific version of a flow.
    
    Returns the full flow_config for the requested version.
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    version = db.query(FlowVersion).filter(
        FlowVersion.tool_id == tool_id,
        FlowVersion.version_number == version_number
    ).first()
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found"
        )
    
    return version.to_dict()


@router.post("/{tool_id}/flow/versions/{version_number}/revert")
def revert_to_version(
    tool_id: str,
    version_number: int,
    hotel_id: str,
    revert_data: Optional[dict] = None,
    db: Session = Depends(get_db)
):
    """
    Revert to a previous version.
    
    Creates a new draft pre-filled with the content from the selected version.
    Does not affect the currently published version until the new draft is published.
    
    Body (optional):
        - description: Description for the new draft
        - publish_immediately: If true, publishes immediately as a new version
    """
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.hotel_id == hotel_id
    ).first()
    
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this hotel"
        )
    
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )
    
    source_version = db.query(FlowVersion).filter(
        FlowVersion.tool_id == tool_id,
        FlowVersion.version_number == version_number
    ).first()
    
    if not source_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found"
        )
    
    description = f"Reverted from version {version_number}"
    if revert_data and revert_data.get("description"):
        description = revert_data["description"]
    
    publish_immediately = revert_data.get("publish_immediately", False) if revert_data else False
    
    if tool.draft_version_id:
        existing_draft = db.query(FlowVersion).filter(
            FlowVersion.id == tool.draft_version_id
        ).first()
        if existing_draft:
            db.delete(existing_draft)
    
    next_version = (tool.published_version_number or 0) + 1
    
    new_version = FlowVersion(
        id=uuid.uuid4(),
        tool_id=tool_id,
        version_number=next_version,
        status=FlowVersionStatus.PUBLISHED if publish_immediately else FlowVersionStatus.DRAFT,
        description=description,
        flow_config=source_version.flow_config,
        published_at=datetime.now(timezone.utc) if publish_immediately else None,
    )
    db.add(new_version)
    db.flush()
    
    if publish_immediately:
        tool.published_version_id = new_version.id
        tool.published_version_number = next_version
        tool.draft_version_id = None
        tool.config = new_version.flow_config
        message = f"Reverted to version {version_number} and published as version {next_version}"
    else:
        tool.draft_version_id = new_version.id
        message = f"Created draft from version {version_number}"
    
    db.commit()
    db.refresh(new_version)
    
    return {
        "tool_id": tool_id,
        "version_id": str(new_version.id),
        "version_number": new_version.version_number,
        "status": new_version.status.value,
        "description": new_version.description,
        "message": message
    }


@router.put("/{tool_id}/flow")
def update_tool_flow_legacy(
    tool_id: str,
    hotel_id: str,
    flow_data: dict,
    db: Session = Depends(get_db)
):
    """
    Legacy endpoint for saving flow configuration.
    
    Now saves as a draft for versioning workflow.
    Use PUT /flow/draft for explicit draft saves.
    """
    return save_flow_draft(tool_id, hotel_id, flow_data, db)

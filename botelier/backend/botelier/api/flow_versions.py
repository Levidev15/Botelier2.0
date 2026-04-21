"""
Flow Versions API endpoints.

Provides endpoints for managing versioned flow configurations:
- Save drafts
- Publish versions
- List version history
- Revert to previous versions

Tools are scoped through their ToolSet's account_id for multi-tenant isolation.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Tuple
from datetime import datetime, timezone
import uuid

from botelier.database import get_db
from botelier.models.tool import Tool, ToolType as DBToolType
from botelier.models.tool_set import ToolSet
from botelier.models.flow_version import FlowVersion, FlowVersionStatus
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission

router = APIRouter(prefix="/api/tools", tags=["flow-versions"])


def _get_flow_tool(db: Session, tool_id: str, account_id: str) -> Tool:
    """Fetch a flow tool by ID, scoped through ToolSet.account_id."""
    tool = db.query(Tool).join(
        ToolSet, Tool.tool_set_id == ToolSet.id
    ).filter(
        Tool.id == tool_id,
        ToolSet.account_id == account_id
    ).first()

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this account"
        )

    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool"
        )

    return tool


def validate_flow_config(flow_config: dict) -> Tuple[bool, List[str]]:
    """
    Validate a flow configuration for publishing.
    
    Returns (is_valid, errors) tuple.
    """
    errors = []
    
    nodes = flow_config.get("nodes", [])
    edges = flow_config.get("edges", [])
    
    if not nodes:
        errors.append("Flow must have at least one node")
        return False, errors
    
    initial_nodes = [n for n in nodes if n.get("type") == "initial"]
    if len(initial_nodes) == 0:
        errors.append("Flow must have a Start node")
    elif len(initial_nodes) > 1:
        errors.append("Flow can only have one Start node")
    
    initial_node_id = flow_config.get("initial_node")
    if not initial_node_id:
        errors.append("No initial node specified in flow configuration")
    else:
        initial_exists = any(n.get("id") == initial_node_id for n in nodes)
        if not initial_exists:
            errors.append(f"Initial node '{initial_node_id}' does not exist in flow")
    
    node_ids = {n.get("id") for n in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and source not in node_ids:
            errors.append(f"Edge references non-existent source node: {source}")
        if target and target not in node_ids:
            errors.append(f"Edge references non-existent target node: {target}")
    
    if initial_node_id and initial_node_id in node_ids:
        connected = set()
        to_visit = [initial_node_id]
        edge_map = {}
        for edge in edges:
            source = edge.get("source")
            if source not in edge_map:
                edge_map[source] = []
            edge_map[source].append(edge.get("target"))
        
        while to_visit:
            current = to_visit.pop()
            if current in connected:
                continue
            connected.add(current)
            for target in edge_map.get(current, []):
                if target not in connected:
                    to_visit.append(target)
        
        end_nodes = [n for n in nodes if n.get("type") == "end"]
        end_ids = {n.get("id") for n in end_nodes}
        
        disconnected = node_ids - connected
        critical_disconnected = disconnected - end_ids
        if critical_disconnected:
            for node_id in critical_disconnected:
                node = next((n for n in nodes if n.get("id") == node_id), None)
                if node:
                    errors.append(f"Node '{node.get('data', {}).get('name', node_id)}' is not reachable from Start")
    
    for node in nodes:
        node_type = node.get("type")
        node_data = node.get("data", {})
        node_name = node_data.get("name", node.get("id"))
        
        if node_type == "collect_slot":
            slot = node_data.get("slot", {})
            if not slot.get("variableKey"):
                errors.append(f"Collect Input node '{node_name}' has no variable key")
            if not slot.get("prompt"):
                errors.append(f"Collect Input node '{node_name}' has no prompt")
        
        elif node_type == "api_request":
            api = node_data.get("api", {})
            if not api.get("url"):
                errors.append(f"API Request node '{node_name}' has no URL")
        
        elif node_type == "condition":
            condition = node_data.get("condition", {})
            if not condition.get("variable"):
                errors.append(f"Condition node '{node_name}' has no variable to check")
        
        elif node_type == "router":
            router_cfg = node_data.get("router", {})
            if not router_cfg.get("variable"):
                errors.append(f"Router node '{node_name}' has no variable to route on")
            if not router_cfg.get("options"):
                errors.append(f"Router node '{node_name}' has no routing options")
        
        elif node_type == "transfer":
            transfer = node_data.get("transfer", {})
            if not transfer.get("phoneNumber"):
                errors.append(f"Transfer node '{node_name}' has no phone number")
        
        elif node_type == "set_variable":
            set_var = node_data.get("setVariable", node_data.get("set_variable", {}))
            if set_var.get("valueType") == "expression" or set_var.get("value_type") == "expression":
                errors.append(f"Set Variable node '{node_name}' uses the expression type, which is not permitted")
    
    return len(errors) == 0, errors


@router.get("/{tool_id}/flow")
def get_tool_flow(
    tool_id: str,
    account_id: str,
    source: Optional[str] = None,
    version: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    Get flow configuration for a flow-type tool.
    
    Query Parameters:
        - source: 'draft', 'published', or omit for auto-select (draft if exists, else published)
        - version: Specific version number to fetch (overrides source)
    
    Returns the visual flow editor data (nodes, edges, variables).
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
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
                "account_id": account_id,
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
        "account_id": account_id,
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
    account_id: str,
    draft_data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.edit", db)
    """
    Save flow as a draft.
    
    Creates or updates the draft version. Drafts can be tested in the simulator
    before publishing to production.
    
    Body:
        - flow_config: The flow configuration (nodes, edges, variables)
        - description: Optional description for this version
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
    flow_config = draft_data.get("flow_config", {})
    description = draft_data.get("description")
    
    if flow_config:
        _, draft_errors = validate_flow_config(flow_config)
        expression_errors = [e for e in draft_errors if "expression type" in e]
        if expression_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Flow configuration contains disallowed content", "errors": expression_errors}
            )
    
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
    account_id: str,
    publish_data: Optional[dict] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.publish", db)
    """
    Publish the current draft as a new version.
    
    The draft becomes immutable and is used for live calls.
    A new draft can be created for future edits.
    
    Body (optional):
        - description: Override or set the version description
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
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
    
    is_valid, validation_errors = validate_flow_config(draft.flow_config or {})
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Flow validation failed",
                "errors": validation_errors
            }
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
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.edit", db)
    """
    Discard the current draft.
    
    Reverts to the last published version for editing.
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
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
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    List all versions of a flow.
    
    Returns version history without full flow_config (for performance).
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
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
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    Get a specific version of a flow.
    
    Returns the full flow_config for the requested version.
    """
    _get_flow_tool(db, tool_id, account_id)
    
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
    account_id: str,
    revert_data: Optional[dict] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.revert", db)
    """
    Revert to a previous version.
    
    Updates the current draft with content from the selected version.
    Does not create a new version number - simply restores the content.
    """
    tool = _get_flow_tool(db, tool_id, account_id)
    
    source_version = db.query(FlowVersion).filter(
        FlowVersion.tool_id == tool_id,
        FlowVersion.version_number == version_number
    ).first()
    
    if not source_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found"
        )
    
    if tool.draft_version_id:
        existing_draft = db.query(FlowVersion).filter(
            FlowVersion.id == tool.draft_version_id
        ).first()
        if existing_draft:
            existing_draft.flow_config = source_version.flow_config
            existing_draft.description = f"Restored from version {version_number}"
            tool.config = source_version.flow_config
            db.commit()
            db.refresh(existing_draft)
            return {
                "tool_id": tool_id,
                "version_id": str(existing_draft.id),
                "version_number": existing_draft.version_number,
                "status": existing_draft.status.value,
                "description": existing_draft.description,
                "message": f"Restored content from version {version_number}",
                "flow_config": existing_draft.flow_config
            }
    
    next_version = (tool.published_version_number or 0) + 1
    
    max_version = db.query(FlowVersion).filter(
        FlowVersion.tool_id == tool_id
    ).order_by(desc(FlowVersion.version_number)).first()
    
    if max_version and max_version.version_number >= next_version:
        next_version = max_version.version_number + 1
    
    new_draft = FlowVersion(
        id=uuid.uuid4(),
        tool_id=tool_id,
        version_number=next_version,
        status=FlowVersionStatus.DRAFT,
        description=f"Restored from version {version_number}",
        flow_config=source_version.flow_config,
    )
    db.add(new_draft)
    
    tool.draft_version_id = new_draft.id
    tool.config = source_version.flow_config
    db.commit()
    db.refresh(new_draft)
    
    return {
        "tool_id": tool_id,
        "version_id": str(new_draft.id),
        "version_number": new_draft.version_number,
        "status": new_draft.status.value,
        "description": new_draft.description,
        "message": f"Restored content from version {version_number}",
        "flow_config": new_draft.flow_config
    }


@router.put("/{tool_id}/flow")
def update_tool_flow_legacy(
    tool_id: str,
    account_id: str,
    flow_data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Legacy endpoint for saving flow configuration.
    
    Now saves as a draft for versioning workflow.
    Use PUT /flow/draft for explicit draft saves.
    """
    return save_flow_draft(tool_id, account_id, flow_data, db, user)

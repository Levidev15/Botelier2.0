"""
Flow Templates API - Pre-built conversation flow templates.

Endpoints:
- GET /api/flow-templates - List available templates
- GET /api/flow-templates/{template_id} - Get a specific template
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from botelier.voice.flows.templates import FlowTemplates


router = APIRouter(prefix="/api/flow-templates", tags=["flow-templates"])


class TemplateInfo(BaseModel):
    """Template metadata."""
    id: str
    name: str
    description: str
    complexity: str
    nodes_count: int


class TemplateResponse(BaseModel):
    """Full template with flow configuration."""
    id: str
    name: str
    description: str
    complexity: str
    nodes_count: int
    flow_config: Dict[str, Any]


@router.get("", response_model=List[TemplateInfo])
async def list_templates():
    """
    List all available flow templates.
    
    Returns metadata about each template without the full configuration.
    """
    return FlowTemplates.list_templates()


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    """
    Get a specific flow template with its full configuration.
    
    Path params:
    - template_id: Template identifier (faq_bot, booking_flow, etc.)
    
    Returns:
    - Template metadata and flow configuration
    """
    templates = {t["id"]: t for t in FlowTemplates.list_templates()}
    
    if template_id not in templates:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found. Available: {list(templates.keys())}"
        )
    
    template_info = templates[template_id]
    flow_config = FlowTemplates.get_template(template_id)
    
    return {
        **template_info,
        "flow_config": flow_config
    }

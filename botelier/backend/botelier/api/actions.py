"""Action Library API.

Reusable no-code actions for certified integrations and account-owned custom
HTTP APIs.
"""

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.integration import (
    IntegrationAction,
    IntegrationActionInvocation,
    IntegrationActionKind,
    IntegrationActionStatus,
    IntegrationActionVersion,
)
from botelier.services.action_executor import (
    ActionContext,
    ActionExecutionRequest,
    ActionExecutor,
)

router = APIRouter(prefix="/api/actions", tags=["actions"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class ActionConfig(BaseModel):
    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    bodyTemplate: Optional[str] = None
    response_mapping: dict[str, str] = Field(default_factory=dict)
    timeout: int = 5
    retryCount: int = 0
    onSuccess: Optional[str] = None
    onError: Optional[str] = None
    onNotFound: Optional[str] = None
    onAuthError: Optional[str] = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        method = value.upper()
        if method not in _METHODS:
            raise ValueError(f"method must be one of {sorted(_METHODS)}")
        return method

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value < 1 or value > 30:
            raise ValueError("timeout must be between 1 and 30 seconds")
        return value


class ActionCreate(BaseModel):
    account_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    slug: str
    config: ActionConfig
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SLUG_RE.match(value):
            raise ValueError("slug must use lowercase letters, digits, underscores, or hyphens")
        return value


class ActionDraftUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[ActionConfig] = None
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None


class ActionTestRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    draft: bool = True


def _action_query(db: Session, account_id: str):
    return db.query(IntegrationAction).filter(
        (IntegrationAction.account_id == account_id) | (IntegrationAction.account_id.is_(None))
    )


def _get_action(db: Session, account_id: str, action_id: str) -> IntegrationAction:
    action = _action_query(db, account_id).filter(IntegrationAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


def _get_draft(db: Session, action_id: str) -> Optional[IntegrationActionVersion]:
    return (
        db.query(IntegrationActionVersion)
        .filter(
            IntegrationActionVersion.action_id == action_id,
            IntegrationActionVersion.status == IntegrationActionStatus.DRAFT,
        )
        .order_by(IntegrationActionVersion.version_number.desc())
        .first()
    )


@router.get("")
def list_actions(
    account_id: str,
    include_disabled: bool = False,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.view", db)
    query = _action_query(db, account_id)
    if not include_disabled:
        query = query.filter(IntegrationAction.status != IntegrationActionStatus.DISABLED)
    actions = query.order_by(IntegrationAction.name.asc()).all()
    return {"actions": [a.to_dict() for a in actions], "total": len(actions)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_action(
    body: ActionCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, body.account_id, "integrations.manage", db)
    existing = (
        db.query(IntegrationAction)
        .filter(IntegrationAction.account_id == body.account_id, IntegrationAction.slug == body.slug)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="An action with this slug already exists")

    action = IntegrationAction(
        id=uuid.uuid4(),
        account_id=body.account_id,
        name=body.name,
        description=body.description,
        slug=body.slug,
        kind=IntegrationActionKind.CUSTOM_HTTP,
        status=IntegrationActionStatus.DRAFT,
        created_by_user_id=getattr(current_user, "id", None),
    )
    version = IntegrationActionVersion(
        id=uuid.uuid4(),
        action_id=action.id,
        version_number=1,
        status=IntegrationActionStatus.DRAFT,
        config=body.config.model_dump(exclude_none=True),
        input_schema=body.input_schema,
        output_schema=body.output_schema,
    )
    db.add(action)
    db.add(version)
    db.commit()
    db.refresh(action)
    return {**action.to_dict(), "draft_version": version.to_dict()}


@router.put("/{action_id}/draft")
def update_action_draft(
    action_id: str,
    account_id: str,
    body: ActionDraftUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.manage", db)
    action = _get_action(db, account_id, action_id)
    if action.account_id is None:
        raise HTTPException(status_code=403, detail="Certified actions cannot be edited here")
    draft = _get_draft(db, action_id)
    if not draft:
        max_version = (
            db.query(IntegrationActionVersion)
            .filter(IntegrationActionVersion.action_id == action.id)
            .order_by(IntegrationActionVersion.version_number.desc())
            .first()
        )
        base_config = {}
        base_input = {}
        base_output = {}
        if action.published_version_id:
            published = (
                db.query(IntegrationActionVersion)
                .filter(IntegrationActionVersion.id == action.published_version_id)
                .first()
            )
            if published:
                base_config = published.config
                base_input = published.input_schema
                base_output = published.output_schema
        draft = IntegrationActionVersion(
            id=uuid.uuid4(),
            action_id=action.id,
            version_number=(max_version.version_number if max_version else 0) + 1,
            status=IntegrationActionStatus.DRAFT,
            config=base_config,
            input_schema=base_input,
            output_schema=base_output,
        )
        db.add(draft)

    if body.name is not None:
        action.name = body.name
    if body.description is not None:
        action.description = body.description
    if body.config is not None:
        draft.config = body.config.model_dump(exclude_none=True)
        action.last_test_success = None
        action.last_tested_at = None
    if body.input_schema is not None:
        draft.input_schema = body.input_schema
        action.last_test_success = None
        action.last_tested_at = None
    if body.output_schema is not None:
        draft.output_schema = body.output_schema
        action.last_test_success = None
        action.last_tested_at = None
    action.status = IntegrationActionStatus.DRAFT
    action.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(action)
    return {**action.to_dict(), "draft_version": draft.to_dict()}


@router.post("/{action_id}/test")
async def test_action(
    action_id: str,
    account_id: str,
    body: ActionTestRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.manage", db)
    action = _get_action(db, account_id, action_id)
    version = _get_draft(db, action_id) if body.draft else None
    version_id = str(version.id) if version else None
    result = await ActionExecutor(db).execute_and_log(
        ActionExecutionRequest(
            context=ActionContext(account_id=account_id, channel="test"),
            action_id=action_id,
            action_version_id=version_id,
            variables=body.variables,
        )
    )
    action.last_tested_at = datetime.utcnow()
    action.last_test_success = result.success
    action.last_error = None if result.success else result.error_message
    db.commit()
    return {
        "success": result.success,
        "status_code": result.status_code,
        "data": result.data,
        "error_type": result.error_type.value,
        "error_message": result.error_message,
        "extracted_variables": result.extracted_variables,
        "request_id": result.request_id,
        "latency_ms": result.latency_ms,
    }


@router.post("/{action_id}/publish")
def publish_action(
    action_id: str,
    account_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.manage", db)
    action = _get_action(db, account_id, action_id)
    if action.account_id is None:
        raise HTTPException(status_code=403, detail="Certified actions are platform managed")
    draft = _get_draft(db, action_id)
    if not draft:
        raise HTTPException(status_code=400, detail="No draft to publish")
    if action.last_test_success is not True:
        raise HTTPException(status_code=400, detail="Action must pass a test before publishing")
    draft.status = IntegrationActionStatus.PUBLISHED
    draft.published_at = datetime.utcnow()
    action.published_version_id = draft.id
    action.status = IntegrationActionStatus.PUBLISHED
    action.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(action)
    return {**action.to_dict(), "published_version": draft.to_dict()}


@router.post("/{action_id}/disable")
def disable_action(
    action_id: str,
    account_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.manage", db)
    action = _get_action(db, account_id, action_id)
    if action.account_id is None:
        raise HTTPException(status_code=403, detail="Certified actions are platform managed")
    action.status = IntegrationActionStatus.DISABLED
    action.updated_at = datetime.utcnow()
    db.commit()
    return {"id": action_id, "status": "disabled"}


@router.get("/{action_id}/invocations")
def list_action_invocations(
    action_id: str,
    account_id: str,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_account_permission(current_user, account_id, "integrations.manage", db)
    _get_action(db, account_id, action_id)
    rows = (
        db.query(IntegrationActionInvocation)
        .filter(
            IntegrationActionInvocation.account_id == account_id,
            IntegrationActionInvocation.action_id == action_id,
        )
        .order_by(IntegrationActionInvocation.called_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return {
        "invocations": [
            {
                "id": str(row.id),
                "request_id": row.request_id,
                "channel": row.channel,
                "method": row.method,
                "endpoint_called": row.endpoint_called,
                "status_code": row.status_code,
                "success": row.success,
                "latency_ms": row.latency_ms,
                "error_type": row.error_type,
                "error_message": row.error_message,
                "called_at": row.called_at.isoformat() if row.called_at else None,
            }
            for row in rows
        ]
    }

"""
Account Team Management API Endpoints.

Provides endpoints for account admins to manage team members,
invitations, and custom roles for their account.
All endpoints require appropriate team.* permissions.
"""

import re
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.user import User
from botelier.models.role import Role, AccountMembership
from botelier.models.invitation import AccountInvitation, InvitationStatus
from botelier.auth.middleware import AccountContext, get_account_context


router = APIRouter(prefix="/api/accounts/{account_id}/team", tags=["Team"])


class MemberResponse(BaseModel):
    membership_id: str
    user_id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    display_name: str
    profile_image_url: Optional[str]
    role_id: str
    role_name: str
    role_slug: str
    is_owner: bool
    accepted_at: Optional[datetime]
    created_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role_id: str


class InvitationResponse(BaseModel):
    id: str
    invitee_email: str
    role_id: str
    role_name: str
    invited_by_name: str
    status: str
    token: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    created_at: datetime


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role_id: str


class RoleResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    is_system_role: bool
    permissions: dict
    member_count: int
    created_at: datetime


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    permissions: dict = Field(default_factory=dict)


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    permissions: Optional[dict] = None


def _generate_role_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:50]


def _build_member_response(m: AccountMembership) -> MemberResponse:
    user = m.user
    return MemberResponse(
        membership_id=str(m.id),
        user_id=str(user.id),
        email=user.email or "",
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        profile_image_url=user.profile_image_url,
        role_id=str(m.role_id),
        role_name=m.role.name if m.role else "Unknown",
        role_slug=m.role.slug if m.role else "",
        is_owner=m.is_owner,
        accepted_at=m.accepted_at,
        created_at=m.created_at,
    )


def _build_role_response(role: Role, member_count: int) -> RoleResponse:
    return RoleResponse(
        id=str(role.id),
        name=role.name,
        slug=role.slug,
        description=role.description,
        is_system_role=role.is_system_role,
        permissions=role.permissions or {},
        member_count=member_count,
        created_at=role.created_at,
    )


@router.get("/members", response_model=List[MemberResponse])
async def list_members(
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """List all active members of the account."""
    ctx.require_permission("team.view")

    memberships = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == ctx.account.id,
            AccountMembership.is_active == True,
        )
        .all()
    )

    return [_build_member_response(m) for m in memberships]


@router.patch("/members/{membership_id}", response_model=MemberResponse)
async def update_member_role(
    membership_id: str,
    data: UpdateMemberRoleRequest,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Change a member's role."""
    ctx.require_permission("team.manage_roles")

    membership = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.id == membership_id,
            AccountMembership.account_id == ctx.account.id,
            AccountMembership.is_active == True,
        )
        .first()
    )

    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    if membership.is_owner:
        raise HTTPException(status_code=400, detail="Cannot change the owner's role")

    role = (
        db.query(Role)
        .filter(
            Role.id == data.role_id,
            or_(
                Role.account_id == ctx.account.id,
                (Role.account_id == None) & (Role.is_system_role == True),
            ),
        )
        .first()
    )

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    membership.role_id = role.id
    db.commit()
    db.refresh(membership)

    return _build_member_response(membership)


@router.delete("/members/{membership_id}")
async def remove_member(
    membership_id: str,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Remove a member from the account."""
    ctx.require_permission("team.remove")

    membership = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.id == membership_id,
            AccountMembership.account_id == ctx.account.id,
            AccountMembership.is_active == True,
        )
        .first()
    )

    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    if membership.is_owner:
        raise HTTPException(status_code=400, detail="Cannot remove the account owner")

    if str(membership.user_id) == str(ctx.user.id):
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    membership.is_active = False
    db.commit()

    return {"success": True, "message": "Member removed successfully"}


@router.get("/invitations", response_model=List[InvitationResponse])
async def list_invitations(
    status: Optional[str] = None,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """List invitations for the account."""
    ctx.require_permission("team.view")

    query = db.query(AccountInvitation).filter(
        AccountInvitation.account_id == ctx.account.id,
    )

    if status:
        try:
            status_enum = InvitationStatus(status)
            query = query.filter(AccountInvitation.status == status_enum)
        except ValueError:
            pass

    invitations = query.order_by(AccountInvitation.created_at.desc()).all()

    now = datetime.utcnow()
    stale_updated = False
    result = []
    for inv in invitations:
        effective_status = inv.status
        if inv.status == InvitationStatus.PENDING and inv.expires_at < now:
            inv.status = InvitationStatus.EXPIRED
            effective_status = InvitationStatus.EXPIRED
            stale_updated = True

        result.append(
            InvitationResponse(
                id=str(inv.id),
                invitee_email=inv.invitee_email,
                role_id=str(inv.role_id),
                role_name=inv.role.name if inv.role else "Unknown",
                invited_by_name=inv.invited_by.display_name if inv.invited_by else "Unknown",
                status=effective_status.value,
                token=inv.token,
                expires_at=inv.expires_at,
                accepted_at=inv.accepted_at,
                created_at=inv.created_at,
            )
        )

    if stale_updated:
        db.commit()

    return result


@router.post("/invitations", response_model=InvitationResponse)
async def create_invitation(
    data: CreateInvitationRequest,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Create an invitation to join the account. Returns token for link building."""
    ctx.require_permission("team.invite")

    role = (
        db.query(Role)
        .filter(
            Role.id == data.role_id,
            or_(
                Role.account_id == ctx.account.id,
                (Role.account_id == None) & (Role.is_system_role == True),
            ),
        )
        .first()
    )

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    email_lower = data.email.lower()

    existing_user = db.query(User).filter(User.email == email_lower).first()
    if existing_user:
        existing_membership = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == existing_user.id,
                AccountMembership.account_id == ctx.account.id,
                AccountMembership.is_active == True,
            )
            .first()
        )
        if existing_membership:
            raise HTTPException(
                status_code=400,
                detail="This user is already a member of this account",
            )

    existing_invitation = (
        db.query(AccountInvitation)
        .filter(
            AccountInvitation.account_id == ctx.account.id,
            AccountInvitation.invitee_email == email_lower,
            AccountInvitation.status == InvitationStatus.PENDING,
        )
        .first()
    )

    if existing_invitation and not existing_invitation.is_expired:
        raise HTTPException(
            status_code=400,
            detail="An active invitation already exists for this email",
        )

    invitation = AccountInvitation(
        account_id=ctx.account.id,
        invitee_email=email_lower,
        role_id=role.id,
        invited_by_id=ctx.user.id,
        token=AccountInvitation.generate_token(),
        expires_at=AccountInvitation.default_expiration(days=7),
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return InvitationResponse(
        id=str(invitation.id),
        invitee_email=invitation.invitee_email,
        role_id=str(invitation.role_id),
        role_name=role.name,
        invited_by_name=ctx.user.display_name,
        status=invitation.status.value,
        token=invitation.token,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
    )


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Revoke a pending invitation."""
    ctx.require_permission("team.invite")

    invitation = (
        db.query(AccountInvitation)
        .filter(
            AccountInvitation.id == invitation_id,
            AccountInvitation.account_id == ctx.account.id,
        )
        .first()
    )

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400, detail="Only pending invitations can be revoked"
        )

    invitation.revoke()
    db.commit()

    return {"success": True, "message": "Invitation revoked"}


@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """List all roles for the account (system roles + custom roles)."""
    ctx.require_permission("team.view")

    roles = (
        db.query(Role)
        .filter(
            or_(
                Role.account_id == ctx.account.id,
                (Role.account_id == None) & (Role.is_system_role == True),
            )
        )
        .order_by(Role.is_system_role.desc(), Role.created_at.asc())
        .all()
    )

    result = []
    for role in roles:
        member_count = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.account_id == ctx.account.id,
                AccountMembership.role_id == role.id,
                AccountMembership.is_active == True,
            )
            .count()
        )
        result.append(_build_role_response(role, member_count))

    return result


@router.post("/roles", response_model=RoleResponse)
async def create_role(
    data: CreateRoleRequest,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Create a custom role for the account."""
    ctx.require_permission("team.manage_roles")

    slug = _generate_role_slug(data.name)

    existing = (
        db.query(Role)
        .filter(Role.account_id == ctx.account.id, Role.slug == slug)
        .first()
    )

    if existing:
        counter = 1
        while (
            db.query(Role)
            .filter(
                Role.account_id == ctx.account.id,
                Role.slug == f"{slug}-{counter}",
            )
            .first()
        ):
            counter += 1
        slug = f"{slug}-{counter}"

    role = Role(
        name=data.name,
        slug=slug,
        description=data.description,
        is_system_role=False,
        account_id=ctx.account.id,
        permissions=data.permissions,
    )

    db.add(role)
    db.commit()
    db.refresh(role)

    return _build_role_response(role, 0)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    data: UpdateRoleRequest,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Update a custom role's name, description, or permissions."""
    ctx.require_permission("team.manage_roles")

    role = (
        db.query(Role)
        .filter(Role.id == role_id, Role.account_id == ctx.account.id)
        .first()
    )

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.is_system_role:
        raise HTTPException(status_code=400, detail="System roles cannot be modified")

    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.permissions is not None:
        role.permissions = data.permissions

    db.commit()
    db.refresh(role)

    member_count = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == ctx.account.id,
            AccountMembership.role_id == role.id,
            AccountMembership.is_active == True,
        )
        .count()
    )

    return _build_role_response(role, member_count)


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    ctx: AccountContext = Depends(get_account_context("account_id")),
    db: Session = Depends(get_db),
):
    """Delete a custom role. Fails if members are still assigned to it."""
    ctx.require_permission("team.manage_roles")

    role = (
        db.query(Role)
        .filter(Role.id == role_id, Role.account_id == ctx.account.id)
        .first()
    )

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.is_system_role:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")

    member_count = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == ctx.account.id,
            AccountMembership.role_id == role.id,
            AccountMembership.is_active == True,
        )
        .count()
    )

    if member_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete role: {member_count} member(s) are using this role. Reassign them first.",
        )

    db.delete(role)
    db.commit()

    return {"success": True, "message": "Role deleted"}

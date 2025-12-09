"""
Public Invitation API Endpoints.

Provides endpoints for accepting invitations (public access with token validation).
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.invitation import AccountInvitation, InvitationStatus
from botelier.models.user import User, UserType
from botelier.models.role import AccountMembership
from botelier.auth.middleware import get_current_user


router = APIRouter(prefix="/api/invitations", tags=["Invitations"])


class InvitationVerifyResponse(BaseModel):
    valid: bool
    invitation_id: str = None
    account_name: str = None
    role_name: str = None
    invitee_email: str = None
    expires_at: str = None
    error: str = None


class InvitationAcceptRequest(BaseModel):
    token: str


class InvitationAcceptResponse(BaseModel):
    success: bool
    message: str
    account_id: str = None
    account_name: str = None
    account_slug: str = None


@router.get("/verify/{token}", response_model=InvitationVerifyResponse)
async def verify_invitation(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Verify an invitation token (public endpoint).
    
    Returns invitation details if valid, or error if invalid/expired.
    """
    invitation = db.query(AccountInvitation).filter(
        AccountInvitation.token == token
    ).first()
    
    if not invitation:
        return InvitationVerifyResponse(
            valid=False,
            error="Invitation not found"
        )
    
    if invitation.status == InvitationStatus.ACCEPTED:
        return InvitationVerifyResponse(
            valid=False,
            error="Invitation has already been accepted"
        )
    
    if invitation.status == InvitationStatus.REVOKED:
        return InvitationVerifyResponse(
            valid=False,
            error="Invitation has been revoked"
        )
    
    if invitation.is_expired:
        if invitation.status == InvitationStatus.PENDING:
            invitation.expire()
            db.commit()
        return InvitationVerifyResponse(
            valid=False,
            error="Invitation has expired"
        )
    
    return InvitationVerifyResponse(
        valid=True,
        invitation_id=str(invitation.id),
        account_name=invitation.account.name if invitation.account else "Unknown",
        role_name=invitation.role.name if invitation.role else "Unknown",
        invitee_email=invitation.invitee_email,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.post("/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    data: InvitationAcceptRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept an invitation (requires authenticated user).
    
    Creates account membership linking the user to the account with the invited role.
    """
    invitation = db.query(AccountInvitation).filter(
        AccountInvitation.token == data.token
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if not invitation.is_valid:
        if invitation.status == InvitationStatus.ACCEPTED:
            raise HTTPException(status_code=400, detail="Invitation has already been accepted")
        elif invitation.status == InvitationStatus.REVOKED:
            raise HTTPException(status_code=400, detail="Invitation has been revoked")
        elif invitation.is_expired:
            if invitation.status == InvitationStatus.PENDING:
                invitation.expire()
                db.commit()
            raise HTTPException(status_code=400, detail="Invitation has expired")
    
    if user.email and user.email.lower() != invitation.invitee_email.lower():
        raise HTTPException(
            status_code=400, 
            detail=f"This invitation was sent to {invitation.invitee_email}. Please sign in with that email."
        )
    
    existing_membership = db.query(AccountMembership).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.account_id == invitation.account_id,
    ).first()
    
    if existing_membership:
        if existing_membership.is_active:
            raise HTTPException(status_code=400, detail="You are already a member of this account")
        else:
            existing_membership.is_active = True
            existing_membership.role_id = invitation.role_id
            existing_membership.invited_by_id = invitation.invited_by_id
            existing_membership.invited_at = invitation.created_at
            existing_membership.accepted_at = datetime.utcnow()
    else:
        membership = AccountMembership(
            user_id=user.id,
            account_id=invitation.account_id,
            role_id=invitation.role_id,
            invited_by_id=invitation.invited_by_id,
            invited_at=invitation.created_at,
            accepted_at=datetime.utcnow(),
        )
        db.add(membership)
    
    invitation.accept()
    
    if not user.email and invitation.invitee_email:
        user.email = invitation.invitee_email
    
    db.commit()
    
    return InvitationAcceptResponse(
        success=True,
        message=f"Successfully joined {invitation.account.name}",
        account_id=str(invitation.account_id),
        account_name=invitation.account.name if invitation.account else None,
        account_slug=invitation.account.slug if invitation.account else None,
    )

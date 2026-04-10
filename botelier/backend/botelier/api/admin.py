"""
Platform Admin API Endpoints.

Provides endpoints for platform administrators to manage accounts, users, and platform settings.
All endpoints require platform_admin user type.
"""

import uuid
import re
import secrets
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from botelier.database import get_db
from botelier.models.account import Account, AccountStatus, SubscriptionTier
from botelier.models.user import User, UserType, SupportSession
from botelier.models.role import Role, AccountMembership
from botelier.models.invitation import AccountInvitation, InvitationStatus
from botelier.auth.permissions import DEFAULT_ROLES, PLATFORM_ADMIN_PERMISSIONS
from botelier.auth.middleware import get_platform_admin, get_current_user
from botelier.auth.features import FEATURE_CATALOG, get_account_features


router = APIRouter(prefix="/api/admin", tags=["Admin"])


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = None
    business_type: Optional[str] = None
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    
    @validator("name")
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    business_type: Optional[str] = None
    status: Optional[AccountStatus] = None
    subscription_tier: Optional[SubscriptionTier] = None


class AccountResponse(BaseModel):
    id: str
    name: str
    slug: str
    email: str
    phone: Optional[str]
    business_type: Optional[str]
    status: str
    subscription_tier: str
    has_twilio: bool
    twilio_sub_account_sid: Optional[str]
    member_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class AccountListResponse(BaseModel):
    accounts: List[AccountResponse]
    total: int
    page: int
    page_size: int


class UserResponse(BaseModel):
    id: str
    replit_id: str
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    profile_image_url: Optional[str]
    user_type: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class MakePlatformAdminRequest(BaseModel):
    user_id: str


class InvitationCreate(BaseModel):
    account_id: str
    email: EmailStr
    role_id: str


class InvitationResponse(BaseModel):
    id: str
    account_id: str
    account_name: str
    invitee_email: str
    role_id: str
    role_name: str
    invited_by_id: str
    invited_by_name: str
    status: str
    token: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class InvitationListResponse(BaseModel):
    invitations: List[InvitationResponse]
    total: int
    page: int
    page_size: int


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from name."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


def ensure_unique_slug(db: Session, base_slug: str) -> str:
    """Ensure slug is unique by appending numbers if needed."""
    slug = base_slug
    counter = 1
    
    while db.query(Account).filter(Account.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    return slug


@router.get("/accounts", response_model=AccountListResponse)
async def list_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[AccountStatus] = None,
    search: Optional[str] = None,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """List all accounts with pagination and filtering."""
    query = db.query(Account)
    
    if status:
        query = query.filter(Account.status == status)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Account.name.ilike(search_term)) |
            (Account.email.ilike(search_term)) |
            (Account.slug.ilike(search_term))
        )
    
    total = query.count()
    
    accounts = query.order_by(Account.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    account_responses = []
    for account in accounts:
        member_count = db.query(func.count(AccountMembership.id)).filter(
            AccountMembership.account_id == account.id,
            AccountMembership.is_active == True,
        ).scalar() or 0
        
        account_responses.append(AccountResponse(
            id=str(account.id),
            name=account.name,
            slug=account.slug,
            email=account.email,
            phone=account.phone,
            business_type=account.business_type,
            status=account.status.value,
            subscription_tier=account.subscription_tier.value,
            has_twilio=account.has_twilio,
            twilio_sub_account_sid=account.twilio_sub_account_sid,
            member_count=member_count,
            created_at=account.created_at,
        ))
    
    return AccountListResponse(
        accounts=account_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/accounts", response_model=AccountResponse)
async def create_account(
    data: AccountCreate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Create a new account. A Twilio sub-account is provisioned automatically."""
    base_slug = generate_slug(data.name)
    slug = ensure_unique_slug(db, base_slug)
    
    account = Account(
        name=data.name,
        slug=slug,
        email=data.email,
        phone=data.phone,
        business_type=data.business_type,
        status=AccountStatus.TRIAL,
        subscription_tier=data.subscription_tier,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
    )
    
    db.add(account)
    db.flush()
    
    for role_slug, role_data in DEFAULT_ROLES.items():
        role = Role(
            name=role_data["name"],
            slug=role_slug,
            description=role_data["description"],
            is_system_role=True,
            account_id=account.id,
            permissions=role_data["permissions"],
        )
        db.add(role)
    
    twilio_warning = None
    try:
        from botelier.integrations.twilio.sub_accounts import create_sub_account
        sub_account_data = create_sub_account(data.name)
        account.twilio_sub_account_sid = sub_account_data["sid"]
        account.twilio_sub_auth_token = sub_account_data["auth_token"]
    except Exception as e:
        print(f"WARNING: Failed to auto-provision Twilio sub-account for '{data.name}': {e}")
        twilio_warning = "Twilio sub-account provisioning failed — use 'Retry Twilio Provisioning' on the account page."
    
    db.commit()
    db.refresh(account)
    
    response = AccountResponse(
        id=str(account.id),
        name=account.name,
        slug=account.slug,
        email=account.email,
        phone=account.phone,
        business_type=account.business_type,
        status=account.status.value,
        subscription_tier=account.subscription_tier.value,
        has_twilio=account.has_twilio,
        twilio_sub_account_sid=account.twilio_sub_account_sid,
        member_count=0,
        created_at=account.created_at,
    )
    if twilio_warning:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=201,
            content={**response.model_dump(mode="json"), "warning": twilio_warning},
        )
    return response


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Get account details."""
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    member_count = db.query(func.count(AccountMembership.id)).filter(
        AccountMembership.account_id == account.id,
        AccountMembership.is_active == True,
    ).scalar() or 0
    
    return AccountResponse(
        id=str(account.id),
        name=account.name,
        slug=account.slug,
        email=account.email,
        phone=account.phone,
        business_type=account.business_type,
        status=account.status.value,
        subscription_tier=account.subscription_tier.value,
        has_twilio=account.has_twilio,
        twilio_sub_account_sid=account.twilio_sub_account_sid,
        member_count=member_count,
        created_at=account.created_at,
    )


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    data: AccountUpdate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Update account details."""
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if data.name is not None:
        account.name = data.name
    if data.email is not None:
        account.email = data.email
    if data.phone is not None:
        account.phone = data.phone
    if data.business_type is not None:
        account.business_type = data.business_type
    if data.status is not None:
        account.status = data.status
    if data.subscription_tier is not None:
        account.subscription_tier = data.subscription_tier
    
    db.commit()
    db.refresh(account)
    
    member_count = db.query(func.count(AccountMembership.id)).filter(
        AccountMembership.account_id == account.id,
        AccountMembership.is_active == True,
    ).scalar() or 0
    
    return AccountResponse(
        id=str(account.id),
        name=account.name,
        slug=account.slug,
        email=account.email,
        phone=account.phone,
        business_type=account.business_type,
        status=account.status.value,
        subscription_tier=account.subscription_tier.value,
        has_twilio=account.has_twilio,
        twilio_sub_account_sid=account.twilio_sub_account_sid,
        member_count=member_count,
        created_at=account.created_at,
    )


@router.post("/accounts/{account_id}/provision-twilio")
async def provision_twilio_for_account(
    account_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Retry Twilio sub-account provisioning for an account that has none (initial provisioning failed)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if account.has_twilio:
        raise HTTPException(status_code=400, detail="Account already has a Twilio sub-account. Use PATCH /admin/accounts/{id}/twilio to update the SID.")
    
    try:
        from botelier.integrations.twilio.sub_accounts import create_sub_account
        sub_account_data = create_sub_account(account.name)
        account.twilio_sub_account_sid = sub_account_data["sid"]
        account.twilio_sub_auth_token = sub_account_data["auth_token"]
        db.commit()
        
        return {
            "success": True,
            "message": "Twilio sub-account provisioned successfully",
            "twilio_sub_account_sid": account.twilio_sub_account_sid,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to provision Twilio: {str(e)}")


class TwilioCredentialsUpdate(BaseModel):
    twilio_sub_account_sid: str = Field(..., description="Twilio sub-account SID (AC...)")
    twilio_sub_auth_token: str = Field(..., description="Twilio sub-account auth token")


@router.patch("/accounts/{account_id}/twilio")
async def update_twilio_credentials(
    account_id: str,
    data: TwilioCredentialsUpdate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Update (or correct) the Twilio sub-account SID and auth token for an account.

    Use this when the stored SID is mismatched with the phone numbers in Twilio — for
    example, when a phone number was provisioned on a different Twilio sub-account than
    what is recorded in the database.  Restricted to platform admins.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    account.twilio_sub_account_sid = data.twilio_sub_account_sid.strip()
    account.twilio_sub_auth_token = data.twilio_sub_auth_token.strip()
    db.commit()
    
    return {
        "success": True,
        "message": "Twilio credentials updated successfully",
        "twilio_sub_account_sid": account.twilio_sub_account_sid,
    }


# ---------------------------------------------------------------------------
# Feature entitlement endpoints (admin)
# ---------------------------------------------------------------------------

class FeatureOverrideUpdate(BaseModel):
    """
    PATCH body for updating feature overrides.

    Each key is a feature slug.  Values:
      True  — force-enable regardless of tier
      False — force-disable regardless of tier
      None  — remove override, revert to tier default
    """
    overrides: Dict[str, Optional[bool]]


@router.get("/accounts/{account_id}/features")
async def get_account_features_admin(
    account_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """
    Return resolved feature entitlements for an account plus catalog metadata.

    Response shape:
        {
            "resolved": {"call_recording": true, "qa_scoring": false, ...},
            "overrides": {"call_recording": true},   # raw per-account overrides only
            "catalog": {
                "call_recording": {
                    "name": "Call Recording",
                    "description": "...",
                    "tier_defaults": {"free": false, "professional": true, ...},
                },
                ...
            }
        }
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    overrides = account.feature_flags or {}
    resolved = get_account_features(
        subscription_tier=account.subscription_tier.value,
        feature_flags_override=overrides,
    )

    return {
        "resolved": resolved,
        "overrides": overrides,
        "catalog": FEATURE_CATALOG,
    }


@router.patch("/accounts/{account_id}/features")
async def update_account_features_admin(
    account_id: str,
    data: FeatureOverrideUpdate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """
    Update per-account feature overrides.

    Pass ``null`` (JSON) / ``None`` for a feature slug to remove the override
    and revert to the tier default.  Unrecognised slugs are silently ignored.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    current_overrides: dict = dict(account.feature_flags or {})

    for slug, value in data.overrides.items():
        if slug not in FEATURE_CATALOG:
            continue
        if value is None:
            current_overrides.pop(slug, None)
        else:
            current_overrides[slug] = bool(value)

    account.feature_flags = current_overrides
    db.commit()
    db.refresh(account)

    overrides = account.feature_flags or {}
    resolved = get_account_features(
        subscription_tier=account.subscription_tier.value,
        feature_flags_override=overrides,
    )

    return {
        "resolved": resolved,
        "overrides": overrides,
        "catalog": FEATURE_CATALOG,
    }


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user_type: Optional[UserType] = None,
    search: Optional[str] = None,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """List all users in the platform."""
    query = db.query(User)
    
    if user_type:
        query = query.filter(User.user_type == user_type)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (User.email.ilike(search_term)) |
            (User.first_name.ilike(search_term)) |
            (User.last_name.ilike(search_term))
        )
    
    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return [
        UserResponse(
            id=str(user.id),
            replit_id=user.replit_id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_image_url=user.profile_image_url,
            user_type=user.user_type.value,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
        for user in users
    ]


@router.post("/users/{user_id}/make-platform-admin")
async def make_platform_admin(
    user_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Promote a user to platform admin."""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.user_type = UserType.PLATFORM_ADMIN
    db.commit()
    
    return {"success": True, "message": f"User {user.display_name} is now a platform admin"}


@router.post("/users/{user_id}/remove-platform-admin")
async def remove_platform_admin(
    user_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Demote a platform admin to regular user."""
    if str(admin.id) == user_id:
        raise HTTPException(status_code=400, detail="You cannot demote yourself")
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.user_type = UserType.ACCOUNT_USER
    db.commit()
    
    return {"success": True, "message": f"User {user.display_name} is no longer a platform admin"}


@router.get("/stats")
async def get_platform_stats(
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Get platform-wide statistics."""
    total_accounts = db.query(func.count(Account.id)).scalar() or 0
    active_accounts = db.query(func.count(Account.id)).filter(
        Account.status.in_([AccountStatus.ACTIVE, AccountStatus.TRIAL])
    ).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    platform_admins = db.query(func.count(User.id)).filter(
        User.user_type == UserType.PLATFORM_ADMIN
    ).scalar() or 0
    
    tier_counts = {}
    for tier in SubscriptionTier:
        count = db.query(func.count(Account.id)).filter(
            Account.subscription_tier == tier
        ).scalar() or 0
        tier_counts[tier.value] = count
    
    return {
        "total_accounts": total_accounts,
        "active_accounts": active_accounts,
        "total_users": total_users,
        "platform_admins": platform_admins,
        "accounts_by_tier": tier_counts,
    }


def _get_effective_permissions(membership: AccountMembership) -> dict:
    """
    Compute the effective permission set for a membership.

    Resolution order (last writer wins per key):

    1. ``DEFAULT_ROLES`` template (for system roles only) — provides the
       baseline.  Any key present in the template but absent from the DB row
       is filled in here.  This is the *defensive* layer: it guarantees that
       a permission added to DEFAULT_ROLES is immediately visible after the
       next deploy, even before the startup sync has had a chance to write
       the updated JSON back to the DB row.

    2. ``role.permissions`` (DB row) — the stored copy of the template,
       kept in sync by ``_sync_system_role_permissions()`` at startup.  For
       any key that exists in both the template and the DB row, the DB row
       value wins (so manual overrides applied directly to the DB are
       preserved).

    3. ``membership.permission_overrides`` — per-user overrides that take
       precedence over everything else.  Allows granting or revoking a
       specific permission for a single team member without changing their
       role.

    Custom roles (``is_system_role == False``) skip step 1; they receive
    only their stored permissions plus any user-level overrides.
    """
    import copy

    # Step 1: start from the DEFAULT_ROLES template for system roles.
    # This ensures that any permission added to the template after the role
    # row was first seeded is still included in the resolved set.
    perms: dict = {}
    if membership.role.is_system_role:
        template = DEFAULT_ROLES.get(membership.role.slug, {})
        perms = copy.deepcopy(template.get("permissions", {}))

    # Step 2: layer the DB row on top.  For keys that exist in both the
    # template and the row, the DB value wins.  For keys only in the row
    # (e.g. custom overrides written directly to the DB), they are preserved.
    db_perms = membership.role.permissions or {}
    for category, category_perms in db_perms.items():
        if isinstance(category_perms, dict):
            if category not in perms:
                perms[category] = {}
            for perm, value in category_perms.items():
                perms[category][perm] = value

    # Step 3: apply per-user overrides last.
    if membership.permission_overrides:
        for category, category_perms in membership.permission_overrides.items():
            if isinstance(category_perms, dict):
                if category not in perms:
                    perms[category] = {}
                for perm, value in category_perms.items():
                    perms[category][perm] = value

    return perms


@router.get("/me/permissions")
async def get_my_permissions(
    account_id: str = Query(..., description="Account ID to retrieve permissions for"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's resolved permissions for a specific account."""
    if user.is_platform_admin:
        return {
            "is_platform_admin": True,
            "permissions": PLATFORM_ADMIN_PERMISSIONS,
        }

    membership = db.query(AccountMembership).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.account_id == account_id,
        AccountMembership.is_active == True,
    ).first()

    if not membership:
        raise HTTPException(
            status_code=403,
            detail="You don't have access to this account",
        )

    return {
        "is_platform_admin": False,
        "permissions": _get_effective_permissions(membership),
        "role": {
            "id": str(membership.role_id),
            "name": membership.role.name,
            "slug": membership.role.slug,
        },
    }


@router.get("/me")
async def get_current_admin_user(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user info with role information."""
    memberships = []
    
    for membership in user.account_memberships:
        if membership.is_active:
            memberships.append({
                "account_id": str(membership.account_id),
                "account_name": membership.account.name,
                "account_slug": membership.account.slug,
                "role_id": str(membership.role_id),
                "role_name": membership.role.name,
                "role_slug": membership.role.slug,
                "is_owner": membership.is_owner,
                "permissions": _get_effective_permissions(membership),
            })
    
    return {
        "id": str(user.id),
        "replit_id": user.replit_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name,
        "profile_image_url": user.profile_image_url,
        "user_type": user.user_type.value,
        "is_platform_admin": user.is_platform_admin,
        "is_active": user.is_active,
        "memberships": memberships,
    }


def build_invitation_response(invitation: AccountInvitation) -> InvitationResponse:
    """Build invitation response from model."""
    return InvitationResponse(
        id=str(invitation.id),
        account_id=str(invitation.account_id),
        account_name=invitation.account.name if invitation.account else "Unknown",
        invitee_email=invitation.invitee_email,
        role_id=str(invitation.role_id),
        role_name=invitation.role.name if invitation.role else "Unknown",
        invited_by_id=str(invitation.invited_by_id),
        invited_by_name=invitation.invited_by.display_name if invitation.invited_by else "Unknown",
        status=invitation.status.value,
        token=invitation.token,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[InvitationStatus] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """List all invitations with pagination and filtering."""
    query = db.query(AccountInvitation)
    
    if status:
        query = query.filter(AccountInvitation.status == status)
    
    if account_id:
        query = query.filter(AccountInvitation.account_id == account_id)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(AccountInvitation.invitee_email.ilike(search_term))
    
    total = query.count()
    
    invitations = query.order_by(AccountInvitation.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return InvitationListResponse(
        invitations=[build_invitation_response(inv) for inv in invitations],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/invitations", response_model=InvitationResponse)
async def create_invitation(
    data: InvitationCreate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Create a new invitation to join an account."""
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    role = db.query(Role).filter(Role.id == data.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        existing_membership = db.query(AccountMembership).filter(
            AccountMembership.user_id == existing_user.id,
            AccountMembership.account_id == account.id,
            AccountMembership.is_active == True,
        ).first()
        if existing_membership:
            raise HTTPException(status_code=400, detail="User is already a member of this account")
    
    pending_invitation = db.query(AccountInvitation).filter(
        AccountInvitation.account_id == account.id,
        AccountInvitation.invitee_email == data.email,
        AccountInvitation.status == InvitationStatus.PENDING,
    ).first()
    if pending_invitation:
        raise HTTPException(status_code=400, detail="An invitation is already pending for this email")
    
    invitation = AccountInvitation(
        account_id=account.id,
        invitee_email=data.email,
        role_id=role.id,
        invited_by_id=admin.id,
        token=AccountInvitation.generate_token(),
        expires_at=AccountInvitation.default_expiration(days=7),
    )
    
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    
    return build_invitation_response(invitation)


@router.get("/invitations/{invitation_id}", response_model=InvitationResponse)
async def get_invitation(
    invitation_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Get invitation details."""
    invitation = db.query(AccountInvitation).filter(AccountInvitation.id == invitation_id).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    return build_invitation_response(invitation)


@router.post("/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Resend an invitation with a new expiration date."""
    invitation = db.query(AccountInvitation).filter(AccountInvitation.id == invitation_id).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Can only resend pending invitations")
    
    invitation.token = AccountInvitation.generate_token()
    invitation.expires_at = AccountInvitation.default_expiration(days=7)
    
    db.commit()
    db.refresh(invitation)
    
    return {
        "success": True,
        "message": f"Invitation resent to {invitation.invitee_email}",
        "new_expires_at": invitation.expires_at.isoformat(),
    }


@router.post("/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Revoke a pending invitation."""
    invitation = db.query(AccountInvitation).filter(AccountInvitation.id == invitation_id).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Can only revoke pending invitations")
    
    invitation.revoke()
    db.commit()
    
    return {
        "success": True,
        "message": f"Invitation to {invitation.invitee_email} has been revoked",
    }


@router.get("/accounts/{account_id}/invitations", response_model=List[InvitationResponse])
async def list_account_invitations(
    account_id: str,
    status: Optional[InvitationStatus] = None,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """List all invitations for a specific account."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    query = db.query(AccountInvitation).filter(AccountInvitation.account_id == account_id)
    
    if status:
        query = query.filter(AccountInvitation.status == status)
    
    invitations = query.order_by(AccountInvitation.created_at.desc()).all()
    
    return [build_invitation_response(inv) for inv in invitations]


@router.get("/accounts/{account_id}/roles", response_model=List[dict])
async def list_account_roles(
    account_id: str,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """List all roles available for an account."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    roles = db.query(Role).filter(Role.account_id == account_id).all()
    
    return [
        {
            "id": str(role.id),
            "name": role.name,
            "slug": role.slug,
            "description": role.description,
            "is_system_role": role.is_system_role,
        }
        for role in roles
    ]


class IntegrationStatus(BaseModel):
    name: str
    status: str
    message: Optional[str] = None
    details: Optional[dict] = None


class IntegrationHealthResponse(BaseModel):
    twilio: IntegrationStatus
    openai: IntegrationStatus
    database: IntegrationStatus


@router.get("/integrations/health", response_model=IntegrationHealthResponse)
async def check_integrations_health(
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Check health status of all platform integrations."""
    import os
    
    twilio_status = IntegrationStatus(name="Twilio", status="not_configured")
    openai_status = IntegrationStatus(name="OpenAI", status="not_configured")
    db_status = IntegrationStatus(name="Database", status="not_configured")
    
    if os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"):
        try:
            from botelier.integrations.twilio.client import BotelierTwilioClient
            client = BotelierTwilioClient()
            if client.test_connection():
                account_count = db.query(Account).filter(
                    Account.twilio_sub_account_sid.isnot(None)
                ).count()
                twilio_status = IntegrationStatus(
                    name="Twilio",
                    status="connected",
                    message="Twilio API connection verified",
                    details={"sub_accounts_provisioned": account_count}
                )
            else:
                twilio_status = IntegrationStatus(
                    name="Twilio",
                    status="error",
                    message="Twilio credentials are invalid"
                )
        except Exception as e:
            twilio_status = IntegrationStatus(
                name="Twilio",
                status="error",
                message=str(e)
            )
    
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai
            openai_client = openai.OpenAI()
            models = openai_client.models.list()
            model_count = len(list(models))
            openai_status = IntegrationStatus(
                name="OpenAI",
                status="connected",
                message="OpenAI API connection verified",
                details={"available_models": model_count}
            )
        except Exception as e:
            openai_status = IntegrationStatus(
                name="OpenAI",
                status="error",
                message=str(e)
            )
    
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        
        user_count = db.query(func.count(User.id)).scalar()
        account_count = db.query(func.count(Account.id)).scalar()
        
        db_status = IntegrationStatus(
            name="Database",
            status="connected",
            message="PostgreSQL connection verified",
            details={
                "total_users": user_count,
                "total_accounts": account_count
            }
        )
    except Exception as e:
        db_status = IntegrationStatus(
            name="Database",
            status="error",
            message=str(e)
        )
    
    return IntegrationHealthResponse(
        twilio=twilio_status,
        openai=openai_status,
        database=db_status
    )


class SupportSessionCreate(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class SupportSessionResponse(BaseModel):
    session_token: str
    account_id: str
    account_name: str
    admin_id: str
    admin_email: str
    reason: str
    created_at: datetime
    expires_at: datetime


@router.post("/accounts/{account_id}/support-session", response_model=SupportSessionResponse)
async def create_support_session(
    account_id: str,
    request: SupportSessionCreate,
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """
    Create a time-limited support session for accessing an account.
    
    This provides SaaS-compliant account access with:
    - Time-limited access (1 hour by default)
    - Audit trail of the access reason
    - Trackable session token
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    session_token = secrets.token_urlsafe(32)
    created_at = datetime.utcnow()
    expires_at = created_at + timedelta(hours=1)
    
    support_session = SupportSession(
        session_token=session_token,
        admin_id=admin.id,
        account_id=account.id,
        reason=request.reason,
        created_at=created_at,
        expires_at=expires_at,
    )
    db.add(support_session)
    db.commit()
    
    print(f"[AUDIT] Support session created: admin={admin.email}, account={account.name}, reason={request.reason}, expires={expires_at}")
    
    return SupportSessionResponse(
        session_token=session_token,
        account_id=str(account.id),
        account_name=account.name,
        admin_id=str(admin.id),
        admin_email=admin.email or "unknown",
        reason=request.reason,
        created_at=created_at,
        expires_at=expires_at
    )


@router.get("/audit-log")
async def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """
    Get platform audit log entries.
    
    Note: This is a placeholder for a full audit logging system.
    In production, this would query an immutable audit log table.
    """
    return {
        "entries": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
        "message": "Audit logging system ready for implementation"
    }

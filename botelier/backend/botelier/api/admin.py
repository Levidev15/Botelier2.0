"""
Platform Admin API Endpoints.

Provides endpoints for platform administrators to manage accounts, users, and platform settings.
All endpoints require platform_admin user type.
"""

import uuid
import re
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from botelier.database import get_db
from botelier.models.account import Account, AccountStatus, SubscriptionTier
from botelier.models.user import User, UserType
from botelier.models.role import Role, AccountMembership
from botelier.auth.permissions import DEFAULT_ROLES
from botelier.auth.middleware import get_platform_admin, get_current_user


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
    provision_twilio: bool = Query(False, description="Auto-provision Twilio sub-account"),
    admin: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Create a new account."""
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
    
    if provision_twilio:
        try:
            from botelier.integrations.twilio.sub_accounts import create_sub_account
            sub_account_data = create_sub_account(data.name)
            account.twilio_sub_account_sid = sub_account_data["sid"]
            account.twilio_sub_auth_token = sub_account_data["auth_token"]
        except Exception as e:
            print(f"Failed to provision Twilio sub-account: {e}")
    
    db.commit()
    db.refresh(account)
    
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
        member_count=0,
        created_at=account.created_at,
    )


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
    """Provision a Twilio sub-account for an existing account."""
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if account.has_twilio:
        raise HTTPException(status_code=400, detail="Account already has Twilio configured")
    
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
                "is_owner": membership.is_owner,
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

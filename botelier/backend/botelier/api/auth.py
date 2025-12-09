"""
Authentication API endpoints for email/password authentication.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
import bcrypt
from jose import jwt, JWTError, ExpiredSignatureError
import os
import uuid

from botelier.database import get_db
from botelier.models.user import User, UserType, AuthProvider
from botelier.models.role import AccountMembership
from botelier.models.invitation import AccountInvitation, InvitationStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET = os.environ.get("NEXTAUTH_SECRET", "botelier-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_jwt_token(user: User) -> str:
    """Create a JWT token for a user."""
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "user_type": user.user_type.value,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    invitation_token: Optional[str] = None


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    redirect_url: Optional[str] = None


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user with email and password."""
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses a different sign-in method",
        )
    
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    
    user.last_login_at = datetime.utcnow()
    db.commit()
    
    token = create_jwt_token(user)
    
    return LoginResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "user_type": user.user_type.value,
            "profile_image_url": user.profile_image_url,
        },
    )


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user with email and password."""
    existing_user = db.query(User).filter(User.email == request.email).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )
    
    invitation = None
    redirect_url = "/dashboard"
    
    if request.invitation_token:
        invitation = db.query(AccountInvitation).filter(
            AccountInvitation.token == request.invitation_token
        ).first()
        
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token",
            )
        
        if invitation.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This invitation has already been {invitation.status.value}",
            )
        
        if invitation.is_expired:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invitation has expired",
            )
        
        if invitation.invitee_email.lower() != request.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match the invitation",
            )
    
    user = User(
        id=uuid.uuid4(),
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        first_name=request.first_name,
        last_name=request.last_name,
        auth_provider=AuthProvider.EMAIL,
        user_type=UserType.ACCOUNT_USER,
        email_verified=True if invitation else False,
        is_active=True,
    )
    db.add(user)
    db.flush()
    
    if invitation:
        membership = AccountMembership(
            user_id=user.id,
            account_id=invitation.account_id,
            role_id=invitation.role_id,
            is_active=True,
        )
        db.add(membership)
        
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.utcnow()
        invitation.accepted_by_user_id = user.id
        
        redirect_url = f"/accounts/{invitation.account_id}"
    
    db.commit()
    
    token = create_jwt_token(user)
    
    return RegisterResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "user_type": user.user_type.value,
            "profile_image_url": user.profile_image_url,
        },
        redirect_url=redirect_url,
    )


class VerifyInvitationResponse(BaseModel):
    valid: bool
    email: Optional[str] = None
    account_name: Optional[str] = None
    role_name: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


@router.get("/verify-invitation/{token}", response_model=VerifyInvitationResponse)
async def verify_invitation(token: str, db: Session = Depends(get_db)):
    """Verify an invitation token and return invitation details."""
    invitation = db.query(AccountInvitation).filter(
        AccountInvitation.token == token
    ).first()
    
    if not invitation:
        return VerifyInvitationResponse(valid=False, error="Invalid invitation token")
    
    if invitation.status != InvitationStatus.PENDING:
        return VerifyInvitationResponse(
            valid=False, 
            error=f"This invitation has been {invitation.status.value}"
        )
    
    if invitation.is_expired:
        return VerifyInvitationResponse(valid=False, error="This invitation has expired")
    
    return VerifyInvitationResponse(
        valid=True,
        email=invitation.invitee_email,
        account_name=invitation.account.name if invitation.account else None,
        role_name=invitation.role.name if invitation.role else None,
        expires_at=invitation.expires_at.isoformat() if invitation.expires_at else None,
    )


class ValidateTokenRequest(BaseModel):
    token: str


class ValidateTokenResponse(BaseModel):
    valid: bool
    user: Optional[dict] = None


@router.post("/validate", response_model=ValidateTokenResponse)
async def validate_token(request: ValidateTokenRequest, db: Session = Depends(get_db)):
    """Validate a JWT token and return user info."""
    try:
        payload = jwt.decode(request.token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        
        if not user_id:
            return ValidateTokenResponse(valid=False)
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user or not user.is_active:
            return ValidateTokenResponse(valid=False)
        
        return ValidateTokenResponse(
            valid=True,
            user={
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": user.display_name,
                "user_type": user.user_type.value,
                "profile_image_url": user.profile_image_url,
            },
        )
    except ExpiredSignatureError:
        return ValidateTokenResponse(valid=False)
    except JWTError:
        return ValidateTokenResponse(valid=False)
    except Exception:
        return ValidateTokenResponse(valid=False)

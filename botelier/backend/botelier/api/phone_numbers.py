"""
Phone Numbers API - CRUD operations for hotel phone numbers.

Endpoints:
- GET /api/phone-numbers/available - Search available numbers by area code
- GET /api/phone-numbers - List hotel's numbers
- POST /api/phone-numbers/purchase - Buy a number
- PUT /api/phone-numbers/{id}/assign - Assign to assistant
- DELETE /api/phone-numbers/{id} - Release number
"""

import os
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID

from botelier.database import get_db
from botelier.models.phone_number import PhoneNumber
from botelier.models.hotel import Hotel
from botelier.models.assistant import Assistant
from botelier.integrations.twilio.phone_numbers import PhoneNumberManager
from botelier.config.domain import get_public_base_url
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission


router = APIRouter(prefix="/api/phone-numbers", tags=["phone-numbers"])


class AvailableNumberResponse(BaseModel):
    """Available phone number from Twilio search."""
    phone_number: str
    friendly_name: str
    capabilities: dict
    locality: Optional[str] = None
    region: Optional[str] = None
    iso_country: str
    postal_code: Optional[str] = None


class PurchaseNumberRequest(BaseModel):
    """Request to purchase a phone number."""
    phone_number: str = Field(..., description="E.164 format: +14155551234")
    friendly_name: Optional[str] = Field(None, description="Label for the number")
    hotel_id: str = Field(..., description="Hotel ID (UUID)")


class AssignAssistantRequest(BaseModel):
    """Request to assign number to assistant."""
    assistant_id: Optional[str] = Field(None, description="Assistant UUID or null to unassign")


class PhoneNumberResponse(BaseModel):
    """Phone number response model."""
    id: str
    phone_number: str
    friendly_name: Optional[str]
    country_code: str
    twilio_sid: str
    hotel_id: str
    assistant_id: Optional[str]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


@router.get("/available", response_model=List[AvailableNumberResponse])
async def search_available_numbers(
    area_code: Optional[str] = Query(None, description="3-digit area code (e.g., 415)"),
    country: str = Query("US", description="Country code (US, GB, etc.)"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    hotel_id: str = Query(..., description="Hotel ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, hotel_id, "phone_numbers.view", db)
    """
    Search for available phone numbers by area code.
    
    This searches Twilio's inventory for the hotel's sub-account.
    
    Query params:
    - area_code: Optional 3-digit area code (e.g., "415" for San Francisco)
    - country: Country code (default: "US")
    - limit: Max results (1-50, default: 10)
    - hotel_id: Hotel UUID
    
    Returns:
    - List of available numbers with capabilities and location info
    """
    # Get hotel and verify sub-account exists
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")
    
    if not hotel.twilio_sub_account_sid or not hotel.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Hotel does not have a Twilio sub-account configured"
        )
    
    # Search available numbers
    try:
        manager = PhoneNumberManager(
            sub_account_sid=hotel.twilio_sub_account_sid,
            sub_auth_token=hotel.twilio_sub_auth_token
        )
        
        available = manager.search_available_numbers(
            area_code=area_code,
            country=country,
            limit=limit
        )
        
        return available
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search available numbers: {str(e)}"
        )


@router.get("", response_model=dict)
async def list_phone_numbers(
    hotel_id: Optional[str] = Query(None, description="Filter by hotel ID"),
    assistant_id: Optional[str] = Query(None, description="Filter by assistant ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if hotel_id:
        check_account_permission(user, hotel_id, "phone_numbers.view", db)
    """
    List phone numbers.
    
    Query params:
    - hotel_id: Filter by hotel (optional)
    - assistant_id: Filter by assigned assistant (optional)
    
    Returns:
    - List of phone numbers
    """
    query = db.query(PhoneNumber)
    
    if hotel_id:
        query = query.filter(PhoneNumber.hotel_id == hotel_id)
    if assistant_id:
        query = query.filter(PhoneNumber.assistant_id == assistant_id)
    
    numbers = query.all()
    
    return {
        "phone_numbers": [num.to_dict() for num in numbers],
        "total": len(numbers)
    }


@router.post("/purchase", response_model=PhoneNumberResponse)
async def purchase_phone_number(
    request: PurchaseNumberRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(request.hotel_id), "phone_numbers.purchase", db)
    """
    Purchase a phone number for a hotel.
    
    Steps:
    1. Verify hotel has sub-account
    2. Purchase number via Twilio API
    3. Store in database
    4. Configure webhook URL
    
    Body:
    - phone_number: E.164 format (e.g., "+14155551234")
    - friendly_name: Optional label
    - hotel_id: Hotel UUID
    
    Returns:
    - Created phone number record
    """
    # Get hotel
    hotel = db.query(Hotel).filter(Hotel.id == request.hotel_id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")
    
    if not hotel.twilio_sub_account_sid or not hotel.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Hotel does not have a Twilio sub-account"
        )
    
    # Check if number already exists
    existing = db.query(PhoneNumber).filter(
        PhoneNumber.phone_number == request.phone_number
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Phone number already exists in database"
        )
    
    # Purchase number from Twilio
    try:
        manager = PhoneNumberManager(
            sub_account_sid=hotel.twilio_sub_account_sid,
            sub_auth_token=hotel.twilio_sub_auth_token
        )
        
        # Construct webhook URLs for incoming calls using domain helper
        # This works in both Replit dev and production with custom domains
        base_url = get_public_base_url()
        voice_url = f"{base_url}/api/calls/incoming"
        status_callback = f"{base_url}/api/calls/status"
        
        purchased = manager.purchase_number(
            phone_number=request.phone_number,
            friendly_name=request.friendly_name,
            voice_url=voice_url,
            voice_method="POST",
            status_callback=status_callback,
        )
        
        # Extract country code from E.164 number
        country_code = "US"  # Default, can be improved with phone number parsing
        
        # Store in database
        phone_number = PhoneNumber(
            phone_number=request.phone_number,
            friendly_name=request.friendly_name,
            country_code=country_code,
            twilio_sid=purchased["sid"],
            hotel_id=request.hotel_id,
            is_active=True
        )
        
        db.add(phone_number)
        db.commit()
        db.refresh(phone_number)
        
        return phone_number.to_dict()
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to purchase number: {str(e)}"
        )


@router.put("/{phone_number_id}/assign", response_model=PhoneNumberResponse)
async def assign_to_assistant(
    phone_number_id: str,
    request: AssignAssistantRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Assign phone number to a voice assistant.
    
    MULTI-TENANCY: Validates that the assistant belongs to the same hotel
    as the phone number to prevent cross-hotel contamination.
    
    Path params:
    - phone_number_id: Phone number UUID
    
    Body:
    - assistant_id: Assistant UUID (or null to unassign)
    
    Returns:
    - Updated phone number record
    """
    # Look up phone number
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()
    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")
    check_account_permission(user, str(phone_number.hotel_id), "phone_numbers.configure", db)
    # Validate assistant belongs to same hotel (CRITICAL for multi-tenancy)
    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        
        if assistant.hotel_id != phone_number.hotel_id:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot assign assistant from hotel {assistant.hotel_id} to phone number from hotel {phone_number.hotel_id}. Multi-tenancy violation."
            )
        
        phone_number.assistant_id = request.assistant_id
    else:
        # Unassign
        phone_number.assistant_id = None
    
    db.commit()
    db.refresh(phone_number)
    
    return phone_number.to_dict()


@router.delete("/{phone_number_id}")
async def release_phone_number(
    phone_number_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Release a phone number back to Twilio.
    
    Path params:
    - phone_number_id: Phone number UUID
    
    Returns:
    - Success message
    """
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()
    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")
    check_account_permission(user, str(phone_number.hotel_id), "phone_numbers.release", db)
    # Get hotel for sub-account credentials
    hotel = db.query(Hotel).filter(Hotel.id == phone_number.hotel_id).first()
    if not hotel or not hotel.twilio_sub_account_sid or not hotel.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Hotel sub-account not configured"
        )
    
    # Release from Twilio
    try:
        manager = PhoneNumberManager(
            sub_account_sid=hotel.twilio_sub_account_sid,
            sub_auth_token=hotel.twilio_sub_auth_token
        )
        
        success = manager.release_number(phone_number.twilio_sid)
        
        if success:
            # Delete from database
            db.delete(phone_number)
            db.commit()
            
            return {"message": "Phone number released successfully"}
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to release number from Twilio"
            )
            
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to release number: {str(e)}"
        )


class SMSConfigRequest(BaseModel):
    hotel_id: str
    sms_enabled: bool
    sms_assistant_id: Optional[str] = None


@router.put("/{phone_number_id}/sms-config")
async def update_sms_config(
    phone_number_id: str,
    request: SMSConfigRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(request.hotel_id), "phone_numbers.configure", db)
    """
    Enable/disable SMS on a phone number and optionally assign an SMS-specific assistant.
    When SMS is enabled, configures the Twilio number's SMS webhook.
    """
    phone_number = db.query(PhoneNumber).filter(
        PhoneNumber.id == phone_number_id,
        PhoneNumber.hotel_id == UUID(request.hotel_id),
    ).first()

    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    hotel = db.query(Hotel).filter(Hotel.id == phone_number.hotel_id).first()
    if not hotel or not hotel.twilio_sub_account_sid or not hotel.twilio_sub_auth_token:
        raise HTTPException(status_code=400, detail="Hotel sub-account not configured")

    if request.sms_assistant_id:
        sms_assistant = db.query(Assistant).filter(
            Assistant.id == UUID(request.sms_assistant_id),
            Assistant.hotel_id == phone_number.hotel_id,
        ).first()
        if not sms_assistant:
            raise HTTPException(status_code=404, detail="SMS assistant not found in this account")

    phone_number.sms_enabled = request.sms_enabled
    phone_number.sms_assistant_id = UUID(request.sms_assistant_id) if request.sms_assistant_id else None

    try:
        manager = PhoneNumberManager(
            sub_account_sid=hotel.twilio_sub_account_sid,
            sub_auth_token=hotel.twilio_sub_auth_token,
        )

        base_url = get_public_base_url()

        if request.sms_enabled:
            sms_url = f"{base_url}/api/sms/webhook"
            manager.update_number_config(
                phone_number_sid=phone_number.twilio_sid,
                sms_url=sms_url,
                sms_method="POST",
            )
        else:
            manager.update_number_config(
                phone_number_sid=phone_number.twilio_sid,
                sms_url="",
                sms_method="POST",
            )

        db.commit()
        return phone_number.to_dict()

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update SMS config: {str(e)}",
        )


@router.post("/{phone_number_id}/reconfigure")
async def reconfigure_phone_number_webhooks(
    phone_number_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Reconfigure phone number webhooks to use correct voice and status callback URLs.
    
    This is useful for fixing phone numbers that were purchased before
    status callbacks were properly configured.
    
    Path params:
    - phone_number_id: Phone number UUID
    
    Returns:
    - Updated webhook configuration
    """
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()
    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")
    check_account_permission(user, str(phone_number.hotel_id), "phone_numbers.configure", db)
    hotel = db.query(Hotel).filter(Hotel.id == phone_number.hotel_id).first()
    if not hotel or not hotel.twilio_sub_account_sid or not hotel.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Hotel sub-account not configured"
        )
    
    try:
        manager = PhoneNumberManager(
            sub_account_sid=hotel.twilio_sub_account_sid,
            sub_auth_token=hotel.twilio_sub_auth_token
        )
        
        base_url = get_public_base_url()
        voice_url = f"{base_url}/api/calls/incoming"
        status_callback = f"{base_url}/api/calls/status"
        
        result = manager.update_number_config(
            phone_number_sid=phone_number.twilio_sid,
            voice_url=voice_url,
            voice_method="POST",
            status_callback=status_callback,
            status_callback_method="POST"
        )
        
        return {
            "message": "Phone number webhooks reconfigured",
            "voice_url": voice_url,
            "status_callback": status_callback,
            "twilio_result": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reconfigure webhooks: {str(e)}"
        )

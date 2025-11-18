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
from botelier.integrations.twilio.phone_numbers import PhoneNumberManager


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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
        
        # Construct webhook URL for incoming calls
        # Use Replit domain in production, or localhost in dev
        replit_slug = os.environ.get("REPL_SLUG")
        replit_owner = os.environ.get("REPL_OWNER")
        
        if replit_slug and replit_owner:
            # Production Replit URL
            base_url = f"https://{replit_slug}.{replit_owner}.repl.co"
        else:
            # Fallback for development
            base_url = os.environ.get("BASE_URL", "https://your-domain.com")
        
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
    db: Session = Depends(get_db)
):
    """
    Assign phone number to a voice assistant.
    
    Path params:
    - phone_number_id: Phone number UUID
    
    Body:
    - assistant_id: Assistant UUID (or null to unassign)
    
    Returns:
    - Updated phone number record
    """
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()
    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")
    
    # Update assignment
    if request.assistant_id:
        phone_number.assistant_id = request.assistant_id
    else:
        phone_number.assistant_id = None
    
    db.commit()
    db.refresh(phone_number)
    
    return phone_number.to_dict()


@router.delete("/{phone_number_id}")
async def release_phone_number(
    phone_number_id: str,
    db: Session = Depends(get_db)
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

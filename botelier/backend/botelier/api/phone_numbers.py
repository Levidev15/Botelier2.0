"""
Phone Numbers API - CRUD operations for account phone numbers.

Endpoints:
- GET /api/phone-numbers/available - Search available numbers by area code
- GET /api/phone-numbers - List account's numbers
- POST /api/phone-numbers/purchase - Buy a number
- PUT /api/phone-numbers/{id}/assign - Assign to assistant
- DELETE /api/phone-numbers/{id} - Release number
"""

import os
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID

from botelier.database import get_db
from botelier.models.phone_number import PhoneNumber
from botelier.models.account import Account
from botelier.models.assistant import Assistant
from botelier.integrations.twilio.phone_numbers import PhoneNumberManager
from twilio.base.exceptions import TwilioRestException
from botelier.config.domain import get_public_base_url
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission, get_hotel_context, AccountContext
from botelier.services.recording_sync import sync_phone_number_recording as _sync_phone_number_recording


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
    account_id: str = Field(..., description="Account ID (UUID)")


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
    account_id: str
    assistant_id: Optional[str]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


@router.get("/available", response_model=List[AvailableNumberResponse])
async def search_available_numbers(
    area_code: Optional[str] = Query(None, description="3-digit area code (e.g., 415)"),
    country: str = Query("US", description="Country code (US, GB, etc.)"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    account_id: str = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "phone_numbers.view", db)
    """
    Search for available phone numbers by area code.

    This searches Twilio's inventory for the account's sub-account.

    Query params:
    - area_code: Optional 3-digit area code (e.g., "415" for San Francisco)
    - country: Country code (default: "US")
    - limit: Max results (1-50, default: 10)
    - account_id: Account UUID

    Returns:
    - List of available numbers with capabilities and location info
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not account.twilio_sub_account_sid or not account.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Account does not have a Twilio sub-account configured"
        )

    try:
        manager = PhoneNumberManager(
            sub_account_sid=account.twilio_sub_account_sid,
            sub_auth_token=account.twilio_sub_auth_token
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
    assistant_id: Optional[str] = Query(None, description="Filter by assistant ID"),
    ctx: AccountContext = Depends(get_hotel_context("phone_numbers.view")),
    db: Session = Depends(get_db),
):
    """List phone numbers for the authenticated account."""
    account_id = str(ctx.account.id)

    query = db.query(PhoneNumber).filter(PhoneNumber.account_id == account_id)

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
    check_account_permission(user, str(request.account_id), "phone_numbers.purchase", db)
    """
    Purchase a phone number for an account.

    Steps:
    1. Verify account has sub-account
    2. Purchase number via Twilio API
    3. Store in database
    4. Configure webhook URL

    Body:
    - phone_number: E.164 format (e.g., "+14155551234")
    - friendly_name: Optional label
    - account_id: Account UUID

    Returns:
    - Created phone number record
    """
    account = db.query(Account).filter(Account.id == request.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not account.twilio_sub_account_sid or not account.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Account does not have a Twilio sub-account"
        )

    existing = db.query(PhoneNumber).filter(
        PhoneNumber.phone_number == request.phone_number
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Phone number already exists in database"
        )

    try:
        manager = PhoneNumberManager(
            sub_account_sid=account.twilio_sub_account_sid,
            sub_auth_token=account.twilio_sub_auth_token
        )

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

        country_code = "US"

        phone_number = PhoneNumber(
            phone_number=request.phone_number,
            friendly_name=request.friendly_name,
            country_code=country_code,
            twilio_sid=purchased["sid"],
            account_id=request.account_id,
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

    MULTI-TENANCY: Validates that the assistant belongs to the same account
    as the phone number to prevent cross-account contamination.

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
    check_account_permission(user, str(phone_number.account_id), "phone_numbers.configure", db)

    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        if assistant.account_id != phone_number.account_id:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot assign assistant from account {assistant.account_id} to phone number from account {phone_number.account_id}. Multi-tenancy violation."
            )

        phone_number.assistant_id = request.assistant_id
    else:
        phone_number.assistant_id = None

    db.commit()
    db.refresh(phone_number)

    # Recording is handled per-call via the in-call Recordings REST API
    # (start_in_call_recording in call_handler.py). No VoiceRecord sync needed on assignment.

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
    check_account_permission(user, str(phone_number.account_id), "phone_numbers.release", db)

    account = db.query(Account).filter(Account.id == phone_number.account_id).first()
    if not account or not account.twilio_sub_account_sid or not account.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Account sub-account not configured"
        )

    try:
        manager = PhoneNumberManager(
            sub_account_sid=account.twilio_sub_account_sid,
            sub_auth_token=account.twilio_sub_auth_token
        )
        released = manager.release_number(phone_number.twilio_sid)
        if not released:
            raise HTTPException(
                status_code=500,
                detail="Failed to release number from Twilio"
            )
        db.delete(phone_number)
        db.commit()
        return {"message": "Phone number released successfully"}

    except TwilioRestException as e:
        if e.status == 404:
            logging.getLogger(__name__).warning(
                f"Phone number {phone_number.twilio_sid} not found in Twilio "
                f"(404) — removing orphaned DB record."
            )
            db.delete(phone_number)
            db.commit()
            return {"message": "Phone number removed (was already released from Twilio)"}
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to release number from Twilio: {str(e)}"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to release number: {str(e)}"
        )


class SMSConfigRequest(BaseModel):
    account_id: str
    sms_enabled: bool
    sms_assistant_id: Optional[str] = None


@router.put("/{phone_number_id}/sms-config")
async def update_sms_config(
    phone_number_id: str,
    request: SMSConfigRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(request.account_id), "phone_numbers.configure", db)
    """
    Enable/disable SMS on a phone number and optionally assign an SMS-specific assistant.
    When SMS is enabled, configures the Twilio number's SMS webhook.
    """
    phone_number = db.query(PhoneNumber).filter(
        PhoneNumber.id == phone_number_id,
        PhoneNumber.account_id == UUID(request.account_id),
    ).first()

    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    account = db.query(Account).filter(Account.id == phone_number.account_id).first()
    if not account or not account.twilio_sub_account_sid or not account.twilio_sub_auth_token:
        raise HTTPException(status_code=400, detail="Account sub-account not configured")

    if request.sms_assistant_id:
        sms_assistant = db.query(Assistant).filter(
            Assistant.id == UUID(request.sms_assistant_id),
            Assistant.account_id == phone_number.account_id,
        ).first()
        if not sms_assistant:
            raise HTTPException(status_code=404, detail="SMS assistant not found in this account")

    phone_number.sms_enabled = request.sms_enabled
    phone_number.sms_assistant_id = UUID(request.sms_assistant_id) if request.sms_assistant_id else None

    try:
        manager = PhoneNumberManager(
            sub_account_sid=account.twilio_sub_account_sid,
            sub_auth_token=account.twilio_sub_auth_token,
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

    Path params:
    - phone_number_id: Phone number UUID

    Returns:
    - Updated webhook configuration
    """
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()
    if not phone_number:
        raise HTTPException(status_code=404, detail="Phone number not found")
    check_account_permission(user, str(phone_number.account_id), "phone_numbers.configure", db)

    account = db.query(Account).filter(Account.id == phone_number.account_id).first()
    if not account or not account.twilio_sub_account_sid or not account.twilio_sub_auth_token:
        raise HTTPException(
            status_code=400,
            detail="Account sub-account not configured"
        )

    try:
        manager = PhoneNumberManager(
            sub_account_sid=account.twilio_sub_account_sid,
            sub_auth_token=account.twilio_sub_auth_token
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

        _sync_phone_number_recording(phone_number=phone_number, account=account, db=db)

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

from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.sms_compliance import (
    SMSComplianceBrand, SMSComplianceCampaign,
    BrandStatus, CampaignStatus, BrandType, CampaignUseCase,
)
from botelier.models.account import Account
from botelier.models.hotel import Hotel
from botelier.models.phone_number import PhoneNumber
from botelier.services.sms_compliance_service import SMSComplianceService

router = APIRouter(prefix="/api/sms-compliance", tags=["SMS Compliance"])


class BrandCreateRequest(BaseModel):
    account_id: str
    brand_type: str = "standard"
    business_name: str
    business_type: Optional[str] = None
    business_industry: Optional[str] = None
    ein: Optional[str] = None
    ein_issuing_country: str = "US"
    company_type: Optional[str] = None
    stock_symbol: Optional[str] = None
    stock_exchange: Optional[str] = None
    website_url: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    rep_first_name: Optional[str] = None
    rep_last_name: Optional[str] = None
    rep_email: Optional[str] = None
    rep_phone: Optional[str] = None
    rep_title: Optional[str] = None
    rep_job_position: Optional[str] = None


class BrandUpdateRequest(BaseModel):
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    business_industry: Optional[str] = None
    ein: Optional[str] = None
    ein_issuing_country: Optional[str] = None
    company_type: Optional[str] = None
    stock_symbol: Optional[str] = None
    stock_exchange: Optional[str] = None
    website_url: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    rep_first_name: Optional[str] = None
    rep_last_name: Optional[str] = None
    rep_email: Optional[str] = None
    rep_phone: Optional[str] = None
    rep_title: Optional[str] = None
    rep_job_position: Optional[str] = None


class CampaignCreateRequest(BaseModel):
    brand_id: str
    hotel_id: str
    friendly_name: str
    use_case: str = "CUSTOMER_CARE"
    description: Optional[str] = None
    message_samples: List[str] = []
    message_flow: Optional[str] = None
    has_embedded_links: bool = False
    has_embedded_phone: bool = False
    opt_in_message: Optional[str] = None
    opt_in_keywords: str = "YES,START"
    opt_out_message: Optional[str] = None
    opt_out_keywords: str = "STOP,END,CANCEL,UNSUBSCRIBE,QUIT"
    help_message: Optional[str] = None
    help_keywords: str = "HELP,INFO"


class CampaignUpdateRequest(BaseModel):
    friendly_name: Optional[str] = None
    use_case: Optional[str] = None
    description: Optional[str] = None
    message_samples: Optional[List[str]] = None
    message_flow: Optional[str] = None
    has_embedded_links: Optional[bool] = None
    has_embedded_phone: Optional[bool] = None
    opt_in_message: Optional[str] = None
    opt_in_keywords: Optional[str] = None
    opt_out_message: Optional[str] = None
    opt_out_keywords: Optional[str] = None
    help_message: Optional[str] = None
    help_keywords: Optional[str] = None


class PhoneNumberAssignRequest(BaseModel):
    phone_number_sid: str


@router.get("/brands")
async def list_brands(
    account_id: str = Query(..., description="Account ID"),
    db: Session = Depends(get_db),
):
    brands = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.account_id == account_id
    ).order_by(SMSComplianceBrand.created_at.desc()).all()
    return [b.to_dict() for b in brands]


@router.get("/brands/{brand_id}")
async def get_brand(brand_id: str, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand.to_dict()


@router.post("/brands")
async def create_brand(request: BrandCreateRequest, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == request.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.account_id == request.account_id,
        SMSComplianceBrand.status.notin_([BrandStatus.FAILED])
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Account already has an active brand registration. Delete or use the existing one."
        )

    brand_type_map = {
        "standard": BrandType.STANDARD,
        "low_volume": BrandType.LOW_VOLUME,
        "starter": BrandType.STARTER,
        "sole_proprietor": BrandType.SOLE_PROPRIETOR,
    }

    brand = SMSComplianceBrand(
        account_id=request.account_id,
        brand_type=brand_type_map.get(request.brand_type, BrandType.STANDARD),
        business_name=request.business_name,
        business_type=request.business_type,
        business_industry=request.business_industry,
        ein=request.ein,
        ein_issuing_country=request.ein_issuing_country,
        company_type=request.company_type,
        stock_symbol=request.stock_symbol,
        stock_exchange=request.stock_exchange,
        website_url=request.website_url,
        street=request.street,
        city=request.city,
        region=request.region,
        postal_code=request.postal_code,
        country=request.country,
        rep_first_name=request.rep_first_name,
        rep_last_name=request.rep_last_name,
        rep_email=request.rep_email,
        rep_phone=request.rep_phone,
        rep_title=request.rep_title,
        rep_job_position=request.rep_job_position,
        status=BrandStatus.DRAFT,
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand.to_dict()


@router.put("/brands/{brand_id}")
async def update_brand(brand_id: str, request: BrandUpdateRequest, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    if brand.status not in [BrandStatus.DRAFT, BrandStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail="Can only edit brands in draft or failed status"
        )

    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(brand, key, value)

    db.commit()
    db.refresh(brand)
    return brand.to_dict()


@router.post("/brands/{brand_id}/submit")
async def submit_brand(brand_id: str, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    if brand.status not in [BrandStatus.DRAFT, BrandStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail=f"Brand is in {brand.status.value} status, cannot submit"
        )

    base_required = ["business_name", "rep_first_name", "rep_last_name", "rep_email", "rep_phone"]
    if brand.brand_type in [BrandType.STANDARD, BrandType.LOW_VOLUME]:
        required_fields = base_required + ["ein", "street", "city", "region", "postal_code"]
    elif brand.brand_type == BrandType.STARTER:
        required_fields = base_required + ["street", "city", "region", "postal_code"]
    else:
        required_fields = base_required
    missing = [f for f in required_fields if not getattr(brand, f)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {', '.join(missing)}"
        )

    try:
        service = SMSComplianceService(db)
        brand = service.submit_brand(brand)
        return brand.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/brands/{brand_id}/refresh")
async def refresh_brand(brand_id: str, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    try:
        service = SMSComplianceService(db)
        brand = service.refresh_brand_status(brand)
        return brand.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/brands/{brand_id}")
async def delete_brand(brand_id: str, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    campaigns = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.brand_id == brand_id
    ).count()
    if campaigns > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete brand with existing campaigns. Delete campaigns first."
        )

    db.delete(brand)
    db.commit()
    return {"status": "deleted"}


@router.get("/campaigns")
async def list_campaigns(
    hotel_id: Optional[str] = Query(None, description="Filter by hotel"),
    brand_id: Optional[str] = Query(None, description="Filter by brand"),
    db: Session = Depends(get_db),
):
    query = db.query(SMSComplianceCampaign)
    if hotel_id:
        query = query.filter(SMSComplianceCampaign.hotel_id == hotel_id)
    if brand_id:
        query = query.filter(SMSComplianceCampaign.brand_id == brand_id)

    campaigns = query.order_by(SMSComplianceCampaign.created_at.desc()).all()
    return [c.to_dict() for c in campaigns]


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign.to_dict()


@router.post("/campaigns")
async def create_campaign(request: CampaignCreateRequest, db: Session = Depends(get_db)):
    brand = db.query(SMSComplianceBrand).filter(
        SMSComplianceBrand.id == request.brand_id
    ).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    if brand.status != BrandStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Brand must be approved before creating campaigns. Current status: " + brand.status.value
        )

    hotel = db.query(Hotel).filter(Hotel.id == request.hotel_id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")

    use_case_map = {v.value: v for v in CampaignUseCase}
    use_case = use_case_map.get(request.use_case, CampaignUseCase.CUSTOMER_CARE)

    campaign = SMSComplianceCampaign(
        brand_id=request.brand_id,
        hotel_id=request.hotel_id,
        friendly_name=request.friendly_name,
        use_case=use_case,
        description=request.description,
        message_samples=request.message_samples,
        message_flow=request.message_flow,
        has_embedded_links=request.has_embedded_links,
        has_embedded_phone=request.has_embedded_phone,
        opt_in_message=request.opt_in_message,
        opt_in_keywords=request.opt_in_keywords,
        opt_out_message=request.opt_out_message,
        opt_out_keywords=request.opt_out_keywords,
        help_message=request.help_message,
        help_keywords=request.help_keywords,
        status=CampaignStatus.DRAFT,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign.to_dict()


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, request: CampaignUpdateRequest, db: Session = Depends(get_db)):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status not in [CampaignStatus.DRAFT, CampaignStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail="Can only edit campaigns in draft or failed status"
        )

    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            if key == "use_case":
                use_case_map = {v.value: v for v in CampaignUseCase}
                value = use_case_map.get(value, CampaignUseCase.CUSTOMER_CARE)
            setattr(campaign, key, value)

    db.commit()
    db.refresh(campaign)
    return campaign.to_dict()


@router.post("/campaigns/{campaign_id}/submit")
async def submit_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status not in [CampaignStatus.DRAFT, CampaignStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail=f"Campaign is in {campaign.status.value} status, cannot submit"
        )

    if not campaign.message_samples or len(campaign.message_samples) < 1:
        raise HTTPException(
            status_code=400,
            detail="At least one message sample is required"
        )

    try:
        service = SMSComplianceService(db)
        campaign = service.submit_campaign(campaign)
        return campaign.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/refresh")
async def refresh_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        service = SMSComplianceService(db)
        campaign = service.refresh_campaign_status(campaign)
        return campaign.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    db.delete(campaign)
    db.commit()
    return {"status": "deleted"}


@router.post("/campaigns/{campaign_id}/phone-numbers")
async def assign_phone_number_to_campaign(
    campaign_id: str,
    request: PhoneNumberAssignRequest,
    db: Session = Depends(get_db),
):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    phone = db.query(PhoneNumber).filter(
        PhoneNumber.twilio_sid == request.phone_number_sid,
        PhoneNumber.hotel_id == campaign.hotel_id,
    ).first()
    if not phone:
        raise HTTPException(
            status_code=404,
            detail="Phone number not found or doesn't belong to this hotel"
        )

    try:
        service = SMSComplianceService(db)
        service.assign_phone_number(campaign, request.phone_number_sid)
        return campaign.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/campaigns/{campaign_id}/phone-numbers/{phone_number_sid}")
async def remove_phone_number_from_campaign(
    campaign_id: str,
    phone_number_sid: str,
    db: Session = Depends(get_db),
):
    campaign = db.query(SMSComplianceCampaign).filter(
        SMSComplianceCampaign.id == campaign_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        service = SMSComplianceService(db)
        service.remove_phone_number(campaign, phone_number_sid)
        return campaign.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotels/{hotel_id}/phone-numbers")
async def get_hotel_phone_numbers(
    hotel_id: str,
    db: Session = Depends(get_db),
):
    numbers = db.query(PhoneNumber).filter(
        PhoneNumber.hotel_id == hotel_id,
        PhoneNumber.is_active == True,
    ).all()
    return [n.to_dict() for n in numbers]

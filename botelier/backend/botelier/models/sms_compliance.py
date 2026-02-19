import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from botelier.database import Base


class BrandStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    FAILED = "failed"
    SUSPENDED = "suspended"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    FAILED = "failed"
    SUSPENDED = "suspended"


class BrandType(str, enum.Enum):
    STANDARD = "standard"
    LOW_VOLUME = "low_volume"
    STARTER = "starter"
    SOLE_PROPRIETOR = "sole_proprietor"


class SMSComplianceBrand(Base):
    __tablename__ = "sms_compliance_brands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)

    brand_type = Column(SQLEnum(BrandType), default=BrandType.STANDARD, nullable=False)

    business_name = Column(String, nullable=False)
    business_type = Column(String, nullable=True)
    business_industry = Column(String, nullable=True)
    ein = Column(String, nullable=True)
    ein_issuing_country = Column(String, default="US")
    company_type = Column(String, nullable=True)
    stock_symbol = Column(String, nullable=True)
    stock_exchange = Column(String, nullable=True)
    website_url = Column(String, nullable=True)

    street = Column(String, nullable=True)
    city = Column(String, nullable=True)
    region = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, default="US")

    rep_first_name = Column(String, nullable=True)
    rep_last_name = Column(String, nullable=True)
    rep_email = Column(String, nullable=True)
    rep_phone = Column(String, nullable=True)
    rep_title = Column(String, nullable=True)
    rep_job_position = Column(String, nullable=True)

    twilio_customer_profile_sid = Column(String, nullable=True)
    twilio_a2p_profile_sid = Column(String, nullable=True)
    twilio_brand_sid = Column(String, nullable=True)
    twilio_address_sid = Column(String, nullable=True)
    twilio_business_info_sid = Column(String, nullable=True)
    twilio_auth_rep_sid = Column(String, nullable=True)

    status = Column(SQLEnum(BrandStatus), default=BrandStatus.DRAFT, nullable=False)
    failure_reason = Column(Text, nullable=True)
    trust_score = Column(String, nullable=True)
    twilio_status_raw = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "brand_type": self.brand_type.value if self.brand_type else None,
            "business_name": self.business_name,
            "business_type": self.business_type,
            "business_industry": self.business_industry,
            "ein": self.ein,
            "ein_issuing_country": self.ein_issuing_country,
            "company_type": self.company_type,
            "stock_symbol": self.stock_symbol,
            "stock_exchange": self.stock_exchange,
            "website_url": self.website_url,
            "street": self.street,
            "city": self.city,
            "region": self.region,
            "postal_code": self.postal_code,
            "country": self.country,
            "rep_first_name": self.rep_first_name,
            "rep_last_name": self.rep_last_name,
            "rep_email": self.rep_email,
            "rep_phone": self.rep_phone,
            "rep_title": self.rep_title,
            "rep_job_position": self.rep_job_position,
            "twilio_customer_profile_sid": self.twilio_customer_profile_sid,
            "twilio_a2p_profile_sid": self.twilio_a2p_profile_sid,
            "twilio_brand_sid": self.twilio_brand_sid,
            "status": self.status.value if self.status else None,
            "failure_reason": self.failure_reason,
            "trust_score": self.trust_score,
            "twilio_status_raw": self.twilio_status_raw,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }


class CampaignUseCase(str, enum.Enum):
    TWO_FA = "2FA"
    ACCOUNT_NOTIFICATION = "ACCOUNT_NOTIFICATION"
    CUSTOMER_CARE = "CUSTOMER_CARE"
    DELIVERY_NOTIFICATION = "DELIVERY_NOTIFICATION"
    FRAUD_ALERT = "FRAUD_ALERT"
    HIGHER_EDUCATION = "HIGHER_EDUCATION"
    MARKETING = "MARKETING"
    POLLING_VOTING = "POLLING_VOTING"
    PUBLIC_SERVICE_ANNOUNCEMENT = "PUBLIC_SERVICE_ANNOUNCEMENT"
    SECURITY_ALERT = "SECURITY_ALERT"
    MIXED = "MIXED"
    LOW_VOLUME = "LOW_VOLUME"


class SMSComplianceCampaign(Base):
    __tablename__ = "sms_compliance_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), ForeignKey("sms_compliance_brands.id"), nullable=False, index=True)
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False, index=True)

    friendly_name = Column(String, nullable=False)
    use_case = Column(SQLEnum(CampaignUseCase), default=CampaignUseCase.CUSTOMER_CARE, nullable=False)
    description = Column(Text, nullable=True)

    message_samples = Column(JSONB, default=list)
    message_flow = Column(Text, nullable=True)
    has_embedded_links = Column(Boolean, default=False)
    has_embedded_phone = Column(Boolean, default=False)

    opt_in_message = Column(Text, nullable=True)
    opt_in_keywords = Column(String, default="YES,START")
    opt_out_message = Column(Text, nullable=True)
    opt_out_keywords = Column(String, default="STOP,END,CANCEL,UNSUBSCRIBE,QUIT")
    help_message = Column(Text, nullable=True)
    help_keywords = Column(String, default="HELP,INFO")

    twilio_messaging_service_sid = Column(String, nullable=True)
    twilio_campaign_sid = Column(String, nullable=True)

    assigned_phone_numbers = Column(JSONB, default=list)

    status = Column(SQLEnum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False)
    failure_reason = Column(Text, nullable=True)
    twilio_status_raw = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "brand_id": str(self.brand_id),
            "hotel_id": str(self.hotel_id),
            "friendly_name": self.friendly_name,
            "use_case": self.use_case.value if self.use_case else None,
            "description": self.description,
            "message_samples": self.message_samples or [],
            "message_flow": self.message_flow,
            "has_embedded_links": self.has_embedded_links or False,
            "has_embedded_phone": self.has_embedded_phone or False,
            "opt_in_message": self.opt_in_message,
            "opt_in_keywords": self.opt_in_keywords,
            "opt_out_message": self.opt_out_message,
            "opt_out_keywords": self.opt_out_keywords,
            "help_message": self.help_message,
            "help_keywords": self.help_keywords,
            "twilio_messaging_service_sid": self.twilio_messaging_service_sid,
            "twilio_campaign_sid": self.twilio_campaign_sid,
            "assigned_phone_numbers": self.assigned_phone_numbers or [],
            "status": self.status.value if self.status else None,
            "failure_reason": self.failure_reason,
            "twilio_status_raw": self.twilio_status_raw,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }

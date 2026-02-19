import os
import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from botelier.models.sms_compliance import (
    SMSComplianceBrand, SMSComplianceCampaign,
    BrandStatus, CampaignStatus,
)

logger = logging.getLogger(__name__)

CUSTOMER_PROFILE_POLICY_SID = "RNb0d4771c2c98518d663e1c8c5c14e1c7"
A2P_PROFILE_POLICY_SID = "RNdfbf35ca999fd90a213969e87815bfcf"


class SMSComplianceService:

    def __init__(self, db: Session):
        self.db = db
        self._master_client = None

    @property
    def master_client(self) -> TwilioClient:
        if self._master_client is None:
            account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
            if not account_sid or not auth_token:
                raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN required")
            self._master_client = TwilioClient(account_sid, auth_token)
        return self._master_client

    def submit_brand(self, brand: SMSComplianceBrand) -> SMSComplianceBrand:
        try:
            if not brand.twilio_customer_profile_sid:
                brand = self._create_customer_profile(brand)

            if not brand.twilio_a2p_profile_sid:
                brand = self._create_a2p_profile(brand)

            if not brand.twilio_brand_sid:
                brand = self._create_brand_registration(brand)

            brand.status = BrandStatus.PENDING
            self.db.commit()
            self.db.refresh(brand)
            logger.info(f"Brand {brand.id} submitted to Twilio: {brand.twilio_brand_sid}")
            return brand

        except TwilioRestException as e:
            brand.status = BrandStatus.FAILED
            brand.failure_reason = str(e)
            self.db.commit()
            logger.exception(f"Twilio error submitting brand {brand.id}: {e}")
            raise
        except Exception as e:
            brand.status = BrandStatus.FAILED
            brand.failure_reason = str(e)
            self.db.commit()
            logger.exception(f"Error submitting brand {brand.id}: {e}")
            raise

    def _create_customer_profile(self, brand: SMSComplianceBrand) -> SMSComplianceBrand:
        client = self.master_client

        profile = client.trusthub.v1.customer_profiles.create(
            friendly_name=f"Botelier - {brand.business_name}",
            email=brand.rep_email or "",
            policy_sid=CUSTOMER_PROFILE_POLICY_SID,
        )
        brand.twilio_customer_profile_sid = profile.sid
        logger.info(f"Created customer profile: {profile.sid}")

        business_attrs = {
            "business_name": brand.business_name,
            "business_type": brand.business_type or "Corporation",
            "business_registration_number": brand.ein or "",
            "business_registration_identifier": "EIN",
            "business_industry": brand.business_industry or "Technology",
            "website_url": brand.website_url or "",
        }
        business_info = client.trusthub.v1.end_users.create(
            friendly_name=f"{brand.business_name} Business Info",
            type="customer_profile_business_information",
            attributes=business_attrs,
        )
        brand.twilio_business_info_sid = business_info.sid
        logger.info(f"Created business info end user: {business_info.sid}")

        address = client.addresses.create(
            friendly_name=f"{brand.business_name} Address",
            customer_name=brand.business_name,
            street=brand.street or "",
            city=brand.city or "",
            region=brand.region or "",
            postal_code=brand.postal_code or "",
            iso_country=brand.country or "US",
        )
        brand.twilio_address_sid = address.sid
        logger.info(f"Created address: {address.sid}")

        rep_attrs = {
            "first_name": brand.rep_first_name or "",
            "last_name": brand.rep_last_name or "",
            "email": brand.rep_email or "",
            "phone_number": brand.rep_phone or "",
            "business_title": brand.rep_title or "",
            "job_position": brand.rep_job_position or "Director",
        }
        auth_rep = client.trusthub.v1.end_users.create(
            friendly_name=f"{brand.rep_first_name} {brand.rep_last_name}",
            type="authorized_representative_1",
            attributes=rep_attrs,
        )
        brand.twilio_auth_rep_sid = auth_rep.sid
        logger.info(f"Created auth rep: {auth_rep.sid}")

        client.trusthub.v1.customer_profiles(profile.sid) \
            .customer_profiles_entity_assignments.create(object_sid=business_info.sid)
        client.trusthub.v1.customer_profiles(profile.sid) \
            .customer_profiles_entity_assignments.create(object_sid=address.sid)
        client.trusthub.v1.customer_profiles(profile.sid) \
            .customer_profiles_entity_assignments.create(object_sid=auth_rep.sid)

        client.trusthub.v1.customer_profiles(profile.sid) \
            .customer_profiles_evaluations.create(policy_sid=CUSTOMER_PROFILE_POLICY_SID)
        logger.info(f"Customer profile {profile.sid} submitted for evaluation")

        self.db.commit()
        return brand

    def _create_a2p_profile(self, brand: SMSComplianceBrand) -> SMSComplianceBrand:
        client = self.master_client

        trust_product = client.trusthub.v1.trust_products.create(
            friendly_name=f"Botelier A2P - {brand.business_name}",
            email=brand.rep_email or "",
            policy_sid=A2P_PROFILE_POLICY_SID,
        )
        brand.twilio_a2p_profile_sid = trust_product.sid
        logger.info(f"Created A2P trust product: {trust_product.sid}")

        a2p_attrs = {
            "company_type": brand.company_type or "private_profit",
            "stock_symbol": brand.stock_symbol or "",
            "stock_exchange": brand.stock_exchange or "NONE",
            "ein": brand.ein or "",
            "ein_issuing_country": brand.ein_issuing_country or "US",
            "business_regions_of_operation": "USA_AND_CANADA",
            "website_url": brand.website_url or "",
        }
        a2p_info = client.trusthub.v1.end_users.create(
            friendly_name=f"{brand.business_name} A2P Info",
            type="a2p_messaging_profile_information",
            attributes=a2p_attrs,
        )
        logger.info(f"Created A2P end user: {a2p_info.sid}")

        client.trusthub.v1.trust_products(trust_product.sid) \
            .trust_products_entity_assignments.create(object_sid=a2p_info.sid)
        if brand.twilio_customer_profile_sid:
            client.trusthub.v1.trust_products(trust_product.sid) \
                .trust_products_entity_assignments.create(object_sid=brand.twilio_customer_profile_sid)

        client.trusthub.v1.trust_products(trust_product.sid) \
            .trust_products_evaluations.create(policy_sid=A2P_PROFILE_POLICY_SID)
        logger.info(f"A2P profile {trust_product.sid} submitted for evaluation")

        self.db.commit()
        return brand

    def _create_brand_registration(self, brand: SMSComplianceBrand) -> SMSComplianceBrand:
        client = self.master_client

        params: Dict[str, Any] = {
            "customer_profile_bundle_sid": brand.twilio_customer_profile_sid,
            "a2p_profile_bundle_sid": brand.twilio_a2p_profile_sid,
        }
        if brand.brand_type and brand.brand_type.value == "low_volume":
            params["skip_automatic_sec_vet"] = True

        brand_reg = client.messaging.v1.brand_registrations.create(**params)
        brand.twilio_brand_sid = brand_reg.sid
        logger.info(f"Created brand registration: {brand_reg.sid}")

        self.db.commit()
        return brand

    def refresh_brand_status(self, brand: SMSComplianceBrand) -> SMSComplianceBrand:
        if not brand.twilio_brand_sid:
            return brand

        try:
            client = self.master_client
            brand_reg = client.messaging.v1.brand_registrations(brand.twilio_brand_sid).fetch()

            brand.twilio_status_raw = brand_reg.status
            status_map = {
                "PENDING": BrandStatus.PENDING,
                "IN_REVIEW": BrandStatus.IN_REVIEW,
                "APPROVED": BrandStatus.APPROVED,
                "FAILED": BrandStatus.FAILED,
                "SUSPENDED": BrandStatus.SUSPENDED,
            }
            brand.status = status_map.get(brand_reg.status, BrandStatus.PENDING)
            brand.failure_reason = getattr(brand_reg, 'failure_reason', None)

            if hasattr(brand_reg, 'brand_score'):
                brand.trust_score = str(brand_reg.brand_score)

            self.db.commit()
            self.db.refresh(brand)
            logger.info(f"Brand {brand.id} status refreshed: {brand.status.value}")
            return brand

        except TwilioRestException as e:
            logger.exception(f"Error refreshing brand status: {e}")
            raise

    def submit_campaign(self, campaign: SMSComplianceCampaign) -> SMSComplianceCampaign:
        try:
            brand = self.db.query(SMSComplianceBrand).filter(
                SMSComplianceBrand.id == campaign.brand_id
            ).first()

            if not brand or brand.status != BrandStatus.APPROVED:
                raise ValueError("Brand must be approved before creating campaigns")

            if not campaign.twilio_messaging_service_sid:
                campaign = self._create_messaging_service(campaign)

            campaign = self._create_campaign_registration(campaign, brand)

            campaign.status = CampaignStatus.PENDING
            self.db.commit()
            self.db.refresh(campaign)
            logger.info(f"Campaign {campaign.id} submitted: {campaign.twilio_campaign_sid}")
            return campaign

        except TwilioRestException as e:
            campaign.status = CampaignStatus.FAILED
            campaign.failure_reason = str(e)
            self.db.commit()
            logger.exception(f"Twilio error submitting campaign {campaign.id}: {e}")
            raise
        except Exception as e:
            campaign.status = CampaignStatus.FAILED
            campaign.failure_reason = str(e)
            self.db.commit()
            logger.exception(f"Error submitting campaign {campaign.id}: {e}")
            raise

    def _create_messaging_service(self, campaign: SMSComplianceCampaign) -> SMSComplianceCampaign:
        client = self.master_client

        service = client.messaging.v1.services.create(
            friendly_name=f"Botelier - {campaign.friendly_name}",
        )
        campaign.twilio_messaging_service_sid = service.sid
        logger.info(f"Created messaging service: {service.sid}")

        self.db.commit()
        return campaign

    def _create_campaign_registration(
        self, campaign: SMSComplianceCampaign, brand: SMSComplianceBrand
    ) -> SMSComplianceCampaign:
        client = self.master_client

        samples = campaign.message_samples or []
        if not samples:
            samples = ["Hello, how can we assist you today?"]

        params: Dict[str, Any] = {
            "brand_registration_sid": brand.twilio_brand_sid,
            "description": campaign.description or campaign.friendly_name,
            "message_flow": campaign.message_flow or "Customers opt in by texting our business number. They can opt out by texting STOP.",
            "message_samples": samples,
            "us_app_to_person_usecase": campaign.use_case.value if campaign.use_case else "CUSTOMER_CARE",
            "has_embedded_links": campaign.has_embedded_links or False,
            "has_embedded_phone": campaign.has_embedded_phone or False,
            "opt_in_message": campaign.opt_in_message or "You have opted in to receive messages. Reply STOP to unsubscribe.",
            "opt_out_message": campaign.opt_out_message or "You have been unsubscribed. Reply START to re-subscribe.",
            "opt_in_keywords": (campaign.opt_in_keywords or "YES,START").split(","),
            "opt_out_keywords": (campaign.opt_out_keywords or "STOP,END,CANCEL,UNSUBSCRIBE,QUIT").split(","),
            "help_message": campaign.help_message or "Reply HELP for assistance or STOP to unsubscribe.",
            "help_keywords": (campaign.help_keywords or "HELP,INFO").split(","),
        }

        us_a2p = client.messaging.v1.services(campaign.twilio_messaging_service_sid) \
            .us_app_to_person.create(**params)
        campaign.twilio_campaign_sid = us_a2p.sid
        logger.info(f"Created campaign: {us_a2p.sid}")

        self.db.commit()
        return campaign

    def refresh_campaign_status(self, campaign: SMSComplianceCampaign) -> SMSComplianceCampaign:
        if not campaign.twilio_campaign_sid or not campaign.twilio_messaging_service_sid:
            return campaign

        try:
            client = self.master_client
            us_a2p = client.messaging.v1.services(campaign.twilio_messaging_service_sid) \
                .us_app_to_person(campaign.twilio_campaign_sid).fetch()

            campaign.twilio_status_raw = us_a2p.campaign_status
            status_map = {
                "PENDING": CampaignStatus.PENDING,
                "IN_PROGRESS": CampaignStatus.IN_REVIEW,
                "VERIFIED": CampaignStatus.APPROVED,
                "FAILED": CampaignStatus.FAILED,
                "SUSPENDED": CampaignStatus.SUSPENDED,
            }
            campaign.status = status_map.get(us_a2p.campaign_status, CampaignStatus.PENDING)
            campaign.failure_reason = getattr(us_a2p, 'failure_reason', None)

            self.db.commit()
            self.db.refresh(campaign)
            logger.info(f"Campaign {campaign.id} status refreshed: {campaign.status.value}")
            return campaign

        except TwilioRestException as e:
            logger.exception(f"Error refreshing campaign status: {e}")
            raise

    def assign_phone_number(self, campaign: SMSComplianceCampaign, phone_number_sid: str) -> bool:
        if not campaign.twilio_messaging_service_sid:
            raise ValueError("Campaign must have a messaging service before assigning numbers")

        try:
            client = self.master_client
            client.messaging.v1.services(campaign.twilio_messaging_service_sid) \
                .phone_numbers.create(phone_number_sid=phone_number_sid)

            current = campaign.assigned_phone_numbers or []
            if phone_number_sid not in current:
                current.append(phone_number_sid)
                campaign.assigned_phone_numbers = current
                self.db.commit()

            logger.info(f"Assigned {phone_number_sid} to campaign {campaign.id}")
            return True

        except TwilioRestException as e:
            logger.exception(f"Error assigning phone number to campaign: {e}")
            raise

    def remove_phone_number(self, campaign: SMSComplianceCampaign, phone_number_sid: str) -> bool:
        if not campaign.twilio_messaging_service_sid:
            return False

        try:
            client = self.master_client
            client.messaging.v1.services(campaign.twilio_messaging_service_sid) \
                .phone_numbers(phone_number_sid).delete()

            current = campaign.assigned_phone_numbers or []
            if phone_number_sid in current:
                current.remove(phone_number_sid)
                campaign.assigned_phone_numbers = current
                self.db.commit()

            logger.info(f"Removed {phone_number_sid} from campaign {campaign.id}")
            return True

        except TwilioRestException as e:
            logger.exception(f"Error removing phone number from campaign: {e}")
            raise

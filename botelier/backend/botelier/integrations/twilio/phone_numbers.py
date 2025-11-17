"""
Twilio Phone Number Operations.

Handles searching, purchasing, and managing phone numbers for hotel sub-accounts.
"""

from typing import List, Dict, Any, Optional
from twilio.base.exceptions import TwilioRestException
from .client import BotelierTwilioClient


class PhoneNumberManager:
    """
    Manages phone number operations for a hotel's Twilio sub-account.
    
    Usage:
        manager = PhoneNumberManager(
            sub_account_sid="AC...",
            sub_auth_token="..."
        )
        
        # Search by area code
        available = manager.search_available_numbers(
            area_code="415",
            country="US"
        )
        
        # Purchase number
        number = manager.purchase_number("+14155551234")
    """
    
    def __init__(self, sub_account_sid: str, sub_auth_token: str):
        """
        Initialize manager for a specific hotel's sub-account.
        
        Args:
            sub_account_sid: Hotel's Twilio sub-account SID
            sub_auth_token: Hotel's Twilio sub-account auth token
        """
        self.client = BotelierTwilioClient(
            account_sid=sub_account_sid,
            auth_token=sub_auth_token
        )
    
    def search_available_numbers(
        self,
        area_code: Optional[str] = None,
        country: str = "US",
        limit: int = 10,
        sms_enabled: bool = True,
        voice_enabled: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search for available phone numbers by area code.
        
        Args:
            area_code: 3-digit area code (e.g., "415", "212")
            country: ISO country code (default: "US")
            limit: Maximum numbers to return
            sms_enabled: Require SMS capability
            voice_enabled: Require voice capability
            
        Returns:
            List of available numbers:
            [
                {
                    "phone_number": "+14155551234",
                    "friendly_name": "(415) 555-1234",
                    "capabilities": {"voice": true, "sms": true},
                    "locality": "San Francisco",
                    "region": "CA",
                    "iso_country": "US"
                },
                ...
            ]
        """
        try:
            # Build search params
            search_params = {
                "limit": limit,
                "sms_enabled": sms_enabled,
                "voice_enabled": voice_enabled,
            }
            
            if area_code:
                search_params["area_code"] = area_code
            
            # Search available numbers
            available_numbers = self.client.client.available_phone_numbers(country) \
                .local.list(**search_params)
            
            # Format results
            results = []
            for number in available_numbers:
                results.append({
                    "phone_number": number.phone_number,
                    "friendly_name": number.friendly_name,
                    "capabilities": {
                        "voice": number.capabilities.get("voice", False),
                        "sms": number.capabilities.get("sms", False),
                        "mms": number.capabilities.get("mms", False),
                    },
                    "locality": number.locality,
                    "region": number.region,
                    "iso_country": number.iso_country,
                    "postal_code": number.postal_code,
                })
            
            return results
            
        except TwilioRestException as e:
            print(f"Failed to search numbers: {e}")
            raise
    
    def purchase_number(
        self,
        phone_number: str,
        friendly_name: Optional[str] = None,
        voice_url: Optional[str] = None,
        voice_method: str = "POST",
        status_callback: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Purchase a phone number for the hotel's sub-account.
        
        Args:
            phone_number: E.164 format number (e.g., "+14155551234")
            friendly_name: Optional label for the number
            voice_url: Webhook URL for incoming calls
            voice_method: HTTP method for voice_url (default: "POST")
            status_callback: URL for call status updates
            
        Returns:
            Purchased number details:
            {
                "sid": "PN...",
                "phone_number": "+14155551234",
                "friendly_name": "Front Desk",
                "capabilities": {"voice": true, "sms": true}
            }
        """
        try:
            purchase_params = {
                "phone_number": phone_number,
            }
            
            if friendly_name:
                purchase_params["friendly_name"] = friendly_name
            
            if voice_url:
                purchase_params["voice_url"] = voice_url
                purchase_params["voice_method"] = voice_method
            
            if status_callback:
                purchase_params["status_callback"] = status_callback
            
            # Purchase the number
            purchased = self.client.client.incoming_phone_numbers.create(
                **purchase_params
            )
            
            return {
                "sid": purchased.sid,
                "phone_number": purchased.phone_number,
                "friendly_name": purchased.friendly_name,
                "capabilities": {
                    "voice": purchased.capabilities.get("voice", False),
                    "sms": purchased.capabilities.get("sms", False),
                    "mms": purchased.capabilities.get("mms", False),
                },
                "date_created": purchased.date_created.isoformat() if purchased.date_created else None,
            }
            
        except TwilioRestException as e:
            print(f"Failed to purchase number {phone_number}: {e}")
            raise
    
    def update_number_config(
        self,
        phone_number_sid: str,
        voice_url: Optional[str] = None,
        voice_method: Optional[str] = None,
        friendly_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update configuration for an existing phone number.
        
        Args:
            phone_number_sid: Twilio phone number SID
            voice_url: New webhook URL for incoming calls
            voice_method: HTTP method (POST/GET)
            friendly_name: New label
            
        Returns:
            Updated number details
        """
        try:
            update_params = {}
            
            if voice_url is not None:
                update_params["voice_url"] = voice_url
            if voice_method is not None:
                update_params["voice_method"] = voice_method
            if friendly_name is not None:
                update_params["friendly_name"] = friendly_name
            
            updated = self.client.client.incoming_phone_numbers(phone_number_sid).update(
                **update_params
            )
            
            return {
                "sid": updated.sid,
                "phone_number": updated.phone_number,
                "friendly_name": updated.friendly_name,
                "voice_url": updated.voice_url,
            }
            
        except TwilioRestException as e:
            print(f"Failed to update number {phone_number_sid}: {e}")
            raise
    
    def release_number(self, phone_number_sid: str) -> bool:
        """
        Release a phone number back to Twilio.
        
        Args:
            phone_number_sid: Twilio phone number SID
            
        Returns:
            True if successful
        """
        try:
            self.client.client.incoming_phone_numbers(phone_number_sid).delete()
            return True
            
        except TwilioRestException as e:
            print(f"Failed to release number {phone_number_sid}: {e}")
            return False
    
    def list_numbers(self) -> List[Dict[str, Any]]:
        """
        List all phone numbers owned by this sub-account.
        
        Returns:
            List of phone numbers with details
        """
        try:
            numbers = self.client.client.incoming_phone_numbers.list()
            
            results = []
            for number in numbers:
                results.append({
                    "sid": number.sid,
                    "phone_number": number.phone_number,
                    "friendly_name": number.friendly_name,
                    "capabilities": {
                        "voice": number.capabilities.get("voice", False),
                        "sms": number.capabilities.get("sms", False),
                        "mms": number.capabilities.get("mms", False),
                    },
                    "voice_url": number.voice_url,
                    "date_created": number.date_created.isoformat() if number.date_created else None,
                })
            
            return results
            
        except TwilioRestException as e:
            print(f"Failed to list numbers: {e}")
            raise

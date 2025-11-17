"""
Twilio Sub-Account Management.

Handles creation and management of Twilio sub-accounts for hotels.
Each hotel gets its own isolated sub-account for billing and phone numbers.
"""

from typing import Dict, Any
from twilio.base.exceptions import TwilioRestException
from .client import BotelierTwilioClient


class SubAccountManager:
    """
    Manages Twilio sub-accounts for hotel multi-tenancy.
    
    Usage:
        manager = SubAccountManager()
        sub_account = manager.create_sub_account("Grand Hotel")
        # Returns: {"sid": "AC...", "auth_token": "...", "friendly_name": "..."}
    """
    
    def __init__(self):
        """Initialize with main Botelier account credentials."""
        self.client = BotelierTwilioClient()
    
    def create_sub_account(self, hotel_name: str) -> Dict[str, Any]:
        """
        Create a new Twilio sub-account for a hotel.
        
        Args:
            hotel_name: Name of the hotel (used as friendly name)
            
        Returns:
            Dictionary with sub-account details:
            {
                "sid": "AC...",
                "auth_token": "...",
                "friendly_name": "Botelier - Hotel Name",
                "status": "active"
            }
            
        Raises:
            TwilioRestException: If sub-account creation fails
        """
        try:
            # Create sub-account with Botelier prefix
            friendly_name = f"Botelier - {hotel_name}"
            
            sub_account = self.client.client.api.accounts.create(
                friendly_name=friendly_name
            )
            
            return {
                "sid": sub_account.sid,
                "auth_token": sub_account.auth_token,
                "friendly_name": sub_account.friendly_name,
                "status": sub_account.status,
                "date_created": sub_account.date_created.isoformat() if sub_account.date_created else None,
            }
            
        except TwilioRestException as e:
            print(f"Failed to create sub-account for {hotel_name}: {e}")
            raise
    
    def get_sub_account(self, sub_account_sid: str) -> Dict[str, Any]:
        """
        Get sub-account details.
        
        Args:
            sub_account_sid: Sub-account SID
            
        Returns:
            Dictionary with sub-account details
        """
        try:
            sub_account = self.client.client.api.accounts(sub_account_sid).fetch()
            
            return {
                "sid": sub_account.sid,
                "friendly_name": sub_account.friendly_name,
                "status": sub_account.status,
                "date_created": sub_account.date_created.isoformat() if sub_account.date_created else None,
            }
            
        except TwilioRestException as e:
            print(f"Failed to fetch sub-account {sub_account_sid}: {e}")
            raise
    
    def suspend_sub_account(self, sub_account_sid: str) -> bool:
        """
        Suspend a sub-account (disable but don't delete).
        
        Args:
            sub_account_sid: Sub-account SID
            
        Returns:
            True if successful
        """
        try:
            self.client.client.api.accounts(sub_account_sid).update(
                status="suspended"
            )
            return True
            
        except TwilioRestException as e:
            print(f"Failed to suspend sub-account {sub_account_sid}: {e}")
            return False
    
    def close_sub_account(self, sub_account_sid: str) -> bool:
        """
        Close a sub-account permanently.
        
        Args:
            sub_account_sid: Sub-account SID
            
        Returns:
            True if successful
        """
        try:
            self.client.client.api.accounts(sub_account_sid).update(
                status="closed"
            )
            return True
            
        except TwilioRestException as e:
            print(f"Failed to close sub-account {sub_account_sid}: {e}")
            return False

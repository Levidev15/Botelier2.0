"""
Twilio Client Wrapper - Manages Twilio API interactions.

This wrapper provides a clean interface to Twilio's API,
hiding implementation details from the rest of the application.
"""

import os
from typing import Optional, List, Dict, Any
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException


class BotelierTwilioClient:
    """
    Wrapper around Twilio REST API client.
    
    Handles both main account and sub-account operations.
    
    Usage:
        # Main account operations
        client = BotelierTwilioClient()
        sub_account = client.create_sub_account("Grand Hotel")
        
        # Sub-account operations
        sub_client = BotelierTwilioClient(
            account_sid=sub_account.sid,
            auth_token=sub_account.auth_token
        )
        numbers = sub_client.search_available_numbers(area_code="415")
    """
    
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None
    ):
        """
        Initialize Twilio client.
        
        Args:
            account_sid: Twilio account SID (uses env var if not provided)
            auth_token: Twilio auth token (uses env var if not provided)
        """
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        
        if not self.account_sid or not self.auth_token:
            raise ValueError(
                "Twilio credentials not found. Set TWILIO_ACCOUNT_SID and "
                "TWILIO_AUTH_TOKEN environment variables or pass them explicitly."
            )
        
        self.client = TwilioClient(self.account_sid, self.auth_token)
    
    def test_connection(self) -> bool:
        """
        Test if Twilio credentials are valid.
        
        Returns:
            True if credentials work, False otherwise
        """
        try:
            self.client.api.accounts(self.account_sid).fetch()
            return True
        except TwilioRestException:
            return False

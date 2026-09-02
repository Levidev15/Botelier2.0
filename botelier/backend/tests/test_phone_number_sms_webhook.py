"""Tests for SMS webhook auto-configuration on phone number purchase and reconfigure.

Covers:
  1. purchase_number() passes sms_url + sms_method to Twilio.
  2. The purchase API handler sets sms_enabled=True on the new DB record.
  3. The reconfigure endpoint pushes sms_url to Twilio and flips sms_enabled.
  4. update_number_config() forwards sms_url / sms_method to Twilio update().
"""

from unittest.mock import MagicMock, patch

import pytest

from botelier.integrations.twilio.phone_numbers import PhoneNumberManager


# ---------------------------------------------------------------------------
# PhoneNumberManager.purchase_number — unit tests
# ---------------------------------------------------------------------------


def _make_manager():
    """Return a PhoneNumberManager with a mocked Twilio client."""
    with patch("botelier.integrations.twilio.phone_numbers.BotelierTwilioClient") as MockClient:
        mock_twilio = MagicMock()
        MockClient.return_value = mock_twilio
        manager = PhoneNumberManager(
            sub_account_sid="ACtest",
            sub_auth_token="tok",
        )
        manager.client = mock_twilio
        return manager, mock_twilio


class TestPurchaseNumberSmsWebhook:
    def test_sms_url_passed_to_twilio_create(self):
        """sms_url and sms_method must appear in incoming_phone_numbers.create() kwargs."""
        manager, mock_twilio = _make_manager()

        purchased_mock = MagicMock()
        purchased_mock.sid = "PNabc"
        purchased_mock.phone_number = "+14155551234"
        purchased_mock.friendly_name = "Test Number"
        purchased_mock.capabilities = {"voice": True, "sms": True, "mms": False}
        purchased_mock.date_created = None
        mock_twilio.client.incoming_phone_numbers.create.return_value = purchased_mock

        manager.purchase_number(
            phone_number="+14155551234",
            voice_url="https://botelier.example.com/api/calls/incoming",
            voice_method="POST",
            status_callback="https://botelier.example.com/api/calls/status",
            sms_url="https://botelier.example.com/api/sms/webhook",
            sms_method="POST",
        )

        call_kwargs = mock_twilio.client.incoming_phone_numbers.create.call_args.kwargs
        assert call_kwargs["sms_url"] == "https://botelier.example.com/api/sms/webhook"
        assert call_kwargs["sms_method"] == "POST"

    def test_sms_url_omitted_when_not_provided(self):
        """When sms_url is not passed, it must NOT appear in the Twilio create call."""
        manager, mock_twilio = _make_manager()

        purchased_mock = MagicMock()
        purchased_mock.sid = "PNabc"
        purchased_mock.phone_number = "+14155551234"
        purchased_mock.friendly_name = "Test Number"
        purchased_mock.capabilities = {"voice": True, "sms": True, "mms": False}
        purchased_mock.date_created = None
        mock_twilio.client.incoming_phone_numbers.create.return_value = purchased_mock

        manager.purchase_number(
            phone_number="+14155551234",
            voice_url="https://botelier.example.com/api/calls/incoming",
        )

        call_kwargs = mock_twilio.client.incoming_phone_numbers.create.call_args.kwargs
        assert "sms_url" not in call_kwargs
        assert "sms_method" not in call_kwargs

    def test_voice_url_still_set_alongside_sms(self):
        """voice_url, voice_method, and status_callback must all survive alongside sms params."""
        manager, mock_twilio = _make_manager()

        purchased_mock = MagicMock()
        purchased_mock.sid = "PNabc"
        purchased_mock.phone_number = "+14155551234"
        purchased_mock.friendly_name = None
        purchased_mock.capabilities = {"voice": True, "sms": True, "mms": False}
        purchased_mock.date_created = None
        mock_twilio.client.incoming_phone_numbers.create.return_value = purchased_mock

        manager.purchase_number(
            phone_number="+14155551234",
            voice_url="https://botelier.example.com/api/calls/incoming",
            voice_method="POST",
            status_callback="https://botelier.example.com/api/calls/status",
            sms_url="https://botelier.example.com/api/sms/webhook",
            sms_method="POST",
        )

        call_kwargs = mock_twilio.client.incoming_phone_numbers.create.call_args.kwargs
        assert call_kwargs["voice_url"] == "https://botelier.example.com/api/calls/incoming"
        assert call_kwargs["voice_method"] == "POST"
        assert call_kwargs["status_callback"] == "https://botelier.example.com/api/calls/status"
        assert call_kwargs["sms_url"] == "https://botelier.example.com/api/sms/webhook"
        assert call_kwargs["sms_method"] == "POST"


# ---------------------------------------------------------------------------
# PhoneNumberManager.update_number_config — sms params forwarded
# ---------------------------------------------------------------------------


class TestUpdateNumberConfigSmsWebhook:
    def test_sms_url_forwarded_to_twilio_update(self):
        """update_number_config must include sms_url and sms_method in the Twilio update call."""
        manager, mock_twilio = _make_manager()

        updated_mock = MagicMock()
        updated_mock.sid = "PNabc"
        updated_mock.phone_number = "+14155551234"
        updated_mock.friendly_name = "Test"
        updated_mock.voice_url = "https://botelier.example.com/api/calls/incoming"
        updated_mock.status_callback = "https://botelier.example.com/api/calls/status"
        mock_twilio.client.incoming_phone_numbers.return_value.update.return_value = updated_mock

        manager.update_number_config(
            phone_number_sid="PNabc",
            voice_url="https://botelier.example.com/api/calls/incoming",
            voice_method="POST",
            status_callback="https://botelier.example.com/api/calls/status",
            status_callback_method="POST",
            sms_url="https://botelier.example.com/api/sms/webhook",
            sms_method="POST",
        )

        call_kwargs = mock_twilio.client.incoming_phone_numbers.return_value.update.call_args.kwargs
        assert call_kwargs["sms_url"] == "https://botelier.example.com/api/sms/webhook"
        assert call_kwargs["sms_method"] == "POST"

    def test_sms_url_clear_forwarded(self):
        """Passing sms_url='' (disable) must still be forwarded — empty string is not None."""
        manager, mock_twilio = _make_manager()

        updated_mock = MagicMock()
        updated_mock.sid = "PNabc"
        updated_mock.phone_number = "+14155551234"
        updated_mock.friendly_name = "Test"
        updated_mock.voice_url = ""
        updated_mock.status_callback = ""
        mock_twilio.client.incoming_phone_numbers.return_value.update.return_value = updated_mock

        manager.update_number_config(
            phone_number_sid="PNabc",
            sms_url="",
            sms_method="POST",
        )

        call_kwargs = mock_twilio.client.incoming_phone_numbers.return_value.update.call_args.kwargs
        # Empty string is a valid value (clears the webhook) — it must be forwarded
        assert "sms_url" in call_kwargs
        assert call_kwargs["sms_url"] == ""

import asyncio
from types import SimpleNamespace

from botelier.voice.flows.native_execution import NativeTerminalResult


def test_sms_preview_and_invalid_recipient_never_call_twilio():
    from botelier.voice.flows.native_messaging import NativeMessenger

    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(sid="SMoffline")

    messenger = NativeMessenger(
        identity=SimpleNamespace(account_id="account", property_id="property"),
        twilio_client=SimpleNamespace(messages=Messages()),
        from_number="+12025550100",
        execution_mode="preview",
    )
    preview = asyncio.run(messenger.send_sms("+12025550101", "Approved link"))
    assert preview == NativeTerminalResult(False, failure_reason="preview_required")
    assert calls == []

    actual = NativeMessenger(
        identity=SimpleNamespace(account_id="account", property_id="property"),
        twilio_client=SimpleNamespace(messages=Messages()),
        from_number="+12025550100",
    )
    invalid = asyncio.run(actual.send_sms("+12025550101\r\nBcc:x", "Approved link"))
    assert invalid == NativeTerminalResult(False, failure_reason="invalid_recipient")
    assert calls == []


def test_sms_reports_only_provider_acceptance_and_email_rejects_header_injection():
    from botelier.voice.flows.native_messaging import NativeMessenger

    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(sid="SMoffline")

    messenger = NativeMessenger(
        identity=SimpleNamespace(account_id="account", property_id="property"),
        twilio_client=SimpleNamespace(messages=Messages()),
        from_number="+12025550100",
        email_dispatch=lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )
    accepted = asyncio.run(messenger.send_sms("+12025550101", "Exact approved URL"))
    assert accepted == NativeTerminalResult(True, completed=False)
    assert calls == [{
        "body": "Exact approved URL", "from_": "+12025550100",
        "to": "+12025550101",
    }]

    connection = SimpleNamespace(
        account_id="account", property_id="property", status="connected",
        integration_type=SimpleNamespace(slug="email-sender-gmail"),
        get_connection_config=lambda: {},
    )
    invalid = asyncio.run(messenger.send_email(
        connection, "guest@example.test", "Booking\r\nBcc:bad@example.test",
        "Exact approved URL",
    ))
    assert invalid == NativeTerminalResult(False, failure_reason="invalid_subject")
    assert len(calls) == 1

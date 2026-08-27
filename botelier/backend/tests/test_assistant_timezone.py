"""Assistant timezone API schema and serialization tests."""

import pytest
from botelier.api.assistants import AssistantCreate, AssistantUpdate
from botelier.models.assistant import Assistant
from pydantic import ValidationError


@pytest.mark.parametrize(
    "timezone",
    ["UTC", "America/Los_Angeles", "America/New_York", "Europe/London", "Asia/Tokyo"],
)
def test_assistant_schemas_accept_iana_timezones(timezone):
    created = AssistantCreate(
        account_id="account-1", name="Assistant", timezone=timezone
    )
    assert created.timezone == timezone
    assert AssistantUpdate(timezone=timezone).timezone == timezone


@pytest.mark.parametrize(
    "timezone", ["", "   ", "PST", "America/Not_A_Zone", "../UTC", None]
)
@pytest.mark.parametrize("schema", [AssistantCreate, AssistantUpdate])
def test_assistant_schemas_reject_invalid_timezones(schema, timezone):
    kwargs = {"timezone": timezone}
    if schema is AssistantCreate:
        kwargs.update(account_id="account-1", name="Assistant")

    with pytest.raises(ValidationError) as exc:
        schema(**kwargs)
    assert "timezone" in str(exc.value)
    if timezone is not None:
        assert "valid IANA timezone" in str(exc.value)


def test_assistant_create_defaults_timezone_to_utc():
    assert AssistantCreate(account_id="account-1", name="Assistant").timezone == "UTC"


def test_assistant_serialization_exposes_timezone_with_legacy_fallback():
    assistant = Assistant(
        name="Assistant", account_id="00000000-0000-0000-0000-000000000001"
    )
    assistant.timezone = None

    assert assistant.to_dict()["timezone"] == "UTC"
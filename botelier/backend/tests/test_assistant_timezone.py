"""Assistant timezone API schema and serialization tests."""

import pytest
from botelier.api.assistants import AssistantCreate, AssistantUpdate
from botelier.models.assistant import Assistant
from botelier.voice.prompt_context import build_business_context_segment
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


def test_business_name_is_an_optional_per_assistant_setting():
    created = AssistantCreate(
        account_id="account-1",
        name="Downtown voice assistant",
        business_name="Mrs Fields – Downtown Las Vegas",
    )
    assert created.business_name == "Mrs Fields – Downtown Las Vegas"
    assert AssistantUpdate(business_name="Mrs Fields – Airport").business_name == (
        "Mrs Fields – Airport"
    )


def test_only_per_assistant_business_name_is_added_to_llm_context():
    prompt_segment = build_business_context_segment("Mrs Fields – Downtown Las Vegas")
    assert "Mrs Fields – Downtown Las Vegas" in prompt_segment
    assert "BUSINESS CONTEXT" in prompt_segment
    assert build_business_context_segment(None) == ""
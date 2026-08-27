"""Account Basic Information (Settings page) schema tests.

Covers the account-level "name" (business/company name — not limited to
hotels) and "timezone" fields introduced for the Settings > Basic
Information page, and used as the default timezone for newly created
assistants.
"""

import pytest
from pydantic import ValidationError

from botelier.api.account import AccountBasicInfoUpdate


@pytest.mark.parametrize(
    "timezone",
    ["UTC", "America/Los_Angeles", "America/New_York", "Europe/London", "Asia/Tokyo"],
)
def test_basic_info_update_accepts_iana_timezones(timezone):
    update = AccountBasicInfoUpdate(timezone=timezone)
    assert update.timezone == timezone


@pytest.mark.parametrize("timezone", ["", "   ", "PST", "America/Not_A_Zone", "../UTC"])
def test_basic_info_update_rejects_invalid_timezones(timezone):
    with pytest.raises(ValidationError) as exc:
        AccountBasicInfoUpdate(timezone=timezone)
    assert "timezone" in str(exc.value).lower()


def test_basic_info_update_timezone_is_optional():
    # Partial updates (e.g. just renaming the business) must not require a
    # timezone value.
    update = AccountBasicInfoUpdate(name="Mrs Fields")
    assert update.timezone is None
    assert update.name == "Mrs Fields"


def test_basic_info_update_accepts_non_hotel_business_names():
    # The field must not assume every account is a hotel.
    for name in ["Mrs Fields", "Joe's Auto Repair", "Sunrise Medical Clinic"]:
        assert AccountBasicInfoUpdate(name=name).name == name


def test_basic_info_update_rejects_blank_name():
    with pytest.raises(ValidationError):
        AccountBasicInfoUpdate(name="   ")


def test_basic_info_update_strips_name_whitespace():
    assert AccountBasicInfoUpdate(name="  Mrs Fields  ").name == "Mrs Fields"

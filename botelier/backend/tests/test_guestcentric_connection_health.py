"""Regression coverage for the GuestCentric Basic-auth connection health check."""

import base64

import pytest

from botelier.api import integrations


@pytest.mark.asyncio
async def test_guestcentric_health_check_builds_basic_auth_header(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers, params, timeout):
            captured.update(
                url=url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            return FakeResponse()

    integration_type = type(
        "GuestCentricType",
        (),
        {"get_auth_config": lambda _self: {"base_url": "https://crs.example.test/v1"}},
    )()
    monkeypatch.setattr(integrations.httpx, "AsyncClient", FakeClient)

    result = await integrations.test_basic_auth_connection(
        integration_type,
        {
            "username": "hotel-user",
            "password": "hotel-password",
            "apikey": "test-api-key",
            "hotelId": "hotel-42",
        },
    )

    expected = base64.b64encode(b"hotel-user:hotel-password").decode()
    assert result["success"] is True
    assert captured["url"] == "https://crs.example.test/v1/hotels"
    assert captured["headers"]["Authorization"] == f"Basic {expected}"
    assert captured["params"] == {"apikey": "test-api-key", "hotelId": "hotel-42"}
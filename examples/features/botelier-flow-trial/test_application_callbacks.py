"""Actual ASGI routes -> real Twilio token/signature code -> real status service."""

import asyncio

import pytest

from callback_io import BASE_URL, CallbackHarness
from callback_store import (
    CHILD_A, CHILD_B, PARENT_A, PARENT_B, PHONE_A, TOKEN_A, TOKEN_B,
)


CALLBACKS = [
    ("/api/calls/status", {"CallSid": PARENT_A, "CallStatus": "ringing"}),
    ("/api/calls/transfer-status", {
        "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
        "CallStatus": "ringing", "To": PHONE_A,
    }),
    ("/api/calls/connect-complete", {"CallSid": PARENT_A}),
    ("/api/calls/recording-status", {
        "CallSid": PARENT_A, "RecordingStatus": "in-progress",
    }),
]


@pytest.mark.parametrize("path,fields", CALLBACKS)
def test_actual_route_accepts_its_owner_signature_and_rejects_a_forgery(path, fields):
    """Replacing real signature validation with allow-all would mutate records."""
    async def scenario():
        async with CallbackHarness() as harness:
            forged = await harness.post(path, fields, signature="not-a-valid-signature")
            assert forged.status_code == 403
            assert harness.store.commits == 0
            assert not harness.jobs
            valid = await harness.post(path, fields)
            assert valid.status_code == 200, valid.text
    asyncio.run(scenario())


def test_signed_to_number_cannot_select_another_calls_authentication_account():
    """A valid signature from account A must not authorize changes to call B."""
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(
                "/api/calls/status",
                {"CallSid": PARENT_B, "To": PHONE_A, "CallStatus": "ringing"},
                token=TOKEN_A,
            )
            assert response.status_code == 403
            assert harness.store.rows["CallLog"][1].status == "initiated"
            assert harness.store.commits == 0
    asyncio.run(scenario())


def test_known_call_owner_wins_over_a_destination_owned_by_another_account():
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(
                "/api/calls/status",
                {"CallSid": PARENT_B, "To": PHONE_A, "CallStatus": "ringing"},
                token=TOKEN_B,
            )
            assert response.status_code == 200
            assert harness.store.rows["CallLog"][1].status == "ringing"
            assert harness.store.rows["CallLog"][0].status == "initiated"
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
def test_known_child_cannot_be_rebound_to_a_different_parent(path):
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(path, {
                "CallSid": CHILD_B, "ParentCallSid": PARENT_A,
                "CallStatus": "ringing", "To": PHONE_A,
            })
            assert response.status_code == 403
            assert harness.store.rows["CallLeg"][1].status == "initiated"
            assert harness.store.commits == 0
            assert not harness.store.rows["CallEvent"]
    asyncio.run(scenario())


@pytest.mark.parametrize("path,fields", CALLBACKS)
def test_signature_covers_the_exact_public_query_string(path, fields):
    from twilio.request_validator import RequestValidator

    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(path + "?attempt=offline%2Fone", fields)
            assert response.status_code == 200, response.text
            tampered = await harness.post(
                path + "?attempt=offline%2Ftwo", fields,
                signature=RequestValidator(TOKEN_A).compute_signature(
                    BASE_URL + path + "?attempt=offline%2Fone", fields,
                ),
            )
            assert tampered.status_code == 403
    asyncio.run(scenario())


def test_new_incoming_call_can_still_resolve_its_number_before_a_call_log_exists():
    from botelier.api._twilio_auth import get_call_auth_token
    from callback_store import CallbackStore

    store = CallbackStore()
    assert get_call_auth_token(
        store, to_number=PHONE_A, call_sid="CA" + "9" * 32,
    ) == TOKEN_A


def test_unrelated_number_cannot_recover_from_an_ownership_lookup_failure():
    from callback_store import CallbackStore

    class UnavailableStore(CallbackStore):
        def query(self, *entities):
            model = getattr(entities[0], "class_", entities[0])
            if model.__name__ == "CallLog":
                raise RuntimeError("synthetic_ownership_lookup_failure")
            return super().query(*entities)

    async def scenario():
        async with CallbackHarness(
            store=UnavailableStore(), expected_rollbacks=1,
        ) as harness:
            response = await harness.post("/api/calls/status", {
                "CallSid": PARENT_B, "CallStatus": "ringing", "To": PHONE_A,
            })
            assert response.status_code == 403
            assert harness.store.commits == 0
            assert not harness.jobs
    asyncio.run(scenario())


def test_registered_connect_complete_get_validates_url_and_query_fields():
    from twilio.request_validator import RequestValidator

    async def scenario():
        async with CallbackHarness() as harness:
            path = "/api/calls/connect-complete?CallSid=" + PARENT_A
            signature = RequestValidator(TOKEN_A).compute_signature(BASE_URL + path, {})
            response = await harness.client.get(path, headers={
                "X-Twilio-Signature": signature,
            })
            assert response.status_code == 200, response.text
    asyncio.run(scenario())


def test_authentication_diagnostics_do_not_log_credentials_or_signature_prefixes():
    from loguru import logger
    from twilio.request_validator import RequestValidator

    async def scenario():
        async with CallbackHarness() as harness:
            fields = {"CallSid": PARENT_A, "CallStatus": "ringing", "To": PHONE_A}
            path = "/api/calls/status"
            signature = RequestValidator(TOKEN_A).compute_signature(BASE_URL + path, fields)
            messages = []
            sink = logger.add(lambda msg: messages.append(str(msg)), level="INFO")
            try:
                response = await harness.post(path, fields, signature=signature)
                assert response.status_code == 200
            finally:
                logger.remove(sink)
            text = "".join(messages)
            assert TOKEN_A[:8] not in text, "Authentication token prefix was logged"
            assert signature[:8] not in text, "Replayable signature prefix was logged"
    asyncio.run(scenario())


def test_rejected_signature_diagnostics_do_not_log_public_query_values():
    from loguru import logger

    async def scenario():
        async with CallbackHarness() as harness:
            messages = []
            sink = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
            try:
                response = await harness.post(
                    "/api/calls/status?opaque=TEST_QUERY_VALUE_MUST_NOT_BE_LOGGED",
                    {"CallSid": PARENT_A, "CallStatus": "ringing"},
                    signature="not-a-valid-signature",
                )
                assert response.status_code == 403
            finally:
                logger.remove(sink)
            assert "TEST_QUERY_VALUE_MUST_NOT_BE_LOGGED" not in "".join(messages)
    asyncio.run(scenario())

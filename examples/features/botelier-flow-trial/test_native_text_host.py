"""Migration fence for the retired six-node host fixture."""

import asyncio

import pytest

from application_support import API_KEYS
from native_text_io import NativeTextFixture


def test_retired_compiled_pilot_is_refused_by_the_actual_native_text_host():
    async def scenario():
        from botelier.voice.flows.native_text_host import (
            NativeTextHost,
            NativeTextHostError,
        )

        async with NativeTextFixture([], create_host=False) as fixture:
            with pytest.raises(NativeTextHostError) as error:
                NativeTextHost(
                    fixture.compiled,
                    config=fixture.config,
                    api_keys=API_KEYS,
                    session_factory=fixture.actions.session,
                )
            assert error.value.code == "invalid"
            assert fixture.providers.requests == []
            assert fixture.providers.business_requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))

#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Deepgram Flux TTS service (WebSocket transport, /v2/speak).

Re-exports :class:`DeepgramFluxTTSService` and :class:`DeepgramFluxTTSSettings`
from :mod:`tts_base` so callers can import from either location.
"""

from pipecat.services.deepgram.flux.tts_base import (
    DeepgramFluxTTSService,
    DeepgramFluxTTSSettings,
)

__all__ = [
    "DeepgramFluxTTSService",
    "DeepgramFluxTTSSettings",
]

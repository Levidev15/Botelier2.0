#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Deepgram Flux TTS base class (WebSocket transport, /v2/speak).

Flux TTS is conversation-aware: it maintains acoustic state across turns on a
single WebSocket connection, so prosody and pacing stay consistent throughout a
call without any extra context-passing by the caller.

Key protocol differences from Aura (/v1/speak):
- Endpoint       : wss://api.deepgram.com/v2/speak
- Barge-in       : {"type": "Interrupt"}  (Aura uses "Clear")
- Turn end signal: SpeechMetadata message  (Aura uses "Flushed")
- Disconnect     : close socket directly, no "Close" message
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService, WebsocketTTSService
from pipecat.utils.tracing.service_decorators import traced_tts

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error(
        "In order to use DeepgramFluxTTSService, you need to `pip install pipecat-ai[deepgram]`."
    )
    raise Exception(f"Missing module: {e}")


@dataclass
class DeepgramFluxTTSSettings(TTSSettings):
    """Settings for DeepgramFluxTTSService."""

    pass


class DeepgramFluxTTSService(WebsocketTTSService):
    """Deepgram Flux WebSocket-based text-to-speech service.

    Uses Deepgram's /v2/speak WebSocket API.  Flux keeps acoustic state across
    turns on the same connection, giving it conversation-level context that
    improves pronunciation of proper nouns (hotel names, guest names) across the
    duration of a call.

    Voice IDs follow the pattern ``flux-{name}-{lang}``
    (e.g. ``flux-heather-en``, ``flux-alexis-en``).

    Event handlers:
    - on_connected: Called when the WebSocket is established.
    - on_disconnected: Called when the WebSocket is closed.
    - on_connection_error: Called on a WebSocket error.
    """

    Settings = DeepgramFluxTTSSettings
    _settings: Settings

    # Flux only supports linear16 over the WebSocket API.
    SUPPORTED_ENCODINGS = ("linear16",)

    def __init__(
        self,
        *,
        api_key: str,
        voice: str | None = None,
        base_url: str = "wss://api.deepgram.com",
        sample_rate: int | None = None,
        encoding: str = "linear16",
        mip_opt_out: bool | None = None,
        settings: Settings | None = None,
        **kwargs,
    ):
        """Initialize the Deepgram Flux WebSocket TTS service.

        Args:
            api_key: Deepgram API key.
            voice: Flux voice model ID (e.g. ``"flux-heather-en"``). Deprecated;
                prefer ``settings=DeepgramFluxTTSService.Settings(voice=...)``.
            base_url: WebSocket base URL. Defaults to ``"wss://api.deepgram.com"``.
            sample_rate: Audio sample rate in Hz. If None, uses the pipeline default.
            encoding: Audio encoding. Must be ``"linear16"`` for Flux WebSocket.
            mip_opt_out: Opt out of the Deepgram Model Improvement Program.
            settings: Runtime-updatable settings; overrides all positional args.
            **kwargs: Passed to parent classes.
        """
        if encoding.lower() not in self.SUPPORTED_ENCODINGS:
            raise ValueError(
                f"Unsupported encoding '{encoding}'. Flux WebSocket only supports "
                f"{', '.join(self.SUPPORTED_ENCODINGS)}."
            )

        default_settings = self.Settings(
            model=None,
            voice="flux-heather-en",
            language=None,
        )

        if voice is not None:
            self._warn_init_param_moved_to_settings("voice", "voice")
            default_settings.model = voice
            default_settings.voice = voice

        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            sample_rate=sample_rate,
            pause_frame_processing=True,
            push_stop_frames=False,
            push_start_frame=True,
            append_trailing_space=True,
            settings=default_settings,
            **kwargs,
        )

        self._api_key = api_key
        self._base_url = base_url
        self._encoding = encoding
        self._mip_opt_out = mip_opt_out
        self._receive_task = None

    def can_generate_metrics(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Service lifecycle  (mirrors DeepgramTTSService pattern)
    # ------------------------------------------------------------------

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def _connect(self):
        await super()._connect()
        await self._connect_websocket()

        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        await super()._disconnect()

        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None

        await self._disconnect_websocket()

    async def _update_settings(self, delta: TTSSettings) -> dict[str, Any]:
        changed = await super()._update_settings(delta)
        if "voice" in changed:
            self._settings.model = self._settings.voice
            self._sync_model_name_to_metrics()
        if changed:
            await self._disconnect()
            await self._connect()
        return changed

    # ------------------------------------------------------------------
    # WebSocket connection
    # ------------------------------------------------------------------

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            logger.debug("Connecting to Deepgram Flux WebSocket (/v2/speak)")

            params = [
                f"model={self._settings.voice}",
                f"encoding={self._encoding}",
                f"sample_rate={self.sample_rate}",
            ]
            if self._mip_opt_out is not None:
                params.append(f"mip_opt_out={str(self._mip_opt_out).lower()}")

            # /v2/speak  — the Flux endpoint (not /v1/speak like Aura)
            url = f"{self._base_url}/v2/speak?{'&'.join(params)}"
            headers = {"Authorization": f"Token {self._api_key}"}

            websocket = await websocket_connect(url, additional_headers=headers)
            self._websocket = websocket

            response_headers = websocket.response.headers if websocket.response else {}
            dg_headers = {k: v for k, v in response_headers.items() if k.startswith("dg-")}
            logger.debug(f'{self}: Flux WebSocket connected: {{"headers": {dg_headers}}}')

            await self._call_event_handler("on_connected")
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            await self.push_error_frame(ErrorFrame(error=f"{self} error: {e}"))
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")

    async def _disconnect_websocket(self):
        """Close the WebSocket.

        Flux: do NOT send a 'Close' message — that asks the server to drain the
        active turn (generating remaining audio that we don't need on teardown).
        Just close the socket to end the session outright.
        """
        try:
            await self.stop_all_metrics()
            if self._websocket:
                logger.debug("Disconnecting from Deepgram Flux WebSocket")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            await self.push_error_frame(ErrorFrame(error=f"{self} error: {e}"))
        finally:
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Flux WebSocket not connected")

    # ------------------------------------------------------------------
    # Barge-in
    # ------------------------------------------------------------------

    async def on_audio_context_interrupted(self, context_id: str):
        """Send Interrupt to Flux when the user barges in.

        Flux 'Interrupt' ends the active turn without closing the connection, so
        the cross-turn acoustic state (the "conversation memory") survives.
        Aura uses 'Clear' — not valid for /v2/speak.
        """
        await self.stop_all_metrics()
        if self._websocket:
            try:
                await self._websocket.send(json.dumps({"type": "Interrupt"}))
            except Exception as e:
                logger.error(f"{self} error sending Interrupt message: {e}")
        await super().on_audio_context_interrupted(context_id)

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def flush_audio(self, context_id: str | None = None):
        """Signal end of text input for the current turn.

        Unlike Aura (where 'Flushed' marks turn end), Flux uses 'Flush' as a
        hint to generate remaining audio.  The actual turn end is signalled by
        the 'SpeechMetadata' message handled in _receive_messages.
        """
        if self._websocket:
            try:
                await self._websocket.send(json.dumps({"type": "Flush"}))
            except Exception as e:
                logger.error(f"{self} error sending Flush message: {e}")

    # ------------------------------------------------------------------
    # run_tts
    # ------------------------------------------------------------------

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        logger.debug(f"{self}: Generating Flux TTS [{text}]")
        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()

            await self._get_websocket().send(json.dumps({"type": "Speak", "text": text}))
            yield None
        except Exception as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")

    # ------------------------------------------------------------------
    # Receive loop  — Flux-specific message handling
    # ------------------------------------------------------------------

    async def _receive_messages(self):
        async for message in self._get_websocket():
            if isinstance(message, bytes):
                # Audio data
                ctx_id = self.get_active_audio_context_id()
                frame = TTSAudioRawFrame(message, self.sample_rate, 1, context_id=ctx_id)
                await self.append_to_audio_context(ctx_id, frame)
            elif isinstance(message, str):
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")

                    if msg_type == "Connected":
                        logger.debug(
                            f"{self}: Flux connected (request_id={msg.get('request_id')}, "
                            f"model={msg.get('model_name')})"
                        )
                    elif msg_type == "SpeechStarted":
                        logger.trace(f"Received SpeechStarted: {msg}")
                    elif msg_type == "Flushed":
                        # Flux: this is NOT end-of-turn.  It is only an
                        # acknowledgment that the server received the Flush
                        # command.  Audio may still follow.  Wait for
                        # SpeechMetadata for the real end-of-turn signal.
                        logger.trace(f"Received Flushed (ack): {msg}")
                    elif msg_type == "SpeechMetadata":
                        # Definitive end-of-turn — all audio for this turn has
                        # been sent.  This is the Flux equivalent of Aura's
                        # 'Flushed'.
                        logger.debug(
                            f"{self}: speech complete "
                            f"(speech_id={msg.get('speech_id')}, "
                            f"duration={msg.get('audio_duration_ms')}ms, "
                            f"chars={msg.get('billable_character_count')})"
                        )
                        ctx_id = self.get_active_audio_context_id()
                        await self.append_to_audio_context(
                            ctx_id, TTSStoppedFrame(context_id=ctx_id)
                        )
                        await self.remove_audio_context(ctx_id)
                    elif msg_type == "SpeechInterrupted":
                        logger.trace(
                            f"{self}: speech interrupted "
                            f"(speech_id={msg.get('speech_id')}, "
                            f"played={msg.get('audio_played_ms')}ms)"
                        )
                    elif msg_type == "SessionMetadata":
                        logger.debug(f"{self}: session totals: {msg}")
                    elif msg_type == "ConfigureSuccess":
                        logger.debug(f"{self}: Configure applied: {msg.get('applied')}")
                    elif msg_type == "ConfigureFailure":
                        logger.warning(
                            f"{self}: Configure rejected "
                            f"({msg.get('code')}, field={msg.get('field')}): "
                            f"{msg.get('description', 'Unknown failure')}"
                        )
                    elif msg_type == "Warning":
                        code = msg.get("code")
                        if code == "NO_ACTIVE_SPEECH":
                            logger.trace(f"{self}: no active turn to interrupt")
                        else:
                            logger.warning(
                                f"{self} warning {code}: "
                                f"{msg.get('description', 'Unknown warning')}"
                            )
                    elif msg_type == "Error":
                        error_msg = (
                            f"{self} Flux error {msg.get('code')}: "
                            f"{msg.get('description', 'Unknown error')}"
                        )
                        logger.error(error_msg)
                        await self.push_error_frame(ErrorFrame(error=error_msg))
                    else:
                        logger.debug(f"Received unknown Flux message type: {msg}")
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from Flux WebSocket: {message}")

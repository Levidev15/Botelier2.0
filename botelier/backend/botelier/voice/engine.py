"""
Botelier Voice Engine Implementation

This module contains the actual implementation that uses Pipecat.
This is an internal module - hotel developers don't interact with this directly.

Key Design Principle:
- Uses Pipecat's proper InputParams classes for type safety
- Maps database configuration to Pipecat's expected parameters
- Supports provider-specific features (Flux STT, prompt caching, etc.)
"""

import asyncio
import os
import time
from typing import Optional, Dict, Any, Callable
from loguru import logger

# Lazy imports for provider services to avoid startup issues with optional dependencies
# Services will be imported only when actually used
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.transcriptions.language import Language
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
)
from pipecat.processors.user_idle_processor import UserIdleProcessor
from pipecat.processors.filters.stt_mute_filter import STTMuteFilter, STTMuteConfig, STTMuteStrategy

from .agent import VoiceAgentConfig
from ..config.providers import is_flux_model


class InterruptionTracker(FrameProcessor):
    """
    Tracks TTS content being spoken and detects when it's interrupted.
    
    Placed before TTS in the pipeline to monitor text frames.
    When an InterruptionFrame is detected, calls the callback with the
    content that was interrupted.
    """
    
    def __init__(self, on_interruption: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(**kwargs)
        self._current_text = ""
        self._on_interruption = on_interruption
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Track outgoing TTS content (text frames from LLM)
        if isinstance(frame, (TextFrame, TTSSpeakFrame)):
            if hasattr(frame, 'text') and frame.text:
                self._current_text = frame.text
                logger.debug(f"🎤 Tracking TTS: {frame.text[:50]}...")
        
        # Detect interruption
        if isinstance(frame, InterruptionFrame):
            if self._current_text and self._on_interruption:
                logger.info(f"🛑 Interruption detected for: {self._current_text[:50]}...")
                self._on_interruption(self._current_text)
            self._current_text = ""  # Reset after interruption
        
        # CRITICAL: Always push frames through to next processor
        await self.push_frame(frame, direction)


class LLMResponseCapture(FrameProcessor):
    """
    Pure-observer processor that captures each complete LLM response.

    Placed immediately after the LLM in the pipeline so it sees LLM output
    frames before they reach the TTS service.  ALL frames are passed through
    unmodified — this processor never drops or delays any frame.

    When a complete response is assembled (LLMFullResponseEndFrame received),
    ``on_llm_response(text, timestamp)`` is called.  The handler stores the
    response in a per-call buffer that is consulted at transcript-save time to
    recover responses that the LLM context never committed (caller hung up
    mid-generation).

    Uses a TextFrame check (superclass of LLMTextFrame) gated by _in_response so
    it works across all LLM providers that may emit generic TextFrame tokens.
    """

    def __init__(self, on_llm_response=None, on_llm_start=None, call_start_mono: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self._buffer: str = ""
        self._in_response: bool = False
        self._on_llm_response = on_llm_response
        self._on_llm_start = on_llm_start
        self._call_start_mono = call_start_mono
        self._llm_turn_start_mono: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._in_response = True
            self._llm_turn_start_mono = time.monotonic()
            _elapsed_ms = (self._llm_turn_start_mono - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            logger.info(f"⏱️ [T+{_elapsed_ms:.0f}ms] LLM first token received")
            if self._on_llm_start:
                try:
                    self._on_llm_start()
                except Exception:
                    logger.exception("LLMResponseCapture: error in on_llm_start callback")

        elif isinstance(frame, TextFrame) and self._in_response:
            if frame.text:
                self._buffer += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._in_response = False
            text = self._buffer.strip()
            self._buffer = ""
            _now_mono = time.monotonic()
            _elapsed_ms = (_now_mono - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            _gen_ms = (_now_mono - self._llm_turn_start_mono) * 1000 if self._llm_turn_start_mono else 0.0
            logger.info(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] LLM response complete: "
                f"{len(text)} chars, generation={_gen_ms:.0f}ms"
            )
            if text and self._on_llm_response:
                try:
                    from datetime import datetime as _dt
                    self._on_llm_response(text, _dt.utcnow())
                except Exception:
                    logger.exception("LLMResponseCapture: error in on_llm_response callback")

        await self.push_frame(frame, direction)


class UserTurnCapture(FrameProcessor):
    """
    Pure-observer processor that captures each finalized user utterance with a
    wall-clock timestamp.

    Placed immediately after the STT mute filter and before the LLM context
    aggregator so it sees only the TranscriptionFrames that will be committed
    to the LLM context (i.e. post-muting).  ALL frames pass through unmodified.

    Calls ``on_user_turn(text, timestamp)`` for each non-empty transcription so
    that ``_extract_transcript`` can annotate user messages with the actual time
    they were finalized rather than the generic save-time stamp.
    """

    def __init__(self, on_user_turn=None, call_start_mono: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self._on_user_turn = on_user_turn
        self._call_start_mono = call_start_mono

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text and frame.text.strip():
            _elapsed_ms = (time.monotonic() - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            logger.info(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] STT transcript finalized: "
                f'"{frame.text.strip()[:60]}"'
            )
            if self._on_user_turn:
                try:
                    from datetime import datetime as _dt
                    self._on_user_turn(frame.text.strip(), _dt.utcnow())
                except Exception:
                    logger.exception("UserTurnCapture: error in on_user_turn callback")

        await self.push_frame(frame, direction)


class FirstUserSpeechTracker(FrameProcessor):
    """
    Detects the first non-empty transcription from the user and logs a
    user_first_speech event via the injected CallEventQueue.

    Placed between the STT service and the context_aggregator so it
    intercepts TranscriptionFrames on the way downstream.
    Only the very first non-empty transcript is reported — subsequent turns
    are intentionally ignored (per spec: no recurring speech events).
    """

    def __init__(self, event_queue=None, **kwargs):
        super().__init__(**kwargs)
        self._event_queue = event_queue
        self._logged = False

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if (
            not self._logged
            and isinstance(frame, TranscriptionFrame)
            and hasattr(frame, "text")
            and frame.text
            and frame.text.strip()
        ):
            self._logged = True
            if self._event_queue is not None:
                self._event_queue.log(
                    "user_first_speech",
                    event_source="pipecat",
                    severity="info",
                    details={"transcript": frame.text.strip()[:200]},
                )
            logger.debug(f"user_first_speech logged: {frame.text.strip()[:50]}...")

        await self.push_frame(frame, direction)


class IdleTimeoutTracker:
    """
    Thin wrapper that builds a UserIdleProcessor whose callback logs an
    idle_timeout event via an injected CallEventQueue.

    Usage::
        tracker = IdleTimeoutTracker(timeout=30.0)
        pipeline = Pipeline([..., tracker.processor, ...])
        # after pipeline creation:
        tracker.set_event_queue(event_queue)
    """

    def __init__(self, timeout: float = 30.0):
        self._event_queue = None
        self._retry_count = 0
        self.processor = UserIdleProcessor(
            callback=self._on_idle,
            timeout=timeout,
        )

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def _on_idle(self, processor: UserIdleProcessor, retry_count: int) -> bool:
        """Called each time the idle timeout fires.  Returns False to stop retrying.

        Note: there is no explicit stop-event guard here against a race with
        pipeline teardown.  That guard lives in CallEventQueue.log() itself —
        it checks _stop_event.is_set() and silently drops any event enqueued
        after flush_and_stop() is called.  This single centralised guard
        protects all callers, including this one.
        """
        if self._event_queue is not None:
            self._event_queue.log(
                "idle_timeout",
                event_source="pipecat",
                severity="warning",
                details={"retry_count": retry_count, "timeout_secs": processor._timeout},
            )
        logger.info(f"idle_timeout logged (retry #{retry_count})")
        return False  # One notification per idle period; let pipeline decide to hang up elsewhere


class GreetingCompletionTracker(FrameProcessor):
    """
    Logs a greeting_completed event when the greeting TTS finishes speaking.

    Placed immediately after the TTS service so it sees BotStoppedSpeakingFrame
    as it flows downstream.  Only the very first BotStoppedSpeakingFrame is
    reported — subsequent ones (regular turn-taking) are ignored.

    WebSocket liveness guard: if ``is_call_active`` is wired (via
    ``set_call_active``), the callback and event are suppressed when the
    WebSocket is already closed.  This prevents buffered TTS frames that drain
    after a hangup from incorrectly marking the greeting as completed — the
    caller never heard those frames.
    """

    def __init__(self, event_queue=None, is_call_active=None, **kwargs):
        super().__init__(**kwargs)
        self._event_queue = event_queue
        self._greeting_callback = None
        self._logged = False
        self._is_call_active = is_call_active  # Optional[Callable[[], bool]]

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def set_greeting_callback(self, callback) -> None:
        """Set an async callback invoked once when the greeting finishes playing."""
        self._greeting_callback = callback

    def set_call_active(self, is_call_active) -> None:
        """
        Wire a callable that returns True when the WebSocket is still connected.

        If the callable returns False when BotStoppedSpeakingFrame arrives, the
        greeting callback is suppressed — the audio drained after the caller hung
        up and was never delivered.
        """
        self._is_call_active = is_call_active

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not self._logged and isinstance(frame, BotStoppedSpeakingFrame):
            self._logged = True

            # Guard: if the WebSocket is already closed the TTS frames are
            # draining from an internal buffer after the caller hung up.
            # Do NOT mark the greeting as completed — the caller never heard it.
            if self._is_call_active is not None and not self._is_call_active():
                logger.info(
                    "GreetingCompletionTracker: WebSocket closed before "
                    "BotStoppedSpeakingFrame — caller hung up mid-greeting, "
                    "suppressing greeting_completed callback"
                )
                await self.push_frame(frame, direction)
                return

            if self._event_queue is not None:
                self._event_queue.log(
                    "greeting_completed",
                    event_source="pipecat",
                    severity="info",
                )
            if self._greeting_callback is not None:
                try:
                    await self._greeting_callback()
                except Exception as _cb_err:
                    logger.error(f"greeting_callback error: {_cb_err}")
            logger.debug("greeting_completed logged")

        await self.push_frame(frame, direction)


class TtsCompletionWatcher(FrameProcessor):
    """
    Watches for BotStoppedSpeakingFrame to signal TTS completion.

    Placed in the pipeline immediately after the TTS service so it can observe
    BotStoppedSpeakingFrame as it flows downstream toward the transport output.

    Two usage modes:

    1. Callback (preferred for transfers) — decouples the action from the
       Pipecat function-call timeout:

        watcher.reset()
        watcher.schedule_after_speech(my_async_callback)
        await llm.push_frame(TTSSpeakFrame(message))
        # return immediately — callback fires when speech ends

    2. Await (legacy, blocks the function handler — subject to Pipecat timeout):

        watcher.reset()
        await llm.push_frame(TTSSpeakFrame(message))
        await watcher.wait_until_done(timeout=15.0)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._speaking_done = asyncio.Event()
        self._speaking_done.set()  # Start in "done" state — no pending speech
        self._on_done_callback = None  # One-shot async callback

    def reset(self):
        """
        Clear the completion event.

        Call this synchronously (no await) just before pushing a TTSSpeakFrame
        so that schedule_after_speech / wait_until_done captures the correct
        BotStoppedSpeakingFrame.
        """
        self._speaking_done.clear()

    def schedule_after_speech(self, callback, timeout: float = 5.0) -> None:
        """
        Run ``callback`` as soon as the current speech is done.

        - If speech has already ended (event is set), fires callback immediately
          via asyncio.create_task so it runs outside the current stack frame.
        - If speech is still in progress, registers it as a one-shot callback
          that fires when the next BotStoppedSpeakingFrame arrives.

        A safety ``timeout`` (default 5 s) guarantees the callback fires even
        when BotStoppedSpeakingFrame never arrives — for example when Pipecat's
        FunctionCallInProgressFrame wipes the TTS context before Deepgram audio
        returns, leaving the pipeline silent and the event permanently unset.

        This is the preferred method for transfer handlers: call reset() first,
        then schedule_after_speech(), then push the TTSSpeakFrame, then return
        immediately to Pipecat. The callback executes after speech completes
        regardless of how long TTS takes — entirely outside Pipecat's function-
        call timeout window.

        For flow transfers where speech was initiated upstream (no reset()),
        call schedule_after_speech() without reset(). If speech is already
        done the callback fires immediately; otherwise it waits.

        Args:
            callback: Async callable (no arguments) to invoke after speech ends.
            timeout:  Seconds to wait for BotStoppedSpeakingFrame before firing
                      the callback unconditionally.  Default 5 s.
        """
        if self._speaking_done.is_set():
            asyncio.create_task(callback())
        else:
            if self._on_done_callback is not None:
                logger.warning("TtsCompletionWatcher: overwriting existing on-done callback")
            self._on_done_callback = callback

            async def _timeout_guard():
                try:
                    await asyncio.wait_for(self._speaking_done.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    # BotStoppedSpeakingFrame never arrived within the window.
                    # Fire the callback now so the transfer is never permanently lost.
                    # Check atomically: process_frame may have already fired it.
                    cb = self._on_done_callback
                    self._on_done_callback = None
                    if cb is not None:
                        logger.warning(
                            f"TtsCompletionWatcher: BotStoppedSpeakingFrame did not arrive "
                            f"within {timeout}s — firing transfer callback via timeout"
                        )
                        try:
                            await cb()
                        except Exception:
                            logger.exception(
                                "TtsCompletionWatcher: unhandled exception in timeout callback"
                            )

            asyncio.create_task(_timeout_guard())

    def clear_callback(self) -> None:
        """
        Remove any pending one-shot callback.

        Call this on pipeline shutdown or call hang-up to avoid firing a
        stale transfer after the call has already ended.
        """
        self._on_done_callback = None

    async def wait_until_done(self, timeout: float = 15.0) -> bool:
        """
        Wait until BotStoppedSpeakingFrame is observed or the timeout expires.

        Returns:
            True  — speech completed within the timeout.
            False — timed out; caller should proceed with the transfer anyway.
        """
        try:
            await asyncio.wait_for(self._speaking_done.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"TtsCompletionWatcher: timed out after {timeout}s waiting for BotStoppedSpeakingFrame")
            return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStoppedSpeakingFrame):
            logger.debug("TtsCompletionWatcher: BotStoppedSpeakingFrame received — signalling done")
            self._speaking_done.set()
            # Fire and clear the one-shot callback if one is registered.
            # Use create_task so the callback runs outside this frame-processing
            # stack, avoiding any re-entrant pipeline issues.
            cb = self._on_done_callback
            self._on_done_callback = None
            if cb is not None:
                async def _guarded_cb(callback=cb):
                    try:
                        await callback()
                    except Exception:
                        logger.exception("TtsCompletionWatcher: unhandled exception in post-speech callback")
                asyncio.create_task(_guarded_cb())
        # Always pass frames through unchanged
        await self.push_frame(frame, direction)


class VoiceEngineFactory:
    """
    Factory for creating voice AI pipelines
    
    This encapsulates all Pipecat-specific code.
    Hotels never see this - they only interact with VoiceAgent.
    """
    
    @staticmethod
    def create_stt_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create STT service using Pipecat's proper configuration classes"""
        provider = config.stt_provider.lower()
        model = config.stt_model or "nova-3-general"
        
        if provider == "deepgram":
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
            
            # Check if using Flux model (advanced turn detection)
            if is_flux_model(model):
                return DeepgramFluxSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    settings=DeepgramFluxSTTService.Settings(
                        model=model,
                        eager_eot_threshold=config.stt_config.get("eager_eot_threshold"),
                        eot_threshold=config.stt_config.get("eot_threshold", 0.7),
                        eot_timeout_ms=config.stt_config.get("eot_timeout_ms", 5000),
                        keyterm=config.stt_config.get("keyterm", []),
                    ),
                )
            else:
                # Standard Deepgram using the Settings API (pipecat 0.0.105+)
                return DeepgramSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    settings=DeepgramSTTService.Settings(
                        model=model,
                        language=config.stt_language,
                        punctuate=config.stt_config.get("punctuate", True),
                        smart_format=config.stt_config.get("smart_format", True),
                        profanity_filter=config.stt_config.get("profanity_filter", True),
                        interim_results=True,
                        endpointing=config.stt_config.get("endpointing", 500),
                    ),
                )
        elif provider == "openai_whisper":
            from pipecat.services.openai.stt import OpenAISTTService
            return OpenAISTTService(
                api_key=api_keys.get("openai_api_key"),
                model=model or "whisper-1",
                language=config.stt_language,
            )
        elif provider == "assemblyai":
            from pipecat.services.assemblyai import AssemblyAISTTService
            return AssemblyAISTTService(
                api_key=api_keys.get("assemblyai_api_key"),
            )
        else:
            raise ValueError(f"Unsupported STT provider: {provider}")
    
    @staticmethod
    def create_llm_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create LLM service using Pipecat's proper InputParams classes"""
        provider = config.llm_provider.lower()
        
        if provider == "openai":
            from pipecat.services.openai.llm import OpenAILLMService
            from pipecat.services.openai.base_llm import BaseOpenAILLMService
            if hasattr(OpenAILLMService, "Settings"):
                return OpenAILLMService(
                    api_key=api_keys.get("openai_api_key"),
                    settings=OpenAILLMService.Settings(
                        model=config.llm_model,
                        temperature=config.llm_temperature,
                        max_completion_tokens=config.llm_max_tokens,
                        frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                        presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                        top_p=config.llm_config.get("top_p", 1.0),
                    ),
                )
            # Fallback for older Pipecat versions without Settings API
            params = BaseOpenAILLMService.InputParams(
                temperature=config.llm_temperature,
                max_completion_tokens=config.llm_max_tokens,
                frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                top_p=config.llm_config.get("top_p", 1.0),
            )
            return OpenAILLMService(
                api_key=api_keys.get("openai_api_key"),
                model=config.llm_model,
                params=params,
            )
        elif provider == "anthropic":
            # TODO: Anthropic support temporarily disabled due to SDK installation issues
            # Will be re-enabled once anthropic package is properly installed in Replit environment
            raise ValueError(
                "Anthropic LLM provider is temporarily unavailable. "
                "Please use OpenAI or Google Gemini instead."
            )
        elif provider == "google_gemini":
            from pipecat.services.google.llm import GoogleLLMService
            return GoogleLLMService(
                api_key=api_keys.get("google_api_key"),
                model=config.llm_model,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def create_tts_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create TTS service using Pipecat's configuration"""
        provider = config.tts_provider.lower()
        
        if provider == "deepgram":
            from pipecat.services.deepgram.tts import DeepgramTTSService
            voice = config.tts_voice_id or "aura-2-helena-en"
            # Twilio Media Streams require 8 kHz audio; tell Deepgram to encode at
            # 8000 Hz so no downstream resampling is needed before the Twilio
            # serialiser μ-law-encodes it for transmission.
            sample_rate = config.tts_config.get("sample_rate", 8000)
            encoding = config.tts_config.get("encoding", "linear16")
            if hasattr(DeepgramTTSService, "Settings"):
                return DeepgramTTSService(
                    api_key=api_keys.get("deepgram_api_key"),
                    sample_rate=sample_rate,
                    encoding=encoding,
                    settings=DeepgramTTSService.Settings(
                        voice=voice,
                    ),
                )
            return DeepgramTTSService(
                api_key=api_keys.get("deepgram_api_key"),
                voice=voice,
                sample_rate=sample_rate,
                encoding=encoding,
            )
        elif provider == "cartesia":
            from pipecat.services.cartesia.tts import CartesiaTTSService
            return CartesiaTTSService(
                api_key=api_keys.get("cartesia_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "elevenlabs":
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
            return ElevenLabsTTSService(
                api_key=api_keys.get("elevenlabs_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "openai":
            from pipecat.services.openai.tts import OpenAITTSService
            return OpenAITTSService(
                api_key=api_keys.get("openai_api_key"),
                voice=config.tts_voice_id or "alloy",
            )
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
    
    @staticmethod
    def create_pipeline(
        config: VoiceAgentConfig,
        api_keys: Dict[str, str],
        transport,
        function_schemas: Optional[list] = None,
        function_handlers: Optional[Dict[str, Any]] = None,
        on_interruption: Optional[Callable[[str], None]] = None,
        on_llm_response: Optional[Callable] = None,
        on_user_turn: Optional[Callable] = None,
        call_start_mono: float = 0.0,
        on_llm_start: Optional[Callable] = None,
    ) -> tuple:
        """
        Create complete voice pipeline from agent configuration.

        This is where Pipecat is actually used, but it's completely hidden
        from the hotel-facing API.

        Args:
            config: Voice agent configuration
            api_keys: API keys for external services
            transport: WebSocket transport
            function_schemas: Optional list of FunctionSchema objects for function calling
            function_handlers: Optional dict mapping function names to async handlers
            on_interruption: Optional callback called when user interrupts (receives interrupted text)
            on_llm_response: Optional callback(text, timestamp) called when each complete LLM
                response is assembled.  Used to recover responses from calls that drop mid-
                generation before the LLM context commits them.
            on_user_turn: Optional callback(text, timestamp) called for each finalized user
                utterance.  Used to record per-turn timestamps for the call transcript.

        Returns:
            9-tuple: (pipeline, task, llm, context_aggregator, context,
                      tts_completion_watcher, first_speech_tracker,
                      greeting_completion_tracker, idle_timeout_tracker).
            - context is returned separately for transcript extraction.
            - tts_completion_watcher can be linked to FunctionMapper.set_tts_completion_watcher()
              so transfer handlers can await TTS completion without time-based sleeps.
            - first_speech_tracker / greeting_completion_tracker / idle_timeout_tracker
              need event_queue injected via set_event_queue() after pipeline creation.
        """
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        stt = VoiceEngineFactory.create_stt_service(config, api_keys)
        llm = VoiceEngineFactory.create_llm_service(config, api_keys)
        tts = VoiceEngineFactory.create_tts_service(config, api_keys)

        # Capture each complete LLM response for transcript recovery.
        # Pure observer — passes all frames through unchanged.
        # call_start_mono threads wall-clock timing into the processor so it can
        # emit per-stage latency logs (LLM first-token, LLM complete).
        llm_response_capture = LLMResponseCapture(
            on_llm_response=on_llm_response,
            on_llm_start=on_llm_start,
            call_start_mono=call_start_mono,
        )

        # Capture finalized user utterances for per-turn timestamp recording.
        # Placed after the STT mute filter so only post-muting transcriptions
        # (i.e. those that reach the LLM) are captured.  Pure observer.
        # call_start_mono enables per-turn STT latency logging.
        user_turn_capture = UserTurnCapture(
            on_user_turn=on_user_turn,
            call_start_mono=call_start_mono,
        )

        # Track text frames/interruptions before TTS
        interruption_tracker = InterruptionTracker(on_interruption=on_interruption)

        # Observe BotStoppedSpeakingFrame after TTS so transfer handlers can
        # await actual TTS completion rather than using fixed-duration sleeps.
        tts_completion_watcher = TtsCompletionWatcher()

        # Detect the caller's first speech utterance for event logging.
        # Placed between STT and context_aggregator so it intercepts
        # TranscriptionFrames before they enter the LLM pipeline.
        first_speech_tracker = FirstUserSpeechTracker()

        # Log greeting_completed on the first BotStoppedSpeakingFrame (greeting TTS done).
        # Placed between TTS and tts_completion_watcher; both see the same frame.
        greeting_completion_tracker = GreetingCompletionTracker()

        # Log idle_timeout when the caller goes silent for too long.
        # UserIdleProcessor fires a callback after `timeout` seconds of silence.
        idle_timeout_tracker = IdleTimeoutTracker(timeout=30.0)

        # Pipecat-native STT mute gate.
        # MUTE_UNTIL_FIRST_BOT_COMPLETE — suppresses all VAD/transcription frames until
        # Ava finishes her opening greeting, preventing speaker bleed-through from
        # reaching Deepgram during the greeting.
        # FUNCTION_CALL — re-mutes during active tool/function calls (e.g. transfers)
        # so the caller cannot interrupt mid-transfer.
        stt_mute_filter = STTMuteFilter(
            config=STTMuteConfig(
                strategies={
                    STTMuteStrategy.MUTE_UNTIL_FIRST_BOT_COMPLETE,
                    STTMuteStrategy.FUNCTION_CALL,
                }
            )
        )

        messages = [
            {
                "role": "system",
                "content": config.system_prompt,
            },
        ]

        # Create context with tools if schemas provided
        if function_schemas:
            tools = ToolsSchema(standard_tools=function_schemas)
            context = LLMContext(messages, tools=tools)
        else:
            context = LLMContext(messages)

        context_aggregator = LLMContextAggregatorPair(context)

        # Register function handlers with LLM
        if function_handlers:
            for function_name, handler in function_handlers.items():
                llm.register_function(function_name, handler)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                stt_mute_filter,               # Mutes STT during greeting + function calls (Pipecat native)
                user_turn_capture,             # Records per-turn user timestamps for transcript (pure observer)
                first_speech_tracker,          # Detects caller's first utterance (non-blocking event log)
                idle_timeout_tracker.processor, # Logs idle_timeout when caller goes silent too long
                context_aggregator.user(),
                llm,
                llm_response_capture,          # Captures complete LLM responses for transcript recovery
                interruption_tracker,          # Observes text frames + InterruptionFrame before TTS
                tts,
                greeting_completion_tracker,   # Logs greeting_completed on first BotStoppedSpeakingFrame
                tts_completion_watcher,        # Observes BotStoppedSpeakingFrame after TTS
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )

        return pipeline, task, llm, context_aggregator, context, tts_completion_watcher, first_speech_tracker, greeting_completion_tracker, idle_timeout_tracker
    
    @staticmethod
    def create_transport_params(config: VoiceAgentConfig):
        """Create transport parameters based on agent config"""
        from pipecat.transports.base_transport import TransportParams
        from pipecat.audio.vad.vad_analyzer import VADParams
        
        params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
        
        if config.enable_vad and config.vad_provider:
            vad_config = config.vad_config or {}
            
            try:
                if config.vad_provider == "silero":
                    from pipecat.audio.vad.silero import SileroVADAnalyzer
                    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
                    
                    vad_params = VADParams(
                        confidence=vad_config.get("confidence", 0.5),
                        start_secs=vad_config.get("start_secs", 0.0),
                        stop_secs=vad_config.get("stop_secs", 0.4),
                        min_volume=vad_config.get("min_volume", 0.0)
                    )
                    params.vad_analyzer = SileroVADAnalyzer(params=vad_params)
                    params.turn_analyzer = LocalSmartTurnAnalyzerV3()
                    logger.info(f"Silero VAD enabled with params: {vad_params}")
                    
                elif config.vad_provider == "webrtc":
                    from pipecat.transports.daily.transport import WebRTCVADAnalyzer
                    
                    vad_params = VADParams(
                        confidence=vad_config.get("confidence", 0.5),
                        start_secs=vad_config.get("start_secs", 0.0),
                        stop_secs=vad_config.get("stop_secs", 0.2),
                        min_volume=vad_config.get("min_volume", 0.0)
                    )
                    params.vad_analyzer = WebRTCVADAnalyzer(params=vad_params)
                    logger.info(f"WebRTC VAD enabled with params: {vad_params}")
                    
                elif config.vad_provider == "aic":
                    from pipecat.audio.vad.aic_vad import AICVADAnalyzer
                    
                    lookback_buffer_size = vad_config.get("lookback_buffer_size")
                    sensitivity = vad_config.get("sensitivity")
                    params.vad_analyzer = AICVADAnalyzer(
                        lookback_buffer_size=lookback_buffer_size,
                        sensitivity=sensitivity
                    )
                    logger.info(f"AIC VAD enabled with lookback={lookback_buffer_size}, sensitivity={sensitivity}")
                    
                else:
                    logger.warning(f"Unknown VAD provider '{config.vad_provider}', VAD disabled")
                    
            except ImportError as e:
                logger.warning(f"VAD provider '{config.vad_provider}' not available (missing dependencies): {e}")
                logger.info("Continuing without VAD. Install dependencies or disable VAD in assistant settings.")
        
        return params

"""Botelier Voice Engine Implementation

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
from collections.abc import Callable
from typing import Any, Dict, Optional

from loguru import logger
from pipecat.processors.idle_frame_processor import IdleFrameProcessor

from pipecat.frames.frames import (
    AudioRawFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputTransportMessageFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputTransportMessageFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData
from botelier.voice.usage_observer import UsageObserver

# Lazy imports for provider services to avoid startup issues with optional dependencies
# Services will be imported only when actually used
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transcriptions.language import Language
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_mute.function_call_user_mute_strategy import FunctionCallUserMuteStrategy
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
    MuteUntilFirstBotCompleteUserMuteStrategy,
)
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_stop import (
    ExternalUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import (
    ExternalUserTurnStrategies,
    UserTurnStrategies,
)

from ..config.providers import is_flux_model
from .agent import VoiceAgentConfig


def is_external_vad_effectively_enabled(config: VoiceAgentConfig) -> bool:
    """Return whether Botelier should attach external VAD for this call.

    Deepgram Flux owns turn detection. A stale DB row may still have
    vad_enabled=true, but external Silero VAD must remain off for Flux models.
    """
    return bool(
        config.enable_vad
        and config.vad_provider == "silero"
        and not is_flux_model(config.stt_model or "")
    )


class InterruptionTracker(FrameProcessor):
    """Tracks the full response being spoken and detects when it's interrupted.

    Placed before TTS in the pipeline to monitor text frames.  Accumulates the
    ENTIRE current response (all token/sentence chunks between
    LLMFullResponseStartFrame and the next response start) rather than only the
    last chunk — the interruption callback receives the full generated text so
    transcript extraction can match it against the committed (possibly
    partially-spoken) context message by prefix.  The buffer is intentionally
    NOT cleared on LLMFullResponseEndFrame: an interruption can arrive while
    TTS is still speaking a fully-generated response.

    When an InterruptionFrame is detected, calls the callback with the
    accumulated content that was interrupted.
    """

    def __init__(self, on_interruption: Callable[[str], None] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._buffer = ""
        self._bot_speaking = False
        self._on_interruption = on_interruption

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            # New response starting — previous response finished uninterrupted.
            self._buffer = ""

        elif isinstance(frame, TTSSpeakFrame):
            # Standalone utterance (e.g. greeting) — replaces the buffer.
            if frame.text:
                self._buffer = frame.text
                logger.debug(f"🎤 Tracking TTS (speak): {frame.text[:50]}...")

        elif isinstance(frame, TextFrame):
            # LLM token/sentence chunks — accumulate the full response.
            if frame.text:
                self._buffer += frame.text

        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True

        elif isinstance(frame, BotStoppedSpeakingFrame):
            # Bot finished speaking normally (or an interruption was already
            # handled) — the buffered response was fully delivered, so it can
            # never be "interrupted" after this point.
            self._bot_speaking = False
            self._buffer = ""

        # Detect interruption.  CRITICAL: Pipecat broadcasts InterruptionFrame
        # on EVERY user turn start (not only during bot speech), so a normal
        # caller reply after a fully-spoken response also delivers one here.
        # Only an interruption that arrives WHILE the bot is speaking actually
        # cut a response short — gate on bot-speaking state or we would mark
        # every completed response as interrupted.
        if isinstance(frame, InterruptionFrame):
            if self._bot_speaking and self._buffer.strip() and self._on_interruption:
                logger.info(f"🛑 Interruption detected for: {self._buffer[:50]}...")
                self._on_interruption(self._buffer)
            self._buffer = ""  # Reset after interruption

        # CRITICAL: Always push frames through to next processor
        await self.push_frame(frame, direction)


class LLMResponseCapture(FrameProcessor):
    """Pure-observer processor that captures each complete LLM response.

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

    def __init__(
        self,
        on_llm_response=None,
        on_llm_start=None,
        call_start_mono: float = 0.0,
        timing_state: dict = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._buffer: str = ""
        self._in_response: bool = False
        self._on_llm_response = on_llm_response
        self._on_llm_start = on_llm_start
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._llm_turn_start_mono: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._in_response = True
            self._llm_turn_start_mono = time.monotonic()
            self._timing_state["t_llm_start"] = self._llm_turn_start_mono
            _elapsed_ms = (
                (self._llm_turn_start_mono - self._call_start_mono) * 1000
                if self._call_start_mono
                else 0.0
            )
            _t_stt = self._timing_state.get("t_stt", 0.0)
            _stt_to_llm_ms = (self._llm_turn_start_mono - _t_stt) * 1000 if _t_stt else 0.0
            # Per-turn latency observability (Task #95). INFO-level so it
            # survives LOG_LEVEL=INFO in production — this is the data we use
            # to diagnose the LLM TTFB and tool-call delays (Task #106).
            logger.info(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] LLM first token received | "
                f"STT→LLM: {_stt_to_llm_ms:.0f}ms"
            )
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
            self._timing_state["t_llm_end"] = _now_mono
            _elapsed_ms = (
                (_now_mono - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            )
            _gen_ms = (
                (_now_mono - self._llm_turn_start_mono) * 1000 if self._llm_turn_start_mono else 0.0
            )
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
    """Pure-observer processor that captures each finalized user utterance with a
    wall-clock timestamp.

    Placed immediately after the STT mute filter and before the LLM context
    aggregator so it sees only the TranscriptionFrames that will be committed
    to the LLM context (i.e. post-muting).  ALL frames pass through unmodified.

    Calls ``on_user_turn(text, timestamp)`` for each non-empty transcription so
    that ``_extract_transcript`` can annotate user messages with the actual time
    they were finalized rather than the generic save-time stamp.

    Also emits a ``turn_finalized`` CallEvent per finalized transcription when
    an ``event_queue`` is wired (via ``set_event_queue``).  This is the true
    per-turn denominator — fires whether or not the pipeline then successfully
    responds.  Maintains a monotonic 1-based ``turn_index`` that is also written
    into ``timing_state["turn_index"]`` so the matching ``turn_latency`` event
    (emitted downstream by ``TtsPipelineLatencyTracker``) can reference it.
    """

    def __init__(
        self,
        on_user_turn=None,
        call_start_mono: float = 0.0,
        timing_state: dict = None,
        event_queue=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._on_user_turn = on_user_turn
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._event_queue = event_queue
        self._turn_index = 0

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text and frame.text.strip():
            _t_stt = time.monotonic()
            self._timing_state["t_stt"] = _t_stt
            self._turn_index += 1
            self._timing_state["turn_index"] = self._turn_index
            _elapsed_ms = (_t_stt - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            _t_last_inbound = self._timing_state.get("t_last_inbound", 0.0)
            _inbound_to_stt_ms = (_t_stt - _t_last_inbound) * 1000 if _t_last_inbound else 0.0
            _transcript = frame.text.strip()
            logger.info(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] STT transcript finalized: "
                f'"{_transcript[:60]}" | '
                f"inbound→STT: {_inbound_to_stt_ms:.0f}ms"
            )
            if self._event_queue is not None:
                self._event_queue.log(
                    "turn_finalized",
                    event_source="pipecat",
                    severity="info",
                    details={
                        "turn_index": self._turn_index,
                        "inbound_to_stt_ms": int(_inbound_to_stt_ms),
                        "transcript_chars": len(_transcript),
                    },
                )
            if self._on_user_turn:
                try:
                    from datetime import datetime as _dt

                    self._on_user_turn(_transcript, _dt.utcnow())
                except Exception:
                    logger.exception("UserTurnCapture: error in on_user_turn callback")

        await self.push_frame(frame, direction)


class GreetingAudioInjector(FrameProcessor):
    """Pushes pre-rendered greeting PCM audio downstream as a TTSStartedFrame +
    TTSAudioRawFrame chunks + TTSStoppedFrame sequence — but does so from a
    point in the pipeline that is downstream of STT, so the cached audio is
    never transcribed by the STT service.

    Why this exists
    ---------------
    Previously the cached greeting was queued via ``PipelineTask.queue_frames``
    which inserts at the *source* of the pipeline. The frames then flowed
    through ``stt`` (which calls ``isinstance(frame, AudioRawFrame)`` and
    forwards the bytes to Deepgram — confirmed against
    pipecat 0.0.108 ``stt_service.py`` line 380, where ``TTSAudioRawFrame``
    matches because it inherits from ``AudioRawFrame`` via
    ``OutputAudioRawFrame``). Deepgram then transcribed the bot's own
    greeting and emitted a ``TranscriptionFrame``, which our
    ``FirstUserSpeechTracker`` recorded as ``user_first_speech``.

    Wired into the pipeline between ``interruption_tracker`` and ``tts`` so
    that ``tts`` still sees the frames as a pass-through (preserving the
    ``_tts_audio_received`` bookkeeping that ``greeting_completion_tracker``
    relies on) while every processor upstream of ``tts`` (including ``stt``)
    is bypassed.

    Lifecycle
    ---------
    ``set_pending_greeting(audio_bytes)`` is called BEFORE the pipeline runs.
    The bytes are stashed. When the injector receives ``StartFrame`` (which
    propagates first, before any other frame), it forwards StartFrame
    downstream and then schedules a one-shot async task to push the cached
    greeting frames downstream. Pushing inside ``process_frame`` cannot occur
    before ``StartFrame`` because ``FrameProcessor._check_started`` would log
    an error otherwise.
    """

    _CHUNK_SIZE = 320  # 20 ms @ 8 kHz linear16 PCM (8000 * 2 bytes/sample * 0.020 s)

    def __init__(self, inject_yield_every_chunks: int | None = 8, **kwargs):
        super().__init__(**kwargs)
        self._pending_audio: bytes | None = None
        self._injected = False
        self._start_received = False
        self._inject_yield_every_chunks = inject_yield_every_chunks

    def set_pending_greeting(self, audio_bytes: bytes) -> None:
        """Stash cached greeting bytes to be injected once the pipeline starts.

        Safe to call before ``runner.run(task)``. If called more than once
        before injection, only the most recent buffer is used. After the
        one-shot injection has fired, further calls are ignored to prevent
        re-greeting on long-lived pipelines.
        """
        if self._injected:
            logger.debug("GreetingAudioInjector: ignoring pending audio — already injected")
            return
        self._pending_audio = audio_bytes

    async def inject(self, audio_bytes: bytes) -> None:
        """Public API: inject cached greeting audio downstream.

        If the pipeline hasn't yet emitted ``StartFrame`` through this
        processor, the bytes are stashed and injected on StartFrame receipt
        (matching ``set_pending_greeting`` semantics). If the processor has
        already started, frames are pushed immediately. Either way, the
        injection is one-shot — subsequent calls after the first injection
        fires are ignored.
        """
        if self._injected:
            logger.debug("GreetingAudioInjector.inject: already injected, ignoring")
            return
        if not self._start_received:
            self._pending_audio = audio_bytes
            return
        self._injected = True
        self._pending_audio = None
        await self._inject(audio_bytes)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        # Forward every frame unchanged — the injector is a pure observer
        # for everything except its one-shot greeting injection.
        await self.push_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._start_received = True
            if not self._injected and self._pending_audio:
                self._injected = True
                audio = self._pending_audio
                self._pending_audio = None
                # Fire-and-forget: chunked push runs concurrently with the
                # rest of pipeline startup. push_frame calls are cheap (queue
                # inserts) so this completes in milliseconds even for long
                # greetings, but we don't want to block the StartFrame
                # propagation through this processor.
                # Task #116 — attach exception logger so any failure raised
                # outside _inject's internal try/except (e.g. scheduler
                # error during reload) surfaces in the logs instead of
                # being swallowed by garbage collection of the task object.
                from ..utils import log_task_exception as _log_task_exception

                _inject_task = asyncio.create_task(self._inject(audio))
                _inject_task.add_done_callback(_log_task_exception)

    async def _inject(self, audio: bytes) -> None:
        """Push the cached greeting downstream as TTS lifecycle frames.

        Mirrors the chunking and frame sequence the previous
        ``task.queue_frames`` path used, so caller-side audio is byte-for-byte
        identical and downstream lifecycle observers
        (``greeting_completion_tracker``, ``tts_completion_watcher``,
        ``MuteUntilFirstBotComplete``) behave exactly as before.
        """
        try:
            await self.push_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
            chunk_idx = 0
            for i in range(0, len(audio), self._CHUNK_SIZE):
                await self.push_frame(
                    TTSAudioRawFrame(
                        audio=audio[i : i + self._CHUNK_SIZE],
                        sample_rate=8000,
                        num_channels=1,
                    ),
                    FrameDirection.DOWNSTREAM,
                )
                chunk_idx += 1
                if (
                    self._inject_yield_every_chunks is not None
                    and self._inject_yield_every_chunks > 0
                    and chunk_idx % self._inject_yield_every_chunks == 0
                ):
                    await asyncio.sleep(0)
            await self.push_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
            chunk_count = -(-len(audio) // self._CHUNK_SIZE)  # ceil division
            logger.info(
                f"🎙️ Greeting injected downstream of STT ({len(audio)} bytes, {chunk_count} chunks)"
            )
        except Exception as e:
            logger.error(f"GreetingAudioInjector._inject failed: {e}")


class FirstUserSpeechTracker(FrameProcessor):
    """Detects the first non-empty transcription from the user and logs a
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
        self._first_speech_callback = None  # Task #98 — async () -> None

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def set_first_speech_callback(self, callback) -> None:
        """Task #98 — wire an async callback fired exactly once on the first
        non-empty caller transcription. Used by call_handler.py to flip
        ``call_logs.caller_spoke = TRUE`` so analytics can distinguish
        silent calls from real conversations.
        """
        self._first_speech_callback = callback

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
            if self._first_speech_callback is not None:
                from ..utils import log_task_exception as _log_task_exception

                _cb_task = asyncio.create_task(self._first_speech_callback())
                _cb_task.add_done_callback(_log_task_exception)
            logger.debug(f"user_first_speech logged: {frame.text.strip()[:50]}...")

        await self.push_frame(frame, direction)


class IdleTimeoutTracker:
    """Thin wrapper that builds an IdleFrameProcessor whose callback logs an
    idle_timeout event via an injected CallEventQueue.

    Usage::
        tracker = IdleTimeoutTracker(timeout=30.0)
        pipeline = Pipeline([..., tracker.processor, ...])
        # after pipeline creation:
        tracker.set_event_queue(event_queue)
        # at call end or transfer initiation:
        tracker.stop()
    """

    def __init__(self, timeout: float = 30.0):
        self._event_queue = None
        self._timeout = timeout
        self._cancelled = asyncio.Event()
        self.processor = IdleFrameProcessor(
            callback=self._on_idle,
            timeout=timeout,
        )

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def stop(self) -> None:
        """Cancel the idle timer — prevents _on_idle from emitting any further events.

        This is the primary guard against ghost idle_timeout events after a call ends
        or a transfer fires.  IdleFrameProcessor (Pipecat) owns an internal asyncio
        Task that is NOT cancelled when PipelineTask.cancel() pushes a CancelFrame
        through the frame chain — it keeps rearming itself every ``timeout`` seconds
        for the lifetime of the event loop.  Calling stop() here gates the callback
        before it can write to the event queue, regardless of asyncio scheduling order.

        Safe to call multiple times — asyncio.Event.set() is idempotent.
        """
        self._cancelled.set()
        logger.debug("IdleTimeoutTracker: stopped — no further idle events will be emitted")

    async def _on_idle(self, processor: IdleFrameProcessor) -> None:
        """Called each time the idle timeout fires.

        Primary guard: _cancelled.is_set() is checked first.  stop() sets this
        flag synchronously in the call finally block (before flush_and_stop()) and
        at transfer initiation — both of which happen before or concurrent with the
        asyncio scheduling of this callback.  This closes the race window that the
        CallEventQueue._stop_event guard alone cannot cover (the guard only fires
        after flush_and_stop() is awaited, but this callback can be scheduled by
        asyncio between runner.run(task) returning and flush_and_stop() being called).
        """
        if self._cancelled.is_set():
            return
        if self._event_queue is not None:
            self._event_queue.log(
                "idle_timeout",
                event_source="pipecat",
                severity="warning",
                details={"timeout_secs": self._timeout},
            )
            # Boundary event: makes "the caller went silent" explicitly visible
            # in the dashboard timeline alongside the existing idle_timeout
            # observability event (Task #94).
            self._event_queue.log(
                "caller_silence_detected",
                event_source="pipecat",
                severity="info",
                details={"timeout_secs": self._timeout},
            )
        logger.info("idle_timeout / caller_silence_detected logged")


class GreetingCompletionTracker(FrameProcessor):
    """Logs a greeting_completed event when the greeting TTS finishes speaking.

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
        """Wire a callable that returns True when the WebSocket is still connected.

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
                from ..utils import log_task_exception as _log_task_exception

                _cb_task = asyncio.create_task(self._greeting_callback())
                _cb_task.add_done_callback(_log_task_exception)
            logger.debug("greeting_completed logged")

        await self.push_frame(frame, direction)


class TtsCompletionWatcher(FrameProcessor):
    """Watches for BotStoppedSpeakingFrame to signal TTS completion.

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
        self._bot_speaking = False  # True between BotStarted/BotStoppedSpeakingFrame
        self._guard_task = None  # Active timeout-guard task (cancelled on teardown)

    def reset(self):
        """Clear the completion event.

        Call this synchronously (no await) just before pushing a TTSSpeakFrame
        so that schedule_after_speech / wait_until_done captures the correct
        BotStoppedSpeakingFrame.
        """
        self._speaking_done.clear()

    def schedule_after_speech(
        self, callback, timeout: float = 5.0, max_wait: float = 60.0
    ) -> None:
        """Run ``callback`` as soon as the current speech is done.

        - If speech has already ended (event is set), fires callback immediately
          via asyncio.create_task so it runs outside the current stack frame.
        - If speech is still in progress, registers it as a one-shot callback
          that fires when the next BotStoppedSpeakingFrame arrives.

        The safety timeout is SPEECH-AWARE: ``timeout`` (default 5 s) only
        applies while the bot is NOT audibly speaking — it covers the failure
        case where speech never starts (e.g. Pipecat's FunctionCallInProgressFrame
        wipes the TTS context before Deepgram audio returns, leaving the pipeline
        silent and the event permanently unset).  Once BotStartedSpeakingFrame is
        observed, the guard waits for the speech to finish naturally instead of
        firing mid-sentence — a configured message longer than ``timeout`` seconds
        of audio is no longer clipped.  ``max_wait`` (default 60 s) is the hard
        upper bound so a stuck pipeline (BotStoppedSpeakingFrame lost while the
        speaking flag stays set) can never strand a caller indefinitely.

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
            timeout:  Seconds to wait for BotStoppedSpeakingFrame while the bot
                      is not speaking, before firing the callback unconditionally.
                      Default 5 s.
            max_wait: Absolute ceiling in seconds regardless of speaking state.
                      Default 60 s.
        """
        if self._speaking_done.is_set():
            asyncio.create_task(callback())
        else:
            if self._on_done_callback is not None:
                logger.warning("TtsCompletionWatcher: overwriting existing on-done callback")
            self._on_done_callback = callback

            async def _timeout_guard():
                loop = asyncio.get_event_loop()
                start = loop.time()
                hard_deadline = start + max_wait
                # Deadline while the bot is silent.  Re-armed each time we
                # observe the bot actively speaking, so silence AFTER speech
                # (e.g. a lost BotStoppedSpeakingFrame) still has a bounded wait.
                silent_deadline = start + timeout
                timed_out = False
                while True:
                    now = loop.time()
                    if now >= hard_deadline:
                        timed_out = True
                        break
                    if self._bot_speaking:
                        # Bot is audibly speaking — do NOT fire mid-sentence.
                        # Push the silence deadline forward so the post-speech
                        # grace period restarts when speech ends.
                        silent_deadline = now + timeout
                    elif now >= silent_deadline:
                        timed_out = True
                        break
                    try:
                        await asyncio.wait_for(
                            self._speaking_done.wait(), timeout=0.25
                        )
                        # Event set — process_frame fires the callback.
                        return
                    except TimeoutError:
                        continue
                if timed_out:
                    # Fire the callback now so the action is never permanently lost.
                    # Check atomically: process_frame may have already fired it.
                    cb = self._on_done_callback
                    self._on_done_callback = None
                    # Detach ourselves BEFORE awaiting the callback so a
                    # concurrent clear_callback() (call teardown) can never
                    # cancel an in-flight transfer/hangup mid-execution.
                    self._guard_task = None
                    if cb is not None:
                        logger.warning(
                            f"TtsCompletionWatcher: BotStoppedSpeakingFrame did not arrive "
                            f"(waited {loop.time() - start:.1f}s, bot_speaking={self._bot_speaking}) "
                            f"— firing post-speech callback via timeout"
                        )
                        try:
                            await cb()
                        except Exception:
                            logger.exception(
                                "TtsCompletionWatcher: unhandled exception in timeout callback"
                            )

            self._guard_task = asyncio.create_task(_timeout_guard())

    def clear_callback(self) -> None:
        """Remove any pending one-shot callback.

        Call this on pipeline shutdown or call hang-up to avoid firing a
        stale transfer after the call has already ended.  Also cancels the
        timeout-guard task so it doesn't linger (up to max_wait) polling for
        a callback that no longer exists.  A guard that has already popped
        its callback detaches itself first, so an in-flight action is never
        cancelled mid-execution.
        """
        self._on_done_callback = None
        if self._guard_task is not None and not self._guard_task.done():
            self._guard_task.cancel()
        self._guard_task = None

    async def wait_until_done(self, timeout: float = 15.0) -> bool:
        """Wait until BotStoppedSpeakingFrame is observed or the timeout expires.

        Returns:
            True  — speech completed within the timeout.
            False — timed out; caller should proceed with the transfer anyway.
        """
        try:
            await asyncio.wait_for(self._speaking_done.wait(), timeout=timeout)
            return True
        except TimeoutError:
            logger.warning(
                f"TtsCompletionWatcher: timed out after {timeout}s waiting for BotStoppedSpeakingFrame"
            )
            return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            # Track audible speech so the schedule_after_speech timeout guard
            # never fires mid-sentence (see _timeout_guard).
            self._bot_speaking = True
        if isinstance(frame, BotStoppedSpeakingFrame):
            logger.debug("TtsCompletionWatcher: BotStoppedSpeakingFrame received — signalling done")
            self._bot_speaking = False
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
                        logger.exception(
                            "TtsCompletionWatcher: unhandled exception in post-speech callback"
                        )

                asyncio.create_task(_guarded_cb())
        # Always pass frames through unchanged
        await self.push_frame(frame, direction)




class TwilioMarkWatcher(FrameProcessor):
    """Send Twilio marks and wait for matching playback acknowledgements.

    Twilio sends a mark event back only after all buffered outbound media before
    that mark has completed playback. Transfers use this as the caller-heard
    boundary before replacing the live call with Dial/Refer TwiML.
    """

    def __init__(self, stream_sid: str = "", **kwargs):
        super().__init__(**kwargs)
        self._stream_sid = stream_sid
        self._pending: dict[str, asyncio.Event] = {}

    async def send_mark_and_wait(self, name: str, timeout: float = 2.0) -> bool:
        if not self._stream_sid:
            logger.warning("TwilioMarkWatcher: no stream SID; skipping playback mark")
            return False

        event = asyncio.Event()
        self._pending[name] = event
        message = {
            "event": "mark",
            "streamSid": self._stream_sid,
            "mark": {"name": name},
        }

        logger.info(f"Sending Twilio playback mark {name}")
        await self.push_frame(OutputTransportMessageFrame(message=message), FrameDirection.DOWNSTREAM)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.info(f"Twilio playback mark acknowledged: {name}")
            return True
        except TimeoutError:
            logger.warning(
                f"Timed out after {timeout}s waiting for Twilio playback mark {name}; proceeding"
            )
            return False
        finally:
            self._pending.pop(name, None)

    def clear_pending(self) -> None:
        for event in self._pending.values():
            event.set()
        self._pending.clear()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputTransportMessageFrame):
            message = frame.message or {}
            if message.get("event") == "mark":
                name = (message.get("mark") or {}).get("name")
                event = self._pending.get(name)
                if event is not None:
                    event.set()

        if isinstance(frame, (EndFrame, CancelFrame)):
            self.clear_pending()

        await self.push_frame(frame, direction)


class VadSuspicionTracker(FrameProcessor):
    """Emit explicit VAD suspicion events for cohort analytics.

    Heuristics are deterministic and only use existing pipeline timing context:

    * vad_false_start_suspected: InterruptionFrame occurs but no finalized user
      turn lands shortly after, suggesting VAD triggered on non-speech/noise.
    * vad_missed_speech_suspected: inbound audio continues but no timely
      turn_finalized event appears, suggesting potential missed speech.
    """

    def __init__(
        self,
        call_start_mono: float = 0.0,
        timing_state: dict = None,
        event_queue=None,
        metadata: dict | None = None,
        enabled: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._event_queue = event_queue
        self._metadata = metadata or {}
        self._enabled = enabled
        self._pending_interruption_mono: float = 0.0
        self._last_turn_finalized_mono: float = 0.0
        self._last_missed_emit_mono: float = 0.0

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def clear_stt_mute(self) -> None:
        """Clear the STT-muted flag and reset the turn clock.

        Called when the greeting window ends (GreetingCompletionTracker fires)
        so the missed-speech heuristic starts from a clean baseline.

        Without the turn-clock reset, _last_turn_finalized_mono = 0.0 would
        immediately satisfy _last_turn_finalized_mono < _t_last_inbound and
        fire a spurious vad_missed_speech_suspected on the very first
        post-greeting audio frame — defeating the purpose of the guard.
        """
        self._timing_state["stt_muted"] = False
        self._last_turn_finalized_mono = time.monotonic()
        if self._enabled:
            logger.debug("VadSuspicionTracker: STT mute cleared — missed-speech heuristic now active")

    def _base_details(self) -> dict:
        return {
            "assistant_id": self._metadata.get("assistant_id"),
            "vad_enabled": self._metadata.get("vad_enabled"),
            "effective_vad_enabled": self._metadata.get("effective_vad_enabled"),
            "vad_provider": self._metadata.get("vad_provider"),
            "stt_model": self._metadata.get("stt_model"),
            "min_volume": self._metadata.get("min_volume"),
        }

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        _now = time.monotonic()

        if not self._enabled:
            await self.push_frame(frame, direction)
            return

        _false_start_window_s = float(self._timing_state.get("vad_false_start_window_s", 1.5))
        _missed_speech_window_s = float(self._timing_state.get("vad_missed_speech_window_s", 2.5))

        if isinstance(frame, InterruptionFrame):
            self._pending_interruption_mono = _now

        if isinstance(frame, TranscriptionFrame) and frame.text and frame.text.strip():
            self._last_turn_finalized_mono = _now
            self._pending_interruption_mono = 0.0

        if self._pending_interruption_mono and (_now - self._pending_interruption_mono) >= _false_start_window_s:
            if self._last_turn_finalized_mono < self._pending_interruption_mono and self._event_queue is not None:
                details = self._base_details()
                details.update({
                    "turn_index": int(self._timing_state.get("turn_index", 0)),
                    "interruption_to_now_ms": int((_now - self._pending_interruption_mono) * 1000),
                    "false_start_window_ms": int(_false_start_window_s * 1000),
                    "confidence_inputs": {"interruption_seen": True, "finalized_turn_seen_in_window": False},
                })
                self._event_queue.log("vad_false_start_suspected", event_source="pipecat", severity="warning", details=details)
            self._pending_interruption_mono = 0.0

        # Only run the missed-speech heuristic when STT is active. During the
        # muted greeting window, Twilio keeps streaming audio continuously but
        # MuteUntilFirstBotCompleteUserMuteStrategy prevents any
        # TranscriptionFrame from arriving — the absence of transcripts is
        # intentional, not anomalous. clear_stt_mute() re-enables this check
        # the moment the greeting finishes and STT begins accepting audio.
        if not self._timing_state.get("stt_muted", False):
            _t_last_inbound = self._timing_state.get("t_last_inbound", 0.0)
            if _t_last_inbound and (_now - _t_last_inbound) <= _missed_speech_window_s:
                _since_last_turn = (_now - self._last_turn_finalized_mono) if self._last_turn_finalized_mono else 999999
                _last_turn_before_inbound = self._last_turn_finalized_mono < _t_last_inbound
                _cooldown_ok = (_now - self._last_missed_emit_mono) >= _missed_speech_window_s
                if _last_turn_before_inbound and _since_last_turn >= _missed_speech_window_s and _cooldown_ok and self._event_queue is not None:
                    details = self._base_details()
                    details.update({
                        "turn_index": int(self._timing_state.get("turn_index", 0)),
                        "inbound_to_now_ms": int((_now - _t_last_inbound) * 1000),
                        "since_last_turn_finalized_ms": int(_since_last_turn * 1000) if self._last_turn_finalized_mono else None,
                        "missed_speech_window_ms": int(_missed_speech_window_s * 1000),
                        "confidence_inputs": {"recent_inbound_audio_seen": True, "timely_turn_finalized_seen": False},
                    })
                    self._event_queue.log("vad_missed_speech_suspected", event_source="pipecat", severity="warning", details=details)
                    self._last_missed_emit_mono = _now

        await self.push_frame(frame, direction)


class TtsAudioGapTracker(FrameProcessor):
    """Pure-observer placed immediately after the TTS service in the pipeline.

    Measures the wall-clock gap between consecutive ``TTSAudioRawFrame`` events.
    When the gap exceeds 30 ms, a DEBUG-level warning is emitted so engineers can
    detect Deepgram sentence-boundary drain without any production overhead.

    Cross-turn leakage is prevented by resetting ``_last_audio_t`` on every
    ``LLMFullResponseStartFrame`` — gaps between separate AI turns are never
    reported as intra-turn audio gaps.

    This processor is completely transparent: every frame is passed through
    unchanged with no blocking awaits on the hot path.
    """

    _GAP_THRESHOLD_S: float = 0.030  # 30 ms

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_audio_t: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            # Reset between turns so inter-turn silence is never flagged.
            self._last_audio_t = 0.0

        elif isinstance(frame, TTSAudioRawFrame):
            now = time.monotonic()
            if self._last_audio_t > 0.0:
                gap_s = now - self._last_audio_t
                if gap_s > self._GAP_THRESHOLD_S:
                    logger.debug(
                        f"TTS audio gap {gap_s * 1000:.1f}ms detected between consecutive "
                        f"TTSAudioRawFrames — consider switching text_aggregation_mode to 'token'"
                    )
            self._last_audio_t = now

        await self.push_frame(frame, direction)


class InboundAudioTracker(FrameProcessor):
    """Pure-observer placed immediately after ``transport.input()`` in the pipeline.

    Stamps ``timing_state["t_last_inbound"]`` with a monotonic clock on every
    inbound AudioRawFrame.  UserTurnCapture reads this to compute:

        Twilio inbound audio → STT transcript finalized  (inbound→STT delta)

    The delta captures total STT processing latency: the time from when the last
    audio chunk was delivered to the pipeline until Deepgram returned the final
    transcript.  Typical range for short utterances: 100–600 ms.
    """

    def __init__(self, timing_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self._timing_state = timing_state if timing_state is not None else {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame):
            self._timing_state["t_last_inbound"] = time.monotonic()
        await self.push_frame(frame, direction)


class TtsPipelineLatencyTracker(FrameProcessor):
    """Measures two pipeline-stage handoffs:

      3. LLM last token → TTS first audio chunk
         Streaming TTS often starts before LLM finishes; the delta may be
         negative (audio leading LLM end) — that is expected and informative.
         Logged when LLMFullResponseEndFrame arrives if first audio is already seen,
         or when first audio arrives if LLM already ended.

      4. TTS first audio chunk dispatched to transport
         Logged as a call-relative timestamp (T+Xms) on the first AudioRawFrame
         after an LLM response starts, capturing the moment audio hits transport.output().

    Place this processor immediately before ``transport.output()`` so it sees
    both the control frames from the LLM and the AudioRawFrames from TTS.

    The shared ``timing_state`` dict (passed by reference) is the only coupling
    between this processor and LLMResponseCapture / UserTurnCapture.
    """

    def __init__(
        self, call_start_mono: float = 0.0, timing_state: dict = None, event_queue=None, **kwargs
    ):
        super().__init__(**kwargs)
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._event_queue = event_queue
        self._expecting_audio: bool = False
        self._t_first_audio: float = 0.0
        self._turn_emitted: bool = False  # Guards against double-emission per turn

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def _emit_turn_latency(self, t_llm_end: float) -> None:
        """Log LLM→TTS delta and emit the ``turn_latency`` CallEvent.

        Called exactly once per responded turn: whichever of LLMFullResponseEndFrame
        / first AudioRawFrame arrives second triggers this (both timestamps are
        required to compute the delta).  The ``_turn_emitted`` flag prevents a
        second emission if both branches end up calling this within the same turn.
        """
        if self._turn_emitted:
            return
        self._turn_emitted = True
        _t_first_audio_local = self._t_first_audio
        # Immediately clear per-turn state after capturing locally, so any stray
        # frames arriving before the next LLMFullResponseStartFrame cannot
        # re-trigger emission paths using stale values.
        self._t_first_audio = 0.0
        self._expecting_audio = False

        _delta_ms = (_t_first_audio_local - t_llm_end) * 1000
        _sign = "" if _delta_ms >= 0 else ""
        logger.info(
            f"⏱️ LLM last token → TTS first audio: {_sign}{_delta_ms:.0f}ms "
            f"({'TTS led LLM end — streaming' if _delta_ms < 0 else 'TTS trailed LLM end'})"
        )

        if self._event_queue is None:
            return

        _t_stt = self._timing_state.get("t_stt", 0.0)
        _t_llm_start = self._timing_state.get("t_llm_start", 0.0)
        _t_last_inbound = self._timing_state.get("t_last_inbound", 0.0)
        _turn_index = self._timing_state.get("turn_index", 0)

        _inbound_to_stt_ms = (
            int((_t_stt - _t_last_inbound) * 1000) if (_t_stt and _t_last_inbound) else 0
        )
        _stt_to_llm_start_ms = (
            int((_t_llm_start - _t_stt) * 1000) if (_t_llm_start and _t_stt) else 0
        )
        _llm_generation_ms = int((t_llm_end - _t_llm_start) * 1000) if _t_llm_start else 0
        _llm_to_tts_first_audio_ms = int(_delta_ms)
        _turn_started_ms = (
            int((_t_last_inbound - self._call_start_mono) * 1000)
            if (_t_last_inbound and self._call_start_mono)
            else 0
        )
        _turn_responded_ms = (
            int((_t_first_audio_local - self._call_start_mono) * 1000)
            if self._call_start_mono
            else 0
        )

        # Task #106 — prompt-cache observability.
        # OpenAI's prompt cache is automatic (>=1024-token prefix), but a stable
        # cached prefix is the only way TTFB on tool-call turns drops below ~1 s
        # when the system prompt is large (~5 k tokens incl. KB injection).
        # Pipecat's BaseOpenAILLMService surfaces these counts via a MetricsFrame
        # carrying LLMUsageMetricsData; we capture them on the same turn (see
        # process_frame below) and stamp them onto turn_latency so an ops query
        # can compute cache_hit_ratio = cached_tokens / prompt_tokens per turn.
        # Pop after read so a later turn that fails to emit usage shows nulls
        # rather than silently inheriting the previous turn's counters.
        _prompt_tokens = self._timing_state.pop("prompt_tokens", None)
        _cached_tokens = self._timing_state.pop("cached_tokens", None)
        _completion_tokens = self._timing_state.pop("completion_tokens", None)

        details = {
            "turn_index": _turn_index,
            "inbound_to_stt_ms": _inbound_to_stt_ms,
            "stt_to_llm_start_ms": _stt_to_llm_start_ms,
            "llm_generation_ms": _llm_generation_ms,
            "llm_to_tts_first_audio_ms": _llm_to_tts_first_audio_ms,
            "turn_started_ms": _turn_started_ms,
            "turn_responded_ms": _turn_responded_ms,
        }
        if _prompt_tokens is not None:
            details["prompt_tokens"] = int(_prompt_tokens)
        if _cached_tokens is not None:
            details["cached_tokens"] = int(_cached_tokens)
        if _completion_tokens is not None:
            details["completion_tokens"] = int(_completion_tokens)

        # Single-line cache verdict at INFO so it shows in prod logs without a
        # DB round-trip — the fastest way to confirm/reject the prompt-cache
        # hypothesis on the next live call.
        if _prompt_tokens:
            _cache_pct = (int(_cached_tokens or 0) * 100) // int(_prompt_tokens)
            logger.info(
                f"⏱️ turn#{_turn_index} prompt={_prompt_tokens} cached={_cached_tokens or 0} "
                f"({_cache_pct}%) completion={_completion_tokens or 0} "
                f"llm_gen={_llm_generation_ms}ms"
            )

        self._event_queue.log(
            "turn_latency",
            event_source="pipecat",
            severity="info",
            details=details,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._expecting_audio = True
            self._t_first_audio = 0.0
            self._turn_emitted = False  # Reset per-turn emission guard
            # Per-turn isolation: clear the previous turn's LLM-end timestamp so
            # the first-audio branch below cannot read a stale value if this
            # turn's TTS audio begins before LLMFullResponseEndFrame arrives
            # (common in streaming TTS).  LLMResponseCapture will refresh this
            # key when it sees this turn's LLMFullResponseEndFrame.
            self._timing_state.pop("t_llm_end", None)
            # Task #106 — also clear cached usage counters at turn start.
            # _emit_turn_latency pops them on a normal responded turn, but a
            # silent turn (LLM produced usage yet pipeline never reached the
            # audio branch) would otherwise leak last turn's counters into
            # the next emitted turn_latency event. Clearing here guarantees
            # per-turn isolation of prompt_tokens / cached_tokens.
            self._timing_state.pop("prompt_tokens", None)
            self._timing_state.pop("cached_tokens", None)
            self._timing_state.pop("completion_tokens", None)

        elif self._expecting_audio and isinstance(frame, AudioRawFrame):
            self._expecting_audio = False
            self._t_first_audio = time.monotonic()
            _elapsed_ms = (
                (self._t_first_audio - self._call_start_mono) * 1000
                if self._call_start_mono
                else 0.0
            )
            logger.info(f"⏱️ [T+{_elapsed_ms:.0f}ms] TTS first audio chunk dispatched to transport")
            # If LLM already ended (t_llm_end set), emit immediately.
            # Otherwise emission fires when LLMFullResponseEndFrame arrives below.
            _t_llm_end = self._timing_state.get("t_llm_end", 0.0)
            if _t_llm_end:
                self._emit_turn_latency(_t_llm_end)

        elif isinstance(frame, LLMFullResponseEndFrame) and self._t_first_audio:
            # LLM just finished; first audio already arrived (streaming overlap).
            _t_llm_end = self._timing_state.get("t_llm_end", 0.0)
            if _t_llm_end:
                self._emit_turn_latency(_t_llm_end)

        elif isinstance(frame, MetricsFrame):
            # Task #106 — capture per-turn LLM token usage so the next call to
            # _emit_turn_latency can stamp prompt_tokens / cached_tokens /
            # completion_tokens onto the turn_latency event. Pipecat's
            # BaseOpenAILLMService pushes this MetricsFrame from the same
            # streaming loop that emits LLM text, so it arrives before
            # LLMFullResponseEndFrame in the pipeline order — meaning the
            # values are present in _timing_state by the time emission fires
            # via either branch above. Multiple MetricsData entries may be
            # bundled (TTFB, processing, usage) — only LLMUsageMetricsData is
            # relevant here.
            for _data in frame.data or []:
                if isinstance(_data, LLMUsageMetricsData):
                    _usage = _data.value
                    self._timing_state["prompt_tokens"] = _usage.prompt_tokens
                    self._timing_state["completion_tokens"] = _usage.completion_tokens
                    # cache_read_input_tokens is None when the response did
                    # not include prompt_tokens_details (e.g. very small
                    # prompts under the 1024-token cache threshold). Coerce
                    # to 0 so dashboards can treat absence as "no cache hit".
                    self._timing_state["cached_tokens"] = _usage.cache_read_input_tokens or 0

        await self.push_frame(frame, direction)


# Fallback allowlist used only if providers.py cannot be imported at runtime.
# Keep in sync with STT_PROVIDERS[STTProvider.DEEPGRAM].available_models.
_DEEPGRAM_VALID_MODELS_FALLBACK: frozenset = frozenset(
    [
        "nova-3-general",
        "nova-3-meeting",
        "nova-3-voicemail",
        "nova-3-finance",
        "nova-3-medical",
        "nova-2-general",
        "nova-2-meeting",
        "nova-2-phonecall",
        "nova-2-voicemail",
        "flux-general-en",
        "flux-general-multi",
    ]
)


def _get_deepgram_valid_models() -> frozenset:
    """Return the canonical Deepgram model allowlist from providers.py.

    Reads the live ``available_models`` list so changes to providers.py are
    reflected without modifying engine.py.  Falls back to the static list
    above only if the import fails, which should never happen in production.
    """
    from ..config.providers import STT_PROVIDERS, STTProvider

    cfg = STT_PROVIDERS.get(STTProvider.DEEPGRAM)
    if cfg and cfg.available_models:
        return frozenset(cfg.available_models)
    return _DEEPGRAM_VALID_MODELS_FALLBACK


class BotelierDeepgramSTTService:
    """Mixin for DeepgramSTTService that aborts the retry loop on permanent
    HTTP errors (400, 401, 403) instead of retrying forever.

    Pipecat's ``_connection_handler`` catches every non-CancelledError
    exception and loops unconditionally.  When Deepgram rejects a model
    name with HTTP 400, this creates an infinite zombie loop that only a
    server restart can clear.  This mixin overrides ``_connection_handler``
    to detect 4xx status codes in the exception message and break the loop,
    logging an actionable ERROR instead.

    Use via multiple inheritance so MRO resolves this override first:
        class _Impl(BotelierDeepgramSTTService, DeepgramSTTService): pass
    """

    async def _connection_handler(self):
        from deepgram.core.events import EventType

        while True:
            connect_kwargs = self._build_connect_kwargs()
            try:
                async with self._client.listen.v1.connect(**connect_kwargs) as connection:
                    self._connection = connection
                    connection.on(EventType.MESSAGE, self._on_message)
                    connection.on(EventType.ERROR, self._on_error)
                    logger.debug(f"{self}: Websocket connection initialized")
                    keepalive_task = self.create_task(
                        self._keepalive_handler(), f"{self}::keepalive"
                    )
                    try:
                        await connection.start_listening()
                    finally:
                        await self.cancel_task(keepalive_task)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_str = str(e)
                # Detect permanent HTTP errors — abort rather than retrying
                # forever, which would create an infinite zombie loop that
                # only a server restart can clear.
                if any(code in err_str for code in ("400", "401", "403")):
                    settings = getattr(self, "_settings", None)
                    model_name = getattr(settings, "model", "unknown") if settings else "unknown"
                    logger.error(
                        f"{self}: Deepgram rejected connection with a permanent HTTP error "
                        f"for model '{model_name}': {err_str}. "
                        f"Retry loop stopped. Update the assistant stt_model to a valid value "
                        f"(e.g. 'nova-3-general') and restart the call."
                    )
                    break
                # Transient error — wait before retrying to avoid a tight
                # loop when the connection fails too quickly to impose its
                # own natural backoff (e.g. DNS error, refused).
                logger.warning(f"{self}: Connection lost, will retry: {e}")
                await asyncio.sleep(0.5)
            finally:
                self._connection = None


class VoiceEngineFactory:
    """Factory for creating voice AI pipelines

    This encapsulates all Pipecat-specific code.
    Hotels never see this - they only interact with VoiceAgent.
    """

    @staticmethod
    def create_stt_service(config: VoiceAgentConfig, api_keys: dict[str, str]):
        """Create STT service using Pipecat's proper configuration classes"""
        provider = config.stt_provider.lower()
        model = config.stt_model

        if provider == "deepgram":
            model = model or "nova-3-general"
            from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.stt_latency import DEEPGRAM_TTFS_P99

            # Validate the model against the canonical allowlist before
            # opening any Deepgram WebSocket.  This runs for ALL Deepgram
            # models — both standard and Flux — so an invalid model name
            # always fails immediately with a clear error rather than creating
            # an infinite retry loop (HTTP 400 → reconnect every ~250 ms).
            valid_models = _get_deepgram_valid_models()
            if model not in valid_models:
                raise ValueError(
                    f"Invalid Deepgram STT model '{model}'. "
                    f"Valid models: {sorted(valid_models)}. "
                    f"Update the assistant's stt_model field to a supported value."
                )

            # Check if using Flux model (advanced turn detection)
            if is_flux_model(model):
                # ttfs_p99_latency:
                #   Pipecat's TurnAnalyzerUserTurnStopStrategy sizes the STT
                #   wait window as max(0, ttfs_p99 - vad.stop_secs).  Without
                #   an explicit value Pipecat falls back to DEFAULT_TTFS_P99=1.0 s
                #   → the window is ~650 ms too wide, adding ~650 ms of dead
                #   silence per turn.  Deepgram Flux benchmarks at ~0.35 s
                #   (DEEPGRAM_TTFS_P99), same as standard Deepgram.  Per-
                #   assistant operators can override via stt_config.ttfs_p99_latency.
                flux_ttfs = float(
                    config.stt_config.get("ttfs_p99_latency", DEEPGRAM_TTFS_P99)
                )
                return DeepgramFluxSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    ttfs_p99_latency=flux_ttfs,
                    # Gate broadcast_interruption() in _handle_start_of_turn.
                    # When the assistant's interruptions toggle is OFF we set this
                    # False so that background noise / breaths during the inter-segment
                    # mute gap cannot trigger a Twilio `clear` that wipes buffered audio
                    # and cuts the bot's voice mid-sentence.  UserStartedSpeaking,
                    # EndOfTurn transcriptions, and metrics still fire normally so
                    # normal turn-taking is completely unaffected.
                    should_interrupt=config.enable_interruptions,
                    settings=DeepgramFluxSTTService.Settings(
                        model=model,
                        eager_eot_threshold=config.stt_config.get("eager_eot_threshold"),
                        eot_threshold=config.stt_config.get("eot_threshold", 0.7),
                        eot_timeout_ms=config.stt_config.get("eot_timeout_ms", 5000),
                        keyterm=config.stt_config.get("keyterm", []),
                    ),
                )
            else:
                # Build a subclass that inherits BotelierDeepgramSTTService's
                # 4xx-abort logic as a defence-in-depth fallback.  Done inline
                # so DeepgramSTTService can be imported lazily.
                class _BotelierDeepgramSTTService(BotelierDeepgramSTTService, DeepgramSTTService):
                    pass

                # Standard Deepgram using the Settings API (pipecat 0.0.105+).
                #
                # ttfs_p99_latency:
                #   Pipecat's TurnAnalyzerUserTurnStopStrategy uses this value
                #   to size the STT wait window after VAD declares end-of-turn
                #   (`max(0, ttfs_p99 - vad.stop_secs)`).  Pipecat's bundled
                #   DEEPGRAM_TTFS_P99 (~0.35 s) is measured against
                #   `stop_secs=0.2` and assumes a clean network path; on
                #   telephony + endpointing=500 ms it is too tight and the
                #   timeout collapses to 0 s.  Per-assistant operators can
                #   override via stt_config.ttfs_p99_latency.
                deepgram_kwargs = dict(
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
                ttfs_override = config.stt_config.get("ttfs_p99_latency")
                if ttfs_override is not None:
                    deepgram_kwargs["ttfs_p99_latency"] = float(ttfs_override)
                return _BotelierDeepgramSTTService(**deepgram_kwargs)
        elif provider == "openai_whisper":
            from pipecat.services.openai.stt import OpenAISTTService

            return OpenAISTTService(
                api_key=api_keys.get("openai_api_key"),
                model=model or "whisper-1",  # noqa: RUF100 — model is None here when stt_model unset
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
    def create_llm_service(config: VoiceAgentConfig, api_keys: dict[str, str]):
        """Create LLM service using Pipecat's proper InputParams classes"""
        provider = config.llm_provider.lower()

        if provider == "openai":
            from pipecat.services.openai.base_llm import BaseOpenAILLMService
            from pipecat.services.openai.llm import OpenAILLMService

            # Task #106 — explicit cache routing.
            #
            # OpenAI's prompt cache is automatic for prompts ≥1024 tokens, but
            # the cache is sharded per OpenAI worker. Without a stable
            # `prompt_cache_key`, requests for the same assistant can land on
            # different shards (especially across our own backend processes
            # behind the load balancer), causing cache misses on the second
            # turn of a call and on the first turn of every new call to the
            # same hotel — exactly the pattern observed in the prod sample
            # (text turn ~0.5 s, tool turn ~2.0 s).
            #
            # Pinning prompt_cache_key to the assistant ID keeps every call
            # for one hotel on the same shard, so the large persona+guidelines
            # prefix (now placed first by call_handler._create_agent_config)
            # has the best possible chance of staying warm. The new
            # turn_latency.cached_tokens telemetry will quantify the win.
            #
            # `extra` is merged into the chat.completions.create() kwargs by
            # BaseOpenAILLMService.build_chat_completion_params (line 337) so
            # this is the supported plumbing for non-default request fields.
            extra: dict[str, Any] = {}
            if config.agent_id:
                extra["prompt_cache_key"] = f"botelier-assistant-{config.agent_id}"
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
                        extra=extra,
                    ),
                )
            # Fallback for older Pipecat versions without Settings API
            params = BaseOpenAILLMService.InputParams(
                temperature=config.llm_temperature,
                max_completion_tokens=config.llm_max_tokens,
                frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                top_p=config.llm_config.get("top_p", 1.0),
                extra=extra,
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
    def create_tts_service(config: VoiceAgentConfig, api_keys: dict[str, str]):
        """Create TTS service using Pipecat's configuration"""
        provider = config.tts_provider.lower()

        if provider == "deepgram":
            from pipecat.services.deepgram.tts import DeepgramTTSService

            # Subclass that emits TTSUsageMetricsData so UsageObserver can
            # capture TTS character counts for Deepgram Aura.  Pipecat's
            # DeepgramTTSService.run_tts() does not call
            # start_tts_usage_metrics(), unlike Cartesia.  We call it before
            # delegating so the MetricsFrame is pushed once per synthesis
            # request — the same call path Cartesia uses internally.
            #
            # Word substitutions: Deepgram Aura-2 mispronounces certain words
            # regardless of context (e.g. "washcloths" → "washcloth-es",
            # "spelled" → "es-pelled").  A substitution pass runs on every
            # text chunk before it reaches the Deepgram API.  Built-in defaults
            # cover known Aura-2 bugs; operators can extend or override via
            # tts_config["word_substitutions"] on the assistant (word → replacement,
            # case-insensitive whole-word match, preserves original casing of
            # the replacement string as written).
            import re as _re
            import json as _json

            _default_substitutions: dict[str, str] = {
                "washcloths": "wash cloths",
                "washcloth": "wash cloth",
                "spelled": "spelt",
                "spells": "spells",
            }
            _word_substitutions: dict[str, str] = {
                **_default_substitutions,
                **config.tts_config.get("word_substitutions", {}),
            }
            # Pre-compile patterns once at call-setup time (not per utterance).
            _sub_patterns: list[tuple[_re.Pattern, str]] = [
                (_re.compile(r"\b" + _re.escape(word) + r"\b", _re.IGNORECASE), replacement)
                for word, replacement in _word_substitutions.items()
            ]

            class _BotelierDeepgramTTSService(DeepgramTTSService):
                """Deepgram TTS with Botelier-specific enhancements.

                1. TTSUsageMetrics: pipecat's DeepgramTTSService.run_tts() does not
                   call start_tts_usage_metrics(); we call it so UsageObserver can
                   capture TTS character counts.  Called once per run_tts invocation,
                   on the original text before substitution.

                2. Word-boundary substitution in TOKEN mode: pipecat's SimpleText
                   Aggregator yields each raw LLM token immediately (e.g. "wash" /
                   "cloth" / "s"), so the whole-word regex \\bwashcloths\\b never
                   sees the complete word.  We buffer sub-word fragments until the
                   last whitespace boundary and carry the trailing partial word into
                   the next call.  flush_audio() sends the remaining partial as a
                   Speak message before the Flush command so the trailing word of
                   every utterance is always synthesised.

                   In SENTENCE mode the complete sentence arrives in one call, so
                   buffering is bypassed entirely to avoid cross-sentence artefacts.

                   On interruption the buffer is cleared so stale partial words
                   never leak into the next LLM response.
                """

                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    # Partial-word accumulator keyed by context_id.
                    # Populated in run_tts (TOKEN mode), drained in flush_audio,
                    # and cleared wholesale on interruption.
                    self._word_buffer: dict[str, str] = {}
                    # One-shot callbacks keyed by context_id.
                    # Registered by terminal handlers (transfer, end-call) so they
                    # fire on the EXACT utterance's audio completion rather than on
                    # the next BotStoppedSpeakingFrame (which Deepgram emits spuriously
                    # between sentences, causing pre-fire clipping bugs).
                    self._context_done_callbacks: dict[str, Callable] = {}

                @staticmethod
                def _apply_substitutions(text: str) -> str:
                    for pattern, replacement in _sub_patterns:
                        text = pattern.sub(replacement, text)
                    return text

                async def run_tts(self, text: str, context_id: str):
                    await self.start_tts_usage_metrics(text)

                    from pipecat.services.tts_service import TextAggregationMode

                    if self._text_aggregation_mode != TextAggregationMode.TOKEN:
                        # SENTENCE mode: the full sentence arrives at once;
                        # whole-word regexes match correctly without buffering.
                        async for frame in super().run_tts(
                            self._apply_substitutions(text), context_id
                        ):
                            yield frame
                        return

                    # TOKEN mode: buffer sub-word fragments and only pass complete
                    # words (everything up to the last whitespace) through substitution.
                    # The trailing partial word is carried in _word_buffer until the
                    # next token arrives or flush_audio() is called.
                    pending = self._word_buffer.pop(context_id, "") + text
                    ws_pos = max(pending.rfind(" "), pending.rfind("\n"), pending.rfind("\t"))
                    if ws_pos >= 0:
                        complete = pending[: ws_pos + 1]          # includes trailing ws
                        self._word_buffer[context_id] = pending[ws_pos + 1 :]
                    else:
                        complete = ""
                        self._word_buffer[context_id] = pending   # whole thing is partial

                    if complete:
                        async for frame in super().run_tts(
                            self._apply_substitutions(complete), context_id
                        ):
                            yield frame

                async def flush_audio(self, context_id: str | None = None):
                    # Drain any buffered partial word BEFORE sending the Flush command.
                    # Metrics for this text were already recorded in the run_tts call
                    # that received it — do NOT call start_tts_usage_metrics here.
                    ctx = context_id if context_id is not None else self._turn_context_id
                    partial = self._word_buffer.pop(ctx, "") if ctx is not None else ""
                    if partial and self._websocket:
                        try:
                            await self._websocket.send(
                                _json.dumps(
                                    {"type": "Speak", "text": self._apply_substitutions(partial)}
                                )
                            )
                        except Exception as e:
                            logger.error(f"{self} error flushing buffered word in TTS: {e}")
                    await super().flush_audio(context_id)

                async def on_audio_context_interrupted(self, context_id: str):
                    # Clear all buffered partial words on interruption so nothing
                    # leaks into the next LLM response.
                    self._word_buffer.clear()
                    # Discard any pending callback for the interrupted context;
                    # the speech was cut short so the transfer/hangup must not fire.
                    self._context_done_callbacks.pop(context_id, None)
                    await super().on_audio_context_interrupted(context_id)

                def register_context_done_callback(
                    self, context_id: str, callback: Callable
                ) -> None:
                    """Register a one-shot async callback for audio-context completion.

                    The callback fires when ``on_audio_context_completed`` is called
                    for exactly this context_id — guaranteed to be after all audio
                    chunks for the utterance have been pushed downstream.  The
                    callback is discarded (not fired) if the context is interrupted.
                    """
                    self._context_done_callbacks[context_id] = callback

                async def on_audio_context_completed(self, context_id: str):
                    """Dispatch per-context callback then delegate to super."""
                    cb = self._context_done_callbacks.pop(context_id, None)
                    if cb is not None:
                        asyncio.create_task(cb())
                    await super().on_audio_context_completed(context_id)

            from pipecat.services.tts_service import TextAggregationMode

            voice = config.tts_voice_id or "aura-2-helena-en"
            # Twilio Media Streams require 8 kHz audio; tell Deepgram to encode at
            # 8000 Hz so no downstream resampling is needed before the Twilio
            # serialiser μ-law-encodes it for transmission.
            sample_rate = config.tts_config.get("sample_rate", 8000)
            encoding = config.tts_config.get("encoding", "linear16")

            # TOKEN mode sends each LLM token to Deepgram the moment it arrives,
            # keeping Deepgram's internal synthesis buffer continuously filled and
            # eliminating sentence-boundary drain gaps.  Default is "token" because
            # "sentence" produces audible 40–1800ms gaps at every sentence boundary;
            # operators can override back to "sentence" via tts_config on the assistant.
            _mode_str = config.tts_config.get("text_aggregation_mode", "token")
            text_aggregation_mode = (
                TextAggregationMode.TOKEN
                if _mode_str == "token"
                else TextAggregationMode.SENTENCE
            )

            if hasattr(DeepgramTTSService, "Settings"):
                return _BotelierDeepgramTTSService(
                    api_key=api_keys.get("deepgram_api_key"),
                    sample_rate=sample_rate,
                    encoding=encoding,
                    text_aggregation_mode=text_aggregation_mode,
                    settings=DeepgramTTSService.Settings(
                        voice=voice,
                    ),
                )
            return _BotelierDeepgramTTSService(
                api_key=api_keys.get("deepgram_api_key"),
                voice=voice,
                sample_rate=sample_rate,
                encoding=encoding,
                text_aggregation_mode=text_aggregation_mode,
            )
        elif provider == "cartesia":
            from pipecat.services.cartesia.tts import CartesiaTTSService

            class _BotelierCartesiaTTSService(CartesiaTTSService):
                """Cartesia TTS with per-context-ID completion callbacks.

                Mirrors the Deepgram subclass: terminal handlers register a
                callback for the specific context_id of the utterance they
                push, so the transfer/hangup fires only when that exact audio
                has been pushed downstream — not on any BotStoppedSpeakingFrame.
                """

                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self._context_done_callbacks: dict[str, Callable] = {}

                def register_context_done_callback(
                    self, context_id: str, callback: Callable
                ) -> None:
                    self._context_done_callbacks[context_id] = callback

                async def on_audio_context_completed(self, context_id: str):
                    cb = self._context_done_callbacks.pop(context_id, None)
                    if cb is not None:
                        asyncio.create_task(cb())
                    await super().on_audio_context_completed(context_id)

                async def on_audio_context_interrupted(self, context_id: str):
                    self._context_done_callbacks.pop(context_id, None)
                    await super().on_audio_context_interrupted(context_id)

            return _BotelierCartesiaTTSService(
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
        api_keys: dict[str, str],
        transport,
        function_schemas: list | None = None,
        function_handlers: dict[str, Any] | None = None,
        on_interruption: Callable[[str], None] | None = None,
        on_llm_response: Callable | None = None,
        on_user_turn: Callable | None = None,
        call_start_mono: float = 0.0,
        on_llm_start: Callable | None = None,
        stream_sid: str = "",
    ) -> tuple:
        """Create complete voice pipeline from agent configuration.

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
            17-tuple: (pipeline, task, llm, context_aggregator, context,
                      tts_completion_watcher, twilio_mark_watcher, first_speech_tracker,
                      greeting_completion_tracker, idle_timeout_tracker,
                      user_turn_capture, tts_latency_tracker, vad_suspicion_tracker,
                      greeting_injector, usage_observer, tts_audio_gap_tracker, tts).
            - context is returned separately for transcript extraction.
            - tts_completion_watcher can be linked to FunctionMapper.set_tts_completion_watcher()
              so transfer handlers can await TTS completion without time-based sleeps.
            - twilio_mark_watcher can be linked to FunctionMapper.set_twilio_mark_watcher()
              so transfer handlers can wait for Twilio to acknowledge playback.
            - tts is the TTS service instance; link it via FunctionMapper.set_tts_service() so
              terminal handlers can bind callbacks to a specific audio context_id rather than
              firing on any BotStoppedSpeakingFrame (the Deepgram spurious-fire bug).
            - first_speech_tracker / greeting_completion_tracker / idle_timeout_tracker /
              user_turn_capture / tts_latency_tracker / vad_suspicion_tracker need event_queue injected via
              set_event_queue() after pipeline creation.
            - usage_observer is a UsageObserver (BaseObserver) attached to PipelineTask; query
              total_prompt_tokens, total_completion_tokens, total_tts_chars, llm_model, tts_model
              at call teardown for billing and future per-model rate lookups.
        """
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        stt = VoiceEngineFactory.create_stt_service(config, api_keys)
        llm = VoiceEngineFactory.create_llm_service(config, api_keys)
        tts = VoiceEngineFactory.create_tts_service(config, api_keys)

        # Shared mutable timing state threaded through all latency-tracking processors.
        # Each processor writes a monotonic timestamp on its key event; downstream
        # processors read earlier timestamps to compute inter-stage deltas.
        #
        # Keys written per turn:
        #   "t_stt"       — UserTurnCapture on TranscriptionFrame
        #   "t_llm_start" — LLMResponseCapture on LLMFullResponseStartFrame
        #   "t_llm_end"   — LLMResponseCapture on LLMFullResponseEndFrame
        _timing_state: dict = {}
        _timing_state["vad_false_start_window_s"] = float(config.stt_config.get("utterance_end_ms", 1000)) / 1000.0
        _timing_state["vad_missed_speech_window_s"] = float(config.stt_config.get("eot_timeout_ms", 5000)) / 2000.0
        # STT is intentionally muted during the greeting window by
        # MuteUntilFirstBotCompleteUserMuteStrategy. VadSuspicionTracker reads
        # this flag to suppress the missed-speech heuristic while no
        # TranscriptionFrames can ever arrive. Cleared via
        # VadSuspicionTracker.clear_stt_mute() in the greeting callback.
        _timing_state["stt_muted"] = True

        llm_response_capture = LLMResponseCapture(
            on_llm_response=on_llm_response,
            on_llm_start=on_llm_start,
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        # Capture finalized user utterances for per-turn timestamp recording.
        # Placed after the STT mute filter so only post-muting transcriptions
        # (i.e. those that reach the LLM) are captured.  Pure observer.
        # call_start_mono enables per-turn STT latency logging.
        user_turn_capture = UserTurnCapture(
            on_user_turn=on_user_turn,
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        # Track text frames/interruptions before TTS
        interruption_tracker = InterruptionTracker(on_interruption=on_interruption)

        # Injects pre-rendered (cached) greeting PCM downstream of STT so the
        # cached audio is never transcribed by Deepgram and surfaced as
        # phantom user_first_speech / caller_spoke. See class docstring.
        greeting_injector = GreetingAudioInjector()

        # Observe BotStoppedSpeakingFrame after TTS so transfer handlers can
        # await actual TTS completion rather than using fixed-duration sleeps.
        tts_completion_watcher = TtsCompletionWatcher()

        # Sends Twilio mark messages and observes mark acks so transfer handlers
        # can wait until the caller has heard the pre-transfer phrase.
        twilio_mark_watcher = TwilioMarkWatcher(stream_sid=stream_sid)

        # Detect the caller's first speech utterance for event logging.
        # Placed between STT and context_aggregator so it intercepts
        # TranscriptionFrames before they enter the LLM pipeline.
        first_speech_tracker = FirstUserSpeechTracker()

        # Detect intra-turn audio gaps >30ms between consecutive TTSAudioRawFrames.
        # Off by default in production (LOG_LEVEL=INFO); enable by raising to DEBUG.
        # Resets on LLMFullResponseStartFrame to prevent cross-turn false positives.
        tts_audio_gap_tracker = TtsAudioGapTracker()

        # Log greeting_completed on the first BotStoppedSpeakingFrame (greeting TTS done).
        # Placed between TTS and tts_completion_watcher; both see the same frame.
        greeting_completion_tracker = GreetingCompletionTracker()

        # Log idle_timeout when the caller goes silent for too long.
        # UserIdleProcessor fires a callback after `timeout` seconds of silence.
        idle_timeout_tracker = IdleTimeoutTracker(timeout=30.0)

        effective_vad_enabled = is_external_vad_effectively_enabled(config)

        vad_suspicion_tracker = VadSuspicionTracker(
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
            metadata={
                "assistant_id": config.agent_id,
                "vad_enabled": config.enable_vad,
                "effective_vad_enabled": effective_vad_enabled,
                "vad_provider": config.vad_provider,
                "stt_model": config.stt_model,
                "min_volume": config.vad_config.get("min_volume"),
            },
            enabled=effective_vad_enabled,
        )

        # Stamps t_last_inbound on every inbound AudioRawFrame from Twilio so that
        # UserTurnCapture can compute "Twilio inbound audio → STT finalized" delta.
        # Placed immediately after transport.input() — pure observer, zero latency impact.
        inbound_audio_tracker = InboundAudioTracker(timing_state=_timing_state)

        # Measures the final two pipeline-stage handoffs:
        #   3. LLM last token → TTS first audio chunk  (LLM→TTS delta, may be negative for streaming TTS)
        #   4. Dispatch of first audio chunk to transport.output() (call-relative timestamp)
        # Placed just before transport.output() so it sees AudioRawFrames on their way out
        # and also receives LLMFullResponseStartFrame flowing downstream from the LLM.
        tts_latency_tracker = TtsPipelineLatencyTracker(
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        # Pipecat-native usage accumulator attached to PipelineTask as an observer.
        # Receives MetricsFrame events outside the pipeline chain (zero latency impact).
        # Accumulates prompt/completion tokens from LLMUsageMetricsData and TTS chars
        # from TTSUsageMetricsData (exact chars passed to run_tts() after aggregation).
        # Also records llm_model and tts_model for future per-model rate lookups.
        usage_observer = UsageObserver()

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

        # Build LLMUserAggregatorParams integrating VAD, SmartTurn end-of-turn
        # detection, and mute strategies in one place.
        #
        # For the Silero VAD path this replaces the three deprecated Pipecat
        # APIs (TransportParams.vad_analyzer, TransportParams.turn_analyzer,
        # STTMuteFilter).  Combining them inside the aggregator eliminates the
        # race condition where a VAD speech-stop event fires while STT is muted,
        # leaving the first caller utterance orphaned with no end-of-turn signal.
        #
        # MuteUntilFirstBotCompleteUserMuteStrategy — suppresses user frames
        #   until the opening greeting finishes (replaces MUTE_UNTIL_FIRST_BOT_COMPLETE).
        # FunctionCallUserMuteStrategy — re-mutes during active tool/function
        #   calls (e.g. transfers) so the caller cannot interrupt mid-transfer
        #   (replaces FUNCTION_CALL).
        user_params: LLMUserAggregatorParams | None = None
        if effective_vad_enabled:
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams

            vad_config = config.vad_config or {}
            vad_params = VADParams(
                confidence=vad_config.get("confidence", 0.7),
                start_secs=vad_config.get("start_secs", 0.2),
                stop_secs=vad_config.get("stop_secs", 0.2),
                # Keep fallback aligned with DB defaults: 0.4 is a balanced baseline,
                # while ~0.35–0.45 is the recommended noisy-environment tuning band.
                min_volume=vad_config.get("min_volume", 0.4),
            )
            # Barge-in gating — background-noise / echo false-interruption fix.
            #
            # Pipecat's DEFAULT user-turn start strategies are
            # [VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy]:
            # raw VAD energy (line noise, background voices, echo of the bot's
            # own speech) starts a user turn and, while the bot is speaking,
            # immediately broadcasts an interruption with ZERO transcribed
            # words.  MinWordsUserTurnStartStrategy instead requires
            # >= min_words transcribed words to interrupt while the bot is
            # speaking (1 word when the bot is silent), so noise that STT never
            # transcribes can no longer cut the bot off mid-word.  Trade-off:
            # legitimate barge-in waits for the first interim transcription
            # (~300 ms).  Set vad_config.interrupt_min_words=0 to restore the
            # legacy raw-VAD start behaviour for an assistant.
            # Defensive coercion: vad_config is an unvalidated JSONB dict from
            # the API — bad operator input must never crash call setup.
            try:
                interrupt_min_words = max(0, int(float(vad_config.get("interrupt_min_words", 2) or 0)))
            except (TypeError, ValueError):
                logger.warning(
                    f"Invalid vad_config.interrupt_min_words value "
                    f"{vad_config.get('interrupt_min_words')!r} — falling back to default 2"
                )
                interrupt_min_words = 2

            stop_strategies = [
                TurnAnalyzerUserTurnStopStrategy(
                    turn_analyzer=LocalSmartTurnAnalyzerV3(
                        params=SmartTurnParams(
                            stop_secs=vad_config.get("smart_turn_stop_secs", 0.5),
                        )
                    )
                )
            ]
            if interrupt_min_words > 0:
                turn_strategies = UserTurnStrategies(
                    start=[MinWordsUserTurnStartStrategy(min_words=interrupt_min_words)],
                    stop=stop_strategies,
                )
            else:
                turn_strategies = UserTurnStrategies(stop=stop_strategies)

            user_mute_strategies = [
                MuteUntilFirstBotCompleteUserMuteStrategy(),
                FunctionCallUserMuteStrategy(),
            ]
            if not config.enable_interruptions:
                # Per-assistant "interruptible" toggle OFF: suppress ALL caller
                # frames (audio, VAD events, transcriptions, interruptions)
                # while the bot is speaking — callers cannot barge in at all.
                user_mute_strategies.insert(0, AlwaysUserMuteStrategy())

            user_params = LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(params=vad_params),
                user_turn_strategies=turn_strategies,
                user_mute_strategies=user_mute_strategies,
            )
            logger.info(
                f"Silero VAD + SmartTurn wired into LLMUserAggregator: {vad_params} | "
                f"interrupt_min_words={interrupt_min_words} | "
                f"interruptions={'enabled' if config.enable_interruptions else 'DISABLED (caller muted during bot speech)'}"
            )

        elif is_flux_model(config.stt_model):
            # Flux path: apply mute strategies WITHOUT a VAD analyzer or SmartTurn.
            #
            # Flux owns its own turn detection (StartOfTurn / EndOfTurn events) so we
            # must NOT attach a Silero VAD analyzer — doing so would create a second,
            # conflicting turn-detection layer.  However, we still need the mute
            # strategies so Pipecat stops forwarding caller audio to run_stt() while
            # the bot is speaking.  Without them user_params is None, audio keeps
            # flowing to the Flux WebSocket during TTS, and the Flux watchdog
            # (_watchdog_task_handler) detects audio stalling mid-response (because
            # the muted frames never arrive), injects synthetic silence, which causes
            # Flux to fire a new StartOfTurn → broadcast_interruption() → the bot's
            # voice is cut off mid-word.  The greeting suffers the same fate on the
            # very first response before the caller has spoken at all.
            #
            # Interruption guard (toggle OFF):
            #   Two independent sources can fire broadcast_interruption() and cause
            #   a Twilio `clear` that wipes audio buffered in the carrier — this is
            #   the root cause of bot speech being audibly cut mid-sentence when the
            #   caller breathes or speaks during inter-segment pauses (BotStoppedSpeaking
            #   fires between TTS segments, briefly lifting the AlwaysUserMuteStrategy
            #   window):
            #
            #   1. DeepgramFluxSTTService._handle_start_of_turn (pipecat flux/base.py):
            #      caller noise during the unmuted window → Flux fires StartOfTurn →
            #      broadcast_interruption() — gated by should_interrupt=False on the
            #      STT service (set in create_stt_service() above).
            #
            #   2. LLMUserAggregator / TranscriptionUserTurnStartStrategy: if a real
            #      word is transcribed during the unmuted gap the aggregator's default
            #      TranscriptionUserTurnStartStrategy (enable_interruptions=True) also
            #      fires an interruption — gated by explicit UserTurnStrategies with
            #      enable_interruptions=False below.
            #
            #   The mute strategies are kept unchanged — they are the primary guard
            #   against Flux watchdog stalls during bot speech.  The interruption gates
            #   are additive (defence-in-depth) for the unmuted inter-segment windows.
            flux_mute_strategies = [
                MuteUntilFirstBotCompleteUserMuteStrategy(),
                FunctionCallUserMuteStrategy(),
            ]
            # Flux owns turn detection (StartOfTurn / EndOfTurn events from the
            # STT service), so turn strategies must be EXPLICIT external ones.
            # Never pass None here: LLMUserAggregator would fall back to the
            # default UserTurnStrategies(), whose __post_init__ constructs a
            # SmartTurn (LocalSmartTurnAnalyzerV3) stop strategy — an ML model
            # this path explicitly omits, and a hard crash on every call if the
            # optional `transformers` dependency is missing from the image.
            flux_turn_strategies: UserTurnStrategies = ExternalUserTurnStrategies()
            if not config.enable_interruptions:
                # Per-assistant "interruptible" toggle OFF:
                #   - AlwaysUserMuteStrategy: mutes caller audio during bot speech so
                #     Flux never sees audio in those windows.
                #   - UserTurnStrategies with enable_interruptions=False: ensures that
                #     even if a word is transcribed during an inter-segment unmuted
                #     gap the aggregator will NOT emit an interruption frame.
                #   - stop must stay explicit (ExternalUserTurnStopStrategy) so the
                #     dataclass __post_init__ never falls back to the SmartTurn default.
                flux_mute_strategies.insert(0, AlwaysUserMuteStrategy())
                flux_turn_strategies = UserTurnStrategies(
                    start=[TranscriptionUserTurnStartStrategy(enable_interruptions=False)],
                    stop=[ExternalUserTurnStopStrategy()],
                )

            user_params = LLMUserAggregatorParams(
                user_mute_strategies=flux_mute_strategies,
                user_turn_strategies=flux_turn_strategies,
            )
            logger.info(
                f"Deepgram Flux mute strategies wired into LLMUserAggregator "
                f"(model={config.stt_model!r}); VAD/SmartTurn omitted — Flux owns turn detection | "
                f"interruptions={'enabled' if config.enable_interruptions else 'DISABLED (should_interrupt=False + enable_interruptions=False on turn strategy)'}"
            )

        context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)

        # Register function handlers with LLM
        if function_handlers:
            for function_name, handler in function_handlers.items():
                llm.register_function(function_name, handler)

        pipeline = Pipeline(
            [
                transport.input(),
                inbound_audio_tracker,  # Stamps t_last_inbound for Twilio→STT latency measurement
                vad_suspicion_tracker,  # Emits vad_*_suspected events from timing context
                stt,
                user_turn_capture,  # Records per-turn user timestamps for transcript (pure observer)
                first_speech_tracker,  # Detects caller's first utterance (non-blocking event log)
                idle_timeout_tracker.processor,  # Logs idle_timeout when caller goes silent too long
                context_aggregator.user(),
                llm,
                llm_response_capture,  # Captures complete LLM responses for transcript recovery
                interruption_tracker,  # Observes text frames + InterruptionFrame before TTS
                greeting_injector,  # One-shot cached-greeting push, downstream of STT
                tts,
                tts_audio_gap_tracker,  # DEBUG-level gap monitor; pure observer, zero hot-path overhead
                greeting_completion_tracker,  # Logs greeting_completed on first BotStoppedSpeakingFrame
                tts_completion_watcher,  # Observes BotStoppedSpeakingFrame after TTS
                twilio_mark_watcher,  # Awaits Twilio mark acks for playback boundaries
                tts_latency_tracker,  # Measures LLM→TTS and TTS→transport handoff latencies
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
            observers=[usage_observer],
        )

        return (
            pipeline,
            task,
            llm,
            context_aggregator,
            context,
            tts_completion_watcher,
            twilio_mark_watcher,
            first_speech_tracker,
            greeting_completion_tracker,
            idle_timeout_tracker,
            user_turn_capture,
            tts_latency_tracker,
            vad_suspicion_tracker,
            greeting_injector,
            usage_observer,
            tts_audio_gap_tracker,
            tts,
        )

    @staticmethod
    def create_transport_params(config: VoiceAgentConfig):
        """Return base TransportParams for the Twilio / FastAPI WebSocket path.

        pipecat 1.1.0 removed vad_analyzer and turn_analyzer from TransportParams
        and FastAPIWebsocketParams entirely.  All VAD (Silero) and SmartTurn wiring
        now lives inside LLMUserAggregatorParams, which is built by create_pipeline().
        This method is kept for API compatibility but only returns the audio I/O flags;
        callers must NOT attempt to read vad_analyzer from the returned object.
        """
        from pipecat.transports.base_transport import TransportParams

        return TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )

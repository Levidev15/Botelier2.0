"""
Pre-warm cache for incoming Twilio calls (Task #111).

Between the `/api/calls/incoming` webhook (which resolves the destination
phone → assistant) and the WebSocket `start` event (which hands control to
``CallHandler.handle_call``) there is a Twilio-side round-trip — the caller's
WebSocket takes ~300–1500 ms to reach us after the webhook returns. That
window is wall-clock idle on our side today, but it is also the last chance
to do the 4 DB reads + the MCP tool-schema handshake + the greeting PCM
fetch without delaying the first audible byte of audio.

This module:

1. Runs those reads in a background ``asyncio.Task`` spawned from the
   ``/api/calls/incoming`` handler (after the TwiML response has been built).
2. Stores the results in an in-memory LRU+TTL cache keyed by Twilio
   ``call_sid`` (globally unique across tenants).
3. Exposes ``PreWarmCache.pop_and_wait()`` so ``handle_call`` can consume
   the bundle on the hot path with a bounded wait (≤500 ms by default).

Any pre-warm failure is swallowed and logged — the webhook response is never
blocked, and ``handle_call`` transparently falls back to the cold path.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


# Task #122 — hard cap on greeting PCM kept in-memory on the bundle.
# 8 kHz mono linear16 = 16 KB/s, so 1 MiB ≈ 64 s of audio — well above any
# realistic greeting length. Anything larger is almost certainly a Deepgram
# response we don't want to ship over the WebSocket and is dropped with a
# log so the consumer falls back to the inline greeting path.
MAX_GREETING_PCM_BYTES = 1_048_576


@dataclass
class AssistantSnapshot:
    """Plain-Python projection of the columns the consumer reads after the
    pre-warm session has been closed. Replaces the detached ORM object on
    :class:`PreWarmBundle` so the hot path never touches SQLAlchemy state
    that may have expired (Task #122)."""

    id: str
    account_id: str
    name: str
    description: Optional[str] = None


@dataclass
class PreWarmBundle:
    """
    Result of a successful pre-warm. All fields are pure Python values —
    no SQLAlchemy ORM objects cross the session boundary (Task #122).
    """

    # `assistant` used to be a detached ORM row; it is now an
    # :class:`AssistantSnapshot` carrying only the scalar columns the hot
    # path actually reads (id, account_id, name, description).
    assistant: Optional[AssistantSnapshot] = None
    config: Any = None  # VoiceAgentConfig built from the assistant
    tools: List[Any] = field(default_factory=list)
    mcp_connection_data: Optional[Dict[str, Any]] = None
    mcp_enabled_tools: List[str] = field(default_factory=list)
    hotel_twilio_sid: Optional[str] = None
    hotel_twilio_token: Optional[str] = None
    should_record_call: bool = False
    greeting_pcm: Optional[bytes] = None
    greeting_error: Optional[str] = None  # populated if greeting pre-fetch failed
    prewarm_duration_ms: Optional[int] = None


@dataclass
class PopResult:
    """Outcome of :meth:`PreWarmCache.pop_and_wait` — exposes the bundle
    plus telemetry so the consumer can distinguish (Task #122):

    * ``ready_before_wait`` — pre-warm finished before the WebSocket opened
      (cache served zero-cost; ideal case)
    * ``ready_during_wait`` — entry was reserved but still in flight; we
      blocked for ``wait_ms`` until ready
    * ``timeout``           — exceeded the wait budget; consumer falls back
    * ``error``             — pre-warm task recorded an error
    * ``missing``           — no reservation was ever placed (true cache
      miss; e.g. unmapped phone number at webhook time)
    """

    state: str
    bundle: Optional[PreWarmBundle] = None
    wait_ms: int = 0
    error_class: Optional[str] = None


@dataclass
class PreWarmEntry:
    """A slot in :class:`PreWarmCache`. Populated atomically by the pre-warm
    task; ``ready`` flips to set when the bundle is either filled or the
    pre-warm failed."""

    call_sid: str
    created_mono: float
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    bundle: Optional[PreWarmBundle] = None
    error: Optional[BaseException] = None


class PreWarmCache:
    """
    LRU+TTL map of ``call_sid → PreWarmEntry``.

    * Size bound: ``max_size`` entries (LRU evict on overflow).
    * TTL: ``ttl_secs`` from insertion — expired entries are lazily purged on
      every ``set`` / ``pop_and_wait`` / ``discard``. Also purged opportunistically
      by any consumer call.
    * Thread-safety: all methods are intended to be called on the asyncio
      event loop; no cross-thread access is expected.  No locking is used.

    Cross-tenant safety: we key by ``call_sid`` which is globally unique in
    Twilio's namespace.  Even if two tenants share an assistant, each call
    gets its own bundle.
    """

    def __init__(self, max_size: int = 256, ttl_secs: float = 60.0) -> None:
        self._store: "OrderedDict[str, PreWarmEntry]" = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_secs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reserve(self, call_sid: str) -> PreWarmEntry:
        """Insert (or replace) an empty entry and return it. The caller is
        expected to fill ``bundle`` / ``error`` and set ``ready`` when the
        pre-warm task finishes."""
        self._purge_expired()
        if call_sid in self._store:
            # Replace any stale entry for the same SID (unlikely but safe).
            old = self._store.pop(call_sid)
            # If an earlier pre-warm task is still running against the old
            # entry, at least let waiters wake up so they can fall back.
            if not old.ready.is_set():
                old.error = RuntimeError("superseded by new pre-warm")
                old.ready.set()
        entry = PreWarmEntry(call_sid=call_sid, created_mono=time.monotonic())
        self._store[call_sid] = entry
        self._enforce_size()
        return entry

    async def pop_and_wait(
        self, call_sid: str, timeout_secs: float = 0.5
    ) -> PopResult:
        """Remove the entry for ``call_sid`` and return a :class:`PopResult`
        describing whether it was already ready, became ready while we
        waited, timed out, errored, or was never reserved.

        The entry is always removed from the cache before returning
        (success or failure). Telemetry on this result powers the
        dev/prod parity diagnostics for Task #122."""
        self._purge_expired()
        entry = self._store.pop(call_sid, None)
        if entry is None:
            return PopResult(state="missing")

        # Classify ready-before-wait vs ready-during-wait WITHOUT racing the
        # producer: if ``ready`` is already set we never enter wait_for.
        if entry.ready.is_set():
            if entry.error is not None:
                logger.warning(
                    f"pre-warm error for call_sid={call_sid}: "
                    f"{type(entry.error).__name__}: {entry.error}"
                )
                return PopResult(
                    state="error",
                    error_class=type(entry.error).__name__,
                )
            return PopResult(state="ready_before_wait", bundle=entry.bundle)

        _t = time.monotonic()
        try:
            await asyncio.wait_for(entry.ready.wait(), timeout=timeout_secs)
        except asyncio.TimeoutError:
            wait_ms = int((time.monotonic() - _t) * 1000)
            logger.warning(
                f"pre-warm wait timed out after {wait_ms} ms "
                f"for call_sid={call_sid} — using cold path"
            )
            return PopResult(state="timeout", wait_ms=wait_ms)

        wait_ms = int((time.monotonic() - _t) * 1000)
        if entry.error is not None:
            logger.warning(
                f"pre-warm error for call_sid={call_sid}: "
                f"{type(entry.error).__name__}: {entry.error}"
            )
            return PopResult(
                state="error",
                wait_ms=wait_ms,
                error_class=type(entry.error).__name__,
            )
        return PopResult(
            state="ready_during_wait", bundle=entry.bundle, wait_ms=wait_ms
        )

    def discard(self, call_sid: str) -> None:
        """Remove an entry if still present (e.g. on call end).  No-op if
        missing."""
        self._store.pop(call_sid, None)

    def has(self, call_sid: str) -> bool:
        """Return True iff a (possibly not-yet-ready) reservation exists for
        ``call_sid``. Used by handle_call to distinguish a true cache-miss
        (``no_prewarm_entry``) from a hit that timed out or errored
        (``wait_timeout_or_error``) in telemetry."""
        return call_sid in self._store

    def size(self) -> int:  # pragma: no cover — trivial accessor
        return len(self._store)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _purge_expired(self) -> None:
        if not self._store:
            return
        cutoff = time.monotonic() - self._ttl
        # Iterate a copy of keys to allow in-loop deletion.
        for sid in list(self._store.keys()):
            if self._store[sid].created_mono < cutoff:
                self._store.pop(sid, None)

    def _enforce_size(self) -> None:
        while len(self._store) > self._max_size:
            # popitem(last=False) evicts the oldest (insertion-ordered).
            evicted_sid, _ = self._store.popitem(last=False)
            logger.info(
                f"pre-warm cache overflow — LRU-evicted call_sid={evicted_sid}"
            )


# ----------------------------------------------------------------------
# Orchestration — runs one pre-warm for a single incoming call.
# ----------------------------------------------------------------------
async def prewarm_call_config(
    entry: PreWarmEntry,
    to_number: str,
    deepgram_api_key: Optional[str],
) -> None:
    """Entry point for the background pre-warm task.

    Resolves ``Assistant`` / ``Account`` / ``Tool`` / ``MCPConnection`` from
    the destination phone number, builds ``VoiceAgentConfig`` (including
    threaded KB load), caches MCP connection metadata, and pre-loads the
    greeting PCM bytes (hot: file read; cold: Deepgram REST call during the
    WebSocket-handshake idle window).

    The caller passes the already-reserved ``PreWarmEntry`` directly so the
    producer and consumer always see the **same** entry object — this closes
    a race where ``pop_and_wait`` could remove the store-side reservation
    before the producer task dereferences it via ``cache._store.get``, which
    would otherwise lead to the producer filling a *different* entry than
    the consumer was awaiting.

    Any exception is captured onto the entry and never raised — the webhook
    caller treats failures as a silent fall-back.
    """
    call_sid = entry.call_sid
    t_start = time.monotonic()

    try:
        bundle = await _build_bundle(
            to_number=to_number,
            deepgram_api_key=deepgram_api_key,
        )
        bundle.prewarm_duration_ms = int((time.monotonic() - t_start) * 1000)
        entry.bundle = bundle
        logger.info(
            f"✅ pre-warm completed for call_sid={call_sid} "
            f"in {bundle.prewarm_duration_ms} ms"
        )
    except BaseException as e:  # noqa: BLE001 — we never want to propagate
        entry.error = e
        logger.warning(
            f"pre-warm failed for call_sid={call_sid} "
            f"({type(e).__name__}): {e}"
        )
    finally:
        entry.ready.set()


async def _build_bundle(
    to_number: str,
    deepgram_api_key: Optional[str],
) -> PreWarmBundle:
    """Do the actual read/handshake work. Split out so it can be unit-tested
    against a sqlite-backed session without touching the cache wiring."""
    # Imports inside the function to avoid circulars at module import time.
    from sqlalchemy.orm import Session  # noqa: F401 — type hint aid
    from ..auth.features import get_account_features
    from ..database import SessionLocal
    from ..models.account import Account
    from ..models.assistant import Assistant
    from ..models.mcp_connection import MCPConnection, MCPConnectionStatus
    from ..models.phone_number import PhoneNumber
    from ..models.tool import Tool
    from .greeting_cache import get_or_generate_greeting_audio

    bundle = PreWarmBundle()

    def _db_reads() -> dict:
        """Run all SQLAlchemy reads in a worker thread; return detached
        ORM objects + dicts.  We ``expunge_all`` before closing the session
        so attribute reads on the hot path don't trigger lazy loads."""
        _db = SessionLocal()
        try:
            phone = (
                _db.query(PhoneNumber)
                .filter(PhoneNumber.phone_number == to_number)
                .first()
            )
            if not phone or not phone.assistant_id:
                return {"skip_reason": "no_assistant_for_phone"}

            assistant = (
                _db.query(Assistant)
                .filter(Assistant.id == phone.assistant_id)
                .first()
            )
            if not assistant:
                return {"skip_reason": "assistant_not_found"}

            account = (
                _db.query(Account)
                .filter(Account.id == assistant.account_id)
                .first()
            )

            tools: List[Any] = []
            if assistant.tool_set_id:
                tools = (
                    _db.query(Tool)
                    .filter(
                        Tool.tool_set_id == assistant.tool_set_id,
                        Tool.is_active == "true",
                    )
                    .all()
                )

            mcp_conn_data: Optional[Dict[str, Any]] = None
            mcp_enabled: List[str] = []
            if assistant.mcp_connection_id:
                mcp_conn = (
                    _db.query(MCPConnection)
                    .filter(
                        MCPConnection.id == assistant.mcp_connection_id,
                        MCPConnection.is_active.is_(True),
                    )
                    .first()
                )
                if mcp_conn and mcp_conn.status == MCPConnectionStatus.CONNECTED:
                    credentials = None
                    if mcp_conn.credentials_encrypted:
                        try:
                            credentials = mcp_conn.get_credentials()
                        except Exception as _e:
                            logger.warning(
                                f"pre-warm: failed to decrypt MCP credentials: {_e}"
                            )
                    mcp_conn_data = {
                        "id": str(mcp_conn.id),
                        "server_url": mcp_conn.server_url,
                        "auth_type": (
                            mcp_conn.auth_type.value if mcp_conn.auth_type else "none"
                        ),
                        "credentials": credentials,
                        "discovered_tools": mcp_conn.discovered_tools or [],
                    }
                    mcp_enabled = list(assistant.mcp_enabled_tools or [])

            hotel_sid = None
            hotel_token = None
            should_record = False
            if account is not None:
                hotel_sid = account.twilio_sub_account_sid
                hotel_token = account.twilio_sub_auth_token
                _features = get_account_features(
                    subscription_tier=(
                        getattr(account, "subscription_tier", None) or "free"
                    ),
                    feature_flags_override=(account.feature_flags or {}),
                )
                _acct_recording_allowed = _features.get("call_recording", False)
                _asst_recording_enabled = bool(
                    (assistant.call_settings or {}).get(
                        "call_recording_enabled", False
                    )
                )
                should_record = _acct_recording_allowed and _asst_recording_enabled

            # Project the assistant ORM into a plain :class:`AssistantSnapshot`
            # so the hot path never reads attributes off a detached SQLAlchemy
            # instance. The full ORM object is still returned alongside it,
            # used ONLY by ``_create_agent_config`` below (which is invoked
            # before this function returns and therefore still inside the
            # producer's coroutine, never on the consumer's hot path).
            snapshot = AssistantSnapshot(
                id=str(assistant.id),
                account_id=str(assistant.account_id),
                name=assistant.name,
                description=getattr(assistant, "description", None),
            )
            # Detach everything from the session so the build-time
            # ``_create_agent_config`` read can still touch attributes
            # without triggering lazy loads / DetachedInstance errors.
            _db.expunge_all()
            return {
                "skip_reason": None,
                "assistant_orm": assistant,
                "assistant_snapshot": snapshot,
                "tools": tools,
                "mcp_conn_data": mcp_conn_data,
                "mcp_enabled": mcp_enabled,
                "hotel_sid": hotel_sid,
                "hotel_token": hotel_token,
                "should_record": should_record,
            }
        finally:
            _db.close()

    reads = await asyncio.to_thread(_db_reads)
    if reads.get("skip_reason"):
        logger.info(
            f"pre-warm: skipping (reason={reads['skip_reason']}, to={to_number})"
        )
        return bundle  # empty bundle — consumer will fall back to cold path

    bundle.assistant = reads["assistant_snapshot"]
    bundle.tools = reads["tools"]
    bundle.mcp_connection_data = reads["mcp_conn_data"]
    bundle.mcp_enabled_tools = reads["mcp_enabled"]
    bundle.hotel_twilio_sid = reads["hotel_sid"]
    bundle.hotel_twilio_token = reads["hotel_token"]
    bundle.should_record_call = reads["should_record"]

    # Build VoiceAgentConfig from the detached ORM assistant. Reuse the
    # process-wide CallHandler singleton rather than instantiating a fresh
    # one per pre-warm — _create_agent_config is an instance method today,
    # but none of its logic depends on per-call handler state, so routing
    # through the singleton avoids constructing a throwaway handler on every
    # incoming call. Imported lazily to avoid a circular import
    # (call_handler -> prewarm -> call_handler).
    #
    # IMPORTANT: ``_create_agent_config`` reads ~20 columns off the ORM row.
    # We pass the detached ORM (``assistant_orm``) here — it is local to the
    # producer task and never escapes onto the bundle. The hot-path consumer
    # only ever sees ``bundle.assistant`` which is the plain
    # ``AssistantSnapshot`` populated above.
    from ..api.calls import _get_call_handler as _get_singleton_handler

    _assistant_orm = reads["assistant_orm"]
    try:
        bundle.config = await _get_singleton_handler()._create_agent_config(
            _assistant_orm
        )
    except Exception as _cfg_err:
        # Config build failure is fatal for the pre-warm — without it the
        # consumer cannot proceed.  Record and let handle_call fall back.
        raise RuntimeError(
            f"_create_agent_config failed: {type(_cfg_err).__name__}: {_cfg_err}"
        )

    # Pre-load greeting PCM (cache hit = 1 file read; miss = 1 REST call).
    # Only for Deepgram TTS — other providers aren't cached.
    if (
        bundle.config is not None
        and str(getattr(bundle.config, "tts_provider", "")).lower() == "deepgram"
        and deepgram_api_key
    ):
        try:
            _voice = bundle.config.tts_voice_id or "aura-2-helena-en"
            _pcm = await get_or_generate_greeting_audio(
                greeting_text=bundle.config.greeting_message,
                tts_config={"voice": _voice},
                api_key=deepgram_api_key,
                assistant_id=str(bundle.assistant.id),
            )
            # Task #122 — refuse to ship oversized payloads through the
            # bundle (consumer falls back to its inline greeting path).
            if _pcm is not None and len(_pcm) > MAX_GREETING_PCM_BYTES:
                logger.warning(
                    f"pre-warm greeting PCM exceeded cap "
                    f"({len(_pcm)} > {MAX_GREETING_PCM_BYTES} bytes) — "
                    f"discarding for assistant={bundle.assistant.id}"
                )
                bundle.greeting_error = (
                    f"oversize_greeting_pcm:{len(_pcm)}"
                )
            else:
                bundle.greeting_pcm = _pcm
        except Exception as _g_err:
            bundle.greeting_error = f"{type(_g_err).__name__}: {_g_err}"
            logger.warning(
                f"pre-warm greeting fetch failed "
                f"(assistant={bundle.assistant.id}): {bundle.greeting_error}"
            )

    return bundle

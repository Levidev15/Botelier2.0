"""Bounded session and resource bookkeeping for the native text simulator.

The session delegates all flow behavior to its supplied native host. It does
not interpret graph nodes, dispatch tools, or construct an LLM conversation.
"""

import asyncio
from collections import defaultdict, deque
from copy import deepcopy
import json
import math
import time
import uuid
from typing import Any, Callable

from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy


_START_WINDOW_SECONDS = 60.0
_START_TIMEOUT_SECONDS = 30.0
_TURN_TIMEOUT_SECONDS = 120.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_MAX_RUNTIME_BYTES = 32 * 1024
_MAX_VARIABLES_BYTES = 64 * 1024
_MAX_HISTORY_BYTES = 512 * 1024
_MAX_HOST_MESSAGES = 16
_MAX_HOST_MESSAGE_CHARS = 8_000
_MAX_HOST_TURN_CHARS = 16_000
_MAX_RATE_OWNERS_FACTOR = 5

_STATUS_BY_CODE = {
    "native_dev_disabled": 403,
    "native_dev_selection": 400,
    "native_dev_resources": 400,
    "native_dev_ownership": 403,
    "native_dev_published_version": 409,
    "native_simulation_published_source_required": 400,
    "native_simulation_version_required": 400,
    "native_simulation_version_changed": 409,
    "native_simulation_provider_unsupported": 400,
    "native_simulation_model_configuration": 400,
    "native_simulation_flow_unsupported": 400,
    "native_simulation_model_unconfigured": 503,
    "native_simulation_start_failed": 502,
    "native_simulation_failed": 400,
    "native_simulation_invalid_input": 400,
    "native_simulation_manual_calls_disabled": 400,
    "native_simulation_not_found": 404,
    "native_simulation_closed": 409,
    "native_simulation_busy": 409,
    "native_simulation_turn_limit": 429,
    "native_simulation_rate_limit": 429,
    "native_simulation_start_rate": 429,
    "native_simulation_owner_limit": 429,
    "native_simulation_capacity": 429,
    "native_simulation_output_limit": 413,
    "native_simulation_expired": 410,
    "native_simulation_disabled": 503,
    "native_simulation_shutdown": 503,
    "native_simulation_timeout": 503,
}

_SAFE_HOST_CODES = {
    "invalid": "native_simulation_failed",
    "busy": "native_simulation_busy",
    "closed": "native_simulation_closed",
    "timeout": "native_simulation_timeout",
    "unsupported_provider": "native_simulation_failed",
    "initialization": "native_simulation_failed",
}

# Designer-facing categories only. Never serialize exception text, saved
# configuration, prompts or provider results as admission diagnostics.
_FLOW_DIAGNOSTICS = frozenset({
    "definition", "definition_size", "definition_json", "global_instructions",
    "node_ids", "node_types", "node_data", "edges", "topology", "initial",
    "slot", "variables", "automatic_instructions", "connected_get", "api_fields",
    "endpoint_identity", "request_template", "request_limits", "speech",
    "mapping", "presentation",
})

_PRIVATE_RUNTIME_KEYS = {
    "api_key",
    "api_keys",
    "authorization",
    "body",
    "credentials",
    "headers",
    "password",
    "private_context",
    "private_prompt",
    "secret",
    "system_prompt",
    "token",
}


class NativeSimulationError(Exception):
    """Payload-free, fixed-category error suitable for an API adapter."""

    def __init__(self, code: str, status_code: int = 400, *, diagnostic=None):
        safe_code = code if code in _STATUS_BY_CODE else "native_simulation_failed"
        expected_status = _STATUS_BY_CODE[safe_code]
        raw_diagnostic = (
            diagnostic.split(":", 1)[0]
            if isinstance(diagnostic, str) else None
        )
        diagnostic_category = {
            "node_type": "node_types",
            "slot_type": "slot",
            "slot_validation": "slot",
            "slot_variable": "slot",
            "initial_count": "initial",
            "initial_node": "initial",
        }.get(raw_diagnostic, raw_diagnostic)
        self.code = safe_code
        self.diagnostic = (
            diagnostic_category
            if safe_code == "native_simulation_flow_unsupported"
            and diagnostic_category in _FLOW_DIAGNOSTICS
            else None
        )
        # A caller may request an explicitly supported status only when it
        # agrees with this fixed code; arbitrary exception status is discarded.
        self.status_code = (
            status_code if status_code == expected_status else expected_status
        )
        super().__init__(safe_code)


def _bounded_json_copy(value: Any, limit: int, *, code: str) -> Any:
    try:
        encoded = json.dumps(
            value, allow_nan=False, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > limit:
            raise NativeSimulationError(code)
        return json.loads(encoded)
    except NativeSimulationError:
        raise
    except Exception:
        raise NativeSimulationError(code) from None


def _private_runtime_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if (
                normalized in _PRIVATE_RUNTIME_KEYS
                or "credential" in normalized
                or "password" in normalized
                or normalized.endswith("_secret")
                or normalized.endswith("_token")
                or "private_prompt" in normalized
                or "system_prompt" in normalized
            ):
                return True
            if _private_runtime_key(child):
                return True
    elif isinstance(value, list):
        return any(_private_runtime_key(item) for item in value)
    return False


def _task_has_pending_cancellation() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class NativeSimulationRegistry:
    """Per-process, event-loop-local bounded registry for native sessions."""

    def __init__(
        self,
        max_sessions: int = 16,
        max_sessions_per_owner: int = 2,
        starts_per_minute: int = 5,
    ):
        for name, value in (
            ("max_sessions", max_sessions),
            ("max_sessions_per_owner", max_sessions_per_owner),
            ("starts_per_minute", starts_per_minute),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_sessions = max_sessions
        self.max_sessions_per_owner = max_sessions_per_owner
        self.starts_per_minute = starts_per_minute
        # Unique-owner traffic is bounded as well as each owner's deque.
        self._max_rate_owners = max_sessions * _MAX_RATE_OWNERS_FACTOR
        self._reservations: dict[str, str] = {}
        self._pending_sessions: dict[str, Any] = {}
        self._sessions: dict[str, Any] = {}
        self._session_maps: dict[str, dict[str, Any]] = {}
        self._owners: dict[str, str] = {}
        self._starts: dict[str, deque[float]] = defaultdict(deque)
        self._shutting_down = False

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def pending_count(self) -> int:
        return len(self._reservations)

    def _prune_start_buckets(self, now: float) -> None:
        cutoff = now - _START_WINDOW_SECONDS
        for owner, starts in tuple(self._starts.items()):
            while starts and starts[0] <= cutoff:
                starts.popleft()
            if not starts:
                self._starts.pop(owner, None)

    def reserve(self, owner_user_id: str) -> str:
        owner = str(owner_user_id or "")
        if not owner or len(owner) > 256:
            raise NativeSimulationError("native_simulation_not_found")
        if self._shutting_down:
            raise NativeSimulationError("native_simulation_shutdown")
        now = time.monotonic()
        self._prune_start_buckets(now)
        starts = self._starts.get(owner)
        if starts is not None and len(starts) >= self.starts_per_minute:
            raise NativeSimulationError("native_simulation_start_rate")

        owner_count = sum(
            stored_owner == owner for stored_owner in self._owners.values()
        )
        if owner_count >= self.max_sessions_per_owner:
            raise NativeSimulationError("native_simulation_owner_limit")
        if len(self._owners) >= self.max_sessions:
            raise NativeSimulationError("native_simulation_capacity")
        if starts is None:
            if len(self._starts) >= self._max_rate_owners:
                raise NativeSimulationError("native_simulation_capacity")
            starts = self._starts[owner]

        session_id = str(uuid.uuid4())
        while session_id in self._owners:
            session_id = str(uuid.uuid4())
        self._reservations[session_id] = owner
        self._owners[session_id] = owner
        starts.append(now)
        return session_id

    def _bind_pending(self, session: Any) -> None:
        session_id = str(getattr(session, "session_id", ""))
        owner = str(getattr(session, "owner_user_id", ""))
        if (
            self._shutting_down
            or self._reservations.get(session_id) != owner
            or session_id in self._pending_sessions
            or session_id in self._sessions
        ):
            raise NativeSimulationError("native_simulation_not_found")
        self._pending_sessions[session_id] = session

    def publish(self, session: Any, session_map: dict[str, Any]) -> None:
        session_id = str(getattr(session, "session_id", ""))
        owner = str(getattr(session, "owner_user_id", ""))
        if (
            self._shutting_down
            or self._reservations.get(session_id) != owner
            or self._pending_sessions.get(session_id) is not session
            or session_id in self._sessions
            or getattr(session, "_closing", True)
        ):
            raise NativeSimulationError("native_simulation_not_found")
        if session_id in session_map and session_map[session_id] is not session:
            raise NativeSimulationError("native_simulation_capacity")

        self._reservations.pop(session_id, None)
        self._pending_sessions.pop(session_id, None)
        session_map[session_id] = session
        self._sessions[session_id] = session
        self._session_maps[session_id] = session_map

    def abandon(self, session_id: str, owner_user_id: str) -> None:
        """Release only this owner's reservation/session and identity-matched map entry."""
        session_id = str(session_id)
        owner = str(owner_user_id or "")
        if self._owners.get(session_id) != owner:
            return

        self._reservations.pop(session_id, None)
        self._pending_sessions.pop(session_id, None)
        session = self._sessions.get(session_id)
        if session is not None and self._owners.get(session_id) == owner:
            self._sessions.pop(session_id, None)
            shared_map = self._session_maps.pop(session_id, None)
            if shared_map is not None and shared_map.get(session_id) is session:
                shared_map.pop(session_id, None)
        self._owners.pop(session_id, None)

    async def shutdown(self) -> None:
        self._shutting_down = True
        sessions = {
            id(session): session
            for session in (*self._pending_sessions.values(), *self._sessions.values())
        }
        # Reservations without a constructed session cannot be published.
        for session_id in tuple(self._reservations):
            if session_id not in self._pending_sessions:
                self._reservations.pop(session_id, None)
                self._owners.pop(session_id, None)
        if sessions:
            await asyncio.gather(
                *(session.close() for session in sessions.values()),
                return_exceptions=True,
            )


class NativeSimulationSession:
    """A public-response boundary around one caller-supplied native text host."""

    engine = "native_pilot"

    def __init__(
        self,
        *,
        session_id: str,
        owner_user_id: str,
        account_id: str,
        runtime: dict,
        variables_to_collect: list[dict],
        host: Any,
        registry: NativeSimulationRegistry,
        session_map: dict[str, Any],
        policy_provider: Callable[[], NativeFlowDevPolicy],
        max_turns: int = 30,
        min_turn_interval: float = 1.0,
        idle_timeout: float = 300.0,
        max_lifetime: float = 900.0,
    ):
        self.session_id = str(session_id)
        self.owner_user_id = str(owner_user_id)
        self.account_id = str(account_id)

        def reject(code: str) -> None:
            if (
                isinstance(registry, NativeSimulationRegistry)
                and registry._owners.get(self.session_id) == self.owner_user_id
                and self.session_id not in registry._pending_sessions
                and self.session_id not in registry._sessions
            ):
                registry.abandon(self.session_id, self.owner_user_id)
            raise NativeSimulationError(code)

        if (
            not self.session_id or not self.owner_user_id or not self.account_id
            or len(self.session_id) > 256
            or len(self.owner_user_id) > 256
            or len(self.account_id) > 256
        ):
            reject("native_simulation_invalid_input")
        if (
            type(max_turns) is not int
            or max_turns < 1
            or not callable(policy_provider)
            or not isinstance(registry, NativeSimulationRegistry)
            or not isinstance(session_map, dict)
            or not isinstance(runtime, dict)
            or not isinstance(variables_to_collect, list)
            or any(not isinstance(item, dict) for item in variables_to_collect)
            or not all(
                callable(getattr(host, method, None))
                for method in ("start", "send", "snapshot", "close")
            )
        ):
            reject("native_simulation_invalid_input")
        for name, value in (
            ("min_turn_interval", min_turn_interval),
            ("idle_timeout", idle_timeout),
            ("max_lifetime", max_lifetime),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
                or (name != "min_turn_interval" and value == 0)
            ):
                reject("native_simulation_invalid_input")

        try:
            self._runtime = _bounded_json_copy(
                runtime, _MAX_RUNTIME_BYTES, code="native_simulation_invalid_input",
            )
        except NativeSimulationError:
            reject("native_simulation_invalid_input")
        if _private_runtime_key(self._runtime):
            reject("native_simulation_invalid_input")
        try:
            self._variables = _bounded_json_copy(
                variables_to_collect,
                _MAX_VARIABLES_BYTES,
                code="native_simulation_invalid_input",
            )
        except NativeSimulationError:
            reject("native_simulation_invalid_input")
        self.host = host
        self.registry = registry
        self.session_map = session_map
        self.policy_provider = policy_provider
        self.max_turns = max_turns
        self.min_turn_interval = float(min_turn_interval)
        self.idle_timeout = float(idle_timeout)
        self.max_lifetime = float(max_lifetime)

        self._messages: list[dict] = []
        self._started_at: float | None = None
        self._last_activity: float | None = None
        self._last_turn_at: float | None = None
        self._turn_count = 0
        self._start_task: asyncio.Task | None = None
        self._active_turn: asyncio.Task | None = None
        self._expiry_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._scheduled_close_task: asyncio.Task | None = None
        self._expiry_changed = asyncio.Event()
        self._started = False
        self._closing = False
        self._closed = False
        try:
            registry._bind_pending(self)
        except Exception:
            raise NativeSimulationError("native_simulation_not_found") from None

    @property
    def runtime(self) -> dict:
        return deepcopy(self._runtime)

    @property
    def messages(self) -> list[dict]:
        return deepcopy(self._messages)

    @property
    def variables_to_collect(self) -> list[dict]:
        return deepcopy(self._variables)

    @property
    def is_ended(self) -> bool:
        return self._closed

    def check_owner(self, user_id: str) -> None:
        if str(user_id or "") != self.owner_user_id:
            raise NativeSimulationError("native_simulation_not_found", 404)

    def assert_live(self) -> None:
        if self._closing or self._closed:
            raise NativeSimulationError("native_simulation_closed")
        if getattr(self.host, "closed", False):
            self._schedule_close()
            raise NativeSimulationError("native_simulation_closed")
        now = time.monotonic()
        if self._started_at is not None:
            if now - self._started_at >= self.max_lifetime:
                self._schedule_close()
                raise NativeSimulationError("native_simulation_expired", 410)
            if (
                self._last_activity is not None
                and now - self._last_activity >= self.idle_timeout
                and self._active_turn is None
            ):
                self._schedule_close()
                raise NativeSimulationError("native_simulation_expired", 410)
        try:
            policy = self.policy_provider()
        except Exception:
            policy = None
        if type(policy) is not NativeFlowDevPolicy or policy.enabled is not True:
            self._schedule_close()
            raise NativeSimulationError("native_simulation_disabled", 503)

    def get_state_snapshot(self) -> dict:
        self.assert_live()
        if not self._started:
            raise NativeSimulationError("native_simulation_closed")
        try:
            snapshot = self.host.snapshot()
            if not isinstance(snapshot, dict):
                raise ValueError("invalid host snapshot")
            return _bounded_json_copy(
                snapshot, _MAX_HISTORY_BYTES,
                code="native_simulation_output_limit",
            )
        except NativeSimulationError:
            self._schedule_close()
            raise
        except Exception:
            self._schedule_close()
            raise NativeSimulationError("native_simulation_failed") from None

    def _schedule_close(self) -> None:
        if self._close_task is None and self._scheduled_close_task is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            # Claim the trigger before yielding. Repeated synchronous state
            # reads must not allocate another cleanup task for the same host.
            task = self._scheduled_close_task = loop.create_task(
                self.close(), name="native-simulation-close-trigger",
            )
            task.add_done_callback(_consume_task_exception)

    def _policy_check(self) -> None:
        self.assert_live()

    def _host_failure(self, error: Exception) -> NativeSimulationError:
        host_code = getattr(error, "code", None)
        if not isinstance(host_code, str):
            host_code = None
        code = _SAFE_HOST_CODES.get(host_code, "native_simulation_failed")
        return NativeSimulationError(code)

    def _public_turn(self, result: Any) -> tuple[list[dict], str, Any]:
        if not isinstance(result, dict):
            raise NativeSimulationError("native_simulation_failed")
        raw_messages = result.get("messages")
        if not isinstance(raw_messages, list) or len(raw_messages) > _MAX_HOST_MESSAGES:
            raise NativeSimulationError("native_simulation_output_limit")

        public_messages = []
        total_chars = 0
        for message in raw_messages:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, str) or len(content) > _MAX_HOST_MESSAGE_CHARS:
                raise NativeSimulationError("native_simulation_output_limit")
            total_chars += len(content)
            public_messages.append({"role": "assistant", "content": content})
        if total_chars > _MAX_HOST_TURN_CHARS:
            raise NativeSimulationError("native_simulation_output_limit")

        called = result.get("function_called")
        # The host contract is None|string. Current SDK host versions may return
        # the actual call record; preserve only its real public function name.
        if isinstance(called, dict):
            called = called.get("name")
        if called is not None and (
            not isinstance(called, str) or len(called) > 128
        ):
            raise NativeSimulationError("native_simulation_failed")
        function_result = result.get("function_result")
        if function_result is not None:
            if not isinstance(function_result, dict):
                raise NativeSimulationError("native_simulation_failed")
            function_result = _bounded_json_copy(
                function_result, _MAX_HISTORY_BYTES,
                code="native_simulation_output_limit",
            )
        return public_messages, called, function_result

    def _messages_with_metadata(
        self, prior: list[dict], outputs: list[dict], called: str | None, result: Any,
    ) -> list[dict]:
        additions = [
            {"role": "assistant", "content": item["content"], "metadata": {}}
            for item in outputs
        ]
        if additions and (called is not None or result is not None):
            additions[-1]["metadata"] = {
                "function_called": called,
                "function_result": result,
            }
        elif not additions and (called is not None or result is not None):
            additions.append({
                "role": "assistant",
                "content": "",
                "metadata": {
                    "function_called": called,
                    "function_result": result,
                },
            })
        updated = prior + additions
        return _bounded_json_copy(
            updated, _MAX_HISTORY_BYTES,
            code="native_simulation_output_limit",
        )

    def _host_snapshot(self) -> dict:
        snapshot = self.host.snapshot()
        if not isinstance(snapshot, dict):
            raise NativeSimulationError("native_simulation_failed")
        return _bounded_json_copy(
            snapshot, _MAX_HISTORY_BYTES,
            code="native_simulation_output_limit",
        )

    def _response_runtime(self) -> dict:
        return deepcopy(self._runtime)

    def _mark_activity(self) -> None:
        self._last_activity = time.monotonic()
        self._expiry_changed.set()

    async def start(self) -> dict:
        if self._started or self._start_task is not None:
            raise NativeSimulationError("native_simulation_busy")
        self._start_task = asyncio.current_task()
        start_timeout = asyncio.timeout(_START_TIMEOUT_SECONDS)
        try:
            self._policy_check()
            async with start_timeout:
                host_result = await self.host.start()
            if self._closing or self._closed:
                raise NativeSimulationError("native_simulation_closed")
            self._policy_check()
            outputs, called, function_result = self._public_turn(host_result)
            new_messages = self._messages_with_metadata(
                [], outputs, called, function_result,
            )
            state = self._host_snapshot()
            greeting = " ".join(
                message["content"]
                for message in outputs
                if message["content"].strip()
            )
            self._started_at = time.monotonic()
            self._last_activity = self._started_at
            self._messages = new_messages
            # Publishing is the final synchronous readiness step: shutdown,
            # close, or policy changes above cannot leave an unready map entry.
            self.registry.publish(self, self.session_map)
            self._started = True
            self._expiry_task = asyncio.create_task(
                self._expiry_loop(), name="native-simulation-expiry",
            )
            return {
                "session_id": self.session_id,
                "greeting": greeting,
                "variables_to_collect": deepcopy(self._variables),
                "state": state,
                "messages": self.messages,
                "runtime": self._response_runtime(),
            }
        except asyncio.CancelledError:
            if self._close_task is None:
                await self.close()
            raise
        except TimeoutError:
            if self._close_task is None:
                await self.close()
            raise NativeSimulationError("native_simulation_timeout") from None
        except NativeSimulationError:
            if self._close_task is None:
                await self.close()
            raise
        except Exception as error:
            if start_timeout.expired():
                if self._close_task is None:
                    await self.close()
                raise NativeSimulationError("native_simulation_timeout") from None
            if _task_has_pending_cancellation():
                if self._close_task is None:
                    await self.close()
                raise asyncio.CancelledError from None
            safe_error = self._host_failure(error)
            if self._close_task is None:
                await self.close()
            raise safe_error from None
        finally:
            if self._start_task is asyncio.current_task():
                self._start_task = None

    async def send(
        self,
        message: str,
        *,
        function_call: Any = None,
        function_args: Any = None,
    ) -> dict:
        # Manual tool-call injection is rejected before any host, history, or
        # provider access; only the host's real model turn may produce a call.
        if function_call is not None or function_args is not None:
            raise NativeSimulationError("native_simulation_manual_calls_disabled")
        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > 2048
        ):
            raise NativeSimulationError("native_simulation_invalid_input")
        self.assert_live()
        if not self._started:
            raise NativeSimulationError("native_simulation_closed")
        if self._active_turn is not None:
            raise NativeSimulationError("native_simulation_busy")
        if self._turn_count >= self.max_turns:
            raise NativeSimulationError("native_simulation_turn_limit")
        now = time.monotonic()
        if (
            self._last_turn_at is not None
            and now - self._last_turn_at < self.min_turn_interval
        ):
            raise NativeSimulationError("native_simulation_rate_limit")
        self._active_turn = asyncio.current_task()
        self._turn_count += 1
        self._last_turn_at = now
        self._mark_activity()
        turn_timeout = asyncio.timeout(_TURN_TIMEOUT_SECONDS)
        try:
            async with turn_timeout:
                result = await self.host.send(message)
            if self._closing or self._closed:
                raise NativeSimulationError("native_simulation_closed")
            self.assert_live()
            outputs, called, function_result = self._public_turn(result)
            updated_messages = self._messages_with_metadata(
                self._messages, outputs, called, function_result,
            )
            response = " ".join(
                item["content"] for item in outputs if item["content"].strip()
            )
            state = self._host_snapshot()
            self._messages = updated_messages
            self._mark_activity()
            return {
                "response": response,
                "function_called": called,
                "function_result": deepcopy(function_result),
                "state": state,
                "messages": self.messages,
                "suggested_functions": [],
                "error": None,
                "runtime": self._response_runtime(),
            }
        except asyncio.CancelledError:
            if self._close_task is None:
                await self.close()
            raise
        except TimeoutError:
            if self._close_task is None:
                await self.close()
            raise NativeSimulationError("native_simulation_timeout") from None
        except NativeSimulationError:
            if self._close_task is None:
                await self.close()
            raise
        except Exception as error:
            if turn_timeout.expired():
                if self._close_task is None:
                    await self.close()
                raise NativeSimulationError("native_simulation_timeout") from None
            if _task_has_pending_cancellation():
                if self._close_task is None:
                    await self.close()
                raise asyncio.CancelledError from None
            safe_error = self._host_failure(error)
            if self._close_task is None:
                await self.close()
            raise safe_error from None
        finally:
            if self._active_turn is asyncio.current_task():
                self._active_turn = None
                self._expiry_changed.set()

    async def _expiry_loop(self) -> None:
        try:
            while not self._closing and not self._closed:
                if self._started_at is None:
                    return
                now = time.monotonic()
                lifetime_deadline = self._started_at + self.max_lifetime
                idle_deadline = (
                    self._last_activity + self.idle_timeout
                    if self._last_activity is not None and self._active_turn is None
                    else float("inf")
                )
                deadline = min(lifetime_deadline, idle_deadline)
                delay = max(0.0, deadline - now)
                self._expiry_changed.clear()
                try:
                    await asyncio.wait_for(self._expiry_changed.wait(), timeout=delay)
                except TimeoutError:
                    if time.monotonic() >= self._started_at + self.max_lifetime:
                        await self.close()
                        return
                    if (
                        self._active_turn is None
                        and self._last_activity is not None
                        and time.monotonic() - self._last_activity >= self.idle_timeout
                    ):
                        await self.close()
                        return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Timer failures fail closed without logging any session data.
            await self.close()

    async def close(self) -> None:
        current = asyncio.current_task()
        if self._close_task is not None:
            if current is not self._close_task:
                await asyncio.shield(self._close_task)
            return
        self._closing = True
        self._close_task = asyncio.create_task(
            self._close_impl(current), name="native-simulation-close",
        )
        if current is not self._close_task:
            await asyncio.shield(self._close_task)

    async def _close_impl(self, initiator: asyncio.Task | None) -> None:
        current = asyncio.current_task()
        tasks = (self._expiry_task, self._active_turn, self._start_task)
        for task in tasks:
            if (
                task is not None
                and task not in (current, initiator)
                and not task.done()
            ):
                task.cancel()
        others = [
            task for task in tasks
            if task is not None and task not in (current, initiator)
        ]
        try:
            if others:
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                        await asyncio.gather(*others, return_exceptions=True)
                except TimeoutError:
                    for task in others:
                        if not task.done():
                            task.cancel()

            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await self.host.close()
            except BaseException:
                # Cleanup stays bounded; never echo provider/host details.
                pass
        finally:
            self._closed = True
            self._closing = True
            self._messages.clear()
            self._variables.clear()
            self.registry.abandon(self.session_id, self.owner_user_id)


def _consume_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:
        pass

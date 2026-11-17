"""Session-owned, one-use response samples for the native simulation host."""

import asyncio
from copy import deepcopy
import json
import math
import re
import uuid


_MAX_SAMPLE_BYTES = 65_536
_MAX_JSON_DEPTH = 64
_MAX_REQUESTS = 128
_MAX_EFFECTS = 128
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MISSING = object()
_EFFECT_KINDS = frozenset({
    "api_request", "integration", "tool_api", "mcp",
    "send_sms", "send_email", "record_create", "record_update",
    "transfer", "mcp_read",
})


class NativePreviewError(ValueError):
    """Stable, payload-free native preview coordination error."""

    _CODES = {
        "preview_busy", "preview_budget", "preview_closed",
        "preview_expired", "preview_request_mismatch",
        "preview_response_invalid", "preview_scope_invalid",
    }

    def __init__(self, code):
        self.code = code if code in self._CODES else "preview_response_invalid"
        super().__init__(self.code)


def _copy_json(value):
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_SAMPLE_BYTES:
            raise ValueError
        return _validate_json_tree(json.loads(encoded))
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise NativePreviewError("preview_response_invalid") from None


def _validate_json_tree(value):
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("json_depth")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif current is None or type(current) in {str, bool, int}:
            continue
        elif type(current) is float:
            if not math.isfinite(current):
                raise ValueError("json_number")
        else:
            raise ValueError("json_type")
    return value


def _reject_json_constant(_value):
    raise ValueError("json_constant")


def _parse_json_text(value):
    if not isinstance(value, str):
        raise NativePreviewError("preview_response_invalid")
    try:
        encoded = value.encode("utf-8")
        if len(encoded) > _MAX_SAMPLE_BYTES:
            raise ValueError("json_size")
        parsed = json.loads(value, parse_constant=_reject_json_constant)
        return _validate_json_tree(parsed)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise NativePreviewError("preview_response_invalid") from None


def _response_error_type(status):
    if status == 0:
        return "network_error"
    if 200 <= status < 300:
        return None
    if status in {401, 403}:
        return "auth_error"
    if status == 404:
        return "not_found"
    if status >= 500:
        return "server_error"
    return "validation_error"


class NativePreviewResponse:
    """Detached bounded HTTP-style response sample; never carries config."""

    __slots__ = ("_status_code", "_data", "_success", "_error_type")

    def __init__(
        self, *, status_code=200, data=_MISSING, data_json=_MISSING,
        success=None, error_type=None,
    ):
        if (
            type(status_code) is not int
            or status_code != 0 and not 200 <= status_code <= 599
        ):
            raise NativePreviewError("preview_response_invalid")
        inferred = _response_error_type(status_code)
        inferred_success = inferred is None
        if success is not None and (
            type(success) is not bool or success != inferred_success
        ):
            raise NativePreviewError("preview_response_invalid")
        if error_type is not None and (
            not isinstance(error_type, str)
            or error_type != inferred
        ):
            raise NativePreviewError("preview_response_invalid")
        if (data is _MISSING) == (data_json is _MISSING):
            raise NativePreviewError("preview_response_invalid")
        self._status_code = status_code
        self._data = (
            _copy_json(data) if data is not _MISSING
            else _parse_json_text(data_json)
        )
        self._success = inferred_success
        self._error_type = inferred

    @property
    def status_code(self):
        return self._status_code

    @property
    def data(self):
        return deepcopy(self._data)

    @property
    def success(self):
        return self._success

    @property
    def error_type(self):
        return self._error_type


class NativeActionPreview:
    """One active sample Future and bounded effect metadata for one session."""

    def __init__(
        self, *, on_change=None, timeout=120.0, max_requests=_MAX_REQUESTS,
    ):
        if (
            on_change is not None and not callable(on_change)
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0 or timeout > 300
            or type(max_requests) is not int or not 1 <= max_requests <= _MAX_REQUESTS
        ):
            raise NativePreviewError("preview_scope_invalid")
        self._on_change = on_change
        self._timeout = float(timeout)
        self._max_requests = max_requests
        self._requests = 0
        self._pending = None
        self._closed = False
        self._effects = []
        self._records = {}
        self._context_provider = None

    async def request(self, *, node_id, source_kind, scope, current_scope=None):
        if self._closed:
            raise NativePreviewError("preview_closed")
        if (
            not isinstance(node_id, str) or not _SAFE_ID.fullmatch(node_id)
            or not isinstance(source_kind, str) or source_kind not in {
                "http", "integration", "tool", "mcp", "record", "transfer",
                "mcp_read", "send_sms", "send_email",
            }
            or not isinstance(scope, tuple) or not scope or len(scope) > 8
            or any(not isinstance(item, str) or not item or len(item) > 256 for item in scope)
            or current_scope is not None and not callable(current_scope)
        ):
            raise NativePreviewError("preview_scope_invalid")
        if self._pending is not None:
            raise NativePreviewError("preview_busy")
        if self._requests >= self._max_requests:
            raise NativePreviewError("preview_budget")

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending = {
            "request_id": uuid.uuid4().hex,
            "node_id": node_id,
            "source_kind": source_kind,
            "scope": tuple(scope),
            "current_scope": current_scope,
            "future": future,
            "expires_at": loop.time() + self._timeout,
        }
        self._requests += 1
        self._pending = pending
        self._changed()
        try:
            async with asyncio.timeout(self._timeout):
                return await future
        except TimeoutError:
            raise NativePreviewError("preview_expired") from None
        finally:
            if self._pending is pending:
                self._pending = None
                if not future.done():
                    future.cancel()
                self._changed()

    def submit(self, request_id, response):
        pending = self._pending
        if (
            self._closed or pending is None
            or not isinstance(request_id, str)
            or request_id != pending["request_id"]
            or pending["future"].done()
        ):
            raise NativePreviewError("preview_request_mismatch")
        current_scope = pending["current_scope"]
        if current_scope is not None:
            try:
                still_current = tuple(current_scope()) == pending["scope"]
            except Exception:
                still_current = False
            if not still_current:
                self._pending = None
                if not pending["future"].done():
                    pending["future"].set_exception(
                        NativePreviewError("preview_request_mismatch"),
                    )
                self._changed()
                raise NativePreviewError("preview_request_mismatch")
        if not isinstance(response, NativePreviewResponse):
            try:
                response = NativePreviewResponse(**response)
            except (TypeError, ValueError):
                raise NativePreviewError("preview_response_invalid") from None
        pending["future"].set_result(response)
        self._changed()

    def snapshot(self):
        pending = self._pending
        if (
            pending is None or self._closed
            or pending["future"].done()
        ):
            return None
        remaining = max(0, pending["expires_at"] - asyncio.get_running_loop().time())
        return {
            "request_id": pending["request_id"],
            "node_id": pending["node_id"],
            "source_kind": pending["source_kind"],
            "expires_in_seconds": max(1, int(remaining + 0.999)),
        }

    @property
    def effects(self):
        return deepcopy(self._effects)

    def set_on_change(self, callback):
        if callback is not None and not callable(callback):
            raise NativePreviewError("preview_scope_invalid")
        self._on_change = callback

    def set_context_provider(self, callback):
        """Bind private live controller context; never include it in snapshots."""
        if callback is not None and not callable(callback):
            raise NativePreviewError("preview_scope_invalid")
        self._context_provider = callback

    def active_context(self):
        if self._closed or self._context_provider is None:
            raise NativePreviewError("preview_scope_invalid")
        value = self._context_provider()
        if (
            not isinstance(value, tuple) or len(value) != 3
            or not callable(getattr(value[0], "config", None))
            or not isinstance(value[1], dict)
            or not isinstance(value[2], tuple) or not 1 <= len(value[2]) <= 7
            or any(not isinstance(item, str) or not item or len(item) > 256 for item in value[2])
        ):
            raise NativePreviewError("preview_scope_invalid")
        return value

    def record_effect(self, kind, node_id):
        if (
            self._closed or kind not in _EFFECT_KINDS
            or not isinstance(node_id, str) or not _SAFE_ID.fullmatch(node_id)
            or len(self._effects) >= _MAX_EFFECTS
        ):
            raise NativePreviewError("preview_response_invalid")
        self._effects.append({
            "kind": kind, "node_id": node_id, "simulated": True,
        })
        self._changed()

    @staticmethod
    def _record_key(node_id, scope):
        if (
            not isinstance(node_id, str) or not _SAFE_ID.fullmatch(node_id)
            or not isinstance(scope, tuple) or len(scope) > 8
            or any(not isinstance(item, str) or not item or len(item) > 256 for item in scope)
        ):
            raise NativePreviewError("preview_scope_invalid")
        return scope, node_id

    def get_record(self, node_id, *, scope=()):
        value = self._records.get(self._record_key(node_id, scope))
        return deepcopy(value) if value is not None else None

    def save_record(self, node_id, record_type_id, data, status, *, scope=()):
        if (
            self._closed or not isinstance(node_id, str)
            or not _SAFE_ID.fullmatch(node_id)
            or not isinstance(record_type_id, str) or not record_type_id
            or not isinstance(data, dict)
        ):
            raise NativePreviewError("preview_response_invalid")
        snapshot = _copy_json({
            "record_type_id": record_type_id, "data": data, "status": status,
        })
        key = self._record_key(node_id, scope)
        if key not in self._records and len(self._records) >= _MAX_EFFECTS:
            raise NativePreviewError("preview_budget")
        self._records[key] = snapshot
        self._changed()

    def close(self):
        if self._closed:
            return
        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending["future"].done():
            pending["future"].cancel()
        self._effects.clear()
        self._records.clear()
        self._context_provider = None
        self._changed()

    def _changed(self):
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass


__all__ = [
    "NativeActionPreview", "NativePreviewError", "NativePreviewResponse",
]

"""Small immutable contracts between native graph control and scoped actions."""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping


_BRANCHES = frozenset({"success", "error", "not_found", "auth_error"})
_SAFE_REASON = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_MAX_BOUNDARY_BYTES = 250_000


def _snapshot(value, code):
    if not isinstance(value, Mapping):
        raise ValueError(code)
    try:
        encoded = json.dumps(
            dict(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) > _MAX_BOUNDARY_BYTES:
            raise ValueError(code)
        copy = json.loads(encoded)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise ValueError(code) from None
    if not isinstance(copy, dict):
        raise ValueError(code)
    return encoded


def _reason(value):
    if value is not None and (
        not isinstance(value, str) or not _SAFE_REASON.fullmatch(value)
    ):
        raise ValueError("native_failure_reason")
    return value


def copy_native_json(value):
    """Detach a bounded JSON output without guessing or coercing its type."""
    return json.loads(_snapshot({"value": value}, "native_json_value"))["value"]


@dataclass(frozen=True, init=False)
class NativeActionResult:
    """Only mapped action values and the explicitly configured LLM projection."""

    success: bool
    branch: str
    failure_reason: str | None
    _variables_json: str = field(repr=False)
    _llm_data_json: str = field(repr=False)

    def __init__(
        self, success, branch="success", variables=None, llm_data=None,
        failure_reason=None,
    ):
        if (
            type(success) is not bool or not isinstance(branch, str)
            or branch not in _BRANCHES
            or success != (branch == "success")
        ):
            raise ValueError("native_action_result")
        if failure_reason is not None and success:
            raise ValueError("native_action_result")
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "failure_reason", _reason(failure_reason))
        object.__setattr__(
            self, "_variables_json",
            _snapshot({} if variables is None else variables, "native_action_variables"),
        )
        object.__setattr__(
            self, "_llm_data_json",
            _snapshot({} if llm_data is None else llm_data, "native_action_projection"),
        )

    @property
    def variables(self) -> dict:
        return json.loads(self._variables_json)

    @property
    def llm_data(self) -> dict:
        return json.loads(self._llm_data_json)


@dataclass(frozen=True, init=False)
class NativeConfirmation:
    """Call-owned proof of explicit confirmation; tool arguments cannot create it."""

    node_id: str
    revision: int
    values_json: str = field(repr=False)
    confirmed_fields: tuple[str, ...]

    def __init__(self, node_id, revision, values_json, confirmed_fields):
        if not isinstance(node_id, str) or not node_id or type(revision) is not int or revision < 1:
            raise ValueError("native_confirmation")
        if isinstance(values_json, str):
            try:
                values = json.loads(values_json)
            except (TypeError, ValueError, RecursionError):
                raise ValueError("native_confirmation") from None
        else:
            values = values_json
        encoded = _snapshot(values, "native_confirmation")
        fields = tuple(confirmed_fields)
        if (
            not fields or len(fields) > 128 or len(fields) != len(set(fields))
            or any(not isinstance(item, str) or not item for item in fields)
        ):
            raise ValueError("native_confirmation")
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "values_json", encoded)
        object.__setattr__(self, "confirmed_fields", fields)

    def values(self) -> dict:
        return json.loads(self.values_json)


@dataclass(frozen=True)
class NativeTerminalResult:
    """Acceptance and actual terminal completion are distinct facts."""

    accepted: bool
    completed: bool = False
    failure_reason: str | None = None

    def __post_init__(self):
        if (
            type(self.accepted) is not bool or type(self.completed) is not bool
            or (self.completed and not self.accepted)
            or (self.accepted and self.failure_reason is not None)
        ):
            raise ValueError("native_terminal_result")
        _reason(self.failure_reason)


__all__ = [
    "NativeActionResult", "NativeConfirmation", "NativeTerminalResult",
    "copy_native_json",
]

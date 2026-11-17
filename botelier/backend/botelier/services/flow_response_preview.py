"""Preview the native mapping/projection on supplied JSON, without any I/O.

This module cannot execute a configured request, discover a connection, fetch
credentials, run a model or persist a result. The HTTP caller must authenticate
and check account permissions before returning a preview.
"""

from dataclasses import dataclass, field
from collections import deque
import json
import math
import re
from threading import Lock
from time import monotonic

from botelier.voice.flows.native_response_mapping import (
    NativeResponseMappingError,
    map_project_response,
    map_response_data,
    resolve_response_variables,
)


_VARIABLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z", re.ASCII)
_CONFIG_FIELDS = frozenset({
    "responseMapping", "responseVariables", "responseProjection",
})


class FlowResponsePreviewError(ValueError):
    """A fixed diagnostic with no sample data, URLs or credentials."""


class FlowPreviewBudget:
    """Bound this free CPU operation per account and process, without a DB.

    Never evict a live bucket to grant fresh quota. This is not an external-
    service or payment quota; this preview cannot dispatch either.
    """

    def __init__(self, *, limit=60, capacity=2048, clock=monotonic):
        self._limit = limit
        self._capacity = capacity
        self._clock = clock
        self._buckets = {}
        self._lock = Lock()

    def admit(self, account):
        now = self._clock()
        cutoff = now - 60
        with self._lock:
            for key, bucket in list(self._buckets.items()):
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    del self._buckets[key]
            bucket = self._buckets.get(account)
            if bucket is None:
                if len(self._buckets) >= self._capacity:
                    return False
                bucket = self._buckets[account] = deque()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True


@dataclass(frozen=True, slots=True)
class _Declaration:
    """The same explicit-declaration protocol consumed by native mapping."""

    key: str
    _data: str = field(repr=False)
    origin: str = "explicit"

    def data(self):
        return json.loads(self._data)


def _encode_bounded(value, *, limit=1_048_576, reason="preview_sample",
                    size_reason="preview_size"):
    """Stop encoding as soon as the total budget is exceeded, not afterward."""
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    )
    chunks = []
    size = 0
    try:
        for fragment in encoder.iterencode(value):
            chunk = fragment.encode("utf-8")
            size += len(chunk)
            if size > limit:
                raise FlowResponsePreviewError(size_reason)
            chunks.append(chunk)
    except FlowResponsePreviewError:
        raise
    except (TypeError, ValueError, RecursionError):
        raise FlowResponsePreviewError(reason) from None
    return b"".join(chunks)


def _copy_json(value, *, limit=1_048_576, reason="preview_sample"):
    seen = set()
    nodes = 0

    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 16_384:
            raise FlowResponsePreviewError(reason)
        kind = type(item)
        if kind in (dict, list):
            identity = id(item)
            if identity in seen or len(item) > 16_384:
                raise FlowResponsePreviewError(reason)
            seen.add(identity)
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str or len(key) > 1024:
                        raise FlowResponsePreviewError(reason)
                    walk(child, depth + 1)
            else:
                for child in item:
                    walk(child, depth + 1)
            seen.remove(identity)
        elif kind is str:
            if len(item) > limit:
                raise FlowResponsePreviewError("preview_size")
        elif kind is float:
            if not math.isfinite(item):
                raise FlowResponsePreviewError(reason)
        elif kind is int:
            if abs(item) > 10 ** 24:
                raise FlowResponsePreviewError(reason)
        elif kind not in (bool, type(None)):
            raise FlowResponsePreviewError(reason)

    walk(value, 0)
    return json.loads(_encode_bounded(value, limit=limit, reason=reason))


def _explicit_declarations(values):
    if type(values) not in (list, tuple) or len(values) > 128:
        raise FlowResponsePreviewError("preview_declarations")
    values = _copy_json(list(values), limit=65_536, reason="preview_declarations")
    declarations = []
    seen = set()
    for value in values:
        if type(value) is not dict:
            raise FlowResponsePreviewError("preview_declarations")
        key = value.get("key")
        if (
            type(key) is not str or not _VARIABLE.fullmatch(key) or key in seen
            or ("required" in value and type(value["required"]) is not bool)
        ):
            raise FlowResponsePreviewError("preview_declarations")
        seen.add(key)
        declarations.append(_Declaration(
            key, json.dumps(value, ensure_ascii=False, allow_nan=False),
        ))
    return tuple(declarations)


def _build_response_preview(sample, configuration, *, variable_declarations=()):
    """Build the detached preview and its bounded UTF-8 encoding in one worker.

    Missing inferred outputs are optional, matching the full native compiler.
    Explicit declarations preserve their actual required flag. Legacy ``text``
    metadata never coerces a provider array/object into text.
    """
    if type(configuration) is not dict or set(configuration) - _CONFIG_FIELDS:
        raise FlowResponsePreviewError("preview_configuration")
    config = _copy_json(configuration, limit=65_536, reason="preview_configuration")
    if config.get("responseMapping") is not None and type(config["responseMapping"]) is not dict:
        raise FlowResponsePreviewError("preview_configuration")
    if config.get("responseVariables") is not None and type(config["responseVariables"]) is not list:
        raise FlowResponsePreviewError("preview_configuration")
    declarations = _explicit_declarations(variable_declarations)
    source = _copy_json(sample)
    try:
        outputs = {item.variable_key for item in resolve_response_variables(config)}
        # The graph compiler normally enforces this before native mapping.
        # A standalone, half-authored sample has no compiled graph yet.
        if any(not _VARIABLE.fullmatch(key) for key in outputs):
            raise FlowResponsePreviewError("mapping_entry")
        # Aliases can multiply the same sample value. Check actual mapped data
        # before the shared projection performs any whole-value JSON encoding.
        scoped_variables = resolve_response_variables(
            config, declared_variables=outputs, variable_declarations=declarations,
        )
        budget_mapped = map_response_data(source, scoped_variables)
        _encode_bounded(
            {"mapped_variables": budget_mapped},
            reason="preview_result", size_reason="preview_result_size",
        )
        mapped, model = map_project_response(
            config, source, declared_variables=outputs,
            variable_declarations=declarations,
        )
    except NativeResponseMappingError as exc:
        raise FlowResponsePreviewError(str(exc)) from None
    result = {"mapped_variables": mapped, "llm_data": model}
    encoded = _encode_bounded(
        result, reason="preview_result", size_reason="preview_result_size",
    )
    return result, encoded


def preview_flow_response(sample, configuration, *, variable_declarations=()):
    """Return detached mappings and the exact native projection, within budget."""
    return _build_response_preview(
        sample, configuration, variable_declarations=variable_declarations,
    )[0]


def preview_flow_response_json(body):
    """Parse a sample-only HTTP envelope and return bounded, encoded JSON."""
    if type(body) is not bytes or len(body) > 1_048_576:
        raise FlowResponsePreviewError("preview_size")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError

    try:
        data = json.loads(
            body.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise FlowResponsePreviewError("preview_json") from None
    if (
        type(data) is not dict or not {"sample", "configuration"} <= set(data)
        or set(data) - {"sample", "configuration", "variableDeclarations"}
    ):
        raise FlowResponsePreviewError("preview_request")
    return _build_response_preview(
        data["sample"], data["configuration"],
        variable_declarations=data.get("variableDeclarations", []),
    )[1]

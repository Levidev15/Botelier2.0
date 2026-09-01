"""Flow Executor - Converts visual flows to Pipecat-compatible function schemas and executes them.

This module handles:
1. Loading flow configurations from the database
2. Converting flow nodes to LLM function schemas
3. Managing conversation state through the flow
4. Executing slot collection, API calls, and conditions
"""

import asyncio
import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from loguru import logger

from botelier.services.ssrf_safe_transport import SSRFSafeTransport

# Defense-in-depth (Task #534): a GET API node with identical arguments fired
# again within this window is treated as an accidental duplicate call (e.g. a
# racing tool call from an LLM provider that ignores parallel_tool_calls)
# rather than a legitimate re-check, and returns the just-completed result
# instead of re-hitting the endpoint. Short enough that a caller-driven re-run
# seconds later (e.g. "check again with different dates") is never suppressed.
GET_DEDUP_WINDOW_SECS: float = 3.0


class NodeType(str, Enum):
    INITIAL = "initial"
    MESSAGE = "message"
    COLLECT_SLOT = "collect_slot"
    COLLECT_FORM = "collect_form"
    API_REQUEST = "api_request"
    CAPABILITY = "capability"
    CONDITION = "condition"
    ROUTER = "router"
    CONFIRMATION = "confirmation"
    SET_VARIABLE = "set_variable"
    SAVE_RECORD = "save_record"
    TRANSFER = "transfer"
    END = "end"
    API_RESPONSE = "api_response"
    OPTION_PICKER = "option_picker"


# Action-node types whose LLM functions must be gated to the reachable flow
# position (the same way slot functions are). Exposing these on every turn —
# especially end_call_<id> and transfer_<id> — lets the model end or branch the
# call mid-collection, which is the root cause of premature hang-ups.
_ACTION_NODE_TYPES = frozenset(
    {
        NodeType.API_REQUEST,
        NodeType.CAPABILITY,
        NodeType.API_RESPONSE,
        NodeType.ROUTER,
        NodeType.CONFIRMATION,
        NodeType.SET_VARIABLE,
        NodeType.SAVE_RECORD,
        NodeType.TRANSFER,
        NodeType.END,
        NodeType.OPTION_PICKER,
    }
)

# Side-effect node types: nodes that mutate external state (persist records,
# call APIs, set variables, confirm data) and must NEVER be skipped.  END and
# TRANSFER are deliberately excluded — they are flow-control terminators, not
# data-mutating actions, and should never block the global end_call gate on
# their own.  Used by has_pending_side_effect_downstream().
_SIDE_EFFECT_NODE_TYPES = frozenset(
    {
        NodeType.API_REQUEST,
        NodeType.CAPABILITY,
        NodeType.CONFIRMATION,
        NodeType.SET_VARIABLE,
        NodeType.SAVE_RECORD,
        NodeType.OPTION_PICKER,
    }
)


class SlotType(str, Enum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    PHONE = "phone"
    EMAIL = "email"
    TIME = "time"
    CHOICE = "choice"


@dataclass
class FlowVariable:
    key: str
    type: SlotType
    description: str
    required: bool = True
    default_value: Optional[str] = None
    choices: Optional[list[str]] = None


@dataclass
class SlotConfig:
    variable_key: str
    prompt: str
    type: SlotType
    retry_prompt: Optional[str] = None
    max_retries: int = 3
    validation: Optional[dict] = None


@dataclass
class ResponseVariableMapping:
    variable_key: str
    json_path: str
    default_value: Optional[str] = None


@dataclass
class APIRequestConfig:
    method: str
    url: str
    headers: Optional[dict[str, str]] = None
    body_template: Optional[str] = None
    response_mapping: Optional[dict[str, str]] = None
    on_success: Optional[str] = None
    on_error: Optional[str] = None
    api_source: str = "custom"
    integration_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    timeout: int = 30
    retry_count: int = 2
    response_variables: list[ResponseVariableMapping] = field(default_factory=list)
    on_not_found: Optional[str] = None
    on_auth_error: Optional[str] = None


@dataclass
class ConditionConfig:
    variable: str
    operator: str
    value: str
    true_target: Optional[str] = None
    false_target: Optional[str] = None


@dataclass
class RouterOption:
    id: str
    value: str
    label: str


@dataclass
class RouterConfig:
    variable: str
    options: list[RouterOption]


@dataclass
class ConfirmationConfig:
    summary_template: str
    confirm_prompt: str
    edit_prompt: Optional[str] = None
    variables_to_confirm: list[str] = field(default_factory=list)
    allow_edit: bool = True


@dataclass
class SetVariableConfig:
    variable_key: str
    value_type: str
    value: str


@dataclass
class TransferConfig:
    phone_number: str
    pre_transfer_message: Optional[str] = None
    warm_transfer: bool = False


@dataclass
class FlowNode:
    id: str
    type: NodeType
    data: dict
    position: dict = field(default_factory=lambda: {"x": 0, "y": 0})


@dataclass
class FlowEdge:
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


@dataclass
class FlowConfig:
    initial_node: Optional[str]
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    variables: list[FlowVariable]
    global_prompt: Optional[str] = None
    # O(1) node lookup by ID — built once at parse time in __post_init__.
    # All code that previously scanned self.nodes with a for-loop should use
    # this index instead.  Use field(init=False) so it is never passed as a
    # constructor argument.
    _node_index: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        self._node_index = {node.id: node for node in self.nodes}


@dataclass
class CallFlowContext:
    """Caller facts shared by every flow executor on one call.

    Values are keyed by the flow variable key.  ``revisions`` makes caller
    corrections explicit: importing a newer caller-provided value always wins
    over a value collected (or imported) earlier in the call.
    """

    values: dict[str, Any] = field(default_factory=dict)
    revisions: dict[str, int] = field(default_factory=dict)
    _next_revision: int = 0
    _bound_slot_maps: list[tuple[dict[str, Any], dict[str, Any]]] = field(
        default_factory=list, repr=False
    )
    _executors: list[Any] = field(default_factory=list, repr=False)
    _notifying: bool = field(default=False, repr=False)
    _pending_changes: set[str] = field(default_factory=set, repr=False)

    def set_caller_value(self, key: str, value: Any) -> None:
        self.set_caller_values({key: value})

    def set_caller_values(self, values: dict[str, Any]) -> None:
        changed: set[str] = set()
        for key, value in values.items():
            if key not in self.values or self.values[key] != value:
                changed.add(key)
            self._next_revision += 1
            self.values[key] = value
            self.revisions[key] = self._next_revision
            for slots, _fallback in self._bound_slot_maps:
                slots[key] = value
        self._notify_executors(changed)

    def _notify_executors(self, changed: set[str]) -> None:
        """Atomically fan caller-fact changes through every bound executor."""
        self._pending_changes.update(changed)
        if self._notifying:
            return
        self._notifying = True
        try:
            while self._pending_changes:
                key = self._pending_changes.pop()
                removals: set[str] = set()
                for executor in tuple(self._executors):
                    removals.update(executor._on_shared_caller_fact_changed(key))
                for removed_key in removals:
                    if removed_key not in self.values:
                        continue
                    self.values.pop(removed_key, None)
                    self.revisions.pop(removed_key, None)
                    for slots, fallback in self._bound_slot_maps:
                        if removed_key in fallback:
                            slots[removed_key] = fallback[removed_key]
                        else:
                            slots.pop(removed_key, None)
                    self._pending_changes.add(removed_key)
        finally:
            self._notifying = False
        # Persist every executor's independently rewound node/local state. This
        # is best-effort and deliberately scheduled only after the whole
        # notification/removal transaction is complete.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for executor in tuple(self._executors):
            # Cancel-and-replace: if an earlier notify already scheduled a
            # snapshot task that hasn't run yet, cancel it — the new task will
            # capture more-current state. If the task has already started
            # writing (to_thread in flight), cancellation is a no-op for the
            # thread itself, but handle_function_call also cancels the task
            # before its own authoritative write, so the two writes capture the
            # same-generation state and last-write-wins is safe.
            existing = getattr(executor, "_pending_notify_snapshot", None)
            if existing is not None and not existing.done():
                existing.cancel()
            task = loop.create_task(executor._snapshot_state())
            # Guard with hasattr so non-FlowExecutor registrants are unaffected.
            if hasattr(executor, "_pending_notify_snapshot"):
                executor._pending_notify_snapshot = task

    def register_executor(self, executor: Any) -> None:
        if not any(bound is executor for bound in self._executors):
            self._executors.append(executor)

    def restore_caller_value(self, key: str, value: Any, revision: int) -> None:
        """Restore an explicit fact without manufacturing a newer revision."""
        if revision < self.revisions.get(key, -1):
            return
        changed = key not in self.values or self.values[key] != value
        self.values[key] = value
        self.revisions[key] = revision
        self._next_revision = max(self._next_revision, revision)
        for slots, _fallback in self._bound_slot_maps:
            slots[key] = value
        if changed:
            self._notify_executors({key})

    def remove_caller_value(self, key: str) -> None:
        if key in self.values:
            self._pending_changes.add(key)
            self.values.pop(key, None)
            self.revisions.pop(key, None)
            for slots, fallback in self._bound_slot_maps:
                if key in fallback:
                    slots[key] = fallback[key]
                else:
                    slots.pop(key, None)
            self._notify_executors(set())

    def bind(self, slots: dict[str, Any], fallback: dict[str, Any]) -> None:
        if not any(bound is slots for bound, _ in self._bound_slot_maps):
            self._bound_slot_maps.append((slots, fallback))
        slots.update(self.values)


_PLACEHOLDER_PATTERNS = frozenset(
    {"[not provided]", "not provided", "n/a", "none", "unknown", ""}
)


def _is_valid_new_value(value: Any) -> bool:
    """Return True only when *value* is a real replacement the caller stated.

    Rejects falsy values and common LLM placeholder strings that indicate the
    caller flagged a field for correction without actually supplying a new value.
    """
    if not value and value != 0:
        return False
    return str(value).strip().lower() not in _PLACEHOLDER_PATTERNS


def _normalize_slot_validation(validation: Optional[dict]) -> dict:
    """Normalize every editor/runtime cross-field spelling in one place."""
    normalized = dict(validation or {})
    cross_field = normalized.get("crossFieldCheck") or normalized.get(
        "cross_field_check"
    )
    compare_with = None
    operator = None
    error_message = None
    if isinstance(cross_field, dict):
        compare_with = cross_field.get("compareWith") or cross_field.get(
            "compare_with"
        )
        operator = cross_field.get("operator")
        error_message = cross_field.get("errorMessage") or cross_field.get(
            "error_message"
        )
    compare_with = (
        compare_with
        or normalized.get("afterDateVariable")
        or normalized.get("after_date_variable")
    )
    if compare_with:
        normalized["cross_field_variable"] = compare_with
        normalized["cross_field_operator"] = (operator or "after").lower()
        if error_message:
            normalized["cross_field_error"] = error_message
    return normalized


def _cross_field_constraint(
    validation: dict, variables: dict[str, Any]
) -> Optional[str]:
    compare_var = validation.get("cross_field_variable")
    if not compare_var:
        return None
    operator = validation.get("cross_field_operator", "after")
    compare_value = variables.get(compare_var)
    # Use `is not None` so falsy-but-valid values (0, False, "") display
    # correctly instead of being replaced by the variable name.
    display = compare_value if compare_value is not None else compare_var
    return f"must be {operator} {display}"


class FlowState:
    """Tracks the state of a conversation flow execution."""

    def __init__(
        self, flow_config: FlowConfig, call_context: Optional[CallFlowContext] = None
    ):
        self.flow_config = flow_config
        self.call_context = call_context or CallFlowContext()
        self.current_node_id: Optional[str] = flow_config.initial_node
        # Flow-local working state. Defaults and derived/API outputs live only
        # here; the shared context overlays explicit caller facts separately.
        # Use `is not None` so falsy-but-valid defaults (0, False, "") are
        # preserved instead of being silently dropped from the working state.
        self.default_slots: dict[str, Any] = {
            var.key: var.default_value
            for var in flow_config.variables
            if var.default_value is not None
        }
        self.collected_slots: dict[str, Any] = dict(self.default_slots)
        self.pending_slot: Optional[str] = None
        self.retry_count: int = 0
        self.is_complete: bool = False
        # Structural signal only: true once we've landed on a node with no
        # outgoing edge (the designed graph has nothing further from here).
        # Deliberately distinct from ``is_complete``, which means "a terminal
        # action (end_call/transfer) has actually executed" and gates
        # idempotency in _handle_end_call. Conflating the two (Task #534
        # completion-review fix) made advance_to() mark is_complete=True the
        # instant we merely *landed* on an END/TRANSFER node — before the
        # handler that actually fires the end/transfer callback ever ran —
        # so that handler's own idempotency guard swallowed itself as a
        # "duplicate" and the call never actually ended or transferred.
        self.graph_exhausted: bool = False
        self.transfer_requested: bool = False
        self.transfer_target: Optional[str] = None
        # Records created by SAVE_RECORD nodes during this session, keyed by
        # node id → record id. Lets post-save variable changes (confirm/edit
        # corrections) sync back into the already-saved record instead of the
        # record silently going stale. Persisted inside the flow_sessions
        # snapshot (under the reserved "_saved_records" key) so it survives a
        # websocket dropout / reconnect on a fresh worker.
        self.saved_records: dict[str, str] = {}
        self.derived_slots: set[str] = set()

        self.call_context.bind(self.collected_slots, self.default_slots)

    def get_variable(self, key: str) -> Optional[Any]:
        return self.collected_slots.get(key)

    def set_variable(self, key: str, value: Any) -> None:
        if key in self.call_context.values:
            return
        self.collected_slots[key] = value
        self.derived_slots.add(key)

    def get_current_node(self) -> Optional[FlowNode]:
        if not self.current_node_id:
            return None
        # O(1) via the index built in FlowConfig.__post_init__
        return self.flow_config._node_index.get(self.current_node_id)

    def get_next_node(self, from_node_id: str, handle: Optional[str] = None) -> Optional[FlowNode]:
        """Find the next node connected via edges."""
        for edge in self.flow_config.edges:
            if edge.source == from_node_id:
                if handle and edge.source_handle != handle:
                    continue
                # O(1) via the index — eliminates the inner O(N) node scan
                return self.flow_config._node_index.get(edge.target)
        return None

    def get_unlabelled_next_node(self, from_node_id: str) -> Optional[FlowNode]:
        """Find a legacy/default edge with no explicit source handle.

        This differs from ``get_next_node(..., handle=None)``, which means
        "accept any edge" and can accidentally select a different labelled
        branch solely because it appeared first in the graph.
        """
        for edge in self.flow_config.edges:
            if edge.source == from_node_id and not edge.source_handle:
                return self.flow_config._node_index.get(edge.target)
        return None

    def has_outgoing_edge(self, node_id: str) -> bool:
        """Whether any edge leaves ``node_id`` — i.e. the graph continues from here."""
        return any(edge.source == node_id for edge in self.flow_config.edges)

    def advance_to(self, node_id: str) -> None:
        """Move to a specific node.

        After moving, immediately resolve any CONDITION node landed on so the
        flow never *sits* on a decision node: it evaluates the condition against
        collected variables and follows the matching branch. CONDITION nodes
        expose no tool, so the tool-call-driven engine would otherwise stall
        here. Resolution is deterministic and identical in live calls and the
        simulator.
        """
        # Guard: advancing to a nonexistent node silently corrupts flow state.
        # Log a warning so misconfigured edges are visible in logs, then still
        # let the safe-fail path below mark graph_exhausted rather than pointing
        # at a ghost node.
        if node_id not in self.flow_config._node_index:
            logger.warning(
                f"advance_to: node {node_id!r} does not exist in this flow "
                f"(current_node_id={self.current_node_id!r}, "
                f"{len(self.flow_config.nodes)} nodes configured) — "
                "keeping current position and marking flow exhausted"
            )
            self.graph_exhausted = True
            return

        self.current_node_id = node_id
        self.pending_slot = None
        self.retry_count = 0
        self._resolve_conditions()

        # Exhausted-flow guardrail (Task #534): a node with no outgoing edge is
        # the end of the designed graph, whatever type it is (a MESSAGE dead
        # end, a CONFIRMATION with no configured next step, etc). Without this,
        # is_complete only ever became True via the explicit END/error-retry
        # paths, so a flow that simply ran off the end of its graph stayed
        # "active" forever — the LLM had no signal the flow was over and could
        # go on claiming actions (bookings, transfers) that never happened,
        # and the durable flow_sessions snapshot never reached a terminal
        # status. END/TRANSFER nodes are almost always themselves outgoing-
        # edge-less, so this naturally covers them without special-casing.
        if self.current_node_id and not self.has_outgoing_edge(self.current_node_id):
            self.graph_exhausted = True

    def _resolve_conditions(self) -> None:
        """Follow CONDITION branches until landing on a non-condition node.

        Deterministic, server-side evaluation (no LLM, no tool). Guards against
        cycles with a hop cap of the node count.
        """
        max_hops = len(self.flow_config.nodes) + 1
        for _ in range(max_hops):
            node = self.get_current_node()
            if not node or node.type != NodeType.CONDITION:
                return
            target = _condition_target_id(
                self.flow_config, node, self.collected_slots
            )
            if not target or target == self.current_node_id:
                return
            self.current_node_id = target

        # If we exhausted the hop cap without landing on a non-CONDITION node,
        # the graph has a condition cycle.  Mark the flow as exhausted so the
        # engine does not silently stall on this node forever.
        logger.error(
            f"_resolve_conditions: condition cycle detected — exceeded {max_hops} "
            f"hops at node {self.current_node_id!r}; marking flow exhausted."
        )
        self.graph_exhausted = True


def _format_variable_value(value: Any) -> str:
    """Render a variable value for prompt/message interpolation.

    Lists of scalars become a comma-separated string; lists/dicts containing
    objects become compact JSON the downstream LLM can read. Everything else
    falls back to ``str()``.
    """
    if isinstance(value, list):
        if all(not isinstance(v, (list, dict)) for v in value):
            return ", ".join(str(v) for v in value)
        return json.dumps(value, separators=(",", ":"), default=str)
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)


_HTML_TAG_RE = re.compile(r"<[^>]+>")

_SPEAKABLE_NAME_KEYS = (
    "name",
    "title",
    "label",
    "rate_plan_name",
    "room_name",
    "room_type_name",
    "plan_name",
    "description",
)


def _speakable_variable_value(value: Any) -> str:
    """Render a variable value as natural spoken text, never raw JSON/HTML.

    Task #547 — collect-slot prompts are spoken verbatim by TTS on live calls
    (the direct-speech guarantee), so a prompt interpolating a mapped API
    result (e.g. a rate-plans array of objects) must become a short, speakable
    summary (names joined with "and"), not compact JSON with codes,
    restrictions objects and HTML descriptions read aloud to the caller.
    """

    def _name_of(item: Any) -> str:
        if isinstance(item, dict):
            for key in _SPEAKABLE_NAME_KEYS:
                v = item.get(key)
                if isinstance(v, str) and v.strip():
                    return _HTML_TAG_RE.sub(" ", v).strip()
            # No name-like field: fall back to the first scalar string value.
            for v in item.values():
                if isinstance(v, str) and v.strip():
                    return _HTML_TAG_RE.sub(" ", v).strip()
            return ""
        if isinstance(item, list):
            return _join_spoken([_name_of(v) for v in item])
        return _HTML_TAG_RE.sub(" ", str(item)).strip()

    def _join_spoken(parts: list[str]) -> str:
        parts = [p for p in parts if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]

    if isinstance(value, (list, dict)):
        spoken = _name_of(value)
        # Structured data with nothing speakable: omit rather than dump JSON.
        return spoken
    return _HTML_TAG_RE.sub(" ", str(value)).strip()


def _get_by_path(value: Any, path: str) -> Any:
    """Resolve a dot-notation path against a nested dict/list structure.

    Used by the OPTION_PICKER handler to pull a field out of the caller's
    selected item (e.g. ``"rate.code"`` or ``"images.0.url"``). Each segment
    is tried as a dict key first, then — only when the segment is a plain
    integer — as a list index. Returns ``None`` the moment any segment is
    missing/out of range rather than raising, since a mapped offer's fields
    are inherently optional per-item and a missing field must simply write
    ``None`` into the bound variable, not blow up the whole selection.
    """
    if not path:
        return value
    current = value
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        elif isinstance(current, list):
            if not segment.lstrip("-").isdigit():
                return None
            index = int(segment)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def substitute_variables(
    template: str, variables: dict[str, Any], speakable: bool = False
) -> str:
    """Replace {{variable_name}} placeholders with actual values.

    ``speakable=True`` is for text that is spoken verbatim to a caller
    (collect prompts, configured success messages): structured values are
    summarized into natural speech instead of compact JSON. Leave it False for
    request/body/set-variable templates and LLM-context instructions, which
    need the full data.
    """

    def replace_var(match):
        var_name = match.group(1)
        value = variables.get(var_name)
        if value is None:
            return match.group(0)
        if speakable:
            return _speakable_variable_value(value)
        return _format_variable_value(value)

    return re.sub(r"\{\{(\w+)\}\}", replace_var, template)


def _build_api_voice_result(success_msg: str, extracted_vars: dict[str, Any]) -> str:
    """Fallback voice result for API nodes whose ``responseInstructions`` is blank.

    Returns *success_msg* plus the display-only mapped-response projection. The
    original values remain unchanged in flow state; this is solely what the LLM
    reads when no designer-authored Voice result script is configured.
    """
    if not extracted_vars:
        return success_msg
    from botelier.services.response_projection import format_mapped_response

    projection = format_mapped_response(extracted_vars)
    return f"{success_msg}.\n{projection}" if projection else success_msg


def _coerce_number(value: Any) -> Optional[float]:
    """Best-effort numeric coercion for comparison operators."""
    try:
        return float(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _evaluate_condition(operator: str, actual: Any, expected: Any) -> bool:
    """Evaluate a CONDITION node's operator against collected data.

    Deterministic and safe — a fixed whitelist of operators, never ``eval``.
    Unknown operators evaluate to False (the 'false' branch) so a misconfigured
    node fails closed rather than branching unpredictably.
    """
    op = (operator or "").strip().lower()

    def _is_empty(v: Any) -> bool:
        if v is None:
            return True
        # Native Python collections: [], {}, set()
        if isinstance(v, (list, dict, set, tuple)):
            return len(v) == 0
        s = str(v).strip()
        # Serialized empty collections stored as strings
        return s in ("", "[]", "{}", "set()", "null", "none")

    if op == "is_empty":
        return _is_empty(actual)
    if op == "is_not_empty":
        return not _is_empty(actual)

    if op in ("greater_than", "less_than"):
        a_num = _coerce_number(actual)
        e_num = _coerce_number(expected)
        if a_num is None or e_num is None:
            a_str = "" if actual is None else str(actual).strip()
            e_str = "" if expected is None else str(expected).strip()
            return a_str > e_str if op == "greater_than" else a_str < e_str
        return a_num > e_num if op == "greater_than" else a_num < e_num

    a_low = ("" if actual is None else str(actual).strip()).lower()
    e_low = ("" if expected is None else str(expected).strip()).lower()
    if op == "equals":
        return a_low == e_low
    if op == "not_equals":
        return a_low != e_low
    if op == "contains":
        return e_low in a_low

    return False


def _condition_target_id(
    flow_config: "FlowConfig", node: "FlowNode", collected_slots: dict
) -> Optional[str]:
    """Resolve which node a CONDITION node branches to.

    Evaluates the condition against ``collected_slots`` and returns the target
    node id of the matching branch. Branch wiring is resolved via the editor's
    ``sourceHandle`` ("true"/"false") first, then the config's
    ``trueTarget``/``falseTarget``, then a single unlabelled edge as a last
    resort. Returns ``None`` when no branch is wired.
    """
    cond = node.data.get("condition", {}) or {}
    variable = cond.get("variable")
    operator = cond.get("operator", "equals")
    expected_raw = cond.get("value", "")
    expected = (
        substitute_variables(str(expected_raw), collected_slots)
        if expected_raw
        else expected_raw
    )
    actual = collected_slots.get(variable) if variable else None

    result = _evaluate_condition(operator, actual, expected)
    handle = "true" if result else "false"

    for edge in flow_config.edges:
        if edge.source == node.id and edge.source_handle == handle:
            return edge.target

    target = cond.get("trueTarget") if result else cond.get("falseTarget")
    if target:
        return target

    for edge in flow_config.edges:
        if edge.source == node.id and not edge.source_handle:
            return edge.target

    return None


def parse_flow_config(config_dict: dict) -> FlowConfig:
    """Parse a raw flow config dict into typed FlowConfig.

    Malformed individual nodes, edges, or variables are skipped with a warning
    so one bad entry never aborts the entire flow parse.  Both ``KeyError``
    (missing required field) and ``ValueError`` (unknown enum value) are caught
    per-item; all other exceptions propagate.
    """
    nodes = []
    for node_data in config_dict.get("nodes", []):
        try:
            nodes.append(
                FlowNode(
                    id=node_data["id"],
                    type=NodeType(node_data.get("type", "message")),
                    data=node_data.get("data", {}),
                    position=node_data.get("position", {"x": 0, "y": 0}),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning(f"parse_flow_config: skipping malformed node {node_data!r}: {exc}")

    edges = []
    for edge_data in config_dict.get("edges", []):
        try:
            edges.append(
                FlowEdge(
                    id=edge_data["id"],
                    source=edge_data["source"],
                    target=edge_data["target"],
                    source_handle=edge_data.get("sourceHandle"),
                    target_handle=edge_data.get("targetHandle"),
                )
            )
        except KeyError as exc:
            logger.warning(f"parse_flow_config: skipping malformed edge {edge_data!r}: {exc}")

    variables = []
    for var_data in config_dict.get("variables", []):
        try:
            variables.append(
                FlowVariable(
                    key=var_data["key"],
                    type=SlotType(var_data.get("type", "text")),
                    description=var_data.get("description", ""),
                    required=var_data.get("required", True),
                    default_value=var_data.get("defaultValue"),
                    choices=var_data.get("choices"),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning(f"parse_flow_config: skipping malformed variable {var_data!r}: {exc}")

    # Accept both snake_case (legacy) and camelCase (current editor) for the
    # initial node so configs saved by either convention load correctly.
    initial_node = (
        config_dict.get("initial_node")
        or config_dict.get("initialNode")
    )

    return FlowConfig(
        initial_node=initial_node,
        nodes=nodes,
        edges=edges,
        variables=variables,
        global_prompt=config_dict.get("global_prompt") or config_dict.get("globalPrompt"),
    )


def build_flow_behavioral_rules(current_date: str, has_past_date_slot: bool) -> str:
    """Build the shared, flow-execution behavioural rules block.

    This is the channel-agnostic guidance that applies whenever a structured
    conversation flow is active: date handling, no-markdown (voice), speak
    verbatim, collect-in-order, and answer-KB-mid-flow-then-resume.

    ``current_date`` is date-only (no wall-clock time) on purpose: the only
    consumer is the year-inference rule below, and keeping it date-stable lets
    the whole live system prompt stay prompt-cacheable within a calendar day
    (see call_handler `_create_agent_config` Task #106 caching note).

    Injected exactly once per call even when several flow tools are present, so
    it lives at module scope rather than being duplicated per flow.
    """
    if has_past_date_slot:
        date_year_rule = (
            "6. When a caller provides a date without a year (e.g., \"Dec 12th\"), "
            "interpret it based on the constraint for that specific field. "
            f"If the field requires future dates, use the next occurrence after today ({current_date}). "
            "If the field allows past dates, interpret it as the most recent past occurrence that makes contextual sense."
        )
    else:
        date_year_rule = (
            "6. When a customer provides a date without a year (e.g., \"Dec 12th\"), "
            f"interpret it as the next occurrence after today ({current_date}). Never assume a past year."
        )

    return f"""Current date: {current_date}

You have access to a structured conversation flow (started when the caller wants to complete the corresponding task).
CRITICAL: the moment the caller expresses intent matching a flow (e.g. wanting to make a booking), call that flow's start function IMMEDIATELY — in that same turn, before asking the caller anything. Never interview the caller for flow details (dates, party size, etc.) before starting the flow; pass along only what they already volunteered and let the flow ask for the rest in its designed order.
Once a flow is active, follow these guidelines:
1. Collect information in the order specified by the flow
2. Use the provided functions to progress through the flow
3. Follow the CURRENT NODE instructions - they tell you what to say or ask
4. When instructions say "Say exactly", speak that text verbatim. When they say "Guidance" or "naturally", you may phrase it in your own words while keeping the meaning.
5. If the customer provides information proactively, acknowledge and record it
{date_year_rule}
7. For number fields, respect the minimum and maximum limits specified.
8. IMPORTANT: Never use markdown formatting (no asterisks, bold, bullets, etc). This is a voice conversation - speak naturally without any special formatting.
9. When a function returns a "speak_exactly" field, speak that text verbatim without paraphrasing.
10. If the caller asks a question mid-flow, answer it briefly (use the knowledge base if one is available), then continue collecting where you left off. Do not restart the flow or lose your place.
11. When a function result includes "node_instructions", follow those instructions when composing your very next reply — they are the flow designer's directions for the step that just completed (e.g. how to confirm the value you just collected).
12. When a function result includes "current_node_context", treat it exactly like CURRENT NODE instructions: it tells you what to say or ask next.
13. Never read raw JSON, code, HTML, field names, or internal ID codes aloud. When a function result contains structured data (lists of rooms, rate plans, etc.), present only the caller-relevant values — names, dates, prices — in short natural sentences.
14. When stating a price from a function result, say the amount exactly as returned — it is the TOTAL for the whole stay unless the field name explicitly says nightly/daily. Never multiply a price by the number of nights or recompute it. State that it is the total, and say the currency as a word ("three hundred twenty euros"), never a code like "EUR".
15. Short transition lines such as "I've completed that check" are spoken automatically by the system when needed. Never say them yourself, repeat them, or adopt them as your own phrasing — go straight to the substance of your reply."""


class FlowExecutor:
    """Executes a conversation flow during a Pipecat call.

    The executor maintains state and provides methods that can be called
    by Pipecat's LLM function calling system.
    """

    def __init__(
        self,
        flow_config: FlowConfig,
        speak_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        transfer_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        end_call_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        db_session: Optional[Any] = None,
        account_id: Optional[str] = None,
        flow_tool_id: Optional[str] = None,
        call_sid: Optional[str] = None,
        escalation_target: Optional[str] = None,
        property_id: Optional[str] = None,
        session_factory: Optional[Callable] = None,
        call_context: Optional[CallFlowContext] = None,
        assistant_timezone: str = "UTC",
    ):
        self.flow_config = flow_config
        self.call_context = call_context or CallFlowContext()
        self.state = FlowState(flow_config, self.call_context)
        self.call_context.register_executor(self)
        self.assistant_timezone = assistant_timezone or "UTC"
        try:
            self._timezone = ZoneInfo(self.assistant_timezone)
        except ZoneInfoNotFoundError:
            logger.warning(
                f"Unknown assistant timezone {self.assistant_timezone!r}; using UTC"
            )
            self.assistant_timezone = "UTC"
            self._timezone = timezone.utc
        self.speak_callback = speak_callback
        self.transfer_callback = transfer_callback
        self.end_call_callback = end_call_callback
        self.db_session = db_session
        # session_factory is used on live voice calls where db_session=None
        # (the long-lived setup session is closed before the call starts).
        # Each DB operation opens its own short-lived session from the factory
        # and closes it in finally — mirroring the SAVE_RECORD pattern.
        # The simulator passes db_session directly and leaves session_factory=None.
        self.session_factory = session_factory
        self.account_id = account_id
        self.flow_tool_id = flow_tool_id
        self.call_sid = call_sid
        # Per-property isolation (Task #327). Resolved once at contact start from
        # the dialed number / assistant and carried through the whole session so
        # every integration resolution is scoped to (account_id, property_id).
        # None → legacy / account-only scoping.
        self.property_id = str(property_id) if property_id else None
        # Assistant-level "talk to a human" fallback number. When set, a slot that
        # exhausts its retries (with no wired fallback branch) escalates here
        # instead of dead-ending. None → escalation disabled (fail closed).
        self.escalation_target = escalation_target
        # Non-GET idempotency guard: prevents two concurrent requests (e.g. two
        # simultaneous POST /api/simulate/message or two voice pipeline turns) from
        # executing the same mutating API node (POST/PUT/PATCH/DELETE) twice in the
        # same session.  GET nodes are skipped — they are safe to repeat.
        #
        # _non_get_results: node_id → cached result dict for already-completed nodes.
        #   A second call returns this immediately without re-firing the endpoint.
        # _non_get_locks: node_id → asyncio.Lock that serialises concurrent callers.
        #   The winner executes; every waiter picks up the cached result afterward.
        self._non_get_results: dict[str, dict] = {}
        self._non_get_locks: dict[str, asyncio.Lock] = {}
        # Defense-in-depth (Task #534) — GET dedup guard. Disabling
        # parallel_tool_calls on the LLM service (engine.py) is the primary
        # fix for a model issuing two tool calls in one turn, but this is a
        # second, independent line of defense: it also catches a duplicate
        # GET that arrives near-simultaneously through some other path (a
        # provider that ignores parallel_tool_calls, a retried turn, etc).
        # Unlike the non-GET guard above this is intentionally short-lived —
        # GETs are legitimately re-run later in a session (e.g. re-checking
        # availability after the caller changes dates), so only calls with
        # identical arguments landing within GET_DEDUP_WINDOW_SECS of each
        # other are treated as the same accidental duplicate.
        # _get_locks: node_id → lock serialising concurrent callers for that node.
        # _get_recent: node_id → (monotonic_time, args_key, result) of the last
        #   completed call, consulted by a waiter that arrives while the winner
        #   is still running or just finished.
        self._get_locks: dict[str, asyncio.Lock] = {}
        self._get_recent: dict[str, tuple[float, str, dict]] = {}
        self._save_record_locks: dict[str, asyncio.Lock] = {}
        # Per-execute-node entry lock acquired in handle_function_call BEFORE
        # _turn_lock.  Serialises same-node execute_ calls at the outermost
        # level, which keeps the per-node inner dedup locks (_non_get_locks,
        # _get_locks) single-holder and prevents an AB-BA deadlock:
        #   A holds inner dedup lock, releases _turn_lock via _suspend_turn_lock
        #   B acquires _turn_lock, waits for inner dedup lock → neither proceeds.
        # Ordering invariant (never reversed): per-node entry lock → _turn_lock.
        self._execute_entry_locks: dict[str, asyncio.Lock] = {}
        # Calls without a stable contact/session id cannot be deduplicated across
        # workers. Keep their fallback explicitly executor-scoped while still
        # protecting retries/concurrency within this executor.
        self._save_record_fallback_scope = uuid.uuid4().hex
        # Tracks whether the built-in confirm_details fallback (flows WITHOUT a
        # CONFIRMATION node) already got a positive confirmation. Once True the
        # fallback is no longer exposed, so the LLM can't loop back into
        # re-confirming already-collected info after the caller says "no thanks".
        self._details_confirmed = False
        # Task #543 — durable-snapshot gate. Every flow executor on a call is
        # registered with the shared CallFlowContext up front (so shared caller
        # facts can fan out), but only flows the caller has actually entered may
        # write flow_sessions rows. Without this gate, a caller-fact change in
        # one flow scheduled _snapshot_state() on EVERY registered executor,
        # persisting unrelated flows' sessions (at their first node, with the
        # shared facts bound into their slots) that a reconnect could resume.
        self._flow_started = False
        # Executor-wide turn lock — prevents two concurrent fast-mutating tool
        # turns from interleaving state changes (e.g. a dropout + reconnect that
        # delivers two collect calls simultaneously). ALL handlers (including
        # execute_ and save_record_) acquire it; execute_/save_record_ release
        # it during slow I/O via _suspend_turn_lock and reacquire after.  A
        # per-node entry lock (see _execute_entry_locks / _save_record_locks) is
        # always acquired BEFORE _turn_lock to prevent AB-BA deadlock.
        self._turn_lock: asyncio.Lock = asyncio.Lock()
        # Tracks the most-recent notify-driven snapshot task scheduled by
        # CallFlowContext._notify_executors. handle_function_call cancels it
        # before writing the authoritative post-dispatch snapshot so a delayed
        # task that captured pre-advance state cannot overwrite the newer one.
        self._pending_notify_snapshot: Optional[asyncio.Task] = None
        # Monotonic write-generation counter for snapshot ordering. Incremented
        # in the asyncio thread (single-writer) before each _snapshot_state
        # call; read in thread-pool workers to detect and skip stale writes.
        # CPython GIL makes int reads/writes effectively atomic across threads.
        self._snapshot_generation: int = 0
        # Thread-level lock that serialises _write_snapshot workers so the
        # stale-generation check and the DB write are an atomic unit — no two
        # workers can interleave their check-then-write on the same executor.
        self._snapshot_write_lock: threading.Lock = threading.Lock()

    @contextmanager
    def _borrow_db_session(self):
        """Yield a live DB session for a single operation.

        Simulator / request-scoped callers pass ``db_session`` at construction;
        the session is borrowed as-is (NOT closed) — the caller owns its lifecycle.

        Live voice calls set ``session_factory`` and leave ``db_session=None``
        because the long-lived setup session is closed before the call begins.
        A short-lived session is opened here, used, then closed in ``finally`` —
        identical to the SAVE_RECORD / track_tool_usage own-SessionLocal pattern.

        Yields ``None`` when neither is configured so callers can guard on
        truthiness without raising.
        """
        if self.db_session is not None:
            yield self.db_session
            return
        if self.session_factory is not None:
            _db = None
            try:
                _db = self.session_factory()
                yield _db
            finally:
                if _db is not None:
                    _db.close()
            return
        yield None

    @asynccontextmanager
    async def _suspend_turn_lock(self):
        """Release the executor turn lock during slow I/O and reacquire after.

        Used inside execute_, save_record_, transfer_, and end_call_ handlers
        so the lock guards only the fast state read/advance/write sections,
        while concurrent fast-mutating turns (collect_, route_, confirm_, etc.)
        can proceed during network waits without head-of-line blocking.

        Callers that currently hold ``self._turn_lock`` will release and
        reacquire it around the I/O.  When the lock is not held (e.g. a handler
        called directly in tests), the context is a no-op so the same handler
        code works safely in both paths.

        Callers MUST re-validate shared state immediately after the context
        exits because another turn may have mutated it during the I/O.
        """
        if not self._turn_lock.locked():
            # Lock is not held — no-op to support direct handler calls in tests.
            yield
            return
        self._turn_lock.release()
        try:
            yield
        finally:
            await self._turn_lock.acquire()

    # -- Durable session state (Task #330) ----------------------------------
    def _snapshot_key(self) -> Optional[tuple[str, str]]:
        """Return ``(session_key, tool_id)`` when this executor is snapshottable.

        Durable snapshots require a stable per-contact identifier (``call_sid``)
        and the flow tool id. Ephemeral contexts (e.g. the simulator, which
        keeps its own state) have no ``call_sid`` and are intentionally skipped.
        """
        if self.call_sid and self.flow_tool_id:
            return str(self.call_sid), str(self.flow_tool_id)
        return None

    async def _snapshot_state(self) -> None:
        """Persist current flow state to ``flow_sessions`` (best-effort).

        Written after every function call in an isolated transaction, decoupled
        from the business write path (last-write-wins, no locks). A failure here
        never affects the live call — the caller already has their result.
        """
        key = self._snapshot_key()
        if not key:
            return
        # Task #543 — never persist a session for a flow the caller has not
        # entered. Shared caller-fact fan-out schedules snapshots on every
        # registered executor; unstarted flows must stay ephemeral so an
        # unrelated flow's booking data never lands in their flow_sessions row.
        if not self._flow_started:
            return
        session_key, tool_id = key
        # Ride the saved-record map inside the collected_slots JSON under a
        # reserved "_saved_records" key so the record ids survive a reconnect
        # without any schema change. Popped back out on rehydrate; the reserved
        # key never lives in the in-memory collected_slots the LLM sees.
        slots_payload: dict[str, Any] = dict(self.state.collected_slots)
        if self.state.saved_records:
            slots_payload["_saved_records"] = self.state.saved_records
        if self._non_get_results:
            slots_payload["_non_get_results"] = self._non_get_results
        if self.state.derived_slots:
            slots_payload["_derived_slots"] = sorted(self.state.derived_slots)
        if self.call_context.revisions:
            slots_payload["_slot_revisions"] = self.call_context.revisions
            slots_payload["_slot_revision_counter"] = self.call_context._next_revision
        payload = {
            "account_id": str(self.account_id) if self.account_id else None,
            "property_id": self.property_id,
            "session_key": session_key,
            "tool_id": tool_id,
            "current_node_id": self.state.current_node_id,
            "collected_slots": json.dumps(slots_payload, default=str),
            "status": (
                "complete"
                if (self.state.is_complete or self.state.graph_exhausted)
                else "active"
            ),
        }
        # Increment the generation counter in the asyncio thread (single-writer)
        # before passing it to the thread-pool worker. The worker checks
        # _snapshot_generation inside _snapshot_write_lock before writing so a
        # stale in-flight write can never overwrite a newer generation.
        self._snapshot_generation += 1
        gen = self._snapshot_generation
        try:
            await asyncio.to_thread(self._write_snapshot, payload, gen)
        except Exception as exc:  # noqa: BLE001 - snapshot must never break a call
            logger.warning(f"Flow session snapshot failed (non-fatal): {exc}")

    def _write_snapshot(self, payload: dict, gen: int) -> None:
        """Upsert a single flow-session row in its own short-lived session.

        Guards the write with ``_snapshot_write_lock`` and the generation
        counter so a stale in-flight thread (from a notify-fan-out that fired
        before a function-call advanced state) can never overwrite a newer
        generation's row.  Both the check and the write are atomic relative to
        other thread-pool workers on the same executor.
        """
        from sqlalchemy import text as _text

        from botelier.database import SessionLocal

        with self._snapshot_write_lock:
            if self._snapshot_generation > gen:
                # A newer snapshot already completed or is about to write;
                # this payload is stale — drop it.
                logger.debug(
                    f"Skipping stale snapshot write (gen={gen}, "
                    f"current={self._snapshot_generation})"
                )
                return
            db = SessionLocal()
            try:
                db.execute(
                    _text(
                        """
                        INSERT INTO flow_sessions (
                            id, account_id, property_id, channel, session_key,
                            tool_id, current_node_id, collected_slots, status,
                            created_at, updated_at
                        ) VALUES (
                            gen_random_uuid(),
                            CAST(:account_id AS UUID),
                            CAST(:property_id AS UUID),
                            'voice',
                            :session_key,
                            CAST(:tool_id AS UUID),
                            :current_node_id,
                            CAST(:collected_slots AS JSONB),
                            :status,
                            now(), now()
                        )
                        ON CONFLICT (session_key, tool_id) DO UPDATE SET
                            current_node_id = EXCLUDED.current_node_id,
                            collected_slots = EXCLUDED.collected_slots,
                            status = EXCLUDED.status,
                            property_id = EXCLUDED.property_id,
                            account_id = EXCLUDED.account_id,
                            updated_at = now()
                        """
                    ),
                    payload,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def rehydrate_from_snapshot(self) -> bool:
        """Restore in-memory state from a durable snapshot, if one exists.

        Called when a fresh executor is created for a reconnecting contact. Saved
        slots overlay the flow-variable defaults (saved wins) and the flow
        resumes at the saved node. Read on the shared session; failures are
        swallowed so a missing/locked snapshot never blocks the call. Returns
        ``True`` when state was restored.
        """
        key = self._snapshot_key()
        if not key:
            return False
        session_key, tool_id = key
        try:
            from sqlalchemy import text as _text

            with self._borrow_db_session() as db:
                if db is None:
                    return False
                row = db.execute(
                    _text(
                        """
                        SELECT current_node_id, collected_slots, status
                        FROM flow_sessions
                        WHERE session_key = :session_key
                          AND tool_id = CAST(:tool_id AS UUID)
                        """
                    ),
                    {"session_key": session_key, "tool_id": tool_id},
                ).fetchone()
        except Exception as exc:  # noqa: BLE001 - resume is best-effort
            logger.warning(f"Flow session rehydrate query failed (non-fatal): {exc}")
            return False

        if not row:
            return False

        saved_node, saved_slots, saved_status = row[0], row[1], row[2]
        if isinstance(saved_slots, str):
            try:
                saved_slots = json.loads(saved_slots)
            except (ValueError, TypeError):
                saved_slots = {}
        if isinstance(saved_slots, dict):
            saved_slots = dict(saved_slots)
            saved_records = saved_slots.pop("_saved_records", None)
            if isinstance(saved_records, dict):
                self.state.saved_records.update(
                    {str(k): str(v) for k, v in saved_records.items()}
                )
            non_get_results = saved_slots.pop("_non_get_results", None)
            if isinstance(non_get_results, dict):
                self._non_get_results.update(
                    {
                        str(k): dict(v)
                        for k, v in non_get_results.items()
                        if isinstance(v, dict)
                    }
                )
            derived_slots = saved_slots.pop("_derived_slots", None)
            if isinstance(derived_slots, list):
                self.state.derived_slots.update(str(k) for k in derived_slots)
            saved_revisions = saved_slots.pop("_slot_revisions", None)
            saved_counter = saved_slots.pop("_slot_revision_counter", 0)
            if isinstance(saved_revisions, dict):
                for slot_key, slot_value in saved_slots.items():
                    try:
                        incoming_revision = int(saved_revisions.get(slot_key, 0) or 0)
                    except (TypeError, ValueError):
                        logger.warning(
                            f"resume: corrupt revision for slot {slot_key!r}; "
                            "defaulting to 0"
                        )
                        incoming_revision = 0
                    if slot_key in saved_revisions:
                        self.call_context.restore_caller_value(
                            slot_key, slot_value, incoming_revision
                        )
                    else:
                        # Defaults and derived/API values are restored only into
                        # this flow's working state, never into shared facts.
                        self.state.collected_slots[slot_key] = slot_value
                try:
                    restored_counter = int(saved_counter or 0)
                except (TypeError, ValueError):
                    logger.warning("resume: corrupt _slot_revision_counter; defaulting to 0")
                    restored_counter = 0
                self.call_context._next_revision = max(
                    self.call_context._next_revision, restored_counter
                )
            else:
                # Backward compatibility for snapshots written before revision
                # metadata existed: provenance is unknown, so fail closed and
                # keep every value flow-local.
                self.state.collected_slots.update(saved_slots)
        if saved_node:
            self.state.current_node_id = saved_node
        # A durable row exists, so this flow was genuinely started on a prior
        # connection — resumed executors may keep snapshotting (Task #543).
        self._flow_started = True
        # A persisted "complete" status can mean either the graph structurally
        # ran off its end OR a terminal action already executed — the latter
        # would mean the call already ended, so there'd be nothing to
        # reconnect to. Restore it as the structural signal only; leave
        # is_complete (the end_call idempotency guard) at its default False
        # so a resumed session sitting on an END/TRANSFER node can still
        # actually execute that terminal action once.
        self.state.graph_exhausted = saved_status == "complete"
        logger.info(
            f"Rehydrated flow session {session_key}/{tool_id} at node "
            f"{self.state.current_node_id} ({len(self.state.collected_slots)} slots)"
        )
        return True

    def get_variables_in_flow_order(self) -> list[FlowVariable]:
        """Get variables in the order they appear in the flow traversal.

        This traverses the flow graph from the initial node and returns
        variables in the order their collect_slot nodes are encountered.
        """
        ordered_keys = []
        visited = set()

        def get_next_nodes(node_id: str) -> list[FlowNode]:
            """Get all nodes connected from a source node."""
            next_nodes = []
            for edge in self.flow_config.edges:
                if edge.source == node_id:
                    for node in self.flow_config.nodes:
                        if node.id == edge.target:
                            next_nodes.append(node)
            return next_nodes

        def traverse(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)

            node = None
            for n in self.flow_config.nodes:
                if n.id == node_id:
                    node = n
                    break

            if not node:
                return

            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                var_key = slot.get("variableKey")
                if var_key and var_key not in ordered_keys:
                    ordered_keys.append(var_key)
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
                for slot in sorted_slots:
                    var_key = slot.get("variableKey")
                    if var_key and var_key not in ordered_keys:
                        ordered_keys.append(var_key)

            for next_node in get_next_nodes(node_id):
                traverse(next_node.id)

        if self.flow_config.initial_node:
            traverse(self.flow_config.initial_node)

        var_by_key = {v.key: v for v in self.flow_config.variables}
        ordered_variables = []
        for key in ordered_keys:
            if key in var_by_key:
                ordered_variables.append(var_by_key[key])

        for var in self.flow_config.variables:
            if var not in ordered_variables:
                ordered_variables.append(var)

        return ordered_variables

    def _has_any_past_date_slot(self) -> bool:
        """Return True if any date slot in the flow has requireFuture explicitly set to False."""
        for node in self.flow_config.nodes:
            node_type = node.type.value if hasattr(node.type, "value") else str(node.type)
            if node_type == "collect_slot":
                slot = node.data.get("slot") or {}
                if slot.get("type") == "date":
                    validation = slot.get("validation") or {}
                    rf = validation.get("requireFuture", validation.get("require_future", True))
                    if not rf:
                        return True
            elif node_type == "collect_form":
                for slot in node.data.get("slots") or []:
                    if slot.get("type") == "date":
                        validation = slot.get("validation") or {}
                        rf = validation.get("requireFuture", validation.get("require_future", True))
                        if not rf:
                            return True
        return False

    def get_flow_persona_section(self) -> str:
        """Return the static, per-flow persona block for this flow.

        Includes the Initial node's ``systemPrompt`` and the flow-level
        ``global_prompt`` (labelled so it augments, rather than silently
        overrides, the assistant's own persona). Returns "" when the flow
        configures neither.

        This is the flow-specific portion that must be injected once *per flow*
        into a live call (a single assistant can host multiple flow tools),
        separate from the shared behavioural rules which are injected only once.
        """
        initial_node = None
        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                initial_node = node
                break

        base_prompt = ""
        if initial_node and initial_node.data.get("systemPrompt"):
            base_prompt = str(initial_node.data["systemPrompt"]).strip()

        global_prompt = (self.flow_config.global_prompt or "").strip()

        parts = []
        if base_prompt:
            parts.append(base_prompt)
        if global_prompt:
            parts.append(
                "FLOW-LEVEL INSTRUCTIONS (apply to entire conversation):\n"
                f"{global_prompt}"
            )
        if not parts:
            return ""
        return "## FLOW INSTRUCTIONS\n" + "\n\n".join(parts)

    def has_past_date_slot(self) -> bool:
        """Public accessor: True if any date slot in the flow allows past dates.

        Used by the live-call system-prompt injector to pick the right
        date-interpretation rule across one or more flows on an assistant.
        """
        return self._has_any_past_date_slot()

    def get_static_system_prompt_additions(self) -> str:
        """The call-invariant portion of the flow system prompt.

        Composes the per-flow persona section (``get_flow_persona_section``)
        with the shared behavioural rules (``build_flow_behavioral_rules``).
        Deliberately excludes ``_generate_flow_context()`` — that is the dynamic
        current-node context, which live calls deliver through tool gating and
        function-result messages rather than the system prompt.

        Both the simulator (via ``get_system_prompt``) and live calls (via
        ``call_handler``) build on these same pieces, so the two paths stay in
        lockstep.
        """
        current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")
        rules = build_flow_behavioral_rules(current_date, self._has_any_past_date_slot())
        persona = self.get_flow_persona_section()
        if persona:
            return f"{persona}\n\n{rules}"
        return rules

    def get_system_prompt(self) -> str:
        """Generate the full simulator system prompt.

        Static additions (persona + behavioural rules) plus the dynamic flow
        context. Kept as ``static + "\\n\\n" + flow_context`` so it stays in
        lockstep with the live-call injection, which reuses the same static
        pieces (enforced by a unit test).
        """
        return f"{self.get_static_system_prompt_additions()}\n\n{self._generate_flow_context()}"

    def _generate_flow_context(self) -> str:
        """Generate context about what information needs to be collected and current node instructions."""
        context_parts = []

        current_node_context = self._get_current_node_context()
        if current_node_context:
            context_parts.append(current_node_context)

        # Collect the variable keys owned by the current node so we can avoid
        # emitting their instructions a second time — _get_current_node_context()
        # already surfaces them as "Node instructions:" in the block above.
        current_node = self.state.get_current_node()
        current_node_var_keys: set[str] = set()
        if current_node:
            if current_node.type == NodeType.COLLECT_SLOT:
                slot = current_node.data.get("slot", {})
                var_key = slot.get("variableKey")
                if var_key:
                    current_node_var_keys.add(var_key)
            elif current_node.type == NodeType.COLLECT_FORM:
                for s in current_node.data.get("slots", []):
                    var_key = s.get("variableKey")
                    if var_key:
                        current_node_var_keys.add(var_key)

        ordered_vars = self.get_variables_in_flow_order()
        slots_to_collect = []

        for var in ordered_vars:
            if var.key not in self.state.collected_slots:
                # Only fetch per-slot instructions for future nodes; the current
                # node's instructions are already in the node-context block above.
                node_instructions = (
                    None
                    if var.key in current_node_var_keys
                    else self._get_instructions_for_variable(var.key)
                )
                validation = self._get_validation_for_variable(var.key)

                slot_info = f"- {var.key}: {var.description} ({var.type.value})"
                constraints = []

                if validation:
                    if "min" in validation:
                        constraints.append(f"minimum: {validation['min']}")
                    if "max" in validation:
                        constraints.append(f"maximum: {validation['max']}")

                    after_date_var = validation.get("cross_field_variable")
                    if after_date_var:
                        constraints.append(
                            _cross_field_constraint(
                                validation, self.state.collected_slots
                            )
                        )

                if var.type == SlotType.DATE:
                    require_future = (
                        validation.get("requireFuture", validation.get("require_future", True))
                        if validation
                        else True
                    )
                    if not any("after" in c for c in constraints):
                        if require_future:
                            constraints.append("must be today or later")
                        else:
                            constraints.append("may be any date including past dates")

                if constraints:
                    slot_info += f" [{', '.join(constraints)}]"

                if node_instructions:
                    node_instructions_resolved = substitute_variables(
                        node_instructions, self.state.collected_slots
                    )
                    slot_info += f"\n  Instructions: {node_instructions_resolved}"
                slots_to_collect.append(slot_info)

        if slots_to_collect:
            context_parts.append(f"""Information to collect (in order):
{chr(10).join(slots_to_collect)}""")
        else:
            context_parts.append("All required information has been collected.")

        return "\n\n".join(context_parts)

    def _get_node_delivery_mode(self, node: FlowNode) -> str:
        """Get the delivery mode for a node (guided or static). Default is guided."""
        if node.type == NodeType.MESSAGE:
            return node.data.get("deliveryMode", "guided")
        elif node.type == NodeType.CONFIRMATION:
            confirmation_data = node.data.get("confirmation", {})
            return confirmation_data.get("deliveryMode", "guided")
        return "guided"

    def _get_current_node_context(self) -> Optional[str]:
        """Get context about the current node including any configured messages.

        In 'guided' mode: Provides guidance that AI can follow naturally
        In 'static' mode: Provides exact text that must be spoken verbatim
        """
        current_node = self.state.get_current_node()
        if not current_node:
            return None

        context_lines = []
        delivery_mode = self._get_node_delivery_mode(current_node)
        is_static = delivery_mode == "static"

        if current_node.type == NodeType.MESSAGE:
            message = current_node.data.get("message", "")
            if message:
                resolved = substitute_variables(message, self.state.collected_slots)
                if is_static:
                    context_lines.append(f'CURRENT NODE: Say exactly: "{resolved}"')
                else:
                    context_lines.append(
                        f'CURRENT NODE: Guidance - Convey this message naturally: "{resolved}"'
                    )

        elif current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            prompt = slot.get("prompt", "")
            if prompt:
                resolved = substitute_variables(prompt, self.state.collected_slots)
                context_lines.append(
                    f'CURRENT NODE: Ask the customer (you may phrase naturally): "{resolved}"'
                )
            context_lines.append(
                "IMPORTANT: Any answer — including 'No', 'Nothing else', 'I'm fine', "
                "or any other declining response — is a valid answer. Call the collect "
                "function to record it. Never call end_call yourself; the flow will "
                "end the call after all required steps have completed."
            )

        elif current_node.type == NodeType.COLLECT_FORM:
            intro = current_node.data.get("introMessage", "")
            if intro:
                resolved = substitute_variables(intro, self.state.collected_slots)
                context_lines.append(f'CURRENT NODE: Say introduction: "{resolved}"')
            slots = current_node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            uncollected = [
                s for s in sorted_slots if s.get("variableKey") not in self.state.collected_slots
            ]
            if uncollected:
                first_slot = uncollected[0]
                prompt = first_slot.get("prompt", "")
                if prompt:
                    resolved = substitute_variables(prompt, self.state.collected_slots)
                    context_lines.append(
                        f'Then ask for {first_slot.get("variableKey")}: "{resolved}"'
                    )
            context_lines.append(
                "IMPORTANT: Any answer — including 'No', 'Nothing else', 'I'm fine', "
                "or any other declining response — is a valid answer. Call the collect "
                "function to record it. Never call end_call yourself; the flow will "
                "end the call after all required steps have completed."
            )

        elif current_node.type == NodeType.CONFIRMATION:
            confirmation_data = current_node.data.get("confirmation", {})
            summary_template = confirmation_data.get(
                "summaryTemplate", confirmation_data.get("summary_template", "")
            )
            confirm_prompt = confirmation_data.get(
                "confirmPrompt", confirmation_data.get("confirm_prompt", "")
            )

            if summary_template:
                resolved_summary = substitute_variables(
                    summary_template, self.state.collected_slots
                )
                if is_static:
                    context_lines.append(
                        f'CURRENT NODE: Say exactly the summary: "{resolved_summary}"'
                    )
                else:
                    context_lines.append(
                        f'CURRENT NODE: Summarize these details naturally: "{resolved_summary}"'
                    )
            if confirm_prompt:
                resolved_confirm = substitute_variables(confirm_prompt, self.state.collected_slots)
                if is_static:
                    context_lines.append(f'Then ask for confirmation: "{resolved_confirm}"')
                else:
                    context_lines.append(
                        f'Then ask if this is correct (naturally): "{resolved_confirm}"'
                    )

        elif current_node.type == NodeType.END:
            closing = current_node.data.get("closingMessage", "")
            end_fn = f"end_call_{current_node.id}"
            if closing:
                resolved = substitute_variables(closing, self.state.collected_slots)
                context_lines.append(
                    f"CURRENT NODE: End Call — you MUST call the `{end_fn}` function NOW "
                    f"to end the call. The function will deliver the closing message "
                    f'"{resolved}" to the caller. Do NOT just say goodbye as plain text — '
                    f"the call only ends when you call the function."
                )
            else:
                context_lines.append(
                    f"CURRENT NODE: End Call — you MUST call the `{end_fn}` function NOW "
                    f"to end the call. Do NOT just say goodbye as plain text — the call "
                    f"only ends when you call the function."
                )

        elif current_node.type == NodeType.TRANSFER:
            transfer = current_node.data.get("transfer", {})
            pre_message = transfer.get("preTransferMessage", "")
            if pre_message:
                resolved = substitute_variables(pre_message, self.state.collected_slots)
                context_lines.append(f'CURRENT NODE: Before transfer, say: "{resolved}"')

        elif current_node.type == NodeType.SAVE_RECORD:
            save_data = current_node.data.get(
                "saveRecord", current_node.data.get("save_record", {})
            )
            record_type_name = (
                save_data.get("recordTypeName")
                or current_node.data.get("name")
                or "record"
            )
            fn_name = f"save_record_{current_node.id}"
            context_lines.append(
                f"CURRENT NODE: Save Record — you MUST call `{fn_name}` NOW to "
                f"save the collected '{record_type_name}' record. Do NOT end the "
                f"call or say goodbye before calling this function — the record "
                f"will be lost if you do."
            )

        elif current_node.type in (NodeType.API_REQUEST, NodeType.CAPABILITY):
            api_config = current_node.data.get("api", {})
            is_capability = current_node.type == NodeType.CAPABILITY
            node_name = current_node.data.get(
                "name", "Capability" if is_capability else "API call"
            )
            thinking_message = (api_config.get("thinkingMessage") or "").strip()
            response_instructions = (api_config.get("responseInstructions") or "").strip()
            node_instructions = (current_node.data.get("instructions") or "").strip()
            fn_name = f"execute_{current_node.id}"
            label = "Capability" if is_capability else "API Request"
            context_lines.append(
                f'CURRENT NODE: {label} — call `{fn_name}` to execute "{node_name}".'
            )
            if thinking_message:
                context_lines.append(f'Say to the customer: "{thinking_message}"')
            if response_instructions:
                context_lines.append(
                    f"After the API responds, follow these instructions: {response_instructions}"
                )
            if node_instructions:
                context_lines.append(f"Additional instructions: {node_instructions}")

        elif current_node.type == NodeType.API_RESPONSE:
            config = current_node.data.get("responsePresentation", {}) or {}
            fn_name = f"continue_response_{current_node.id}"
            array_var = (config.get("arrayVariable") or "").strip()
            desc = f"array '{array_var}'" if array_var else "the API result"
            context_lines.append(
                f"CURRENT NODE: API Response — {desc} has already been spoken directly "
                f"to the caller. Call `{fn_name}` NOW to acknowledge and advance the flow."
            )

        elif current_node.type == NodeType.OPTION_PICKER:
            config = current_node.data.get("optionPicker", {}) or {}
            fn_name = f"select_option_{current_node.id}"
            prompt = (config.get("prompt") or "").strip()
            items = self._resolve_option_picker_items(config)
            if prompt:
                resolved_prompt = substitute_variables(prompt, self.state.collected_slots)
                context_lines.append(
                    f'CURRENT NODE: Ask the customer (if not already clear from context): "{resolved_prompt}"'
                )
            if items:
                context_lines.append(
                    f"There are {len(items)} option(s) to choose from. Once the caller "
                    "clearly indicates which one they want — by name or by position "
                    f'("the first one", "the second option") — call `{fn_name}` with '
                    "that ordinal and/or label. Never guess: if it's unclear which one "
                    "they mean, ask them to clarify first."
                )
            else:
                context_lines.append(
                    f"CURRENT NODE: Option Picker — no options are currently available "
                    f"to select from. Do not call `{fn_name}` yet."
                )

        # Every other node type: surface the node's typed instructions so the
        # editor's per-node guidance is honored while that node is active —
        # on live calls exactly as in the simulator (API/CAPABILITY nodes
        # already appended theirs above).
        if current_node.type not in (NodeType.API_REQUEST, NodeType.CAPABILITY):
            generic_instructions = (current_node.data.get("instructions") or "").strip()
            if generic_instructions:
                resolved_instructions = substitute_variables(
                    generic_instructions, self.state.collected_slots
                )
                context_lines.append(f"Node instructions: {resolved_instructions}")

        # Exhausted-flow guardrail (Task #534): the graph ran off its end
        # (no outgoing edge from here — see FlowState.advance_to) without
        # going through END/TRANSFER, whose own guidance above already tells
        # the model exactly what to do. Every other node type has nothing
        # left telling the model what to do next, and without this line
        # nothing stops it from improvising — including claiming it performed
        # an action (a booking, a save, a transfer) that never actually
        # happened once the designed flow is over.
        if (
            self.state.graph_exhausted
            and current_node.type not in (NodeType.END, NodeType.TRANSFER)
        ):
            context_lines.append(
                "FLOW COMPLETE: This flow has reached the end of its configured "
                "steps — there is nothing further defined here. Do NOT claim to "
                "have booked, saved, transferred, or otherwise completed any "
                "action unless a function result already confirmed it. If the "
                "caller needs something else, offer to transfer them or end the "
                "call gracefully; do not invent an outcome."
            )

        return "\n".join(context_lines) if context_lines else None

    def get_current_node_context(self) -> Optional[str]:
        """Public accessor for the active node's guidance block.

        Used by live-call function results (flow trigger + every flow function)
        so a real call sees the same CURRENT NODE guidance the simulator puts
        in its per-turn system prompt.
        """
        return self._get_current_node_context()

    def _get_validation_for_variable(self, var_key: str) -> Optional[dict]:
        """Get the validation config for the node that collects a specific variable."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return _normalize_slot_validation(slot.get("validation"))
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        return _normalize_slot_validation(slot.get("validation"))
        return None

    def _slot_config_for_variable(self, var_key: str) -> Optional[dict]:
        """Return the concrete collect-node slot config for ``var_key``."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return slot
            elif node.type == NodeType.COLLECT_FORM:
                for slot in node.data.get("slots", []):
                    if slot.get("variableKey") == var_key:
                        return slot
        return None

    def import_caller_slots(self, values: Optional[dict[str, Any]]) -> dict:
        """Validate and atomically import structured caller facts.

        This is used by ``start_<flow>`` arguments. Invalid values never enter
        authoritative state, and a mixed valid/invalid payload imports nothing.
        """
        values = values or {}
        variables = {var.key: var for var in self.flow_config.variables}
        errors: dict[str, str] = {}
        normalized: dict[str, Any] = {}
        for key in values:
            if key not in variables:
                errors[key] = "Unknown flow variable."
        original_values = dict(self.state.collected_slots)
        # Validate in declared flow order and expose earlier candidate values to
        # later validators (notably departure.afterDateVariable=arrival).
        for var in self.flow_config.variables:
            key = var.key
            if key not in values:
                continue
            value = values[key]
            if not _is_valid_new_value(value):
                errors[key] = "A real value is required."
                continue
            error = self._validate_slot_value(var, self._slot_config_for_variable(key), value)
            if error:
                errors[key] = error
                continue
            if var.type == SlotType.NUMBER and isinstance(value, str):
                try:
                    value = int(value)
                except ValueError:
                    pass
            normalized[key] = value
            self.state.collected_slots[key] = value
        self.state.collected_slots.clear()
        self.state.collected_slots.update(original_values)
        if errors:
            return {"success": False, "errors": errors, "imported": {}}
        self.call_context.set_caller_values(normalized)
        self.advance_past_satisfied_collects()
        return {"success": True, "errors": {}, "imported": normalized}

    def advance_past_satisfied_collects(self) -> None:
        """Skip only collect gates already satisfied by authoritative state.

        Each hop follows the real graph edge and delegates condition evaluation
        to ``FlowState.advance_to``.  It stops at every non-collect node, so API,
        save, router, confirmation, transfer, end, and other action gates can
        never be bypassed by proactive slot import.
        """
        for _ in range(len(self.flow_config.nodes) + 1):
            node = self.state.get_current_node()
            if not node or node.type not in (
                NodeType.COLLECT_SLOT,
                NodeType.COLLECT_FORM,
            ):
                return
            if self._node_has_uncollected_slot(node):
                return
            next_node = self.state.get_next_node(node.id)
            if not next_node:
                return
            self.state.advance_to(next_node.id)

    def _dependent_keys(self, changed_key: str) -> set[str]:
        """Return transitive variables whose value derives from ``changed_key``."""
        dependencies: dict[str, set[str]] = {}
        for var in self.flow_config.variables:
            validation = self._get_validation_for_variable(var.key) or {}
            parent = validation.get("cross_field_variable")
            if parent:
                dependencies.setdefault(var.key, set()).add(parent)
        for node in self.flow_config.nodes:
            if node.type == NodeType.SET_VARIABLE:
                config = node.data.get("setVariable", node.data.get("set_variable", {}))
                target = config.get("variableKey", config.get("variable_key"))
                if target:
                    dependencies.setdefault(target, set()).update(
                        re.findall(r"\{\{(\w+)\}\}", str(config.get("value", "")))
                    )
            elif node.type in (NodeType.API_REQUEST, NodeType.CAPABILITY):
                api = node.data.get("api", {})
                source_text = json.dumps(
                    {
                        "url": api.get("url"),
                        "headers": api.get("headers"),
                        "body": api.get("bodyTemplate", api.get("body")),
                    },
                    default=str,
                )
                inputs = set(re.findall(r"\{\{(\w+)\}\}", source_text))
                for mapping in api.get("responseVariables", []):
                    target = mapping.get("variableKey")
                    if target:
                        dependencies.setdefault(target, set()).update(inputs)
        affected: set[str] = set()
        frontier = {changed_key}
        while frontier:
            parent = frontier.pop()
            for child, parents in dependencies.items():
                if parent in parents and child not in affected:
                    affected.add(child)
                    frontier.add(child)
        return affected

    def correct_caller_slot(self, key: str, value: Any) -> Optional[str]:
        """Apply a validated correction across every executor on this call."""
        var = next((v for v in self.flow_config.variables if v.key == key), None)
        if var is None:
            return "Unknown flow variable."
        error = self._validate_slot_value(var, self._slot_config_for_variable(key), value)
        if error:
            return error
        self.call_context.set_caller_value(key, value)
        return None

    def _on_shared_caller_fact_changed(self, key: str) -> set[str]:
        """Invalidate and rewind this flow after a shared caller-fact change.

        Returns explicit dependent facts that the context must remove globally.
        The context owns the notification queue, so this method never calls back
        into it and cannot recurse.
        """
        invalidated: set[str] = set()
        explicit_removals: set[str] = set()
        own_keys = {var.key for var in self.flow_config.variables}
        dependent_keys = self._dependent_keys(key)
        if key not in own_keys and not dependent_keys:
            return explicit_removals
        if key in own_keys and key not in self.state.collected_slots:
            invalidated.add(key)
        for dependent in dependent_keys:
            if dependent not in self.state.collected_slots:
                continue
            dep_var = next((v for v in self.flow_config.variables if v.key == dependent), None)
            # Caller-entered constrained slots survive when still valid. Derived
            # values (API/set-variable outputs) are always invalidated.
            dep_error = (
                self._validate_slot_value(
                    dep_var,
                    self._slot_config_for_variable(dependent),
                    self.state.collected_slots[dependent],
                )
                if dep_var
                else "derived"
            )
            if dependent in self.state.derived_slots or dep_var is None or dep_error:
                if dependent in self.call_context.values:
                    explicit_removals.add(dependent)
                else:
                    self.state.collected_slots.pop(dependent, None)
                    self.state.derived_slots.discard(dependent)
                invalidated.add(dependent)
        if invalidated:
            target = self._earliest_collect_node_for(invalidated)
            if target:
                self.state.graph_exhausted = False
                self.state.advance_to(target.id)
            self._get_recent.clear()
        self._details_confirmed = False
        return explicit_removals

    def _earliest_collect_node_for(self, keys: set[str]) -> Optional[FlowNode]:
        """Find the earliest reachable collect node owning any affected key."""
        nodes = self.flow_config._node_index
        distances: dict[str, int] = {}
        queue: list[tuple[str, int]] = (
            [(self.flow_config.initial_node, 0)]
            if self.flow_config.initial_node
            else []
        )
        while queue:
            node_id, distance = queue.pop(0)
            if node_id in distances and distances[node_id] <= distance:
                continue
            distances[node_id] = distance
            for edge in self.flow_config.edges:
                if edge.source == node_id:
                    queue.append((edge.target, distance + 1))
        candidates: list[tuple[int, int, FlowNode]] = []
        for index, node in enumerate(self.flow_config.nodes):
            node_keys: set[str] = set()
            if node.type == NodeType.COLLECT_SLOT:
                node_keys.add(node.data.get("slot", {}).get("variableKey"))
            elif node.type == NodeType.COLLECT_FORM:
                node_keys.update(
                    slot.get("variableKey") for slot in node.data.get("slots", [])
                )
            if keys.intersection(node_keys):
                candidates.append((distances.get(node.id, 10**9), index, node))
        return min(candidates, default=(0, 0, None))[2]

    def _get_instructions_for_variable(self, var_key: str) -> Optional[str]:
        """Get the instructions for the node that collects a specific variable."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return node.data.get("instructions")
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        return node.data.get("instructions")
        return None

    def _find_next_reachable_collect_slot(self) -> tuple:
        """Find the next COLLECT_SLOT or COLLECT_FORM node reachable from the current position.
        Traverses edges from current node without skipping collect nodes.

        Returns: (node, variable_key) or (None, None) if no collect node reachable
        """
        current_node = self.state.get_current_node()
        if not current_node:
            return (None, None)

        if current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            return (current_node, slot.get("variableKey"))

        if current_node.type == NodeType.COLLECT_FORM:
            slots = current_node.data.get("slots", [])
            first = self._first_uncollected_slot(slots)
            if first:
                return (current_node, first.get("variableKey"))

        visited = set()
        queue = [current_node.id]

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = None
            for n in self.flow_config.nodes:
                if n.id == node_id:
                    node = n
                    break

            if not node:
                continue

            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                var_key = slot.get("variableKey")
                if var_key and var_key not in self.state.collected_slots:
                    return (node, var_key)

            if node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
                for slot in sorted_slots:
                    var_key = slot.get("variableKey")
                    if var_key and var_key not in self.state.collected_slots:
                        return (node, var_key)

            for target in self._bfs_next_targets(node):
                if target not in visited:
                    queue.append(target)

        return (None, None)

    # ------------------------------------------------------------------
    # Form-slot helpers — single source of truth for "find uncollected"
    # ------------------------------------------------------------------

    @staticmethod
    def _sorted_form_slots(slots: list) -> list:
        """Return form slot dicts sorted by configured order, skipping non-dict items.

        This is the canonical ordering function used everywhere we iterate form
        slots.  Centralising it ensures all paths (context, prompts, validation,
        schema building) use identical ordering and skip the same bad entries.
        """
        return sorted(
            (s for s in slots if isinstance(s, dict)),
            key=lambda s: s.get("order", 0),
        )

    def _first_uncollected_slot(self, slots: list) -> Optional[dict]:
        """Return the first form slot not yet in collected_slots, in order.

        Returns ``None`` when all slots are collected or the list is empty.
        Slots with a missing / None variableKey are silently skipped.
        """
        for slot in self._sorted_form_slots(slots):
            var_key = slot.get("variableKey")
            if var_key and var_key not in self.state.collected_slots:
                return slot
        return None

    def _uncollected_slots(self, slots: list) -> list:
        """Return every form slot not yet in collected_slots, in order."""
        return [
            s for s in self._sorted_form_slots(slots)
            if s.get("variableKey") and s.get("variableKey") not in self.state.collected_slots
        ]

    def _node_has_uncollected_slot(self, node: FlowNode) -> bool:
        """True if a collect node still has at least one uncollected slot."""
        if node.type == NodeType.COLLECT_SLOT:
            var_key = (node.data.get("slot") or {}).get("variableKey")
            return bool(var_key) and var_key not in self.state.collected_slots
        if node.type == NodeType.COLLECT_FORM:
            return self._first_uncollected_slot(node.data.get("slots", [])) is not None
        return False

    def _bfs_next_targets(self, node: FlowNode) -> list:
        """Outgoing target ids to follow when walking the flow graph.

        For a CONDITION node whose variable is already known, follow ONLY the
        branch it currently evaluates to — otherwise a lookahead would wrongly
        expose action nodes (end_call / transfer / api) on the branch that will
        never be taken. When the variable is not yet collected the condition
        stays transparent (all branches) so no reachable path is prematurely
        gated out.
        """
        if node.type == NodeType.CONDITION:
            cond = node.data.get("condition", {}) or {}
            variable = cond.get("variable")
            if variable and variable in self.state.collected_slots:
                target = _condition_target_id(
                    self.flow_config, node, self.state.collected_slots
                )
                return [target] if target else []
        return [
            edge.target
            for edge in self.flow_config.edges
            if edge.source == node.id
        ]

    def is_on_required_action_node(self) -> bool:
        """Return True when the flow is sitting on an action node that must fire next.

        Used by FunctionMapper to decide whether to block the global end_call tool
        from the non-flow tool list.  When True, the LLM must invoke the action node
        function (e.g. save_record, api_request, confirmation) before it can end the
        call — preventing it from skipping required steps via the global end_call.
        The flow's own end_call_<node_id> is still exposed via get_function_schemas().

        Also True while sitting on a "stuck" MESSAGE node (see
        ``_get_pending_message_advance_node``): a waiting MESSAGE node with no
        reachable collect/action node ahead gives the LLM nothing concrete to
        call, which otherwise leaves it free to improvise (including
        fabricating a completed outcome) before reaching for the global
        end_call. Task #600.
        """
        current = self.state.get_current_node()
        if current is not None and current.type in _ACTION_NODE_TYPES:
            return True
        return self._get_pending_message_advance_node() is not None

    def has_pending_side_effect_downstream(self) -> bool:
        """Return True if a side-effect node exists on any reachable path ahead.

        Side-effect nodes (``_SIDE_EFFECT_NODE_TYPES``): SAVE_RECORD, API_REQUEST,
        CAPABILITY, CONFIRMATION, SET_VARIABLE.  END and TRANSFER are excluded —
        they are flow-control terminators, not data mutators, and must not prevent
        the LLM from ending a pure Q&A flow.

        Unlike ``_get_reachable_action_node_ids``, this BFS **passes through**
        unsatisfied collect nodes instead of stopping there.  The failing production
        scenario is exactly "sitting on the final collect node ('anything else?')
        while SAVE_RECORD is downstream" — the existing ``is_on_required_action_node``
        check returned False in that position, leaving the global end_call available.

        Used together with ``is_on_required_action_node()`` in FunctionMapper:
        block global end_call if EITHER check is True.
        """
        current = self.state.get_current_node()
        if not current:
            return False

        # Sitting directly on a side-effect node → True immediately.
        if current.type in _SIDE_EFFECT_NODE_TYPES:
            return True

        node_by_id = self.flow_config._node_index
        visited: set = set()
        queue = list(self._bfs_next_targets(current))

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = node_by_id.get(node_id)
            if not node:
                continue

            if node.type in _SIDE_EFFECT_NODE_TYPES:
                return True

            # END and TRANSFER are not side-effects; stop this branch without
            # triggering the gate.
            if node.type in (NodeType.END, NodeType.TRANSFER):
                continue

            # Every other node type — MESSAGE, INITIAL, CONDITION, ROUTER, and
            # collect nodes (satisfied OR unsatisfied) — is transparent: keep
            # traversing so downstream side-effects are always reachable.
            for target in self._bfs_next_targets(node):
                if target not in visited:
                    queue.append(target)

        return False

    def _get_reachable_action_node_ids(self) -> set:
        """Return ids of action nodes whose functions may be exposed right now.

        Mirrors the slot-function gating: an action node's function is only
        offered to the LLM when the flow is AT that node, or can reach it from
        the current position without first crossing an unsatisfied collect node
        or another action node (which must fire first). This stops the model from
        calling end_call / transfer / api / router / etc. out of flow order — the
        root cause of premature hang-ups mid-collection.

        The same forward-BFS precedent as ``_find_next_reachable_collect_slot`` is
        used: INITIAL / MESSAGE / CONDITION nodes and already-satisfied collect
        nodes are transparent (traversed through); unsatisfied collect nodes and
        action nodes are gates (traversal stops there).
        """
        current = self.state.get_current_node()
        if not current:
            return set()

        # Still collecting on the current node → no action nodes are reachable yet.
        if self._node_has_uncollected_slot(current):
            return set()

        # Sitting on an action node → expose only it; do not look past it so each
        # action fires in strict order.
        if current.type in _ACTION_NODE_TYPES:
            return {current.id}

        # Otherwise walk forward, stopping at the first gate on each branch.
        node_by_id = self.flow_config._node_index
        reachable: set = set()
        visited: set = set()
        queue = [edge.target for edge in self.flow_config.edges if edge.source == current.id]

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = node_by_id.get(node_id)
            if not node:
                continue

            if node.type in (NodeType.COLLECT_SLOT, NodeType.COLLECT_FORM):
                if self._node_has_uncollected_slot(node):
                    # Unsatisfied collect gate — stop this branch.
                    continue
                # Already satisfied — fall through and keep traversing.
            elif node.type in _ACTION_NODE_TYPES:
                reachable.add(node.id)
                # Do not traverse past an action node (it must fire first).
                continue

            for target in self._bfs_next_targets(node):
                if target not in visited:
                    queue.append(target)

        return reachable

    def _get_pending_message_advance_node(self) -> Optional[FlowNode]:
        """Return the current node when it is a "stuck" waiting MESSAGE node.

        MESSAGE nodes expose no LLM-callable function of their own — their
        content is delivered purely through node-context guidance in the
        system prompt. That is harmless as long as a COLLECT_SLOT/COLLECT_FORM
        or action node (SAVE_RECORD, API_REQUEST, CONFIRMATION, END, TRANSFER,
        etc.) is reachable ahead: the LLM has something concrete to call once
        it finishes delivering the message, and calling it implicitly carries
        the flow state forward past every MESSAGE node in between.

        But when a waiting MESSAGE node (``waitForResponse`` true) leads only
        to more MESSAGE/CONDITION nodes and nothing the engine can expose —
        no reachable collect node, no reachable action node — the LLM has
        *no* flow tool to call. Nothing then ever advances
        ``current_node_id`` past this point, so the model is left to
        freelance: invent its own follow-up questions, or narrate a
        fabricated outcome (e.g. "your booking is confirmed") before falling
        back to the global end_call. This was the root cause of Task #600's
        fake-confirmation bug — the flow's configured "disabled" message was
        never reachable, spoken, or advanced past.

        Returns the current node (so callers can build/gate an explicit
        ``continue_flow_<id>`` function for it), or None when the LLM
        already has a real function to call, or the current node is not a
        waiting MESSAGE node.
        """
        current = self.state.get_current_node()
        if not current or current.type != NodeType.MESSAGE:
            return None
        if not current.data.get("waitForResponse", True):
            return None
        # A node with no outgoing edge has nothing to advance to — landing on
        # it already marks the flow exhausted (FlowState.advance_to), so no
        # further tool call is needed to "unstick" it; requiring one would
        # gate end_call forever with nothing left for the LLM to call.
        if not self.state.has_outgoing_edge(current.id):
            return None
        next_collect_node, _ = self._find_next_reachable_collect_slot()
        if next_collect_node is not None:
            return None
        if self._get_reachable_action_node_ids():
            return None
        return current

    def _get_next_slot_instructions(self) -> Optional[dict]:
        """Get instructions for the next slot to collect, with dynamic constraints based on collected values."""
        current_node = self.state.get_current_node()
        if not current_node:
            return None

        slot = None
        var_key = None

        if current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            var_key = slot.get("variableKey")
        elif current_node.type == NodeType.COLLECT_FORM:
            slots = current_node.data.get("slots", [])
            first = self._first_uncollected_slot(slots)
            if first:
                slot = first
                var_key = first.get("variableKey")

        if not slot or not var_key:
            return None

        if var_key in self.state.collected_slots:
            return None

        var_info = None
        for var in self.flow_config.variables:
            if var.key == var_key:
                var_info = var
                break

        if not var_info:
            return None

        validation = _normalize_slot_validation(slot.get("validation"))
        constraints = []

        now = datetime.now(self._timezone)
        current_date = now.strftime("%Y-%m-%d")

        if var_info.type == SlotType.NUMBER:
            if "min" in validation:
                constraints.append(f"minimum: {validation['min']}")
            if "max" in validation:
                constraints.append(f"maximum: {validation['max']}")

        elif var_info.type == SlotType.DATE:
            require_future = (
                validation.get("requireFuture", validation.get("require_future", True))
                if validation
                else True
            )
            after_date_var = validation.get("cross_field_variable")
            if after_date_var:
                constraints.append(
                    _cross_field_constraint(validation, self.state.collected_slots)
                )
            elif require_future:
                constraints.append("must be today or later")
            else:
                constraints.append("may be any date including past dates")

        instructions = current_node.data.get("instructions")
        if instructions:
            instructions = substitute_variables(instructions, self.state.collected_slots)

        return {
            "variable": var_key,
            "type": var_info.type.value,
            "description": var_info.description,
            "prompt": substitute_variables(
                str(slot.get("prompt") or ""), self.state.collected_slots, speakable=True
            ),
            "constraints": constraints if constraints else None,
            "instructions": instructions,
        }

    def get_current_node_instructions(self) -> Optional[str]:
        """Get instructions for the current node."""
        current_node = self.state.get_current_node()
        if current_node:
            return current_node.data.get("instructions")
        return None

    def get_greeting(self) -> str:
        """Get the initial greeting message."""
        # Speaking the greeting means the caller entered this flow (Task #543).
        self._flow_started = True
        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                return node.data.get("greeting", "Hello! How can I assist you?")
        return "Hello! How can I assist you?"

    def get_initial_messages(self) -> list[str]:
        """Get all initial messages, following auto-advance chain.

        If the initial node has waitForResponse=false, it will continue
        to get messages from connected nodes until one requires a response
        or reaches a node that collects input (collect_slot, end, transfer).
        """
        # Entering the initial node means the caller started this flow — its
        # durable snapshots are legitimate from here on (Task #543).
        self._flow_started = True
        messages = []
        initial_node = None

        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                initial_node = node
                break

        if not initial_node:
            return ["Hello! How can I assist you?"]

        messages.append(initial_node.data.get("greeting", "Hello! How can I assist you?"))

        await_response = initial_node.data.get("waitForResponse", True)
        # Enter the graph even when the initial greeting waits for the caller.
        # ``waitForResponse`` controls whether we continue the auto-walk and
        # speak downstream messages; it must not leave the state at INITIAL.
        # Otherwise the flow trigger stays exposed and a caller's already-known
        # slot values cannot advance to the next valid action.
        first_node = self.state.get_next_node(initial_node.id)
        if await_response:
            if first_node:
                self.state.advance_to(first_node.id)
            return messages

        # Guard against cycles: track every node ID we visit so a cycle of
        # waitForResponse=False nodes cannot spin forever.
        visited: set[str] = set()
        current_node = first_node
        while current_node:
            if current_node.id in visited:
                logger.error(
                    f"get_initial_messages: cycle detected at node "
                    f"{current_node.id!r} — breaking traversal."
                )
                break
            visited.add(current_node.id)

            if current_node.type in (NodeType.COLLECT_SLOT, NodeType.COLLECT_FORM):
                self.state.advance_to(current_node.id)
                if not self._node_has_uncollected_slot(current_node):
                    next_node = self.state.get_next_node(current_node.id)
                    if not next_node:
                        break
                    # advance_to evaluates CONDITION nodes server-side; continue
                    # from the actual branch destination, not the condition
                    # object itself.
                    self.state.advance_to(next_node.id)
                    current_node = self.state.get_current_node()
                    continue
            node_message = self._get_node_message(current_node)
            if node_message:
                messages.append(node_message)

            self.state.advance_to(current_node.id)

            if current_node.type in [
                NodeType.COLLECT_SLOT,
                NodeType.COLLECT_FORM,
                NodeType.END,
                NodeType.TRANSFER,
                NodeType.OPTION_PICKER,
            ]:
                break

            node_await = current_node.data.get("waitForResponse", True)
            if node_await:
                break

            current_node = self.state.get_next_node(current_node.id)

        return messages

    def _get_node_message(self, node: FlowNode) -> Optional[str]:
        """Extract the spoken message from a node based on its type."""
        if node.type == NodeType.MESSAGE:
            return substitute_variables(node.data.get("message", ""), self.state.collected_slots)
        elif node.type == NodeType.COLLECT_SLOT:
            slot = node.data.get("slot") or {}
            prompt = slot.get("prompt", "")
            # Apply speakable substitution so embedded variable references are
            # rendered in a caller-friendly form, not left as raw {{tokens}}.
            return substitute_variables(prompt, self.state.collected_slots, speakable=True) if prompt else ""
        elif node.type == NodeType.COLLECT_FORM:
            intro = node.data.get("introMessage", "")
            if intro:
                return substitute_variables(intro, self.state.collected_slots)
            first = self._first_uncollected_slot(node.data.get("slots", []))
            if first:
                prompt = first.get("prompt", "")
                return substitute_variables(prompt, self.state.collected_slots, speakable=True) if prompt else ""
        elif node.type == NodeType.END:
            return substitute_variables(
                node.data.get("closingMessage", "Thank you for calling. Goodbye!"),
                self.state.collected_slots,
            )
        elif node.type == NodeType.TRANSFER:
            transfer = node.data.get("transfer", {})
            return transfer.get("preTransferMessage", "Please hold while I transfer you.")
        elif node.type == NodeType.OPTION_PICKER:
            config = node.data.get("optionPicker", {}) or {}
            prompt = config.get("prompt", "")
            return substitute_variables(prompt, self.state.collected_slots, speakable=True) if prompt else ""
        return None

    def get_function_schemas(self) -> list[dict]:
        """Generate Pipecat-compatible function schemas from the flow.

        This creates functions for:
        1. Collecting slot variables - ONLY for the current/next collect node (enforces flow order)
        2. API requests
        3. Transfer calls
        4. Ending the call

        For collect_slot nodes: Only exposes the single slot function for that node
        For collect_form nodes: Exposes all slots in the form for flexible collection
        """
        functions = []

        # Only expose slot functions for the current collect node (strict flow order)
        current_node = self.state.get_current_node()

        # Determine which slot functions to expose based on current node type
        slots_to_expose = set()

        if current_node and current_node.type == NodeType.COLLECT_SLOT:
            # For collect_slot: only expose this single slot
            slot = current_node.data.get("slot", {})
            var_key = slot.get("variableKey")
            if var_key and var_key not in self.state.collected_slots:
                slots_to_expose.add(var_key)
        elif current_node and current_node.type == NodeType.COLLECT_FORM:
            # For collect_form: expose all uncollected slots in the form (flexible within form)
            form_slots = current_node.data.get("slots", [])
            for slot in form_slots:
                var_key = slot.get("variableKey")
                if var_key and var_key not in self.state.collected_slots:
                    slots_to_expose.add(var_key)
        elif current_node and current_node.type in _ACTION_NODE_TYPES:
            # Sitting on an action node (SAVE_RECORD, API_REQUEST, ROUTER, etc.) — the
            # action must fire before any downstream collect slot is reachable.
            # Exposing a downstream slot here lets the LLM call it first, which advances
            # the flow state past the action node without it ever executing.
            # Leave slots_to_expose empty; only the action tool itself will be in the list.
            pass
        else:
            # Not on a collect node - find next reachable collect node
            next_collect_node, next_var_key = self._find_next_reachable_collect_slot()
            if next_collect_node:
                if next_collect_node.type == NodeType.COLLECT_SLOT:
                    if next_var_key and next_var_key not in self.state.collected_slots:
                        slots_to_expose.add(next_var_key)
                elif next_collect_node.type == NodeType.COLLECT_FORM:
                    # Expose all form slots
                    form_slots = next_collect_node.data.get("slots", [])
                    for slot in form_slots:
                        var_key = slot.get("variableKey")
                        if var_key and var_key not in self.state.collected_slots:
                            slots_to_expose.add(var_key)

        # Create function schemas only for slots we should expose
        for var in self.flow_config.variables:
            if var.key in slots_to_expose:
                func_schema = self._create_slot_function(var)
                functions.append(func_schema)

        # Gate action-node functions to the reachable flow position, mirroring the
        # slot-function gating above. Without this, end_call_<id> / transfer_<id>
        # (and every api/router/confirmation/set_var/save_record function) would be
        # callable on every turn, letting the LLM end or branch the call mid-
        # collection — the root cause of premature hang-ups.
        reachable_action_ids = self._get_reachable_action_node_ids()

        for node in self.flow_config.nodes:
            if node.id not in reachable_action_ids:
                continue
            if node.type in (NodeType.API_REQUEST, NodeType.CAPABILITY):
                functions.append(self._create_api_function(node))
            elif node.type == NodeType.ROUTER:
                functions.append(self._create_router_function(node))
            elif node.type == NodeType.CONFIRMATION:
                functions.append(self._create_confirmation_function(node))
            elif node.type == NodeType.SET_VARIABLE:
                functions.append(self._create_set_variable_function(node))
            elif node.type == NodeType.SAVE_RECORD:
                functions.append(self._create_save_record_function(node))
            elif node.type == NodeType.TRANSFER:
                functions.append(self._create_transfer_function(node))
            elif node.type == NodeType.END:
                functions.append(self._create_end_function(node))
            elif node.type == NodeType.OPTION_PICKER:
                functions.append(self._create_option_picker_function(node))

        # Give a "stuck" waiting MESSAGE node (see
        # _get_pending_message_advance_node) an explicit, real function to
        # call so the LLM is never left improvising with zero flow tools —
        # the root structural cause of Task #600's fake-confirmation bug.
        pending_message_node = self._get_pending_message_advance_node()
        if pending_message_node is not None:
            functions.append(self._create_message_continue_function(pending_message_node))

        # API_RESPONSE nodes expose a continue_response_<id> function so the
        # LLM (or simulator) can explicitly advance past the narration step.
        pending_response_node = self._get_pending_api_response_node()
        if pending_response_node is not None:
            functions.append(self._create_api_response_continue_function(pending_response_node))

        has_confirmation_node = any(
            node.type == NodeType.CONFIRMATION for node in self.flow_config.nodes
        )
        if not has_confirmation_node and self._should_expose_confirm_details(current_node):
            functions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "confirm_details",
                        "description": "Confirm the collected details with the customer after all information is gathered. Summarize all collected information in plain text (no markdown or special formatting) and ask the customer to confirm.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "confirmed": {
                                    "type": "boolean",
                                    "description": "True if the customer confirms all details are correct. False if they want a change — also populate field_to_change and new_value if the customer specified what to correct in the same message.",
                                },
                                "field_to_change": {
                                    "type": "string",
                                    "description": "When confirmed is False and the customer specified which field to correct, the variable key of that field (e.g. 'name', 'room_number'). Omit if the customer did not specify.",
                                },
                                "new_value": {
                                    "type": "string",
                                    "description": "The corrected value for field_to_change. Only set when field_to_change is also set.",
                                },
                            },
                            "required": ["confirmed"],
                        },
                    },
                }
            )

        return functions

    def _should_expose_confirm_details(self, current_node) -> bool:
        """Gate the built-in confirm_details fallback (flows WITHOUT a CONFIRMATION node).

        Previously this fallback was exposed ungated on every turn, so after the
        caller declined an optional slot ("no thank you") the LLM could call
        confirm_details instead of the collect function — the handler returned
        "Great, confirmed." without advancing flow state, looping the bot back
        into re-summarizing and re-asking. Only expose it when:
        - all required variables are collected (there is something to confirm),
        - the flow has not already moved past collection into an action/end node
          (those must fire, not re-confirm), and
        - no successful confirmation has already happened this session.
        """
        if self._details_confirmed:
            return False
        if current_node is not None and current_node.type in _ACTION_NODE_TYPES:
            return False
        required_keys = [v.key for v in self.flow_config.variables if v.required]
        if not required_keys:
            return False
        return all(key in self.state.collected_slots for key in required_keys)

    def get_all_function_schemas(self) -> list[dict]:
        """Generate ALL function schemas from the flow (for handler registration).

        Unlike get_function_schemas() which only returns the current slot,
        this method returns ALL possible functions. Use this at initialization
        to register all handlers, while get_function_schemas() is used for
        dynamic tool updates.
        """
        functions = []

        for var in self.flow_config.variables:
            func_schema = self._create_slot_function(var)
            functions.append(func_schema)

        for node in self.flow_config.nodes:
            if node.type in (NodeType.API_REQUEST, NodeType.CAPABILITY):
                func_schema = self._create_api_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.ROUTER:
                func_schema = self._create_router_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.CONFIRMATION:
                func_schema = self._create_confirmation_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.SET_VARIABLE:
                func_schema = self._create_set_variable_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.SAVE_RECORD:
                func_schema = self._create_save_record_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.TRANSFER:
                func_schema = self._create_transfer_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.END:
                func_schema = self._create_end_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.OPTION_PICKER:
                func_schema = self._create_option_picker_function(node)
                functions.append(func_schema)
            elif (
                node.type == NodeType.MESSAGE
                and node.data.get("waitForResponse", True)
                and self.state.has_outgoing_edge(node.id)
            ):
                # Registered unconditionally for every waiting MESSAGE node
                # that has somewhere to advance to (handler must exist);
                # get_function_schemas() only exposes it when the node is
                # actually "stuck" (see _get_pending_message_advance_node).
                # Terminal MESSAGE nodes (no outgoing edge) never need this —
                # arriving there already marks the flow exhausted.
                functions.append(self._create_message_continue_function(node))
            elif node.type == NodeType.API_RESPONSE:
                # Registered for every API_RESPONSE node (handler must always
                # exist); get_function_schemas() only exposes it when the node
                # is actually current (_get_pending_api_response_node).
                functions.append(self._create_api_response_continue_function(node))

        has_confirmation_node = any(
            node.type == NodeType.CONFIRMATION for node in self.flow_config.nodes
        )
        if not has_confirmation_node:
            functions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "confirm_details",
                        "description": "Confirm the collected details with the customer after all information is gathered.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "confirmed": {
                                    "type": "boolean",
                                    "description": "True if the customer confirms all details are correct. False if they want a change — also populate field_to_change and new_value if the customer specified what to correct in the same message.",
                                },
                                "field_to_change": {
                                    "type": "string",
                                    "description": "When confirmed is False and the customer specified which field to correct, the variable key of that field (e.g. 'name', 'room_number'). Omit if the customer did not specify.",
                                },
                                "new_value": {
                                    "type": "string",
                                    "description": "The corrected value for field_to_change. Only set when field_to_change is also set.",
                                },
                            },
                            "required": ["confirmed"],
                        },
                    },
                }
            )

        return functions

    def _create_slot_function(self, var: FlowVariable) -> dict:
        """Create a function schema for collecting a slot."""
        validation = self._get_validation_for_variable(var.key) or {}

        # Choice options may live on the flow-level variable (var.choices) OR on
        # the collecting node's slot.validation.choices (the editor stores them
        # there). Fall back to the node's list so choice slots always present an
        # enum to the LLM instead of a free-text parameter.
        choice_options = var.choices or validation.get("choices")

        if var.type == SlotType.CHOICE and choice_options:
            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            var.key: {
                                "type": "string",
                                "enum": choice_options,
                                "description": var.description,
                            }
                        },
                        "required": [var.key],
                    },
                },
            }

        if var.type == SlotType.NUMBER:
            param_schema = {"type": "integer", "description": var.description}
            if validation:
                if "min" in validation:
                    param_schema["minimum"] = validation["min"]
                if "max" in validation:
                    param_schema["maximum"] = validation["max"]
            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {var.key: param_schema},
                        "required": [var.key],
                    },
                },
            }

        if var.type == SlotType.DATE:
            now = datetime.now(self._timezone)
            current_date = now.strftime("%Y-%m-%d")

            after_date_var = validation.get("cross_field_variable")
            after_date_str = None
            if after_date_var and hasattr(self, "state"):
                after_date_str = self.state.get_variable(after_date_var)

            require_future = validation.get(
                "requireFuture", validation.get("require_future", True)
            )
            if after_date_var:
                date_constraint = _cross_field_constraint(
                    validation, self.state.collected_slots
                )
            elif require_future:
                date_constraint = f"must be today ({current_date}) or later"
            else:
                date_constraint = "may be any date including past dates"

            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}. Constraint: {date_constraint}. Accept any reasonable date format the caller provides and convert to YYYY-MM-DD internally.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            var.key: {
                                "type": "string",
                                "description": f"{var.description} ({date_constraint})",
                            }
                        },
                        "required": [var.key],
                    },
                },
            }

        return {
            "type": "function",
            "function": {
                "name": f"collect_{var.key}",
                "description": f"Record the {var.description}",
                "parameters": {
                    "type": "object",
                    "properties": {var.key: {"type": "string", "description": var.description}},
                    "required": [var.key],
                },
            },
        }

    def _create_api_function(self, node: FlowNode) -> dict:
        """Create a function schema for an API request node."""
        api_config = node.data.get("api", {})
        thinking_message = (api_config.get("thinkingMessage") or "").strip()
        node_name = node.data.get("name", node.id)
        description = f"Execute the '{node_name}' API call."
        if thinking_message:
            description += f' While executing, say to the customer: "{thinking_message}".'
        return {
            "type": "function",
            "function": {
                "name": f"execute_{node.id}",
                "description": description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _create_transfer_function(self, node: FlowNode) -> dict:
        """Create a function schema for a transfer node."""
        transfer_data = node.data.get("transfer", {})
        return {
            "type": "function",
            "function": {
                "name": f"transfer_{node.id}",
                "description": f"Transfer call: {node.data.get('name', 'to agent')}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string", "description": "Reason for the transfer"}
                    },
                    "required": [],
                },
            },
        }

    def _create_end_function(self, node: FlowNode) -> dict:
        """Create a function schema for an end node."""
        return {
            "type": "function",
            "function": {
                "name": f"end_call_{node.id}",
                "description": f"End the call: {node.data.get('name', 'End Call')}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _create_router_function(self, node: FlowNode) -> dict:
        """Create a function schema for a router node."""
        router_data = node.data.get("router", {})
        variable = router_data.get("variable", "choice")
        options = router_data.get("options", [])

        option_values = [opt.get("value", "") for opt in options if opt.get("value")]
        option_labels = [opt.get("label", opt.get("value", "")) for opt in options]

        description = f"Route the conversation based on {variable}. "
        if option_labels:
            description += f"Options: {', '.join(option_labels)}"

        return {
            "type": "function",
            "function": {
                "name": f"route_{node.id}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "choice": {
                            "type": "string",
                            "enum": option_values if option_values else ["default"],
                            "description": f"The selected option for {variable}",
                        }
                    },
                    "required": ["choice"],
                },
            },
        }

    def _create_confirmation_function(self, node: FlowNode) -> dict:
        """Create a function schema for a confirmation node."""
        confirmation_data = node.data.get("confirmation", {})
        summary_template = confirmation_data.get(
            "summaryTemplate", confirmation_data.get("summary_template", "")
        )
        confirm_prompt = confirmation_data.get(
            "confirmPrompt", confirmation_data.get("confirm_prompt", "")
        )
        variables_to_confirm = confirmation_data.get(
            "variablesToConfirm", confirmation_data.get("variables_to_confirm", [])
        )

        # Coerce each item to str so non-string editor data (ints, bools) does
        # not raise TypeError in join.
        var_list = ", ".join(str(v) for v in variables_to_confirm) if variables_to_confirm else "collected details"

        resolved_summary = (
            substitute_variables(summary_template, self.state.collected_slots)
            if summary_template
            else ""
        )
        resolved_confirm = (
            substitute_variables(confirm_prompt, self.state.collected_slots)
            if confirm_prompt
            else ""
        )

        description = f"Confirm or edit {var_list}. "
        if resolved_summary:
            description += f'First say exactly: "{resolved_summary}" '
        if resolved_confirm:
            description += f'Then ask: "{resolved_confirm}"'
        else:
            description += "Then ask if this is correct."

        return {
            "type": "function",
            "function": {
                "name": f"confirm_{node.id}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confirmed": {
                            "type": "boolean",
                            "description": "True if the customer confirms all details are correct. False if they want a change — also populate field_to_change and new_value if the customer specified what to correct in the same message.",
                        },
                        "field_to_change": {
                            "type": "string",
                            "description": "When confirmed is False and the customer specified which field to correct, the variable key of that field (e.g. 'name', 'room_number'). Omit if the customer did not specify.",
                        },
                        "new_value": {
                            "type": "string",
                            "description": "The corrected value for field_to_change. Only set when field_to_change is also set.",
                        },
                    },
                    "required": ["confirmed"],
                },
            },
        }

    def _create_set_variable_function(self, node: FlowNode) -> dict:
        """Create a function schema for a set variable node."""
        set_var_data = node.data.get("setVariable", node.data.get("set_variable", {}))
        var_key = set_var_data.get("variableKey", set_var_data.get("variable_key", "variable"))

        return {
            "type": "function",
            "function": {
                "name": f"set_var_{node.id}",
                "description": f"Set the value of {var_key}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _create_save_record_function(self, node: FlowNode) -> dict:
        """Create a function schema for a save record node (voice-only)."""
        save_data = node.data.get("saveRecord", node.data.get("save_record", {}))
        record_type_name = save_data.get("recordTypeName") or node.data.get("name") or "record"
        return {
            "type": "function",
            "function": {
                "name": f"save_record_{node.id}",
                "description": (
                    f"Save the collected information as a '{record_type_name}' record. "
                    "Call this once the details for this record have been gathered."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _create_message_continue_function(self, node: FlowNode) -> dict:
        """Create a function schema that advances past a waiting MESSAGE node.

        Exposed only when the node is "stuck" (see
        ``_get_pending_message_advance_node``) — the LLM otherwise has no
        flow tool to call once it has delivered the message and heard the
        caller's reply. Calling it moves the flow to whatever comes next
        (or marks the flow exhausted when this was the last node), instead
        of leaving the model to improvise or fabricate an outcome.
        """
        return {
            "type": "function",
            "function": {
                "name": f"continue_flow_{node.id}",
                "description": (
                    "Call this immediately after you have delivered the current "
                    "message above (and received any reply from the caller), so "
                    "the flow can proceed. Call it every time you reach this "
                    "point — do not skip it, and do not describe any outcome "
                    "(such as a completed booking or reservation) that this "
                    "function does not itself confirm."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def handle_function_call(self, function_name: str, arguments: dict) -> dict:
        """Handle a function call from the LLM, then durably snapshot state.

        Dispatches to the concrete handler, then persists the resulting flow
        state (current node + collected slots) to ``flow_sessions`` so a
        websocket dropout / reconnect can resume where the caller left off
        (Task #330). The snapshot is best-effort and post-dispatch: a snapshot
        failure never affects the caller-facing result.

        Returns a result dict with:
        - success: bool
        - message: str (to speak to the customer)
        - action: Optional action type (transfer, end, etc.)
        """
        # Deadlock-prevention: execute_/save_record_ handlers release _turn_lock
        # during slow I/O via _suspend_turn_lock while still holding the per-node
        # dedup lock (_non_get_locks, _get_locks, _save_record_locks).  If a
        # concurrent same-node call acquired _turn_lock first and then waited for
        # the per-node lock, neither could proceed (AB-BA deadlock).
        #
        # Fix: acquire a per-node *entry* lock BEFORE _turn_lock for execute_/
        # save_record_ calls.  This serialises same-node calls at the outermost
        # level; the inner dedup locks are then single-holder and safe.
        # Invariant (never reversed): per-node entry lock → _turn_lock.
        if function_name.startswith("execute_"):
            _en_id = function_name[len("execute_"):]
            _entry_lock: Optional[asyncio.Lock] = self._execute_entry_locks.setdefault(
                _en_id, asyncio.Lock()
            )
        elif function_name.startswith("save_record_"):
            _sr_id = function_name[len("save_record_"):]
            _entry_lock = self._save_record_locks.setdefault(_sr_id, asyncio.Lock())
        else:
            _entry_lock = None

        if _entry_lock is not None:
            async with _entry_lock:
                async with self._turn_lock:
                    result = await self._dispatch_function_call(function_name, arguments)
        else:
            async with self._turn_lock:
                result = await self._dispatch_function_call(function_name, arguments)
        # A function of THIS flow was accepted — the caller is in this flow, so
        # its durable snapshots are legitimate from here on (Task #543). A
        # rejected call (stale/out-of-order action, unknown function) must NOT
        # mark the flow started: all handlers stay registered even when their
        # schemas are not exposed, so a stray tool call aimed at an unentered
        # flow would otherwise start persisting its session.
        if not (
            isinstance(result, dict)
            and (
                result.get("out_of_order")
                or result.get("message") == "Unknown function"
            )
        ):
            self._flow_started = True
        # Live↔simulator parity: attach the now-active node's guidance to every
        # non-terminal result so the live LLM receives per-node instructions at
        # the moment that node becomes current (the simulator gets the same
        # block via its per-turn system prompt rebuild).
        if isinstance(result, dict) and result.get("action") not in ("transfer", "end"):
            if "current_node_context" not in result:
                try:
                    node_context = self._get_current_node_context()
                except Exception as exc:  # noqa: BLE001 - guidance is best-effort
                    logger.warning(f"current_node_context enrichment failed (non-fatal): {exc}")
                    node_context = None
                if node_context:
                    result["current_node_context"] = node_context
        await self._sync_saved_records()
        # Cancel any pending notify-driven snapshot before writing the
        # authoritative post-dispatch snapshot. A notify task scheduled before
        # this dispatch captured pre-advance state; cancelling it ensures it
        # cannot land in the DB after our write and silently rewind the flow.
        pending = self._pending_notify_snapshot
        if pending is not None and not pending.done():
            pending.cancel()
        self._pending_notify_snapshot = None
        await self._snapshot_state()
        return result

    async def _dispatch_function_call(self, function_name: str, arguments: dict) -> dict:
        """Route a function call to its concrete handler (no persistence)."""
        action_prefixes = (
            "execute_",
            "route_",
            "confirm_",
            "set_var_",
            "save_record_",
            "transfer_",
            "end_call_",
            "continue_flow_",
            "continue_response_",
            "select_option_",
        )
        if function_name.startswith(action_prefixes):
            exposed = {
                schema.get("function", schema)["name"]
                for schema in self.get_function_schemas()
            }
            if function_name not in exposed:
                return {
                    "success": False,
                    "message": "That flow action is not currently reachable.",
                    "action": None,
                    "out_of_order": True,
                    "current_node_id": self.state.current_node_id,
                }
        if function_name.startswith("collect_"):
            return await self._handle_slot_collection(function_name, arguments)
        elif function_name.startswith("execute_"):
            return await self._handle_api_request(function_name, arguments)
        elif function_name.startswith("route_"):
            return await self._handle_router(function_name, arguments)
        elif function_name == "confirm_details":
            return await self._handle_confirm_details(arguments)
        elif function_name.startswith("confirm_"):
            return await self._handle_confirmation(function_name, arguments)
        elif function_name.startswith("set_var_"):
            return await self._handle_set_variable(function_name, arguments)
        elif function_name.startswith("save_record_"):
            return await self._handle_save_record(function_name, arguments)
        elif function_name.startswith("transfer_"):
            return await self._handle_transfer(function_name, arguments)
        elif function_name.startswith("end_call_"):
            return await self._handle_end_call(function_name, arguments)
        elif function_name.startswith("continue_flow_"):
            return await self._handle_message_continue(function_name, arguments)
        elif function_name.startswith("continue_response_"):
            return await self._handle_api_response(function_name, arguments)
        elif function_name.startswith("select_option_"):
            return await self._handle_option_picker(function_name, arguments)
        else:
            return {"success": False, "message": "Unknown function", "action": None}

    def _render_api_response_text(self, node: FlowNode) -> str:
        """Render the complete spoken narration for an API_RESPONSE node.

        Iterates over the configured array variable (parsed as JSON if stored
        as a string), applies the per-item template to each element, and
        returns the combined text: intro → item narrations → outro.  Falls
        back to ``noResultsText`` when the array is empty or not found.
        """
        import json as _json

        config = node.data.get("responsePresentation", {}) or {}
        array_var = (config.get("arrayVariable") or "").strip()
        intro = substitute_variables(
            (config.get("introText") or "").strip(), self.state.collected_slots
        )
        item_template = (config.get("itemTemplate") or "").strip()
        outro = substitute_variables(
            (config.get("outroText") or "").strip(), self.state.collected_slots
        )
        no_results = substitute_variables(
            (config.get("noResultsText") or "No results were found.").strip(),
            self.state.collected_slots,
        )

        items: list = []
        if array_var:
            raw = self.state.collected_slots.get(array_var)
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, str):
                try:
                    parsed = _json.loads(raw)
                    if isinstance(parsed, list):
                        items = parsed
                except Exception:
                    pass

        if not items:
            if array_var:
                # Array variable configured but resolved to empty/None —
                # the caller should hear the no-results message.
                return no_results
            # No array variable configured at all — speak intro + outro as a
            # fixed narration (e.g. "Your booking is confirmed. Goodbye!").
            direct_parts = [p for p in [intro, outro] if p]
            return " ".join(direct_parts) if direct_parts else no_results

        parts: list[str] = []
        if intro:
            parts.append(intro)

        for i, item in enumerate(items):
            if item_template:
                rendered = self._substitute_template_variables_indexed(
                    item_template, item, self.state.collected_slots, i
                )
                if rendered:
                    parts.append(rendered)
            else:
                # Fallback: render item as a natural string.
                if isinstance(item, dict):
                    kv = ", ".join(
                        f"{k}: {_speakable_variable_value(v)}"
                        for k, v in list(item.items())[:5]
                    )
                    parts.append(kv)
                else:
                    parts.append(_speakable_variable_value(item))

        if outro:
            parts.append(outro)

        return " ".join(p for p in parts if p)

    def _substitute_template_variables_indexed(
        self,
        template: str,
        item: Any,
        variables: dict,
        index: int,
    ) -> str:
        """Substitute ``{{variable}}`` refs in a per-item loop template.

        Merges the item's own fields (when it is a dict) into the substitution
        namespace on top of the flow's collected slots.  Special tokens:
        ``{{index}}`` → 1-based ordinal, ``{{item}}`` → str(item) for
        non-dict items.
        """
        merged: dict[str, Any] = dict(variables)
        merged["index"] = str(index + 1)
        if isinstance(item, dict):
            merged.update({k: v for k, v in item.items()})
        else:
            merged["item"] = item
        return substitute_variables(template, merged, speakable=True)

    def _get_pending_api_response_node(self) -> Optional[FlowNode]:
        """Return the current node when it is an API_RESPONSE node.

        Used by ``get_function_schemas`` to expose ``continue_response_<id>``
        so the LLM (or simulator) can explicitly advance past the presentation
        step when the function_mapper auto-execution path is not in play (e.g.
        in the simulator where the LLM must explicitly call the function after
        the narration is delivered).
        """
        current = self.state.get_current_node()
        if current and current.type == NodeType.API_RESPONSE:
            return current
        return None

    def _create_api_response_continue_function(self, node: FlowNode) -> dict:
        """Create a function schema that advances past an API_RESPONSE node."""
        config = node.data.get("responsePresentation", {}) or {}
        array_var = (config.get("arrayVariable") or "").strip()
        array_desc = f" presenting '{array_var}'" if array_var else ""
        return {
            "type": "function",
            "function": {
                "name": f"continue_response_{node.id}",
                "description": (
                    f"Call this after the API response has been presented to the caller"
                    f"{array_desc}. The platform will have already spoken the result "
                    "directly — call this function to acknowledge and advance the flow."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _api_response_has_results(self, node: FlowNode) -> bool:
        """Return True when the node's array variable resolves to a non-empty list.

        Used by ``_handle_api_response`` to pick the correct output handle
        (``has_results`` vs ``no_results``) for branching.  Fixed-narration
        mode (no arrayVariable configured) is treated as "has results" so the
        flow always continues forward on the default path.
        """
        import json as _json

        config = node.data.get("responsePresentation", {}) or {}
        array_var = (config.get("arrayVariable") or "").strip()
        if not array_var:
            # No array variable — fixed narration, always "has results".
            return True
        raw = self.state.collected_slots.get(array_var)
        if isinstance(raw, list):
            return len(raw) > 0
        if isinstance(raw, str):
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    return len(parsed) > 0
            except Exception:
                pass
        return False

    async def _handle_api_response(self, function_name: str, arguments: dict) -> dict:
        """Advance the flow past an API_RESPONSE node.

        Routes via the ``has_results`` or ``no_results`` source handle so
        designers can wire different downstream paths for each case.  Falls
        back to any unlabelled edge for backward compatibility with flows
        built before dual-handle support was added.
        """
        node_id = function_name[len("continue_response_"):]
        node = self.flow_config._node_index.get(node_id)
        if not node or node.type != NodeType.API_RESPONSE:
            return {"success": False, "message": "Unknown response node", "action": None}
        if self.state.current_node_id != node_id:
            return {
                "success": False,
                "message": "That API response is not currently ready to continue.",
                "action": None,
                "out_of_order": True,
                "current_node_id": self.state.current_node_id,
            }

        has_results = self._api_response_has_results(node)
        handle = "has_results" if has_results else "no_results"

        # Try the specific handle first; fall back to an unlabelled edge so
        # flows built before dual-handle support still advance normally.
        next_node = self.state.get_next_node(node_id, handle=handle)
        if not next_node:
            next_node = self.state.get_unlabelled_next_node(node_id)

        if next_node:
            self.state.advance_to(next_node.id)
        else:
            self.state.advance_to(node_id)

        return {
            "success": True,
            "message": "Response presented.",
            "has_results": has_results,
            "action": None,
            "current_node_id": self.state.current_node_id,
        }

    def _create_option_picker_function(self, node: FlowNode) -> dict:
        """Create a function schema for an OPTION_PICKER node.

        Exposes ``ordinal`` (1-based position in the presented list) and
        ``label`` (the caller's spoken description) as alternative ways to
        resolve the same underlying choice — the handler tries ordinal
        first, then falls back to label matching. When the source array is
        already resolvable, bounding ``ordinal`` to the live item count
        gives the LLM a concrete range instead of letting it guess.
        """
        config = node.data.get("optionPicker", {}) or {}
        node_name = node.data.get("name") or "option"
        items = self._resolve_option_picker_items(config)

        ordinal_schema: dict = {
            "type": "integer",
            "description": (
                "The 1-based position of the caller's choice in the presented "
                "list (e.g. 2 for \"the second one\")."
            ),
        }
        if items:
            ordinal_schema["minimum"] = 1
            ordinal_schema["maximum"] = len(items)

        return {
            "type": "function",
            "function": {
                "name": f"select_option_{node.id}",
                "description": (
                    f"Record the caller's selection for {node_name}. Call this only "
                    "once the caller's choice is clear — by position (\"the first "
                    "one\") or by name. Provide ordinal, label, or both. Never guess "
                    "if the caller hasn't actually indicated which one they want."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ordinal": ordinal_schema,
                        "label": {
                            "type": "string",
                            "description": (
                                "The caller's spoken name for the chosen item, as "
                                "close to verbatim as possible."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        }

    def _resolve_option_picker_items(self, config: dict) -> list:
        """Resolve an OPTION_PICKER node's source array to a concrete list.

        Mirrors the array resolution used by API_RESPONSE nodes: the configured
        variable may hold a real list or a JSON-encoded string (both are valid
        shapes produced by response-mapping). Returns [] for anything else so
        callers can treat "no items" and "not yet resolved" identically.
        """
        source_var = (config.get("sourceVariable") or "").strip()
        if not source_var:
            return []
        raw = self.state.collected_slots.get(source_var)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return []

    def _resolve_option_picker_choice(
        self, items: list, config: dict, arguments: dict
    ) -> tuple[Optional[tuple[int, Any]], bool]:
        """Resolve the caller's spoken choice to exactly one (index, item) pair.

        Tries ``ordinal`` first (deterministic 1-based position), then falls
        back to ``label`` matched against each item's ``labelPath`` field —
        first an exact case-insensitive match, then a substring match at each
        stage. Returns ``(None, True)`` when a stage matches more than one
        item (genuinely ambiguous — this never guesses), and ``(None, False)``
        when nothing matches at all or the arguments were unusable.
        """
        raw_ordinal = arguments.get("ordinal")
        if isinstance(raw_ordinal, bool):
            raw_ordinal = None  # bool is an int subclass in Python — reject it
        if isinstance(raw_ordinal, (int, float)):
            ordinal = int(raw_ordinal)
            if 1 <= ordinal <= len(items):
                return (ordinal - 1, items[ordinal - 1]), False

        raw_label = arguments.get("label")
        label_path = (config.get("labelPath") or "").strip()
        if isinstance(raw_label, str) and raw_label.strip() and label_path:
            needle = raw_label.strip().lower()

            def _label_of(item: Any) -> Optional[str]:
                value = _get_by_path(item, label_path)
                return value.strip().lower() if isinstance(value, str) else None

            exact = [
                (i, it) for i, it in enumerate(items) if _label_of(it) == needle
            ]
            if len(exact) == 1:
                return exact[0], False
            if len(exact) > 1:
                return None, True

            contains = [
                (i, it)
                for i, it in enumerate(items)
                if (lambda lbl: lbl is not None and needle in lbl)(_label_of(it))
            ]
            if len(contains) == 1:
                return contains[0], False
            if len(contains) > 1:
                return None, True

        return None, False

    @staticmethod
    def _option_picker_max_retries(config: dict) -> int:
        """Resolve the retry budget for an OPTION_PICKER (editor ``maxRetries``, default 3)."""
        raw = (config or {}).get("maxRetries")
        if isinstance(raw, int) and raw > 0:
            return raw
        return 3

    def _handle_option_picker_retry_exhaustion(self, node_id: str, node_name: str) -> dict:
        """Give up on a selection after ``maxRetries`` failed attempts.

        Mirrors ``_handle_retry_exhaustion``'s priority order (fallback branch
        → escalation → graceful end) so an Option Picker that can't resolve
        the caller's choice degrades exactly like a stuck slot collection,
        never leaving the call stuck in a silent retry loop.
        """
        fallback_target = None
        for edge in self.flow_config.edges:
            if edge.source == node_id and edge.source_handle == "fallback":
                fallback_target = edge.target
                break

        if fallback_target:
            self.state.advance_to(fallback_target)
            return {
                "success": False,
                "action": None,
                "retry_exhausted": True,
                "current_node_id": self.state.current_node_id,
                "message": f"I'm having trouble narrowing down your {node_name.lower()}. Let's move on.",
            }

        if self.escalation_target:
            self.state.transfer_requested = True
            self.state.transfer_target = self.escalation_target
            return {
                "success": False,
                "action": "transfer",
                "target": self.escalation_target,
                "transfer_mode": "warm",
                "retry_exhausted": True,
                "message": (
                    f"I'm having trouble narrowing down your {node_name.lower()}. "
                    "Let me connect you with someone who can help."
                ),
            }

        self.state.is_complete = True
        return {
            "success": False,
            "action": "end",
            "retry_exhausted": True,
            "message": (
                f"I'm sorry, I wasn't able to confirm your {node_name.lower()}. "
                "Please try again later or reach out to us for help."
            ),
        }

    async def _handle_option_picker(self, function_name: str, arguments: dict) -> dict:
        """Bind the caller's chosen item from a presented list to flow variables.

        Resolves the caller's choice (by 1-based ordinal, by spoken label, or
        both) against the node's configured source array, then atomically
        writes every configured ``writes`` mapping from the single matched
        item — every declared destination variable is (re)written on every
        successful call, including ``None`` for a field the chosen item
        doesn't have. That makes re-selection (the caller changes their mind
        and this node fires again later) safe by construction: a later choice
        can never leave behind a stale field from an earlier one, without any
        extra bookkeeping of "what was bound last time".
        """
        node_id = function_name[len("select_option_"):]
        node = self.flow_config._node_index.get(node_id)
        if not node or node.type != NodeType.OPTION_PICKER:
            return {"success": False, "message": "Unknown option picker node", "action": None}

        if self.state.current_node_id != node_id:
            return {
                "success": False,
                "message": "That selection is not currently available.",
                "action": None,
                "out_of_order": True,
                "current_node_id": self.state.current_node_id,
            }

        config = node.data.get("optionPicker", {}) or {}
        items = self._resolve_option_picker_items(config)
        node_name = node.data.get("name") or "option"

        if not items:
            # Structural problem (the upstream step produced no options), not a
            # caller mistake — never charged against the retry budget.
            logger.warning(
                f"_handle_option_picker node {node_id!r}: source variable "
                f"{config.get('sourceVariable')!r} resolved to no items"
            )
            return {
                "success": False,
                "action": None,
                "current_node_id": node_id,
                "message": "I don't have any options to choose from right now.",
            }

        match, ambiguous = self._resolve_option_picker_choice(items, config, arguments)

        if match is None:
            self.state.retry_count += 1
            if self.state.retry_count >= self._option_picker_max_retries(config):
                return self._handle_option_picker_retry_exhaustion(node_id, node_name)
            if ambiguous:
                retry_message = (
                    "More than one option matches that — could you give me the "
                    "number of the one you'd like?"
                )
            else:
                retry_prompt = (config.get("retryPrompt") or "").strip()
                retry_message = (
                    substitute_variables(retry_prompt, self.state.collected_slots)
                    if retry_prompt
                    else "I didn't catch which option you'd like — could you repeat that, by name or number?"
                )
            return {
                "success": False,
                "action": None,
                "current_node_id": node_id,
                "message": retry_message,
            }

        index, item = match

        # Build the full write-set before touching any state. If resolving a
        # path were ever to raise, nothing would have been written yet — the
        # same all-or-nothing guarantee the router/confirmation handlers rely
        # on for their own state mutations.
        writes = config.get("writes", []) or []
        bound: dict[str, Any] = {}
        for entry in writes:
            var_key = (entry or {}).get("variableKey")
            if not var_key:
                continue
            bound[var_key] = _get_by_path(item, entry.get("path", ""))

        for var_key, value in bound.items():
            self.state.set_variable(var_key, value)

        self.state.retry_count = 0

        next_node = self.state.get_next_node(node_id, handle="selected")
        if not next_node:
            next_node = self.state.get_unlabelled_next_node(node_id)
        next_node_id = next_node.id if next_node else node_id
        if next_node:
            self.state.advance_to(next_node.id)

        # If selecting lands straight on END/TRANSFER, execute it rather than
        # merely surfacing its message text (Task #534 completion-review fix,
        # applied here for consistency with router/confirmation/set_variable).
        terminal_result = await self._maybe_execute_terminal_transition(next_node)
        if terminal_result is not None:
            return terminal_result

        result: dict = {
            "success": True,
            "action": None,
            "current_node_id": next_node_id,
            "selected_index": index + 1,
            "bound": bound,
        }

        next_node_message, is_static = (
            self._get_next_node_configured_message(next_node) if next_node else (None, False)
        )
        if next_node_message:
            result["message"] = next_node_message
            result["speak_directly"] = True
            if is_static:
                result["speak_exactly"] = next_node_message
        else:
            label_path = (config.get("labelPath") or "").strip()
            label = _get_by_path(item, label_path) if label_path else None
            confirm_label = label if isinstance(label, str) and label else f"option {index + 1}"
            result["message"] = f"Got it — {confirm_label}."

        return result

    async def _handle_message_continue(self, function_name: str, arguments: dict) -> dict:
        """Advance past a "stuck" waiting MESSAGE node (Task #600).

        The node itself carries no data to record — this simply acknowledges
        that its message was delivered and moves the flow to whatever comes
        next, or marks the flow exhausted when this was the last node.
        Reachability (the node must currently be the pending one) is already
        enforced by the ``exposed`` check in ``_dispatch_function_call``.
        """
        node_id = function_name[len("continue_flow_"):]
        node = self.flow_config._node_index.get(node_id)
        if not node:
            return {"success": False, "message": "Unknown flow node", "action": None}

        next_node = self.state.get_next_node(node_id)
        if next_node:
            self.state.advance_to(next_node.id)
        else:
            # No outgoing edge — this was the last node in the graph.
            # advance_to() marks the flow exhausted when it lands somewhere
            # with no further edges, so re-affirming the current position
            # reuses that exact, already-tested logic.
            self.state.advance_to(node_id)

        return {
            "success": True,
            "message": "Continued.",
            "action": None,
            "current_node_id": self.state.current_node_id,
        }

    async def _handle_slot_collection(self, function_name: str, arguments: dict) -> dict:
        """Handle collecting a slot value."""
        var_key = function_name.replace("collect_", "")

        if var_key in arguments:
            value = arguments[var_key]

            var_info = None
            for var in self.flow_config.variables:
                if var.key == var_key:
                    var_info = var
                    break

            collecting_node_id = None
            slot_config = None

            current_node = self.state.get_current_node()
            if current_node and current_node.type == NodeType.COLLECT_SLOT:
                slot = current_node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    collecting_node_id = current_node.id
                    slot_config = slot
            elif current_node and current_node.type == NodeType.COLLECT_FORM:
                slots = current_node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        collecting_node_id = current_node.id
                        slot_config = slot
                        break

            if not collecting_node_id:
                next_collect_node, next_collect_var = self._find_next_reachable_collect_slot()

                if next_collect_node and next_collect_var != var_key:
                    expected_info = None
                    for v in self.flow_config.variables:
                        if v.key == next_collect_var:
                            expected_info = v
                            break
                    expected_desc = expected_info.description if expected_info else next_collect_var
                    return {
                        "success": False,
                        "message": f"Please collect {expected_desc} first before moving to {var_info.description if var_info else var_key}.",
                        "action": None,
                        "out_of_order": True,
                        "expected_variable": next_collect_var,
                        "current_node_id": self.state.current_node_id,
                    }

                if next_collect_node and next_collect_var == var_key:
                    if next_collect_node.type == NodeType.COLLECT_SLOT:
                        slot = next_collect_node.data.get("slot", {})
                        slot_config = slot
                    elif next_collect_node.type == NodeType.COLLECT_FORM:
                        slots = next_collect_node.data.get("slots", [])
                        for slot in slots:
                            if slot.get("variableKey") == var_key:
                                slot_config = slot
                                break
                    collecting_node_id = next_collect_node.id
                    self.state.advance_to(next_collect_node.id)

            if not _is_valid_new_value(value):
                self.state.retry_count += 1
                if self.state.retry_count >= self._slot_max_retries(slot_config):
                    return self._handle_retry_exhaustion(
                        collecting_node_id, var_key, var_info
                    )
                retry_prompt_template = slot_config.get("retryPrompt", "") if slot_config else ""
                if retry_prompt_template:
                    reprompt = substitute_variables(
                        retry_prompt_template, self.state.collected_slots
                    )
                else:
                    var_desc = var_info.description if var_info else var_key
                    reprompt = f"Could you please provide your {var_desc}?"
                return {
                    "success": False,
                    "message": reprompt,
                    "action": None,
                    "current_node_id": collecting_node_id or self.state.current_node_id,
                }

            validation_error = self._validate_slot_value(var_info, slot_config, value)
            if validation_error:
                self.state.retry_count += 1
                if self.state.retry_count >= self._slot_max_retries(slot_config):
                    return self._handle_retry_exhaustion(
                        collecting_node_id, var_key, var_info
                    )
                retry_prompt_template = slot_config.get("retryPrompt", "") if slot_config else ""
                if retry_prompt_template:
                    retry_prompt = substitute_variables(
                        retry_prompt_template, self.state.collected_slots
                    )
                else:
                    retry_prompt = "Please try again."
                return {
                    "success": False,
                    "message": f"{validation_error} {retry_prompt}",
                    "action": None,
                    "validation_error": validation_error,
                    "current_node_id": collecting_node_id or self.state.current_node_id,
                }

            self.call_context.set_caller_value(var_key, value)

            next_node = None
            next_node_id = None
            form_next_slot_prompt = None
            if collecting_node_id:
                collecting_node = self.flow_config._node_index.get(collecting_node_id)

                if collecting_node and collecting_node.type == NodeType.COLLECT_FORM:
                    remaining = self._uncollected_slots(collecting_node.data.get("slots", []))
                    if remaining:
                        next_node_id = collecting_node_id
                        prompt = remaining[0].get("prompt", "")
                        if prompt:
                            form_next_slot_prompt = substitute_variables(
                                prompt, self.state.collected_slots, speakable=True
                            )
                    else:
                        next_node = self.state.get_next_node(collecting_node_id)
                        if next_node:
                            next_node_id = next_node.id
                            self.state.advance_to(next_node.id)
                else:
                    next_node = self.state.get_next_node(collecting_node_id)
                    if next_node:
                        next_node_id = next_node.id
                        self.state.advance_to(next_node.id)

            next_slot_instructions = self._get_next_slot_instructions()

            next_node_message, is_static = (
                self._get_next_node_configured_message(next_node) if next_node else (None, False)
            )

            # Surface the collecting node's typed instructions with the result
            # so the LLM applies them to the value it just collected (e.g.
            # "spell the name back to confirm"). Resolved AFTER the value is
            # stored so {{var}} placeholders include the fresh value.
            node_instructions = None
            if collecting_node_id:
                _instr_node = self.flow_config._node_index.get(collecting_node_id)
                if _instr_node:
                    raw_instructions = (_instr_node.data.get("instructions") or "").strip()
                    if raw_instructions:
                        node_instructions = substitute_variables(
                            raw_instructions, self.state.collected_slots
                        )

            result = {
                "success": True,
                "action": None,
                "collected": {var_key: value},
                "current_node_id": next_node_id or collecting_node_id or self.state.current_node_id,
                "next_slot": next_slot_instructions,
            }

            if node_instructions:
                result["node_instructions"] = node_instructions

            if next_node_message:
                result["message"] = next_node_message
                if is_static:
                    result["speak_exactly"] = next_node_message
            elif form_next_slot_prompt:
                result["message"] = f"Got it. {form_next_slot_prompt}"
            else:
                result["message"] = "Got it."

            return result

        return {
            "success": False,
            "message": f"Missing value for {var_key}",
            "action": None,
            "current_node_id": self.state.current_node_id,
        }

    @staticmethod
    def _slot_max_retries(slot_config: Optional[dict]) -> int:
        """Resolve the retry budget for a slot (editor ``maxRetries``, default 3)."""
        if slot_config:
            raw = slot_config.get("maxRetries")
            if isinstance(raw, int) and raw > 0:
                return raw
        return 3

    def _handle_retry_exhaustion(
        self,
        collecting_node_id: Optional[str],
        var_key: str,
        var_info: Optional[FlowVariable],
    ) -> dict:
        """Give up on a slot after ``maxRetries`` failed attempts.

        Exhaustion path, in priority order:
          1. A ``fallback`` branch wired from the collect node in the editor.
          2. Escalation to a human (assistant-level target), if configured.
          3. Graceful end of the flow.

        This runs identically in live calls and the simulator.
        """
        var_desc = var_info.description if var_info else var_key
        node_id = collecting_node_id or self.state.current_node_id

        fallback_target = None
        if node_id:
            for edge in self.flow_config.edges:
                if edge.source == node_id and edge.source_handle == "fallback":
                    fallback_target = edge.target
                    break

        if fallback_target:
            self.state.advance_to(fallback_target)
            return {
                "success": False,
                "action": None,
                "retry_exhausted": True,
                "current_node_id": self.state.current_node_id,
                "message": f"I'm having trouble getting your {var_desc}. Let's move on.",
            }

        if self.escalation_target:
            self.state.transfer_requested = True
            self.state.transfer_target = self.escalation_target
            return {
                "success": False,
                "action": "transfer",
                "target": self.escalation_target,
                "transfer_mode": "warm",
                "retry_exhausted": True,
                "message": (
                    f"I'm having trouble getting your {var_desc}. "
                    "Let me connect you with someone who can help."
                ),
            }

        self.state.is_complete = True
        return {
            "success": False,
            "action": "end",
            "retry_exhausted": True,
            "message": (
                f"I'm sorry, I wasn't able to get your {var_desc}. "
                "Please try again later or reach out to us for help."
            ),
        }

    def _validate_slot_value(
        self, var_info: Optional[FlowVariable], slot_config: Optional[dict], value: Any
    ) -> Optional[str]:
        """Validate a slot value. Returns error message or None if valid."""
        if not var_info:
            return None

        validation = _normalize_slot_validation(
            slot_config.get("validation") if slot_config else None
        )

        if var_info.type == SlotType.NUMBER:
            try:
                num_value = int(value) if isinstance(value, str) else value
                if "min" in validation and num_value < validation["min"]:
                    return f"Value must be at least {validation['min']}."
                if "max" in validation and num_value > validation["max"]:
                    return f"Value cannot exceed {validation['max']}."
            except (ValueError, TypeError):
                return "Please provide a valid number."

        elif var_info.type == SlotType.DATE:
            if isinstance(value, str):
                try:
                    date_value = datetime.strptime(value, "%Y-%m-%d").date()
                    today = datetime.now(self._timezone).date()
                    require_future = validation.get(
                        "requireFuture", validation.get("require_future", True)
                    )
                    if require_future and date_value < today:
                        return f"Date must be today or in the future (on or after {today})."

                    compare_var = validation.get("cross_field_variable")
                    if compare_var:
                        compare_date_str = self.state.get_variable(compare_var)
                        if compare_date_str:
                            try:
                                compare_date = datetime.strptime(
                                    compare_date_str, "%Y-%m-%d"
                                ).date()
                                operator = validation.get(
                                    "cross_field_operator", "after"
                                )
                                invalid = (
                                    date_value <= compare_date
                                    if operator in ("after", "greater")
                                    else date_value >= compare_date
                                )
                                if invalid:
                                    return validation.get("cross_field_error") or (
                                        f"Date must be {operator} {compare_date_str}."
                                    )
                            except ValueError:
                                pass
                except ValueError:
                    return (
                        "I didn't quite catch that date. Could you please tell me the date again?"
                    )

        return None

    def _resolve_api_edge(self, node_id: str, *, success: bool) -> "Optional[FlowNode]":
        """Resolve the next node for an API REQUEST / CAPABILITY node.

        Prefers the ``success`` or ``error`` sourceHandle when the builder drew
        one; falls back to the first unhandled outgoing edge so flows drawn
        without explicit handle labels continue to work as before.
        """
        preferred = "success" if success else "error"
        node = self.state.get_next_node(node_id, handle=preferred)
        if node is None:
            node = self.state.get_next_node(node_id)
        return node

    async def _handle_api_request(self, function_name: str, arguments: dict) -> dict:
        """Execute an API request.

        Supports two modes:
        1. Custom URL - Direct HTTP request to a specified URL
        2. Integration - Uses IntegrationClient for authenticated requests to connected services
        """
        node_id = function_name.replace("execute_", "")
        node = self.flow_config._node_index.get(node_id)

        if not node:
            return {"success": False, "message": "API node not found", "action": None}

        api_config = node.data.get("api", {})
        api_source = api_config.get("apiSource", "custom")
        thinking_message = (api_config.get("thinkingMessage") or "").strip()
        method = (api_config.get("method", "GET") or "GET").upper()

        # Template-applied nodes ship with integrationSlug but no integrationId
        # (the editor panel resolves slug→ID only when the panel is opened).
        # Resolve the slug at runtime so the integration path is taken even when
        # the operator never opened the panel in the UI.
        if (
            api_source == "integration"
            and not api_config.get("integrationId")
            and api_config.get("integrationSlug")
        ):
            resolved_id = await self._resolve_integration_slug(
                api_config["integrationSlug"]
            )
            if resolved_id:
                api_config = {**api_config, "integrationId": resolved_id}

        # Guard: when the node is configured as an integration node but no
        # connection ID could be resolved (slug not found, no CONNECTED integration,
        # or no DB/account context), fail loudly with a caller-safe error instead of
        # silently falling through to _handle_custom_api_request which would make a
        # generic HTTP call with no credentials and return nothing useful to the
        # caller.
        if api_source == "integration" and not api_config.get("integrationId"):
            _slug = api_config.get("integrationSlug", "")
            logger.warning(
                "flow_executor: API node %r has apiSource='integration' but no "
                "integrationId could be resolved (slug=%r). Returning error to "
                "caller — verify the connection is CONNECTED and the slug matches.",
                node_id,
                _slug,
            )
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": api_config.get(
                    "onError",
                    "I'm unable to reach that service right now. Please try again shortly.",
                ),
                "action": None,
                "current_node_id": failed_node_id,
            }

        # Capability nodes (Task #329) carry no HTTP method of their own — it
        # lives on the vendor endpoint resolved at runtime. Derive an effective
        # method from the registry `mutating` flag so write capabilities
        # (book/cancel) get the same non-GET idempotency guard as write
        # integration nodes, and read capabilities bypass it like GETs.
        if api_source == "capability":
            from botelier.services.capabilities import get_capability

            cap_spec = get_capability(api_config.get("capability"))
            method = "POST" if (cap_spec and cap_spec.mutating) else "GET"

        # Non-GET idempotency guard: POST/PUT/PATCH/DELETE nodes must fire at most
        # once per session even when two requests arrive concurrently (e.g. two
        # simultaneous POST /api/simulate/message or a voice pipeline race).
        # GET nodes are inherently idempotent and bypass the guard entirely.
        if method != "GET":
            if node_id in self._non_get_results:
                cached = self._non_get_results[node_id]
                logger.info(
                    f"API node {node_id} ({method}) already executed this session — "
                    "returning cached result to prevent duplicate request"
                )
                cached_copy = dict(cached)
                cached_copy["thinking_message"] = thinking_message
                return cached_copy

            if node_id not in self._non_get_locks:
                self._non_get_locks[node_id] = asyncio.Lock()
            lock = self._non_get_locks[node_id]

            async with lock:
                if node_id in self._non_get_results:
                    cached = self._non_get_results[node_id]
                    logger.info(
                        f"API node {node_id} ({method}) executed by concurrent request — "
                        "returning cached result to prevent duplicate request"
                    )
                    cached_copy = dict(cached)
                    cached_copy["thinking_message"] = thinking_message
                    return cached_copy

                if api_source == "capability" and api_config.get("capability"):
                    result = await self._handle_capability_request(node_id, node, api_config)
                elif api_source == "integration" and api_config.get("integrationId"):
                    result = await self._handle_integration_api_request(node_id, node, api_config)
                else:
                    result = await self._handle_custom_api_request(node_id, node, api_config)

                if result.get("success"):
                    self._non_get_results[node_id] = result

        else:
            # GET dedup guard (Task #534, defense-in-depth) — see the
            # _get_locks/_get_recent comment at __init__ for why this is
            # short-lived rather than a permanent per-session cache like the
            # non-GET guard above.
            _args_key = repr(sorted(arguments.items())) if arguments else ""
            if node_id not in self._get_locks:
                self._get_locks[node_id] = asyncio.Lock()
            _get_lock = self._get_locks[node_id]

            async with _get_lock:
                _recent = self._get_recent.get(node_id)
                if (
                    _recent
                    and _recent[1] == _args_key
                    and (time.monotonic() - _recent[0]) < GET_DEDUP_WINDOW_SECS
                ):
                    logger.info(
                        f"API node {node_id} (GET) called again with identical "
                        f"arguments within {GET_DEDUP_WINDOW_SECS}s — returning "
                        "the just-completed result instead of re-firing the request"
                    )
                    result = dict(_recent[2])
                else:
                    if api_source == "capability" and api_config.get("capability"):
                        result = await self._handle_capability_request(node_id, node, api_config)
                    elif api_source == "integration" and api_config.get("integrationId"):
                        result = await self._handle_integration_api_request(
                            node_id, node, api_config
                        )
                    else:
                        result = await self._handle_custom_api_request(node_id, node, api_config)
                    self._get_recent[node_id] = (time.monotonic(), _args_key, result)

        result["thinking_message"] = thinking_message

        return result

    async def _resolve_integration_slug(self, slug: str) -> Optional[str]:
        """Resolve an integration type slug to the account's active connection ID.

        Used when a flow node was saved with ``integrationSlug`` but no
        ``integrationId`` (e.g. templates applied without opening the editor
        panel).

        Resolution rules (matches the per-property isolation contract):
        1. Only CONNECTED connections are considered — disconnected ones are
           ignored even when they match the slug.
        2. If ``self.property_id`` is set, prefer an exact property-scoped
           connection.  If none exists, fall back to an account-global
           connection (``property_id IS NULL``).
        3. If multiple account-global connections match the slug, return
           ``None`` (ambiguous — the caller must set an explicit integrationId).

        Fails open — a missing slug, absent session, or unresolvable match
        returns ``None`` so the caller falls through to the custom HTTP path
        rather than crashing.
        """
        if not slug or not self.account_id:
            return None
        with self._borrow_db_session() as db:
            if db is None:
                logger.warning(
                    "flow_executor: cannot resolve integration slug %r — no DB "
                    "session available. Pass session_factory=SessionLocal when "
                    "constructing FlowExecutor for live voice calls.",
                    slug,
                )
                return None
            try:
                from botelier.models.integration import (
                    AccountIntegration,
                    IntegrationStatus,
                    IntegrationType,
                )

                base_q = (
                    db.query(AccountIntegration)
                    .join(
                        IntegrationType,
                        AccountIntegration.integration_type_id == IntegrationType.id,
                    )
                    .filter(
                        AccountIntegration.account_id == self.account_id,
                        AccountIntegration.status == IntegrationStatus.CONNECTED,
                        IntegrationType.slug == slug,
                    )
                )

                # --- Step 1: exact property match ---
                if self.property_id:
                    exact = base_q.filter(
                        AccountIntegration.property_id == self.property_id
                    ).all()
                    if len(exact) == 1:
                        return str(exact[0].id)
                    if len(exact) > 1:
                        logger.warning(
                            "flow_executor: ambiguous slug %r — %d property-scoped "
                            "connections for property %s; cannot resolve",
                            slug,
                            len(exact),
                            self.property_id,
                        )
                        return None

                # --- Step 2: account-global connection (property_id IS NULL) ---
                global_conns = base_q.filter(
                    AccountIntegration.property_id.is_(None)
                ).all()
                if len(global_conns) == 1:
                    return str(global_conns[0].id)
                if len(global_conns) > 1:
                    logger.warning(
                        "flow_executor: ambiguous slug %r — %d account-global "
                        "connections for account %s; cannot resolve",
                        slug,
                        len(global_conns),
                        self.account_id,
                    )
                    return None

                return None
            except Exception:
                logger.debug(
                    "flow_executor: slug resolution failed for %r (account %s)",
                    slug,
                    self.account_id,
                )
                return None

    async def _handle_capability_request(
        self, node_id: str, node: FlowNode, api_config: dict
    ) -> dict:
        """Handle a flow API node that references an abstract capability (Task #329).

        Resolves the capability to the session's property-scoped provider
        connection (fail-closed — Task #327/#329), translates the flow slots to
        that vendor's variable keys, then delegates to
        ``_handle_integration_api_request`` so response mapping, node
        advancement, and onSuccess/onError rendering are byte-identical to a
        normal integration node. The AI author picked a capability; the flow
        never records which vendor served it.
        """
        from botelier.services.capabilities import CapabilityResolver, get_capability

        capability_name = api_config.get("capability")

        if not self.account_id:
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": "Capability calls require account context",
                "action": None,
                "current_node_id": failed_node_id,
            }

        spec = get_capability(capability_name)
        if spec is None:
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": f"Unknown capability '{capability_name}'.",
                "action": None,
                "current_node_id": failed_node_id,
            }

        # Service-backed capabilities (e.g. collect_payment) do not resolve to a
        # PMS vendor endpoint — route them to their internal service and advance
        # the node from the AI-safe result. Property scope + durable idempotency
        # are enforced inside the service (Task #330).
        if spec.service_backed:
            return await self._handle_service_backed_capability(
                node_id, node, api_config, capability_name
            )

        with self._borrow_db_session() as db:
            resolver = CapabilityResolver(db, self.account_id, self.property_id)
            resolution = resolver.resolve(capability_name)
            if resolution is None:
                failed_node = self._resolve_api_edge(node_id, success=False)
                failed_node_id = node_id
                if failed_node and self.state.current_node_id == node_id:
                    self.state.advance_to(failed_node.id)
                    failed_node_id = failed_node.id
                return {
                    "success": False,
                    "message": "That capability is not available right now.",
                    "action": None,
                    "current_node_id": failed_node_id,
                }

            # Inject the resolved connection's config constants (hotel_name, currency,
            # …) into flow slots BEFORE translating so capability calls that need them
            # (e.g. GuestCentric booking) resolve them exactly like integration nodes.
            # Property-identity keys are re-forced from the connection by
            # IntegrationClient regardless (Task #327).
            self._inject_connection_config_to_slots(resolution.integration_id)
            translated = resolver.translate_variables(resolution, self.state.collected_slots)

        # Synthesize an integration api_config from the resolution so the shared
        # integration path executes the concrete vendor endpoint.
        synth_config = dict(api_config)
        synth_config["apiSource"] = "integration"
        synth_config["integrationId"] = resolution.integration_id
        synth_config["endpointId"] = resolution.endpoint_id
        synth_config["method"] = resolution.method

        return await self._handle_integration_api_request(
            node_id, node, synth_config, variables=translated
        )

    async def _handle_service_backed_capability(
        self, node_id: str, node: FlowNode, api_config: dict, capability_name: str
    ) -> dict:
        """Execute a service-backed capability (collect_payment) in a flow node.

        Reads the vendor-neutral params from flow slots, delegates to the
        capability's internal service (``PaymentService``), then advances the node
        like a successful/failed integration node. A durable idempotency key keyed
        to (call, flow tool, node) dedups a reconnect/retry to a single charge.
        The AI-safe result (``{status, payment_id, message}``) drives the branch;
        processor identifiers never enter flow state.
        """
        slots = self.state.collected_slots or {}

        idem_key = None
        if self.call_sid:
            import hashlib

            raw = "|".join(
                [
                    "pay",
                    "flow",
                    str(self.account_id or ""),
                    str(self.property_id or ""),
                    str(self.call_sid),
                    str(self.flow_tool_id or ""),
                    str(node_id),
                ]
            )
            idem_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        def _run() -> dict:
            from botelier.services.payments import PaymentService

            service = PaymentService(self.account_id, self.property_id)
            return service.collect_payment(
                amount=slots.get("amount"),
                currency=slots.get("currency", "USD"),
                description=slots.get("description"),
                reference=slots.get("reference"),
                channel="flow",
                call_sid=self.call_sid,
                idempotency_key=idem_key,
            )

        import asyncio

        try:
            async with self._suspend_turn_lock():
                result = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001 — never break a live call
            # PaymentService raised (DB error, Stripe SDK exception, misconfiguration).
            # The charge outcome is ambiguous; return a structured failure so the
            # LLM can tell the caller something went wrong rather than going silent.
            logger.error(
                "service_backed_capability (collect_payment) raised for node %r: %s",
                node_id, exc, exc_info=True,
            )
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": api_config.get("onError") or "There was an issue processing your payment. Please try again.",
                "action": None,
                "current_node_id": failed_node_id,
            }
        # Turn lock reacquired — state mutations happen below.

        status = (result or {}).get("status")
        message = (result or {}).get("message", "")
        # Expose non-sensitive outcome to flow state so downstream CONDITION nodes
        # can branch on it. payment_id is an opaque internal id (safe); no
        # processor refs or link tokens are ever written here.
        self.state.set_variable("payment_status", status)
        if result and result.get("payment_id"):
            self.state.set_variable("payment_id", result["payment_id"])

        succeeded = status in ("pending", "authorized", "captured")
        if succeeded:
            if self.state.current_node_id == node_id:
                next_node = self._resolve_api_edge(node_id, success=True)
                if next_node:
                    self.state.advance_to(next_node.id)
                    next_node_id = next_node.id
                else:
                    self.state.advance_to(node_id)
                    next_node_id = node_id
            else:
                next_node_id = self.state.current_node_id
                logger.info(
                    "Service-backed capability node %r: flow advanced to %r during "
                    "payment I/O — skipping advance, payment state applied",
                    node_id,
                    next_node_id,
                )

            response_instructions = (api_config.get("responseInstructions") or "").strip()
            if response_instructions:
                voice_result = substitute_variables(
                    response_instructions, self.state.collected_slots
                )
            else:
                voice_result = message

            return {
                "success": True,
                "message": api_config.get("onSuccess") or message,
                "action": None,
                "voice_result": voice_result,
                "current_node_id": next_node_id,
            }

        failed_node = self._resolve_api_edge(node_id, success=False)
        failed_node_id = node_id
        if failed_node and self.state.current_node_id == node_id:
            self.state.advance_to(failed_node.id)
            failed_node_id = failed_node.id
        return {
            "success": False,
            "message": api_config.get("onError") or message,
            "action": None,
            "current_node_id": failed_node_id,
        }

    async def _handle_integration_api_request(
        self, node_id: str, node: FlowNode, api_config: dict, variables: dict = None
    ) -> dict:
        """Handle API request using IntegrationClient for connected integrations.

        Returns a dict with the following contract:
        - ``success`` (bool) — whether the API call succeeded.
        - ``action`` (None | "transfer" | "end") — terminal action to take.
        - ``voice_result`` (str, success only) — rendered ``responseInstructions``
          (with ``{{variables}}`` substituted) **or** a compact extracted-data
          summary when ``responseInstructions`` is blank.  This is what the LLM
          reads as the tool result after ``FunctionMapper`` promotes it to ``result``.
        - ``voice_result_is_auto_summary`` (bool) — True when ``voice_result`` is
          the raw field-name/value digest built because no ``responseInstructions``
          was configured. FunctionMapper must NEVER speak this text verbatim to a
          caller (it is LLM context only, for the model to narrate naturally);
          only designer-authored ``responseInstructions`` (False) may be spoken
          directly.
        - ``message`` (str) — human-readable status (onSuccess / onError text).
        - ``current_node_id`` (str) — node the flow advanced to.
        - Error-only keys: ``error_type``, ``status_code``.
        """
        from botelier.services.action_executor import (
            ActionContext,
            ActionExecutionRequest,
            ActionExecutor,
        )
        from botelier.services.integration_client import (
            IntegrationAPIConfig,
            ResponseVariable,
            get_llm_friendly_error_message,
        )

        if not self.account_id:
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": "Integration API calls require account context",
                "action": None,
                "current_node_id": failed_node_id,
            }

        response_vars = []
        for rv in api_config.get("responseVariables", []):
            if not isinstance(rv, dict):
                logger.warning(f"skipping non-dict responseVariable entry: {rv!r}")
                continue
            response_vars.append(
                ResponseVariable(
                    variable_key=rv.get("variableKey", ""),
                    json_path=rv.get("jsonPath", ""),
                    default_value=rv.get("defaultValue"),
                )
            )
        # Newer flow nodes store extraction as a responseMapping dict
        # ({variable_key: jsonPath}). Merge it into the response variables so a
        # single extraction path (IntegrationClient, which also applies seed
        # precedence) maps API output into flow variables. Explicit
        # responseVariables win on key collisions.
        explicit_keys = {rv.variable_key for rv in response_vars}
        for variable_key, json_path in (api_config.get("responseMapping") or {}).items():
            if variable_key and json_path and variable_key not in explicit_keys:
                response_vars.append(
                    ResponseVariable(
                        variable_key=variable_key,
                        json_path=json_path,
                    )
                )

        raw_body_template = api_config.get("bodyTemplate")
        resolved_body_template = (
            self._substitute_secrets(raw_body_template) if raw_body_template else raw_body_template
        )

        raw_headers = api_config.get("headers") or {}
        resolved_headers = (
            {k: self._substitute_secrets(v) for k, v in raw_headers.items()}
            if raw_headers
            else None
        )

        raw_path = api_config.get("path", api_config.get("url", ""))
        resolved_path = self._substitute_secrets(raw_path) if raw_path else raw_path

        # Node-level query-param overrides: resolve {{secrets.*}} for parity with
        # headers/body/path so an operator can reference a secret in an override.
        raw_query_param_overrides = api_config.get("queryParamOverrides") or {}
        resolved_query_param_overrides = {
            k: self._substitute_secrets(v) if isinstance(v, str) else v
            for k, v in raw_query_param_overrides.items()
        }

        config = IntegrationAPIConfig(
            integration_id=api_config.get("integrationId", ""),
            endpoint_id=api_config.get("endpointId"),
            method=api_config.get("method", "GET"),
            path=resolved_path,
            endpoint_template=raw_path,
            headers=resolved_headers,
            body_template=resolved_body_template,
            timeout=api_config.get("timeout", 30),
            retry_count=api_config.get("retryCount", 2),
            query_param_overrides=resolved_query_param_overrides,
            response_variables=response_vars,
            on_success_message=api_config.get("onSuccess", "Request completed successfully"),
            on_error_message=api_config.get(
                "onError", "There was an issue processing your request"
            ),
            on_not_found_message=api_config.get(
                "onNotFound", "The requested information was not found"
            ),
            on_auth_error_message=api_config.get(
                "onAuthError", "There was an authentication issue"
            ),
        )

        # Inject integration connection_config into flow state before calling the
        # API.  This makes property-level constants (hotel_id, hotel_name,
        # hotel_reservations_email, currency, …) available as flow variables, so
        # downstream SET_VARIABLE nodes (e.g. building the hotels array for
        # cancellation-policy lookups) can resolve {{hotel_id}} without requiring
        # those values to be collected from callers each turn.  Never overwrites a
        # variable that the flow has already set.
        self._inject_connection_config_to_slots(api_config.get("integrationId", ""))

        # Release the turn lock during the HTTP round-trip so concurrent fast
        # turns (collect_, route_, confirm_) can proceed.  Reacquired before
        # any state mutation below.
        try:
            async with self._suspend_turn_lock():
                with self._borrow_db_session() as db:
                    response = await ActionExecutor(db).execute_and_log(
                        ActionExecutionRequest(
                            context=ActionContext(
                                account_id=self.account_id,
                                channel="flow",
                                call_sid=self.call_sid,
                                flow_tool_id=self.flow_tool_id,
                                node_id=node_id,
                                source_label=node.data.get("name") or node_id,
                                property_id=self.property_id,
                            ),
                            variables=variables if variables is not None else self.state.collected_slots,
                            integration_config=config,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — defense-in-depth; ActionExecutor already catches most errors
            logger.error(
                "Unhandled exception in _handle_integration_api_request for node %r: %s",
                node_id, exc, exc_info=True,
            )
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": api_config.get("onError", "There was an issue processing your request"),
                "action": None,
                "error_type": "unknown",
                "status_code": 0,
                "current_node_id": failed_node_id,
            }
        # Turn lock reacquired — validate and mutate state atomically.

        if response.success:
            # responseMapping is merged into response_vars above, so all
            # extraction (and seed precedence) happens once in IntegrationClient.
            for var_key, value in response.extracted_variables.items():
                self.state.set_variable(var_key, value)

            # Advance only if the flow hasn't already moved on during I/O.
            if self.state.current_node_id == node_id:
                next_node = self._resolve_api_edge(node_id, success=True)
                if next_node:
                    self.state.advance_to(next_node.id)
                    next_node_id = next_node.id
                else:
                    self.state.advance_to(node_id)
                    next_node_id = node_id
            else:
                # A concurrent fast turn already advanced the flow; report the
                # current position without overwriting it.
                next_node_id = self.state.current_node_id
                logger.info(
                    "Integration API node %r: flow advanced to %r during I/O "
                    "— skipping advance, variables applied",
                    node_id,
                    next_node_id,
                )

            success_msg = config.on_success_message
            success_msg = substitute_variables(
                success_msg, self.state.collected_slots, speakable=True
            )

            response_instructions = (api_config.get("responseInstructions") or "").strip()
            if response_instructions:
                voice_result = substitute_variables(response_instructions, self.state.collected_slots)
                voice_result_is_auto_summary = False
            else:
                # No designer-authored narration configured: fall back to a
                # compact field-name/value digest of the extracted variables.
                # This is LLM CONTEXT ONLY (so it can narrate naturally next
                # turn) — never caller-facing speech. voice_result_is_auto_summary
                # tells FunctionMapper not to push this text to TTS verbatim.
                voice_result = _build_api_voice_result(success_msg, response.extracted_variables)
                voice_result_is_auto_summary = True

            return {
                "success": True,
                "message": success_msg,
                "action": None,
                "voice_result": voice_result,
                "voice_result_is_auto_summary": voice_result_is_auto_summary,
                "current_node_id": next_node_id,
            }
        else:
            error_msg = get_llm_friendly_error_message(response, config)
            error_msg = substitute_variables(error_msg, self.state.collected_slots)

            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id

            return {
                "success": False,
                "message": error_msg,
                "action": None,
                "error_type": response.error_type.value,
                "status_code": response.status_code,
                # Raw underlying error text (e.g. "Currency not supported"),
                # distinct from `message` which is the LLM/caller-facing
                # wording. Lets operators see the real failure reason on the
                # call detail page without reading integration_call_logs
                # directly.
                "error_detail": response.error_message,
                "current_node_id": failed_node_id,
            }

    def _substitute_secrets(self, text: str) -> str:
        """Replace {{secrets.key_name}} references with decrypted values from AccountSecret.

        Substitution is server-side only — secret values never leave the backend.
        Unresolvable references are left as-is so misconfiguration is visible in logs.
        """
        if not text or "{{secrets." not in text or not self.account_id:
            return text

        import re as _re

        secret_refs = set(_re.findall(r"\{\{secrets\.(\w+)\}\}", text))
        if not secret_refs:
            return text

        from botelier.models.integration import AccountSecret

        with self._borrow_db_session() as db:
            if db is None:
                return text
            secrets = (
                db.query(AccountSecret)
                .filter(
                    AccountSecret.account_id == self.account_id,
                    AccountSecret.key.in_(list(secret_refs)),
                )
                .all()
            )
        secret_map = {s.key: s.get_value() for s in secrets}

        def replace_secret(m):
            key = m.group(1)
            if key in secret_map:
                return secret_map[key]
            logger.warning(f"Secret '{{secrets.{key}}}' not found for account {self.account_id}")
            return m.group(0)

        return _re.sub(r"\{\{secrets\.(\w+)\}\}", replace_secret, text)

    def _inject_connection_config_to_slots(self, integration_id: str) -> None:
        """Merge integration connection_config into collected_slots (non-destructive).

        Loads the ``connection_config`` JSON from the matching ``account_integrations``
        row and copies each key into ``collected_slots`` only when that key is not
        already present.  This lets property-level constants (hotel_id, hotel_name,
        hotel_reservations_email, default currency, …) be stored once per connection
        and automatically flow into SET_VARIABLE templates and downstream API calls
        without manual collection from the caller every turn.

        Failures are logged at DEBUG and never bubble up — a missing or malformed
        connection_config is not a blocking error for the flow.
        """
        if not integration_id or not self.account_id:
            return
        try:
            from botelier.models.integration import AccountIntegration

            with self._borrow_db_session() as db:
                if db is None:
                    return
                integration = (
                    db.query(AccountIntegration)
                    .filter(
                        AccountIntegration.id == integration_id,
                        AccountIntegration.account_id == self.account_id,
                    )
                    .first()
                )
            if not integration:
                return
            conn_config = integration.get_connection_config() or {}
            for key, value in conn_config.items():
                if key not in self.state.collected_slots and value is not None:
                    self.state.set_variable(key, value)
        except Exception as exc:
            logger.debug(
                f"Non-fatal: could not inject connection_config into flow slots "
                f"for integration {integration_id}: {exc}"
            )

    def _write_custom_call_log(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        success: bool,
        latency_ms: int,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Fire-and-forget IntegrationCallLog write for custom-URL API calls (integration_id=None)."""
        if not self.account_id:
            return
        with self._borrow_db_session() as db:
            if db is None:
                return
            try:
                from botelier.models.integration import IntegrationCallLog as _ICL
                from botelier.services.integration_client import _sanitize_endpoint_for_log

                log = _ICL(
                    id=uuid.uuid4(),
                    account_id=self.account_id,
                    integration_id=None,
                    endpoint_called=_sanitize_endpoint_for_log(endpoint),
                    method=method,
                    status_code=status_code,
                    success=success,
                    latency_ms=latency_ms,
                    error_type=error_type,
                    error_message=error_message[:500] if error_message else None,
                    called_at=datetime.utcnow(),
                )
                db.add(log)
                db.commit()
            except Exception as exc:
                logger.warning(f"Failed to write custom URL call log (non-fatal): {exc}")

    async def _handle_custom_api_request(
        self, node_id: str, node: FlowNode, api_config: dict
    ) -> dict:
        """Handle direct custom URL API request through ActionExecutor.

        Returns the same dict contract as ``_handle_integration_api_request``:
        ``success``, ``action``, ``voice_result`` + ``voice_result_is_auto_summary``
        (success) or ``error_type`` / ``status_code`` (failure), ``message``,
        ``current_node_id``.

        Response shaping (variable extraction, voice result, error classification) is
        handled entirely by ``ActionExecutor.execute_and_log``; there is no in-line
        response-processing logic here.
        """
        from botelier.services.action_executor import (
            ActionContext,
            ActionExecutionRequest,
            ActionExecutor,
        )

        try:
            async with self._suspend_turn_lock():
                with self._borrow_db_session() as db:
                    response = await ActionExecutor(db).execute_and_log(
                        ActionExecutionRequest(
                            context=ActionContext(
                                account_id=self.account_id,
                                channel="flow",
                                call_sid=self.call_sid,
                                flow_tool_id=self.flow_tool_id,
                                node_id=node_id,
                                source_label=node.data.get("name") or node_id,
                                property_id=self.property_id,
                            ),
                            variables=self.state.collected_slots,
                            legacy_config=api_config,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — defense-in-depth; ActionExecutor already catches most errors
            logger.error(
                "Unhandled exception in _handle_custom_api_request for node %r: %s",
                node_id, exc, exc_info=True,
            )
            failed_node = self._resolve_api_edge(node_id, success=False)
            failed_node_id = node_id
            if failed_node and self.state.current_node_id == node_id:
                self.state.advance_to(failed_node.id)
                failed_node_id = failed_node.id
            return {
                "success": False,
                "message": api_config.get("onError", "There was an issue processing your request"),
                "action": None,
                "error_type": "unknown",
                "status_code": 0,
                "current_node_id": failed_node_id,
            }
        # Turn lock reacquired.

        if response.success:
            for var_key, value in response.extracted_variables.items():
                self.state.set_variable(var_key, value)

            if self.state.current_node_id == node_id:
                next_node = self._resolve_api_edge(node_id, success=True)
                if next_node:
                    self.state.advance_to(next_node.id)
                effective_node_id = next_node.id if next_node else node_id
            else:
                effective_node_id = self.state.current_node_id
                next_node = None
                logger.info(
                    "Custom API node %r: flow advanced to %r during I/O "
                    "— skipping advance, variables applied",
                    node_id,
                    effective_node_id,
                )

            success_msg = api_config.get("onSuccess", "Request completed successfully")
            success_msg = substitute_variables(
                success_msg, self.state.collected_slots, speakable=True
            )

            response_instructions = (api_config.get("responseInstructions") or "").strip()
            if response_instructions:
                voice_result = substitute_variables(response_instructions, self.state.collected_slots)
                voice_result_is_auto_summary = False
            else:
                # No designer-authored narration configured: fall back to a
                # compact field-name/value digest of the extracted variables.
                # This is LLM CONTEXT ONLY (so it can narrate naturally next
                # turn) — never caller-facing speech. voice_result_is_auto_summary
                # tells FunctionMapper not to push this text to TTS verbatim.
                voice_result = _build_api_voice_result(success_msg, response.extracted_variables)
                voice_result_is_auto_summary = True

            return {
                "success": True,
                "message": success_msg,
                "action": None,
                "voice_result": voice_result,
                "voice_result_is_auto_summary": voice_result_is_auto_summary,
                "current_node_id": effective_node_id,
            }

        failed_node = self._resolve_api_edge(node_id, success=False)
        failed_node_id = node_id
        if failed_node and self.state.current_node_id == node_id:
            self.state.advance_to(failed_node.id)
            failed_node_id = failed_node.id
        return {
            "success": False,
            "message": response.error_message
            or api_config.get("onError", "There was an issue processing your request"),
            "action": None,
            "error_type": response.error_type.value,
            "status_code": response.status_code,
            "current_node_id": failed_node_id,
        }

    def _extract_json_value(self, data: dict, path: str) -> Any:
        """Extract a value from a JSON response.

        Delegates to the shared extractor so flow nodes and IntegrationClient
        resolve paths identically (``$`` prefix, ``[n]`` index, ``[*]`` wildcard).
        """
        from botelier.services.integration_client import extract_json_value

        return extract_json_value(data, path)

    async def _handle_router(self, function_name: str, arguments: dict) -> dict:
        """Handle routing based on a choice value."""
        node_id = function_name.replace("route_", "")
        node = self.flow_config._node_index.get(node_id)

        if not node:
            return {
                "success": False,
                "message": "Router node not found",
                "action": None,
                "current_node_id": None,
            }

        router_data = node.data.get("router", {})
        variable = router_data.get("variable", "")
        options = router_data.get("options", [])
        raw_choice = arguments.get("choice")

        # Guard: the LLM can pass JSON null (Python None) or a numeric value when
        # the schema does not strictly enforce a non-null string.  Coerce to str
        # so the subsequent .lower() call never raises AttributeError/TypeError.
        if raw_choice is None:
            logger.warning(
                f"_handle_router node {node_id!r}: 'choice' argument is null "
                "— treating as empty string"
            )
            choice = ""
        else:
            choice = str(raw_choice)

        if variable:
            self.state.set_variable(variable, choice)

        matched_option_id = None
        matched_label = choice
        choice_lower = choice.lower()
        for opt in options:
            if opt.get("value", "").lower() == choice_lower:
                matched_option_id = opt.get("id")
                matched_label = opt.get("label", choice)
                break

        if not matched_option_id:
            configured = [opt.get("value") for opt in options]
            logger.warning(
                f"_handle_router node {node_id!r}: choice {choice!r} matched no configured "
                f"option {configured!r} — falling through to default/first-edge fallback"
            )

        next_node_id = None
        if matched_option_id:
            next_node = self.state.get_next_node(node_id, handle=matched_option_id)
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)

        if not next_node_id:
            next_node = self.state.get_next_node(node_id, handle="default")
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)

        if not next_node_id:
            next_node = self.state.get_next_node(node_id)
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)
            else:
                self.state.advance_to(node_id)
                next_node_id = node_id

        result = {
            "success": True,
            "message": f"Routing to: {matched_label}",
            "action": None,
            "routed_to": matched_label,
            "current_node_id": next_node_id,
        }

        # If routing lands straight on END/TRANSFER, actually execute that
        # terminal action rather than merely speaking its message (Task #534
        # completion-review fix).
        terminal_result = await self._maybe_execute_terminal_transition(next_node)
        if terminal_result is not None:
            return terminal_result

        # ROUTER is a silent branch decision — "Routing to: X" is debug context,
        # never meant to be spoken. But like SET_VARIABLE, it can branch
        # straight into a node with real caller-facing content and no other
        # direct-speech guarantee. Surface that content for the mapper to
        # speak directly instead of leaving the branch outcome unannounced.
        next_node_message, next_is_static = (
            self._get_next_node_configured_message(next_node) if next_node else (None, False)
        )
        if next_node_message:
            result["message"] = next_node_message
            result["speak_directly"] = True
            if next_is_static:
                result["speak_exactly"] = next_node_message

        return result

    def _confirmed_branch_next_node(self, node_id: str) -> Optional[FlowNode]:
        """Resolve the node a confirmation node advances to when confirmed.

        Prefers the explicit ``confirmed`` source handle. If no such edge
        exists, falls back to any outgoing edge that is NOT the explicit
        ``edit`` branch. Confirmation edges that were seeded/imported without a
        ``sourceHandle`` (e.g. template flows using simple edge ids like
        ``e12``) would otherwise never match ``handle="confirmed"``, leaving the
        flow stuck on the confirmation node — the customer confirms, but the
        engine never advances to the next action (such as the booking API POST),
        so the LLM just narrates "one moment" indefinitely. Only the strict
        ``edit`` handle is excluded from the fallback so a "no" answer can never
        be routed to the confirmed path.
        """
        next_node = self.state.get_next_node(node_id, handle="confirmed")
        if next_node:
            return next_node
        for edge in self.flow_config.edges:
            if edge.source == node_id and edge.source_handle != "edit":
                target = self.flow_config._node_index.get(edge.target)
                if target:
                    return target
        return None

    async def _run_confirmation_logic(
        self,
        node: FlowNode,
        confirmed: bool,
        arguments: dict,
    ) -> dict:
        """Canonical confirmation handler — shared by both entry points.

        Called by ``_handle_confirmation`` (LLM invoked ``confirm_<node_id>``)
        and by ``_handle_confirm_details`` when a CONFIRMATION node is found in
        the flow.  Centralising here ensures both paths:

        * use ``_confirmed_branch_next_node()`` with its edge-fallback guard
          (so flows imported/seeded without an explicit ``confirmed``
          sourceHandle are not silently stuck forever on the confirmation node),
        * produce an identical result shape, and
        * carry the ``speak_directly`` guarantee that prevents dead-air on
          live calls.
        """
        node_id = node.id
        confirmation_data = node.data.get("confirmation", {})

        # Read all templates upfront so the correction sub-path can re-render
        # them after ``correct_caller_slot`` updates collected_slots.
        summary_template = confirmation_data.get(
            "summaryTemplate", confirmation_data.get("summary_template", "")
        )
        confirm_prompt = confirmation_data.get(
            "confirmPrompt", confirmation_data.get("confirm_prompt", "")
        )
        edit_prompt = confirmation_data.get("editPrompt", confirmation_data.get("edit_prompt", ""))

        summary_message = (
            substitute_variables(summary_template, self.state.collected_slots)
            if summary_template
            else ""
        )
        edit_message = (
            substitute_variables(edit_prompt, self.state.collected_slots)
            if edit_prompt
            else "What would you like to change?"
        )

        delivery_mode = confirmation_data.get("deliveryMode", "guided")
        is_static = delivery_mode == "static"

        if confirmed:
            # Use the fallback-guarded helper so flows whose edges were seeded
            # without an explicit ``confirmed`` sourceHandle still advance.
            next_node = self._confirmed_branch_next_node(node_id)
            next_node_id = next_node.id if next_node else node_id
            if next_node:
                self.state.advance_to(next_node.id)

            # If confirming lands directly on END/TRANSFER, execute it rather
            # than merely surfacing the message text.
            terminal_result = await self._maybe_execute_terminal_transition(next_node)
            if terminal_result is not None:
                return terminal_result

            next_node_message, next_is_static = (
                self._get_next_node_configured_message(next_node) if next_node else (None, False)
            )

            result: dict = {
                "success": True,
                "action": None,
                "confirmed": True,
                "current_node_id": next_node_id,
            }

            if next_node_message:
                result["message"] = next_node_message
                if next_is_static:
                    result["speak_exactly"] = next_node_message
            elif summary_message:
                confirmed_text = f"Thank you for confirming. {summary_message}"
                result["message"] = confirmed_text
                if is_static:
                    result["speak_exactly"] = confirmed_text
            else:
                result["message"] = "Thank you for confirming."

            # Operator-authored summary/prompt text must be spoken directly —
            # without this guarantee a live call went silent for ~10s.
            result["speak_directly"] = True
            return result

        # Not confirmed — caller wants a change.
        field_to_change = arguments.get("field_to_change")
        new_value = arguments.get("new_value")

        if field_to_change and _is_valid_new_value(new_value):
            correction_error = self.correct_caller_slot(field_to_change, new_value)
            if correction_error:
                return {
                    "success": False,
                    "action": None,
                    "confirmed": False,
                    "current_node_id": node_id,
                    "message": correction_error,
                    "speak_directly": True,
                }
            # Re-render after the slot update so the new value appears inline.
            updated_summary = (
                substitute_variables(summary_template, self.state.collected_slots)
                if summary_template
                else ""
            )
            updated_confirm = (
                substitute_variables(confirm_prompt, self.state.collected_slots)
                if confirm_prompt
                else "Is everything else correct?"
            )
            message = (
                f"{updated_summary} {updated_confirm}".strip()
                if updated_summary
                else updated_confirm
            )
            return {
                "success": True,
                "action": None,
                "confirmed": False,
                "current_node_id": node_id,
                "message": message,
                "speak_directly": True,
            }

        if field_to_change:
            return {
                "success": True,
                "action": None,
                "confirmed": False,
                "current_node_id": node_id,
                "message": self._targeted_field_question(field_to_change),
                "speak_directly": True,
            }

        # No specific field named — follow the edit edge and ask the generic prompt.
        next_node = self.state.get_next_node(node_id, handle="edit")
        next_node_id = next_node.id if next_node else node_id
        if next_node:
            self.state.advance_to(next_node.id)

        terminal_result = await self._maybe_execute_terminal_transition(next_node)
        if terminal_result is not None:
            return terminal_result

        return {
            "success": True,
            "action": None,
            "confirmed": False,
            "current_node_id": next_node_id,
            "message": edit_message,
            "speak_directly": True,
        }

    async def _handle_confirmation(self, function_name: str, arguments: dict) -> dict:
        """Handle a CONFIRMATION node — the LLM called ``confirm_<node_id>``.

        Thin dispatcher: resolves the node then delegates all logic to
        ``_run_confirmation_logic``.
        """
        node_id = function_name.replace("confirm_", "")
        node = self.flow_config._node_index.get(node_id)
        if not node:
            return {
                "success": False,
                "message": "Confirmation node not found",
                "action": None,
                "current_node_id": None,
            }
        confirmed = arguments.get("confirmed", True)
        return await self._run_confirmation_logic(node, confirmed, arguments)

    def _targeted_field_question(self, field_key: str) -> str:
        """Return a targeted correction prompt for *field_key*.

        Looks up the variable's description so the AI can ask specifically for
        the right piece of information instead of a generic fallback.
        """
        for var in self.flow_config.variables:
            if var.key == field_key:
                return f"May I have your correct {var.description}?"
        return "What is the correct value?"

    def _get_next_node_configured_message(
        self, node: Optional[FlowNode]
    ) -> tuple[Optional[str], bool]:
        """Get the configured message from a node and whether to speak it exactly.

        Returns: (message, is_static) tuple
        - message: The resolved message text, or None if no message
        - is_static: True if the node is in static delivery mode (speak exactly)
        """
        if not node:
            return (None, False)

        delivery_mode = self._get_node_delivery_mode(node)
        is_static = delivery_mode == "static"

        if node.type == NodeType.MESSAGE:
            message = node.data.get("message", "")
            resolved = (
                substitute_variables(message, self.state.collected_slots) if message else None
            )
            return (resolved, is_static)
        elif node.type == NodeType.COLLECT_SLOT:
            slot = node.data.get("slot", {})
            prompt = slot.get("prompt", "")
            resolved = substitute_variables(prompt, self.state.collected_slots) if prompt else None
            return (resolved, False)
        elif node.type == NodeType.COLLECT_FORM:
            intro = node.data.get("introMessage", "")
            if intro:
                resolved = substitute_variables(intro, self.state.collected_slots)
                return (resolved, False)
            first = self._first_uncollected_slot(node.data.get("slots", []))
            if first:
                prompt = first.get("prompt", "")
                resolved = substitute_variables(prompt, self.state.collected_slots) if prompt else None
                return (resolved, False)
            return (None, False)
        elif node.type == NodeType.CONFIRMATION:
            confirmation_data = node.data.get("confirmation", {})
            summary_template = confirmation_data.get(
                "summaryTemplate", confirmation_data.get("summary_template", "")
            )
            confirm_prompt = confirmation_data.get(
                "confirmPrompt", confirmation_data.get("confirm_prompt", "")
            )
            parts = []
            if summary_template:
                parts.append(substitute_variables(summary_template, self.state.collected_slots))
            if confirm_prompt:
                parts.append(substitute_variables(confirm_prompt, self.state.collected_slots))
            resolved = " ".join(parts) if parts else None
            return (resolved, is_static)
        elif node.type == NodeType.END:
            message = node.data.get("closingMessage", "")
            resolved = (
                substitute_variables(message, self.state.collected_slots) if message else None
            )
            return (resolved, False)
        elif node.type == NodeType.TRANSFER:
            transfer = node.data.get("transfer", {})
            message = transfer.get("preTransferMessage", "")
            resolved = (
                substitute_variables(message, self.state.collected_slots) if message else None
            )
            return (resolved, False)
        elif node.type in (NodeType.API_REQUEST, NodeType.CAPABILITY):
            api_config = node.data.get("api", {})
            return (api_config.get("onSuccess", None), False)
        elif node.type == NodeType.OPTION_PICKER:
            config = node.data.get("optionPicker", {}) or {}
            prompt = (config.get("prompt") or "").strip()
            resolved = substitute_variables(prompt, self.state.collected_slots) if prompt else None
            return (resolved, False)

        return (None, False)

    async def _maybe_execute_terminal_transition(
        self, next_node: Optional[FlowNode]
    ) -> Optional[dict]:
        """Actually execute the terminal action when a silent advance lands
        on an END or TRANSFER node — never just surface its message.

        SET_VARIABLE, ROUTER, SAVE_RECORD, and CONFIRMATION can all advance
        straight into END/TRANSFER with no LLM function call in between. The
        naive fix (surface that node's configured message with
        speak_directly=True) only ever spoke the words: it never invoked
        end_call_callback/transfer_callback, so the call itself never
        actually ended or transferred (Task #534 completion-review fix).
        Routing through the exact same handlers a direct end_call_<id>/
        transfer_<id> function call would use guarantees identical behavior
        — closing-message resolution, the real callback invocation, and the
        "action": "end"/"transfer" result the voice mapper already knows how
        to speak-and-finalize (see function_mapper.py's dedicated handling
        for those two action values, which bypasses speak_directly entirely).

        Returns the terminal handler's result dict, or None if *next_node*
        is not a terminal node (caller should fall back to its normal
        message-surfacing behavior).
        """
        if next_node is None:
            return None
        if next_node.type == NodeType.END:
            return await self._handle_end_call(f"end_call_{next_node.id}", {})
        if next_node.type == NodeType.TRANSFER:
            return await self._handle_transfer(
                f"transfer_{next_node.id}", {"reason": "Flow reached a transfer step"}
            )
        return None

    async def _handle_set_variable(self, function_name: str, arguments: dict) -> dict:
        """Handle setting a variable value."""
        node_id = function_name.replace("set_var_", "")
        node = self.flow_config._node_index.get(node_id)

        if not node:
            return {
                "success": False,
                "message": "Set variable node not found",
                "action": None,
                "current_node_id": None,
            }

        set_var_data = node.data.get("setVariable", node.data.get("set_variable", {}))
        var_key = set_var_data.get("variableKey", set_var_data.get("variable_key", ""))
        value_type = set_var_data.get("valueType", set_var_data.get("value_type", "static"))
        value = set_var_data.get("value", "")

        if value_type == "template":
            final_value = substitute_variables(value, self.state.collected_slots)
        else:
            final_value = value

        if var_key:
            self.state.set_variable(var_key, final_value)

        next_node = self.state.get_next_node(node_id)
        next_node_id = next_node.id if next_node else node_id
        if next_node:
            self.state.advance_to(next_node.id)

        result = {
            "success": True,
            "message": f"Set {var_key} to {final_value}",
            "action": None,
            "set_variable": {var_key: final_value},
            "current_node_id": next_node_id,
        }

        # If this silently advances straight into END/TRANSFER, actually
        # execute that terminal action rather than merely speaking its
        # message (Task #534 completion-review fix).
        terminal_result = await self._maybe_execute_terminal_transition(next_node)
        if terminal_result is not None:
            return terminal_result

        # SET_VARIABLE is a silent internal step — its own message is debug
        # context only and must never be spoken. But it can advance straight
        # into a node with real caller-facing content (a MESSAGE, CONFIRMATION,
        # END, or TRANSFER node) with no other direct-speech guarantee, which
        # is exactly the class of dead-air bug this surfaced on a live call.
        # Surface that destination content so the mapper can speak it directly.
        next_node_message, next_is_static = self._get_next_node_configured_message(next_node)
        if next_node_message:
            result["message"] = next_node_message
            result["speak_directly"] = True
            if next_is_static:
                result["speak_exactly"] = next_node_message

        return result

    async def _handle_save_record(self, function_name: str, arguments: dict) -> dict:
        """Serialize SAVE_RECORD per node and reuse the winner's durable id.

        Lock ordering note: ``handle_function_call`` already acquired
        ``_save_record_locks[node_id]`` (the per-node entry lock) BEFORE the
        executor-wide ``_turn_lock``.  Re-acquiring it here would deadlock.
        The outer entry lock + turn lock together already ensure only one
        active coroutine per node reaches this point.
        """
        return await self._handle_save_record_locked(function_name, arguments)

    def _save_record_idempotency_key(self, node_id: str) -> tuple[str, bool]:
        """Return a stable SAVE_RECORD key and whether it is cross-worker durable."""
        if self.flow_tool_id:
            flow_identity = str(self.flow_tool_id)
        else:
            canonical_flow = {
                "initial": self.flow_config.initial_node,
                "nodes": sorted((n.id, n.type.value) for n in self.flow_config.nodes),
                "variables": sorted(v.key for v in self.flow_config.variables),
            }
            flow_identity = hashlib.sha256(
                json.dumps(canonical_flow, sort_keys=True).encode()
            ).hexdigest()
        if self.call_sid:
            contact_scope = f"call:{self.call_sid}"
            durable = True
        else:
            contact_scope = f"executor:{self._save_record_fallback_scope}"
            durable = False
        material = "|".join(
            (
                "save_record:v1",
                str(self.account_id or ""),
                contact_scope,
                flow_identity,
                node_id,
            )
        )
        return hashlib.sha256(material.encode()).hexdigest(), durable

    async def _handle_save_record_locked(
        self, function_name: str, arguments: dict
    ) -> dict:
        """Handle a SAVE_RECORD flow node (voice-only).

        Persists the collected flow variables as a structured Record for the
        node's configured RecordType. The RecordType MUST belong to the same
        account as the executor (validated here as well as at flow-save time).

        Failures are logged and swallowed: a persistence problem must never
        derail a live call, so we always advance to the next node.
        """
        node_id = function_name.replace("save_record_", "")
        node = self.flow_config._node_index.get(node_id)

        # Always compute the next node up front so a failure still advances.
        next_node = self.state.get_next_node(node_id) if node else None
        next_node_id = next_node.id if next_node else node_id
        if next_node:
            self.state.advance_to(next_node.id)

        def _result(saved: bool, message: str) -> dict:
            return {
                "success": True,
                "message": message,
                "action": None,
                "record_saved": saved,
                "current_node_id": next_node_id,
            }

        if not node:
            return _result(False, "Save record node not found")

        if node_id in self.state.saved_records:
            return _result(True, "Record was already saved")

        if not self.account_id:
            logger.warning("SAVE_RECORD skipped: no account_id on executor")
            return _result(False, "Record could not be saved")

        save_data = node.data.get("saveRecord", node.data.get("save_record", {}))
        record_type_id = save_data.get("recordTypeId", save_data.get("record_type_id"))
        if not record_type_id:
            logger.warning(f"SAVE_RECORD node {node_id} has no recordTypeId configured")
            return _result(False, "Record type not configured")

        # Capture all inputs under the turn lock BEFORE releasing it.  The DB
        # transaction runs in a thread pool (asyncio.to_thread) so it must work
        # with a point-in-time snapshot rather than the live mutable state.
        _idempotency_key, _durable_key = self._save_record_idempotency_key(node_id)
        if not _durable_key:
            logger.warning(
                f"SAVE_RECORD node {node_id} has no call/session identity; "
                "idempotency is scoped to this executor only"
            )
        _slots_snap = dict(self.state.collected_slots)
        _account_id = self.account_id
        _call_sid = self.call_sid
        _flow_tool_id = self.flow_tool_id

        def _run_db() -> tuple[Optional[str], bool, str, Optional[str]]:
            """Synchronous DB work — runs in asyncio.to_thread().

            Returns: (record_id | None, created, record_type_name, error | None)
            All inputs are captured from the enclosing scope at definition time;
            none of them aliases live mutable state on the executor.
            """
            import uuid as _uuid_mod

            from sqlalchemy.exc import IntegrityError

            from botelier.database import SessionLocal
            from botelier.models.call_log import CallLog
            from botelier.models.record import CaptureMethod, Record, SourceChannel
            from botelier.models.record_type import RecordType

            try:
                account_uuid = _uuid_mod.UUID(str(_account_id))
                record_type_uuid = _uuid_mod.UUID(str(record_type_id))
            except (ValueError, TypeError):
                logger.warning(f"SAVE_RECORD node {node_id}: invalid account/record_type id")
                return None, False, "", "Record could not be saved"

            db = SessionLocal()
            try:
                # Tenant isolation: the record type must belong to this account.
                record_type = (
                    db.query(RecordType)
                    .filter(
                        RecordType.id == record_type_uuid,
                        RecordType.account_id == account_uuid,
                    )
                    .first()
                )
                if record_type is None:
                    logger.warning(
                        f"SAVE_RECORD node {node_id} references record_type "
                        f"{record_type_id} not owned by account {_account_id}"
                    )
                    return None, False, "", "Record type not available"

                # Resolve using the slot snapshot captured before lock release.
                data, status = self._resolve_record_payload(
                    save_data, record_type, slots=_slots_snap
                )

                # Link back to the originating call (best-effort).
                source_call_log_id = None
                assistant_id = None
                if _call_sid:
                    call_log = (
                        db.query(CallLog)
                        .filter(CallLog.call_sid == _call_sid)
                        .first()
                    )
                    if call_log is not None:
                        source_call_log_id = call_log.id
                        assistant_id = call_log.assistant_id

                record = Record(
                    account_id=account_uuid,
                    record_type_id=record_type_uuid,
                    status=status,
                    data=data,
                    source_channel=SourceChannel.VOICE.value,
                    capture_method=CaptureMethod.FLOW_NODE.value,
                    source_call_log_id=source_call_log_id,
                    assistant_id=assistant_id,
                    idempotency_key=_idempotency_key,
                )
                record_type_name = record_type.name
                db.add(record)
                created = True
                try:
                    db.commit()
                except IntegrityError:
                    # Another worker committed first — reuse the winner.
                    db.rollback()
                    record = (
                        db.query(Record)
                        .filter(
                            Record.account_id == account_uuid,
                            Record.idempotency_key == _idempotency_key,
                        )
                        .first()
                    )
                    if record is None:
                        raise
                    created = False
                return str(record.id), created, record_type_name, None
            except Exception as exc:  # noqa: BLE001 - never break a live call
                logger.error(f"SAVE_RECORD node {node_id} failed: {exc}", exc_info=True)
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                return None, False, "", "Record could not be saved"
            finally:
                try:
                    db.close()
                except Exception:  # noqa: BLE001
                    pass

        # Release the turn lock and dispatch all synchronous DB work to a
        # thread pool worker.  SQLAlchemy is blocking — running it directly on
        # the event-loop thread would prevent any other coroutine from
        # progressing even after the asyncio lock is released.
        async with self._suspend_turn_lock():
            _record_id, _created, _record_type_name, _io_error = (
                await asyncio.to_thread(_run_db)
            )
        # Turn lock reacquired — apply state mutations.

        if _io_error:
            return _result(False, _io_error)
        if _record_id is None:
            return _result(False, "Record could not be saved")

        # Remember the saved record so later variable changes (e.g. a
        # confirm/edit correction after the save already fired) sync back
        # into it instead of leaving the record stale.
        try:
            self.state.saved_records[node_id] = _record_id  # state mutation inside lock ✓
        except Exception:  # noqa: BLE001 - tracking is best-effort
            pass

        # Persist the idempotency marker: release the turn lock so a slow
        # snapshot DB write does not stall other handlers.  The outer
        # dispatcher also snapshots after handle_function_call returns; this
        # earlier call closes the reconnect window between DB commit and that
        # outer snapshot.
        async with self._suspend_turn_lock():
            await self._snapshot_state()
        # Turn lock reacquired.

        if not _created:
            logger.info(
                f"SAVE_RECORD: reused atomic winner for node {node_id} "
                f"(call_sid={self.call_sid})"
            )
            return _result(True, "Record was already saved")
        logger.info(
            f"SAVE_RECORD: saved {_record_type_name} record for type "
            f"{record_type_id} (call_sid={self.call_sid})"
        )
        # Post-I/O state revalidation: another turn may have advanced the flow
        # while the DB write was suspended.  Only execute the terminal
        # transition derived BEFORE I/O if the current node still matches
        # what we advanced to; otherwise the transition targets stale state.
        if next_node and self.state.current_node_id != next_node_id:
            logger.info(
                "SAVE_RECORD node %r: flow advanced to %r during I/O "
                "— skipping terminal transition on stale next_node %r",
                node_id,
                self.state.current_node_id,
                next_node_id,
            )
            next_node = None

        # The raw field dump is LLM context only — never spoken verbatim to a
        # caller. If the node advances into real caller-facing content, speak
        # that; otherwise speak a short, friendly acknowledgment.
        # If the save silently advances straight into END/TRANSFER, actually
        # execute that terminal action (Task #534 completion-review fix).
        terminal_result = await self._maybe_execute_terminal_transition(next_node)
        if terminal_result is not None:
            return terminal_result

        result = _result(True, f"Saved {_record_type_name} record")
        # _record_type_name is kept local diagnostic only — never added to
        # the result dict which function_mapper passes to LLM context.
        next_node_message, next_is_static = self._get_next_node_configured_message(next_node)
        if next_node_message:
            result["message"] = next_node_message
            result["speak_directly"] = True
            if next_is_static:
                result["speak_exactly"] = next_node_message
        else:
            result["message"] = "Got it, that's saved."
            result["speak_directly"] = True
        return result

    def _resolve_record_payload(
        self,
        save_data: dict,
        record_type,
        slots: Optional[dict] = None,
    ) -> tuple[dict, Optional[str]]:
        """Resolve a SAVE_RECORD node's field mapping + status against slots.

        ``slots`` defaults to ``self.state.collected_slots`` when not provided.
        Pass an explicit snapshot dict when calling from a thread pool worker
        (``asyncio.to_thread``) so the resolver uses a safe point-in-time copy
        of the state rather than the live mutable dict.

        Shared by the initial save and the post-save sync so both always
        produce identical payloads for identical variable state.
        """
        _slots = slots if slots is not None else self.state.collected_slots
        mapping = save_data.get("mapping", save_data.get("fieldMapping", {})) or {}
        valid_keys = {
            f.get("key") for f in (record_type.fields or []) if isinstance(f, dict)
        }
        data: dict[str, Any] = {}
        for field_key, template in mapping.items():
            if field_key not in valid_keys:
                continue
            if not isinstance(template, str):
                data[field_key] = template
                continue
            resolved = substitute_variables(template, _slots).strip()
            if resolved:
                data[field_key] = resolved

        # Optional static/template status, validated against status_options.
        status = None
        status_raw = save_data.get("status")
        if isinstance(status_raw, str) and status_raw.strip():
            candidate = substitute_variables(status_raw, _slots).strip()
            allowed = {
                o.get("value")
                for o in (record_type.status_options or [])
                if isinstance(o, dict)
            }
            if not allowed or candidate in allowed:
                status = candidate or None

        return data, status

    async def _sync_saved_records(self) -> None:
        """Re-sync already-saved records after any post-save variable change.

        If a SAVE_RECORD node fired and the caller then corrects a value (e.g.
        via the confirmation edit path), the stored record would silently go
        stale. Runs after every function call; no-op until a record exists.
        Best-effort in a worker thread with its own session — a sync failure
        never affects the live call.
        """
        if not self.state.saved_records or not self.account_id:
            return
        try:
            await asyncio.to_thread(self._sync_saved_records_blocking)
        except Exception as exc:  # noqa: BLE001 - sync must never break a call
            logger.warning(f"Saved-record sync failed (non-fatal): {exc}")

    def _sync_saved_records_blocking(self) -> None:
        """Recompute each saved record's payload and update it if it changed.

        Account-scoped on every lookup (tenant isolation); uses a dedicated
        short-lived session, mirroring ``_handle_save_record``.

        Implementation note — bulk-load strategy: collecting all relevant
        Record and RecordType rows in two queries (one per model) avoids
        the 2N+N round trips the per-record approach produces under a flow
        with N saved records.  All filtering and comparison happens in-memory;
        a single commit closes out any rows that changed.
        """
        import uuid as _uuid

        from botelier.database import SessionLocal
        from botelier.models.record import Record
        from botelier.models.record_type import RecordType

        try:
            account_uuid = _uuid.UUID(str(self.account_id))
        except (ValueError, TypeError):
            return

        # --- Phase 1: collect valid entries and resolve node data ---------------
        entries: list[tuple[str, _uuid.UUID, dict]] = []
        for node_id, record_id in list(self.state.saved_records.items()):
            node = self.flow_config._node_index.get(node_id)
            if node is None:
                continue
            try:
                record_uuid = _uuid.UUID(str(record_id))
            except (ValueError, TypeError):
                continue
            save_data = node.data.get("saveRecord", node.data.get("save_record", {}))
            entries.append((node_id, record_uuid, save_data))

        if not entries:
            return

        record_uuid_set = [record_uuid for _, record_uuid, _ in entries]

        db = SessionLocal()
        try:
            # --- Phase 2: bulk-load all needed Record rows in one query ----------
            records_by_id: dict[_uuid.UUID, Record] = {
                r.id: r
                for r in db.query(Record)
                .filter(Record.id.in_(record_uuid_set), Record.account_id == account_uuid)
                .all()
            }

            # --- Phase 3: bulk-load all needed RecordType rows in one query ------
            record_type_ids = {r.record_type_id for r in records_by_id.values()}
            record_types_by_id: dict[_uuid.UUID, RecordType] = {
                rt.id: rt
                for rt in db.query(RecordType)
                .filter(
                    RecordType.id.in_(record_type_ids),
                    RecordType.account_id == account_uuid,
                )
                .all()
            }

            # --- Phase 4: in-memory diff and mark dirty rows --------------------
            updated_ids: list[str] = []
            for _node_id, record_uuid, save_data in entries:
                record = records_by_id.get(record_uuid)
                if record is None:
                    continue
                record_type = record_types_by_id.get(record.record_type_id)
                if record_type is None:
                    continue

                data, status = self._resolve_record_payload(save_data, record_type)

                changed = False
                if data != (record.data or {}):
                    record.data = data
                    changed = True
                if status is not None and status != record.status:
                    record.status = status
                    changed = True

                if changed:
                    updated_ids.append(str(record_uuid))

            # --- Phase 5: single commit for all dirty rows ----------------------
            if updated_ids:
                db.commit()
                logger.info(
                    f"SAVE_RECORD sync: updated {len(updated_ids)} record(s) after "
                    f"post-save variable change (call_sid={self.call_sid}): {updated_ids}"
                )
        except Exception:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_transfer(self, function_name: str, arguments: dict) -> dict:
        """Handle a call transfer request."""
        node_id = function_name.replace("transfer_", "")
        node = self.flow_config._node_index.get(node_id)

        if not node:
            return {
                "success": False,
                "message": "Transfer node not found",
                "action": None,
                "current_node_id": None,
            }

        transfer_config = node.data.get("transfer", {})
        phone_number = transfer_config.get("phoneNumber", "")
        pre_message = transfer_config.get("preTransferMessage", "Please hold while I transfer you.")
        transfer_mode = transfer_config.get("transferMode", "warm")

        # Guard: forwarding an empty phone number to the PSTN/SIP carrier
        # triggers a carrier-level error rather than a clean in-flow failure.
        # Catch this early — before any state mutation or callback — so the
        # operator sees a structured result and the caller hears something useful.
        if not phone_number or not phone_number.strip():
            logger.warning(
                f"_handle_transfer node {node_id!r}: phone number is empty — "
                "transfer is not configured; returning failure without mutating state"
            )
            return {
                "success": False,
                "message": "Transfer is not configured — no phone number set.",
                "action": None,
                "current_node_id": self.state.current_node_id,
            }

        # Snapshot the current node position before releasing the turn lock.
        # If a concurrent permitted turn advances the flow during the carrier
        # wait, we must not roll it back by calling advance_to(node_id)
        # unconditionally on reacquisition.  (Same post-I/O revalidation
        # contract used by _handle_integration_api_request and friends.)
        _pre_callback_node_id = self.state.current_node_id

        if self.transfer_callback:
            # Attempt the callback BEFORE committing state so a carrier rejection
            # leaves the executor in a clean, un-mutated position.  Release the
            # turn lock during the slow telephony round-trip; reacquire before
            # writing state below.
            try:
                async with self._suspend_turn_lock():
                    await self.transfer_callback(
                        phone_number, arguments.get("reason", ""), transfer_mode=transfer_mode
                    )
            except Exception as exc:
                # Callback failed — state is NOT mutated.  Return a structured
                # failure so the LLM can narrate the error to the caller instead
                # of going silent.
                logger.error(
                    "transfer_callback raised for node %r (target=%r): %s",
                    node_id, phone_number, exc, exc_info=True,
                )
                return {
                    "success": False,
                    "message": "The transfer could not be completed. Please try again or ask to speak with someone.",
                    "action": None,
                    "current_node_id": self.state.current_node_id,
                }

        # Callback succeeded (or no callback) — commit the transfer terminal
        # signals.  These are always safe to write: the telephony platform is
        # already executing the transfer regardless of flow position.
        self.state.transfer_requested = True
        self.state.transfer_target = phone_number

        # Post-I/O node revalidation: only advance to the transfer node if a
        # concurrent turn has not already moved the flow elsewhere.  Rolling
        # back to an older node would corrupt any progress made during the
        # carrier wait.
        if self.state.current_node_id == _pre_callback_node_id:
            self.state.advance_to(node_id)
        else:
            logger.info(
                "_handle_transfer: flow advanced to %r during carrier wait "
                "— skipping advance to transfer node %r; transfer signal committed",
                self.state.current_node_id,
                node_id,
            )

        return {
            "success": True,
            "message": pre_message,
            "action": "transfer",
            "target": phone_number,
            "transfer_mode": transfer_mode,
            "current_node_id": node_id,
        }

    async def _handle_end_call(self, function_name: str, arguments: dict) -> dict:
        """Handle ending the call."""
        # Idempotency guard: if the call is already ending (e.g. a second LLM turn
        # arrived while EndFrame was propagating), swallow the duplicate silently.
        # Include current_node_id so the result shape is consistent with the
        # normal end path (mapper and tests expect it to always be present).
        if self.state.is_complete:
            node_id_idem = function_name.replace("end_call_", "")
            return {"success": True, "message": "", "action": "end", "current_node_id": node_id_idem}

        node_id = function_name.replace("end_call_", "")
        node = self.flow_config._node_index.get(node_id)

        closing_message = "Thank you for calling. Goodbye!"
        if node:
            closing_message = node.data.get("closingMessage", closing_message)

        closing_message = substitute_variables(closing_message, self.state.collected_slots)

        self.state.is_complete = True
        self.state.advance_to(node_id)

        if self.end_call_callback:
            try:
                # Release the turn lock while the end-call callback runs — it
                # may trigger telephony teardown which can be slow.
                async with self._suspend_turn_lock():
                    await self.end_call_callback(closing_message)
            except Exception as exc:
                # A callback failure must not leave is_complete=True while the
                # caller receives no result — log and continue so the result
                # dict is still returned to the mapper.
                logger.error(f"end_call_callback raised: {exc}", exc_info=True)

        return {
            "success": True,
            "message": closing_message,
            "action": "end",
            "current_node_id": node_id,
        }

    async def _handle_confirm_details(self, arguments: dict) -> dict:
        """Handle the built-in ``confirm_details`` fallback (flows without a CONFIRMATION node).

        This tool is only exposed to the LLM when the flow has no CONFIRMATION
        node (``_should_expose_confirm_details``).  If a CONFIRMATION node is
        present anyway — e.g. the LLM called the wrong function — we still
        delegate to ``_run_confirmation_logic`` so the behaviour is identical to
        ``_handle_confirmation`` and the edge-fallback guard is applied.

        The no-node tail handles genuinely node-free flows and is intentionally
        kept separate: it has no graph to advance, so it only updates the
        ``_details_confirmed`` flag and returns a simple acknowledgement.
        """
        confirmed = arguments.get("confirmed", False)

        # Defensive: if a CONFIRMATION node exists, use the canonical shared logic.
        confirmation_node = next(
            (n for n in self.flow_config.nodes if n.type == NodeType.CONFIRMATION), None
        )
        if confirmation_node:
            return await self._run_confirmation_logic(confirmation_node, confirmed, arguments)

        # ── No CONFIRMATION node in the flow ─────────────────────────────────
        if confirmed:
            # Prevent the LLM from looping back into re-confirming after success.
            self._details_confirmed = True
            return {
                "success": True,
                "message": "Great, confirmed.",
                "action": "confirmed",
                "collected_data": self.state.collected_slots.copy(),
                "current_node_id": self.state.current_node_id,
                "speak_directly": True,
            }

        field_to_change = arguments.get("field_to_change")
        new_value = arguments.get("new_value")
        if field_to_change and _is_valid_new_value(new_value):
            correction_error = self.correct_caller_slot(field_to_change, new_value)
            if correction_error:
                return {
                    "success": False,
                    "message": correction_error,
                    "action": None,
                    "current_node_id": self.state.current_node_id,
                    "speak_directly": True,
                }
            return {
                "success": True,
                "message": "Got it, I've updated that. Is everything else correct?",
                "action": None,
                "current_node_id": self.state.current_node_id,
                "speak_directly": True,
            }
        if field_to_change:
            return {
                "success": True,
                "message": self._targeted_field_question(field_to_change),
                "action": None,
                "current_node_id": self.state.current_node_id,
                "speak_directly": True,
            }
        return {
            "success": True,
            "message": "What would you like to change?",
            "action": None,
            "current_node_id": self.state.current_node_id,
            "speak_directly": True,
        }

    def get_collected_data(self) -> dict:
        """Get all collected slot values."""
        return self.state.collected_slots.copy()

    def get_progress(self) -> dict:
        """Get flow execution progress."""
        total_required = sum(1 for v in self.flow_config.variables if v.required)
        collected = sum(
            1
            for v in self.flow_config.variables
            if v.required and v.key in self.state.collected_slots
        )

        return {
            "total_slots": len(self.flow_config.variables),
            "required_slots": total_required,
            "collected_slots": len(self.state.collected_slots),
            "required_collected": collected,
            "is_complete": collected >= total_required,
            "current_node": self.state.current_node_id,
        }

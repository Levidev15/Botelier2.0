"""Bounded, immutable admission for editor-authored native flow graphs.

Compilation is deliberately pure: it validates and snapshots configuration but
never resolves integrations, records, providers, or runtime actions.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
import re
from typing import Any

from botelier.services.request_templates import RequestTemplateError, render_json_template
from botelier.services.response_projection import (
    ResponseProjectionError,
    validate_mapped_projection,
)
from botelier.voice.flows.pilot_contract import PilotIdentity


MAX_NODES = 128
MAX_EDGES = 512
MAX_DEFINITION_BYTES = 256_000
MAX_NODE_BYTES = 32_000
MAX_TOTAL_IO_BYTES = 1_000_000
MAX_REVISITS = 12

_NODE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_VARIABLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_SECRET_TOKEN = re.compile(r"{{\s*secrets\.([A-Za-z][A-Za-z0-9_]*)\s*}}")
_RESERVED_VARIABLES = frozenset({
    "status", "current_node_id", "flow_version_id", "account_id",
    "property_id", "call_sid", "tool_id", "outcome", "success",
})
_SLOT_TYPES = frozenset({"text", "date", "number", "phone", "email", "time", "choice"})
_NODE_TYPES = frozenset({
    "initial", "message", "collect_slot", "collect_form", "api_request",
    "api_response", "condition", "router", "confirmation", "set_variable",
    "save_record", "transfer", "capability", "option_picker", "end",
})
_COMMON_DATA = frozenset({"name", "description", "instructions"})
_NODE_FIELDS = {
    "initial": {"systemPrompt", "greeting", "waitForResponse"},
    "message": {"message", "waitForResponse", "deliveryMode"},
    "collect_slot": {"slot"},
    "collect_form": {"introMessage", "slots"},
    "api_request": {"api"},
    "api_response": {"responsePresentation"},
    "condition": {"condition"},
    "router": {"router"},
    "confirmation": {"confirmation"},
    "set_variable": {"setVariable", "set_variable"},
    "save_record": {"saveRecord", "save_record"},
    "transfer": {"transfer"},
    "capability": {"api"},
    "option_picker": {"optionPicker", "option_picker"},
    "end": {"closingMessage"},
}
_NODE_UI_FIELDS = frozenset({
    "id", "type", "data", "position", "selected", "dragging", "measured",
    "width", "height", "style", "className", "hidden", "zIndex", "origin",
    "extent", "expandParent", "parentId", "sourcePosition", "targetPosition",
    "selectable", "draggable", "connectable", "focusable", "deletable", "resizing",
})
_EDGE_UI_FIELDS = frozenset({
    "id", "source", "target", "sourceHandle", "targetHandle", "animated",
    "label", "type", "style", "selected", "markerEnd", "markerStart",
    "className", "deletable", "focusable", "interactionWidth", "reconnectable",
    "hidden", "zIndex",
})
_API_FIELDS = frozenset({
    "method", "url", "headers", "bodyTemplate", "responseMapping",
    "responseProjection", "responseInstructions", "thinkingMessage", "timeout",
    "retryCount", "retryDelay", "onSuccess", "onError", "onComplete",
    "onNotFound", "onAuthError", "apiSource", "capability", "integrationId",
    "integrationSlug", "endpointId", "endpointName", "autoMappingSource",
    "queryParamOverrides", "path", "responseVariables",
    "mcpConnectionId", "mcpToolName", "argumentsTemplate", "toolId",
})
_SLOT_FIELDS = frozenset({
    "id", "order", "variableKey", "prompt", "type", "validation",
    "retryPrompt", "maxRetries", "useBuiltInValidator", "instructions",
})
_VALIDATION_FIELDS = frozenset({
    "pattern", "min", "max", "minLength", "maxLength", "choices",
    "requireFuture", "minDaysAhead", "maxDaysAhead", "allowDecimal",
    "crossFieldCheck", "afterDateVariable", "after_date_variable",
})
_NUMERIC_VALIDATION = frozenset({
    "min", "max", "minLength", "maxLength", "minDaysAhead", "maxDaysAhead",
})


class NativeGraphError(ValueError):
    """Safe, stable category diagnostic; never contains configuration values."""


def _fail(category: str, node_id: str | None = None, field_name: str | None = None):
    parts = [category]
    if node_id is not None:
        parts.append(node_id)
    result = ":".join(parts)
    if field_name is not None:
        result += "." + field_name
    raise NativeGraphError(result)


def _keys(value: dict, allowed: frozenset[str], category: str, node_id=None):
    for key in value:
        if not isinstance(key, str) or key not in allowed:
            safe_key = key if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key) else "unknown"
            _fail(category, node_id, safe_key)


def _text(value: Any, category: str, node_id: str, field_name: str, *, required=False,
          limit=8000) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _fail(category, node_id, field_name)
    return value


def _identifier(value: Any, regex: re.Pattern, category: str, node_id=None,
                field_name=None) -> str:
    if not isinstance(value, str) or not regex.fullmatch(value):
        _fail(category, node_id, field_name)
    return value


def _integer(value: Any, low: int, high: int, category: str, node_id: str, field: str):
    if type(value) is not int or not low <= value <= high:
        _fail(category, node_id, field)


def _boolean(value: Any, category: str, node_id: str, field: str):
    if type(value) is not bool:
        _fail(category, node_id, field)


def _template(value: Any, declared: set[str], category: str, node_id: str,
              field_name: str, *, required=False, local_tokens=frozenset(), limit=8000):
    value = _text(value, category, node_id, field_name, required=required, limit=limit)
    residual = _TOKEN.sub("", value)
    if "{{" in residual or "}}" in residual:
        _fail(category, node_id, field_name)
    missing = set(_TOKEN.findall(value)) - declared - set(local_tokens)
    if missing:
        _fail("template_variable", node_id, field_name)
    return value


def _json_path(value: Any, category: str, node_id: str, field_name: str, *,
               allow_empty=False):
    """Validate JSONPath-lite; '$' is root, empty is reserved for whole-item writes."""
    if not isinstance(value, str) or len(value) > 512:
        _fail(category, node_id, field_name)
    if value == "$":
        return
    if not value:
        if allow_empty:
            return
        _fail(category, node_id, field_name)
    normalized = value[1:] if value.startswith("$") else value
    if normalized.startswith("."):
        normalized = normalized[1:]
    if not normalized or normalized.endswith(".") or ".." in normalized:
        _fail(category, node_id, field_name)
    normalized = normalized.replace("[", ".[")
    parts = [part for part in normalized.split(".") if part]
    if not parts:
        _fail(category, node_id, field_name)
    if any(not re.fullmatch(
        r"(?:[A-Za-z_][A-Za-z0-9_-]*|\d+|\[(?:\d+|\*)\])", part
    ) for part in parts):
        _fail(category, node_id, field_name)


def _safe_expression_names(expression: str) -> set[str] | None:
    """Allow deterministic scalar ASTs and return references; never evaluate."""
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    allowed = (
        ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
        ast.UAdd, ast.USub, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq,
        ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Not, ast.IfExp,
    )
    pending = [tree]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > 128 or not isinstance(item, allowed):
            return None
        if isinstance(item, ast.Constant) and not (
            item.value is None or type(item.value) in {str, int, float, bool}
        ):
            return None
        if isinstance(item, ast.Name) and not _VARIABLE.fullmatch(item.id):
            return None
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Pow):
            # Powers can produce unbounded work/results; they are not deterministic-safe here.
            return None
        pending.extend(ast.iter_child_nodes(item))
    return {item.id for item in ast.walk(tree) if isinstance(item, ast.Name)}


def _json_snapshot(value: Any) -> tuple[str, int]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        size = len(encoded.encode("utf-8"))
        if size > MAX_DEFINITION_BYTES:
            _fail("definition_size")
        snapshot = json.loads(encoded)
    except NativeGraphError:
        raise
    except (TypeError, ValueError, RecursionError, OverflowError):
        _fail("definition_json")
    # Bound pathological depth and container fan-out before graph traversal.
    pending = [(snapshot, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 48:
            _fail("definition_depth")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                _fail("definition_json")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return encoded, size


@dataclass(frozen=True)
class CallerSlot:
    node_id: str
    variable: str
    prompt: str
    type: str


@dataclass(frozen=True)
class CompiledNode:
    node_id: str
    type: str
    _data_json: str = field(repr=False)

    def data(self) -> dict:
        """Return a fresh mutable copy of the node's behavior configuration."""
        return json.loads(self._data_json)


@dataclass(frozen=True)
class CompiledVariableDeclaration:
    """Immutable explicit input or mapping-derived output declaration."""

    key: str
    origin: str
    _data_json: str = field(repr=False)

    def data(self) -> dict:
        """Return a fresh detached legacy-shaped declaration."""
        return json.loads(self._data_json)


@dataclass(frozen=True)
class CompiledEdge:
    edge_id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


@dataclass(frozen=True)
class CompiledFlow:
    identity: PilotIdentity
    initial_node_id: str
    nodes: tuple[CompiledNode, ...]
    edges: tuple[CompiledEdge, ...]
    caller_slots: tuple[CallerSlot, ...]
    variable_declarations: tuple[CompiledVariableDeclaration, ...]
    max_nodes: int
    max_edges: int
    max_revisits: int
    max_config_bytes: int
    max_total_io_bytes: int
    _config_json: str = field(repr=False)

    @property
    def native_names(self) -> frozenset[str]:
        return frozenset(
            f"native_{node.node_id}" for node in self.nodes
            if node.type in {
                "message", "collect_slot", "collect_form", "api_request",
                "api_response", "condition", "router", "confirmation",
                "set_variable", "save_record", "transfer", "capability",
                "option_picker", "end",
            }
        )

    def node(self, node_id: str) -> CompiledNode | None:
        return next((item for item in self.nodes if item.node_id == node_id), None)

    def next_node(self, node_id: str, handle: str | None = None) -> CompiledNode | None:
        if not isinstance(node_id, str) or (handle is not None and not isinstance(handle, str)):
            return None
        current = self.node(node_id)
        if current is None:
            return None
        edges = [edge for edge in self.edges if edge.source == node_id]
        if handle is not None:
            selected = next((edge for edge in edges if edge.source_handle == handle), None)
            if selected is not None:
                return self.node(selected.target)
            # Preserve only the legacy confirmed/selected/success default-edge
            # cases; arbitrary or unsupported handles never take that edge.
            defaults = [edge for edge in edges if not edge.source_handle]
            legacy_default_handles = {
                "api_request": {"success"},
                "capability": {"success"},
                "confirmation": {"confirmed"},
                "option_picker": {"selected"},
            }
            if len(defaults) == 1 and handle in legacy_default_handles.get(current.type, set()):
                return self.node(defaults[0].target)
            return None
        default = next((edge for edge in edges if not edge.source_handle), None)
        if default is not None:
            return self.node(default.target)
        return None

    def config(self) -> dict:
        """Return an independent mutable copy; internal active state stays immutable."""
        return json.loads(self._config_json)


def _validate_variable_declarations(config: dict) -> tuple[dict[str, dict], set[str]]:
    variables = config.get("variables", [])
    if not isinstance(variables, list) or len(variables) > 512:
        _fail("variables")
    declarations: dict[str, dict] = {}
    for declaration in variables:
        if not isinstance(declaration, dict):
            _fail("variables")
        _keys(declaration, frozenset({
            "key", "type", "description", "required", "defaultValue", "choices",
        }), "variables")
        key = _identifier(declaration.get("key"), _VARIABLE, "variables", field_name="key")
        if key in _RESERVED_VARIABLES:
            _fail("variables", field_name="key")
        slot_type = declaration.get("type", "text")
        if not isinstance(slot_type, str) or slot_type not in _SLOT_TYPES or key in declarations:
            _fail("variables", field_name="type")
        description = declaration.get("description", "")
        if not isinstance(description, str) or len(description) > 2000:
            _fail("variables", field_name="description")
        required = declaration.get("required", True)
        _boolean(required, "variables", key, "required")
        choices = declaration.get("choices")
        if slot_type == "choice":
            if not isinstance(choices, list) or not choices or len(choices) > 100:
                _fail("variables", key, "choices")
            if any(not isinstance(choice, str) or not choice.strip() for choice in choices):
                _fail("variables", key, "choices")
            if len(set(choices)) != len(choices):
                _fail("variables", key, "choices")
        elif choices is not None:
            _fail("variables", key, "choices")
        if "defaultValue" in declaration and declaration["defaultValue"] is not None:
            default = declaration["defaultValue"]
            if not isinstance(default, (str, int, float, bool)) or (
                isinstance(default, float) and not (default == default and abs(default) != float("inf"))
            ):
                _fail("variables", key, "defaultValue")
        declarations[key] = declaration
    return declarations, set(declarations)


def _validate_slot(slot: Any, node_id: str, variables: dict[str, dict], *, form=False):
    if not isinstance(slot, dict):
        _fail("slot", node_id)
    _keys(slot, _SLOT_FIELDS, "unknown_field", node_id)
    key = _identifier(slot.get("variableKey"), _VARIABLE, "slot", node_id, "variableKey")
    if key not in variables:
        _fail("slot_variable", node_id, "variableKey")
    slot_type = slot.get("type", variables[key].get("type", "text"))
    if not isinstance(slot_type, str) or slot_type not in _SLOT_TYPES or variables[key].get("type", "text") != slot_type:
        _fail("slot_type", node_id, "type")
    prompt = _template(slot.get("prompt"), set(variables), "slot", node_id,
                       "prompt", required=True)
    if "retryPrompt" in slot:
        _template(slot["retryPrompt"], set(variables), "slot", node_id, "retryPrompt")
    retries = slot.get("maxRetries", 3)
    _integer(retries, 0, 20, "slot", node_id, "maxRetries")
    if "useBuiltInValidator" in slot:
        _boolean(slot["useBuiltInValidator"], "slot", node_id, "useBuiltInValidator")
    if "instructions" in slot:
        _template(slot["instructions"], set(variables), "slot", node_id, "instructions")
    validation = slot.get("validation")
    if validation is not None:
        if not isinstance(validation, dict):
            _fail("slot_validation", node_id, "validation")
        _keys(validation, _VALIDATION_FIELDS, "slot_validation", node_id)
        for name, value in validation.items():
            if name in _NUMERIC_VALIDATION:
                if type(value) not in {int, float} or (isinstance(value, float) and abs(value) == float("inf")):
                    _fail("slot_validation", node_id, name)
            elif name in {"requireFuture", "allowDecimal"}:
                _boolean(value, "slot_validation", node_id, name)
            elif name == "pattern":
                _text(value, "slot_validation", node_id, name, limit=512)
                try:
                    re.compile(value)
                except re.error:
                    _fail("slot_validation", node_id, name)
            elif name == "choices":
                if not isinstance(value, list) or len(value) > 100 or any(
                    not isinstance(item, str) or not item.strip() for item in value
                ):
                    _fail("slot_validation", node_id, name)
                if len(set(value)) != len(value):
                    _fail("slot_validation", node_id, name)
            elif name in {"afterDateVariable", "after_date_variable"}:
                if not isinstance(value, str) or value not in variables:
                    _fail("slot_validation", node_id, name)
            elif name == "crossFieldCheck":
                if not isinstance(value, dict):
                    _fail("slot_validation", node_id, name)
                _keys(value, frozenset({"compareWith", "operator", "errorMessage"}),
                      "slot_validation", node_id)
                if not isinstance(value.get("compareWith"), str) or value["compareWith"] not in variables or value.get("operator") not in {
                    "after", "before", "greater", "less",
                }:
                    _fail("slot_validation", node_id, name)
                _text(value.get("errorMessage"), "slot_validation", node_id,
                      "errorMessage", required=True)
        if "min" in validation and "max" in validation and validation["min"] > validation["max"]:
            _fail("slot_validation", node_id, "min")
        if "minLength" in validation and "maxLength" in validation and validation["minLength"] > validation["maxLength"]:
            _fail("slot_validation", node_id, "minLength")
        if "minDaysAhead" in validation and "maxDaysAhead" in validation and validation["minDaysAhead"] > validation["maxDaysAhead"]:
            _fail("slot_validation", node_id, "minDaysAhead")
    if variables[key].get("type") == "choice" and not variables[key].get("choices"):
        _fail("slot_type", node_id, "choices")
    return CallerSlot(node_id, key, prompt, slot_type)


def _validate_api(
    api: Any, node_id: str, variables: dict[str, dict], *,
    available_variables=None, capability=False,
):
    if not isinstance(api, dict):
        _fail("api_config", node_id, "api")
    declared = set(available_variables) if available_variables is not None else set(variables)
    _keys(api, _API_FIELDS, "unknown_field", node_id)
    source = api.get("apiSource", "capability" if capability else "custom")
    allowed_sources = (
        {"capability"} if capability else
        {"custom", "integration", "mcp", "tool", "capability"}
    )
    if not isinstance(source, str) or source not in allowed_sources:
        _fail("api_source", node_id, "apiSource")
    integration_bindings = {
        "integrationId", "integrationSlug", "endpointId", "endpointName",
    }
    mcp_bindings = {"mcpConnectionId", "mcpToolName"}
    if source == "integration":
        incompatible = {
            "url", "mcpConnectionId", "mcpToolName", "argumentsTemplate", "toolId",
        }
    elif source == "mcp":
        incompatible = integration_bindings | {
            "toolId", "url", "method", "headers", "bodyTemplate",
            "queryParams", "queryParamOverrides", "path",
        }
    elif source == "tool":
        incompatible = integration_bindings | mcp_bindings | {
            "url", "method", "headers", "bodyTemplate", "queryParams",
            "queryParamOverrides", "path",
        }
    elif source == "capability":
        incompatible = {
            "integrationId", "integrationSlug", "endpointId", "endpointName",
            "mcpConnectionId", "mcpToolName", "argumentsTemplate", "toolId",
        }
    elif source == "custom":
        incompatible = {
            "integrationId", "integrationSlug", "endpointId", "endpointName",
            "mcpConnectionId", "mcpToolName", "argumentsTemplate", "toolId",
        }
    else:
        incompatible = set()
    if set(api) & incompatible:
        _fail("api_source", node_id, "binding")
    if source == "capability":
        _text(api.get("capability"), "api_config", node_id, "capability", required=True, limit=128)
        from botelier.services.capabilities.registry import get_capability

        capability_spec = get_capability(api.get("capability"))
        if capability_spec is not None and capability_spec.service_backed:
            _fail("capability_unavailable", node_id, "capability")
    elif source in {"custom", "integration"}:
        method = api.get("method", "GET")
        if not isinstance(method, str) or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            _fail("api_config", node_id, "method")
        if source == "custom":
            url = api.get("url")
            _text(url, "api_config", node_id, "url", required=True, limit=4096)
            if not re.match(r"^https?://[^\s?#@]+(?:[/?#][^\s]*)?$", url, re.I) or "@" in url.split("://", 1)[1].split("/", 1)[0]:
                _fail("api_config", node_id, "url")
        else:
            if not (api.get("integrationId") or api.get("integrationSlug")):
                _fail("api_config", node_id, "integrationId")
            for key in ("integrationId", "integrationSlug", "endpointId"):
                if key in api:
                    _text(api[key], "api_config", node_id, key, required=True, limit=256)
            if not api.get("endpointId"):
                _text(api.get("path"), "api_config", node_id, "path", required=True, limit=4096)
    elif source in {"mcp", "tool"}:
        bindings = {
            "mcp": ("mcpConnectionId", "mcpToolName"),
            "tool": ("toolId",),
        }[source]
        for key in bindings:
            _text(api.get(key), "api_source", node_id, key, required=True, limit=256)
        if source == "mcp" and "toolId" in api or source == "tool" and (
            "mcpConnectionId" in api or "mcpToolName" in api
        ):
            _fail("api_source", node_id, "binding")
        template = _text(
            api.get("argumentsTemplate"), "api_template", node_id,
            "argumentsTemplate", required=True, limit=32_000,
        )
        residual = _TOKEN.sub("", template)
        if set(_TOKEN.findall(template)) - declared or "{{" in residual or "}}" in residual:
            _fail("api_template", node_id, "argumentsTemplate")
        try:
            parsed_arguments = render_json_template(
                template, {name: "" for name in declared},
            )
        except (RequestTemplateError, TypeError, ValueError, RecursionError):
            _fail("api_template", node_id, "argumentsTemplate")
        if not isinstance(parsed_arguments, dict):
            _fail("api_template", node_id, "argumentsTemplate")
    if api.get("url") is not None:
        _template(api["url"], declared, "api_template", node_id, "url")
    for key in ("bodyTemplate",):
        if key in api:
            body = _text(api[key], "api_template", node_id, key, limit=32_000)
            without_secrets = _SECRET_TOKEN.sub("", body)
            residual = _TOKEN.sub("", without_secrets)
            if (
                set(_TOKEN.findall(body)) - declared or "{{" in residual or "}}" in residual
                or source != "custom" and _SECRET_TOKEN.search(body)
            ):
                _fail("api_template", node_id, key)
            try:
                rendered = render_json_template(
                    body, {name: "" for name in declared},
                    secret_resolver=lambda _key: "",
                )
            except (RequestTemplateError, TypeError, ValueError, RecursionError):
                _fail("api_template", node_id, key)
    if "path" in api:
        _template(api["path"], declared, "api_template", node_id, "path", limit=4096)
    for key in ("thinkingMessage", "onSuccess", "onError", "onComplete", "onNotFound",
                "onAuthError", "responseInstructions"):
        if key in api:
            _template(api[key], declared, "api_template", node_id, key)
    timeout = api.get("timeout", 8)
    _integer(timeout, 1, 60, "api_limits", node_id, "timeout")
    _integer(api.get("retryCount", 0), 0, 3, "api_limits", node_id, "retryCount")
    if "retryDelay" in api:
        _integer(api["retryDelay"], 0, 30_000, "api_limits", node_id, "retryDelay")
    for name in ("headers", "queryParamOverrides"):
        value = api.get(name)
        if value is not None and (
            not isinstance(value, dict)
            or len(value) > 100
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items())
        ):
            _fail("api_config", node_id, name)
    headers = api.get("headers") or {}
    for key, value in headers.items():
        lower = key.casefold()
        secret = _SECRET_TOKEN.fullmatch(value)
        if (
            not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", key)
            or lower in {
                "host", "content-length", "transfer-encoding", "connection",
                "proxy-authorization", "proxy-connection", "cookie", "set-cookie",
            }
            or "\r" in value or "\n" in value
            or ("{{" in value and not secret)
            or lower in {"authorization", "x-api-key", "api-key"} and not secret
            or secret and source != "custom"
        ):
            _fail("api_config", node_id, "headers")
    for name in ("responseMapping", "autoMappingSource"):
        mapping = api.get(name)
        if mapping is not None:
            if not isinstance(mapping, dict) or len(mapping) > 128:
                _fail("api_mapping", node_id, name)
            for key, path in mapping.items():
                if not isinstance(key, str):
                    _fail("api_mapping", node_id, name)
                _identifier(key, _VARIABLE, "api_mapping", node_id, name)
                if key in _RESERVED_VARIABLES:
                    _fail("api_mapping", node_id, name)
                if name == "autoMappingSource" and key not in declared:
                    _fail("api_mapping", node_id, name)
                _json_path(path, "api_mapping", node_id, name)
    if "responseVariables" in api:
        mappings = api["responseVariables"]
        if not isinstance(mappings, list) or len(mappings) > 128:
            _fail("api_mapping", node_id, "responseVariables")
        seen_response_variables = set()
        for entry in mappings:
            if not isinstance(entry, dict) or set(entry) - {"variableKey", "jsonPath", "defaultValue"}:
                _fail("api_mapping", node_id, "responseVariables")
            if not isinstance(entry.get("variableKey"), str) or not isinstance(entry.get("jsonPath"), str):
                _fail("api_mapping", node_id, "responseVariables")
            key = _identifier(
                entry["variableKey"], _VARIABLE, "api_mapping", node_id,
                "responseVariables",
            )
            if key in _RESERVED_VARIABLES or key in seen_response_variables:
                _fail("api_mapping", node_id, "responseVariables")
            seen_response_variables.add(key)
            _json_path(entry["jsonPath"], "api_mapping", node_id, "responseVariables")
            if "defaultValue" in entry:
                _validate_mapped_default(
                    entry["defaultValue"], variables.get(key), node_id,
                )
    projection = api.get("responseProjection")
    mappings = dict(api.get("responseMapping") or {})
    for entry in api.get("responseVariables", []):
        mappings[entry["variableKey"]] = entry["jsonPath"]
    try:
        validate_mapped_projection(projection, mappings)
    except ResponseProjectionError:
        _fail("api_projection", node_id, "responseProjection")


def _validate_mapped_default(value, declaration, node_id):
    if value is None or declaration is None:
        return
    kind = declaration.get("type", "text")
    valid = {
        "text": lambda item: isinstance(item, str),
        "date": lambda item: isinstance(item, str),
        "phone": lambda item: isinstance(item, str),
        "email": lambda item: isinstance(item, str),
        "time": lambda item: isinstance(item, str),
        "choice": lambda item: isinstance(item, str) and item in declaration.get("choices", []),
        "number": lambda item: type(item) in (int, float),
    }.get(kind)
    if valid is None or not valid(value):
        _fail("api_mapping", node_id, "responseVariables.defaultValue")


def _compiled_variable_declarations(declarations, nodes):
    outputs = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in {"api_request", "capability"}:
            continue
        data = node.get("data")
        api = data.get("api") if isinstance(data, dict) else None
        if not isinstance(api, dict):
            continue
        for key in (api.get("responseMapping") or {}):
            outputs[key] = {"key": key, "type": None, "required": False}
        for entry in api.get("responseVariables") or []:
            if not isinstance(entry, dict):
                continue
            declaration = {
                "key": entry.get("variableKey"),
                "type": None,
                "required": False,
            }
            if "defaultValue" in entry:
                declaration["defaultValue"] = entry["defaultValue"]
            outputs[entry.get("variableKey")] = declaration
    result = []
    for key, declaration in declarations.items():
        result.append(CompiledVariableDeclaration(
            key=key, origin="explicit",
            _data_json=json.dumps(
                declaration, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ),
        ))
    for key, declaration in outputs.items():
        if key in declarations:
            continue
        result.append(CompiledVariableDeclaration(
            key=key, origin="output",
            _data_json=json.dumps(
                declaration, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ),
        ))
    return tuple(result)


def _validate_record_update_bindings(nodes, by_id, edges):
    adjacency = {}
    for edge in edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "save_record":
            continue
        data = node.get("data") or {}
        setting = data.get("saveRecord", data.get("save_record")) or {}
        source_id = setting.get("updateSourceNodeId")
        if source_id is None:
            continue
        source = by_id.get(source_id)
        source_data = source.get("data") if isinstance(source, dict) else None
        source_setting = (
            source_data.get("saveRecord", source_data.get("save_record"))
            if isinstance(source_data, dict) else None
        )
        if (
            source is None or source.get("type") != "save_record"
            or not isinstance(source_setting, dict)
            or source_setting.get("updateSourceNodeId") is not None
            or source_setting.get("recordTypeId") != setting.get("recordTypeId")
            or source_id == node.get("id")
        ):
            _fail("save_record_update_binding", node.get("id"), "updateSourceNodeId")
        visited = set()
        pending = [source_id]
        while pending:
            current = pending.pop()
            if current == node["id"]:
                break
            if current in visited:
                continue
            visited.add(current)
            pending.extend(adjacency.get(current, ()))
        else:
            _fail("save_record_update_unreachable", node.get("id"), "updateSourceNodeId")


def _candidate_output_names(nodes):
    names = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if not isinstance(node_type, str) or node_type not in {
            "api_request", "capability",
        }:
            continue
        data = node.get("data")
        api = data.get("api") if isinstance(data, dict) else None
        if not isinstance(api, dict):
            continue
        mapping = api.get("responseMapping")
        if isinstance(mapping, dict):
            names.update(key for key in mapping if isinstance(key, str))
        response_variables = api.get("responseVariables")
        if isinstance(response_variables, list):
            names.update(
                item.get("variableKey") for item in response_variables
                if isinstance(item, dict)
                and isinstance(item.get("variableKey"), str)
            )
    return names


def _validate_node(
    node: dict, variables: dict[str, dict], declared: set[str],
) -> tuple[CallerSlot, ...]:
    node_id, kind = node["id"], node["type"]
    data = node.get("data")
    if not isinstance(data, dict):
        _fail("node_data", node_id)
    _keys(data, frozenset(_COMMON_DATA | _NODE_FIELDS[kind]), "unknown_field", node_id)
    for name in ("name", "description"):
        if name in data:
            _text(data[name], "node_data", node_id, name)
    if "instructions" in data:
        _template(data["instructions"], declared, "node_data", node_id, "instructions")
    for field_name in ("systemPrompt", "greeting", "message", "introMessage", "closingMessage"):
        if field_name in data:
            _template(data[field_name], declared, "node_template", node_id, field_name)
    slots: list[CallerSlot] = []
    if kind == "initial":
        if "waitForResponse" in data:
            _boolean(data["waitForResponse"], "node_data", node_id, "waitForResponse")
    elif kind == "message":
        if "waitForResponse" in data:
            _boolean(data["waitForResponse"], "node_data", node_id, "waitForResponse")
        if not isinstance(data.get("deliveryMode", "guided"), str) or data.get("deliveryMode", "guided") not in {"guided", "static"}:
            _fail("node_data", node_id, "deliveryMode")
    elif kind == "collect_slot":
        slots.append(_validate_slot(data.get("slot"), node_id, variables))
    elif kind == "collect_form":
        form_slots = data.get("slots")
        if not isinstance(form_slots, list) or not form_slots or len(form_slots) > 32:
            _fail("form_slots", node_id, "slots")
        slot_ids, orders, keys = set(), [], set()
        for slot in form_slots:
            if not isinstance(slot, dict):
                _fail("form_slots", node_id, "slots")
            slot_id = _identifier(slot.get("id"), _NODE_ID, "form_slots", node_id, "id")
            order = slot.get("order")
            _integer(order, 0, len(form_slots) - 1, "form_slots", node_id, "order")
            declaration = _validate_slot(slot, node_id, variables, form=True)
            if slot_id in slot_ids or order in orders or declaration.variable in keys:
                _fail("form_order", node_id, "slots")
            slot_ids.add(slot_id)
            orders.append(order)
            keys.add(declaration.variable)
            slots.append(declaration)
        if sorted(orders) != list(range(len(form_slots))):
            _fail("form_order", node_id, "slots")
    elif kind in {"api_request", "capability"}:
        _validate_api(
            data.get("api"), node_id, variables,
            available_variables=declared, capability=(kind == "capability"),
        )
    elif kind == "api_response":
        presentation = data.get("responsePresentation")
        if not isinstance(presentation, dict):
            _fail("api_presentation", node_id, "responsePresentation")
        allowed = frozenset({"arrayVariable", "introText", "itemTemplate", "outroText", "noResultsText"})
        _keys(presentation, allowed, "unknown_field", node_id)
        array_variable = presentation.get("arrayVariable", "")
        if not isinstance(array_variable, str) or (array_variable and array_variable not in declared):
            _fail("api_presentation", node_id, "arrayVariable")
        if array_variable and array_variable in variables and (
            variables[array_variable].get("type", "text") != "array"
        ):
            _fail("api_presentation", node_id, "arrayVariable")
        for key in ("introText", "outroText", "noResultsText"):
            if key in presentation:
                _template(presentation[key], declared, "api_presentation", node_id, key)
        if "itemTemplate" in presentation:
            item_template = _text(
                presentation["itemTemplate"], "api_presentation", node_id, "itemTemplate",
            )
            _template(
                item_template, set(_TOKEN.findall(item_template)), "api_presentation",
                node_id, "itemTemplate", local_tokens=frozenset({"item", "index"}),
            )
    elif kind == "condition":
        condition = data.get("condition")
        if not isinstance(condition, dict):
            _fail("condition", node_id, "condition")
        _keys(condition, frozenset({"variable", "operator", "value", "trueTarget", "falseTarget"}),
              "unknown_field", node_id)
        if not isinstance(condition.get("variable"), str) or condition.get("variable") not in declared or not isinstance(condition.get("operator"), str) or condition.get("operator") not in {
            "equals", "not_equals", "contains", "greater_than", "less_than", "is_empty", "is_not_empty",
        }:
            _fail("condition", node_id, "variable")
        _template(condition.get("value", ""), declared, "condition", node_id, "value")
        for key in ("trueTarget", "falseTarget"):
            if key in condition:
                _identifier(condition[key], _NODE_ID, "condition", node_id, key)
    elif kind == "router":
        router = data.get("router")
        if not isinstance(router, dict):
            _fail("router", node_id, "router")
        _keys(router, frozenset({"variable", "options"}), "unknown_field", node_id)
        options = router.get("options")
        if not isinstance(router.get("variable"), str) or router.get("variable") not in declared or not isinstance(options, list) or not options or len(options) > 64:
            _fail("router", node_id, "options")
        option_ids = set()
        for option in options:
            if not isinstance(option, dict) or set(option) != {"id", "value", "label"}:
                _fail("router", node_id, "options")
            option_id = _identifier(option["id"], _NODE_ID, "router", node_id, "options")
            if option_id in option_ids:
                _fail("router", node_id, "options")
            option_ids.add(option_id)
            for field_name in ("value", "label"):
                _text(option[field_name], "router", node_id, field_name, required=True)
    elif kind == "confirmation":
        confirmation = data.get("confirmation")
        if not isinstance(confirmation, dict):
            _fail("confirmation", node_id, "confirmation")
        _keys(confirmation, frozenset({
            "summaryTemplate", "confirmPrompt", "editPrompt", "variablesToConfirm",
            "allowEdit", "deliveryMode",
        }), "unknown_field", node_id)
        for key in ("summaryTemplate", "confirmPrompt"):
            _template(confirmation.get(key), declared, "confirmation", node_id, key, required=True)
        if "editPrompt" in confirmation:
            _template(confirmation["editPrompt"], declared, "confirmation", node_id, "editPrompt")
        selected = confirmation.get("variablesToConfirm")
        if not isinstance(selected, list) or not selected or any(not isinstance(key, str) for key in selected) or len(set(selected)) != len(selected):
            _fail("confirmation", node_id, "variablesToConfirm")
        if any(key not in declared for key in selected):
            _fail("confirmation", node_id, "variablesToConfirm")
        allow_edit = confirmation.get("allowEdit", False)
        _boolean(allow_edit, "confirmation", node_id, "allowEdit")
        if allow_edit and not confirmation.get("editPrompt"):
            _fail("confirmation", node_id, "editPrompt")
        if not isinstance(confirmation.get("deliveryMode", "guided"), str) or confirmation.get("deliveryMode", "guided") not in {"guided", "static"}:
            _fail("confirmation", node_id, "deliveryMode")
    elif kind == "set_variable":
        setting = data.get("setVariable", data.get("set_variable"))
        if not isinstance(setting, dict):
            _fail("set_variable", node_id, "setVariable")
        _keys(setting, frozenset({"variableKey", "valueType", "value"}), "unknown_field", node_id)
        key = setting.get("variableKey")
        if not isinstance(key, str) or key not in declared or not isinstance(setting.get("valueType"), str) or setting.get("valueType") not in {"static", "template", "expression"}:
            _fail("set_variable", node_id, "variableKey")
        if key not in variables:
            _fail("set_variable", node_id, "variableKey")
        value = _text(setting.get("value"), "set_variable", node_id, "value", limit=8000)
        if setting["valueType"] == "template":
            _template(value, declared, "set_variable", node_id, "value")
        if setting["valueType"] == "expression":
            references = _safe_expression_names(value)
            if references is None or references - declared:
                _fail("set_variable_expression", node_id, "value")
    elif kind == "save_record":
        record = data.get("saveRecord", data.get("save_record"))
        if not isinstance(record, dict):
            _fail("save_record", node_id, "saveRecord")
        _keys(record, frozenset({
            "recordTypeId", "recordTypeName", "mapping", "status",
            "updateSourceNodeId",
        }),
              "unknown_field", node_id)
        _text(record.get("recordTypeId"), "save_record", node_id, "recordTypeId", required=True, limit=128)
        if "updateSourceNodeId" in record:
            _identifier(
                record.get("updateSourceNodeId"), _NODE_ID,
                "save_record", node_id, "updateSourceNodeId",
            )
        mapping = record.get("mapping")
        if not isinstance(mapping, dict) or not mapping or len(mapping) > 128:
            _fail("save_record", node_id, "mapping")
        for key, value in mapping.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key):
                _fail("save_record", node_id, "mapping")
            _template(value, declared, "save_record", node_id, "mapping")
        if "status" in record:
            _template(record["status"], declared, "save_record", node_id, "status")
    elif kind == "transfer":
        transfer = data.get("transfer")
        if not isinstance(transfer, dict):
            _fail("transfer", node_id, "transfer")
        _keys(transfer, frozenset({"phoneNumber", "preTransferMessage", "warmTransfer", "transferMode"}),
              "unknown_field", node_id)
        _text(transfer.get("phoneNumber"), "transfer", node_id, "phoneNumber", required=True, limit=64)
        if "preTransferMessage" in transfer:
            _template(transfer["preTransferMessage"], declared, "transfer", node_id, "preTransferMessage")
        if "warmTransfer" in transfer:
            _boolean(transfer["warmTransfer"], "transfer", node_id, "warmTransfer")
        if transfer.get("transferMode") is not None and (
            not isinstance(transfer.get("transferMode"), str)
            or transfer["transferMode"] not in {"warm", "cold"}
        ):
            _fail("transfer", node_id, "transferMode")
    elif kind == "option_picker":
        picker = data.get("optionPicker", data.get("option_picker"))
        if not isinstance(picker, dict):
            _fail("option_picker", node_id, "optionPicker")
        _keys(picker, frozenset({"sourceVariable", "labelPath", "prompt", "retryPrompt",
                                 "maxRetries", "writes"}), "unknown_field", node_id)
        if not isinstance(picker.get("sourceVariable"), str) or picker.get("sourceVariable") not in declared:
            _fail("option_picker", node_id, "sourceVariable")
        if picker["sourceVariable"] in variables and (
            variables[picker["sourceVariable"]].get("type", "text") != "array"
        ):
            _fail("option_picker", node_id, "sourceVariable")
        _json_path(picker.get("labelPath"), "option_picker", node_id, "labelPath")
        if not picker.get("labelPath"):
            _fail("option_picker", node_id, "labelPath")
        _template(picker.get("prompt"), declared, "option_picker", node_id, "prompt", required=True)
        if "retryPrompt" in picker:
            _template(picker["retryPrompt"], declared, "option_picker", node_id, "retryPrompt")
        _integer(picker.get("maxRetries", 3), 0, 20, "option_picker", node_id, "maxRetries")
        writes = picker.get("writes")
        if not isinstance(writes, list) or not writes or len(writes) > 64:
            _fail("option_picker", node_id, "writes")
        destinations = set()
        for write in writes:
            if not isinstance(write, dict) or set(write) != {"variableKey", "path"}:
                _fail("option_picker", node_id, "writes")
            key = write.get("variableKey")
            if (
                not isinstance(key, str) or key not in variables
                or key in destinations
            ):
                _fail("option_picker", node_id, "writes")
            destinations.add(key)
            _json_path(write.get("path"), "option_picker", node_id, "writes",
                       allow_empty=True)
    return tuple(slots)


def _validate_edges(edges: list[dict], by_id: dict[str, dict]):
    compiled: list[CompiledEdge] = []
    outgoing: dict[str, list[CompiledEdge]] = defaultdict(list)
    seen_handles: set[tuple[str, str]] = set()
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            _fail("edge")
        _keys(edge, _EDGE_UI_FIELDS, "edge_field")
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in by_id or target not in by_id:
            _fail("edge_target")
        handle = edge.get("sourceHandle")
        target_handle = edge.get("targetHandle")
        if handle is not None and not isinstance(handle, str):
            _fail("edge_handle")
        if target_handle is not None and not isinstance(target_handle, str):
            _fail("edge_handle")
        handle = handle or None
        target_handle = target_handle or None
        if handle is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", handle):
            _fail("edge_handle")
        if edge.get("id") is not None:
            edge_id = _identifier(edge["id"], _NODE_ID, "edge_id")
            if edge_id in edge_ids:
                _fail("edge_id")
            edge_ids.add(edge_id)
        else:
            edge_id = f"{source}-{handle or 'default'}-{target}"
        identity = (source, handle or "")
        if identity in seen_handles:
            _fail("duplicate_handle", source)
        seen_handles.add(identity)
        compiled_edge = CompiledEdge(edge_id, source, target, handle, target_handle)
        compiled.append(compiled_edge)
        outgoing[source].append(compiled_edge)
    return tuple(compiled), outgoing


def _validate_topology(nodes: list[dict], by_id: dict[str, dict],
                       edges: tuple[CompiledEdge, ...], outgoing: dict[str, list[CompiledEdge]],
                       initial_id: str):
    if initial_id not in by_id or by_id[initial_id]["type"] != "initial":
        _fail("initial_node")
    for node_id, node in by_id.items():
        kind = node["type"]
        exits = outgoing.get(node_id, [])
        handles = {edge.source_handle for edge in exits}
        if kind in {"end", "transfer"} and exits:
            _fail("terminal_edge", node_id)
        if kind == "condition":
            if handles != {"true", "false"}:
                _fail("condition_handles", node_id)
            setting = node["data"]["condition"]
            for handle in ("true", "false"):
                configured = setting.get(handle + "Target")
                wired = next(edge.target for edge in exits if edge.source_handle == handle)
                if configured is not None and configured != wired:
                    _fail("condition_target", node_id, handle + "Target")
        elif kind == "router":
            expected = {option["id"] for option in node["data"]["router"]["options"]}
            if not expected.issubset(handles) or handles - expected - {"fallback"}:
                _fail("router_handles", node_id)
        elif kind == "api_response":
            if handles != {"has_results", "no_results"}:
                _fail("response_handles", node_id)
        elif kind == "confirmation":
            setting = node["data"]["confirmation"]
            default_only = len(exits) == 1 and not exits[0].source_handle
            if ("confirmed" not in handles and not default_only) or handles - {"confirmed", "edit", None}:
                _fail("confirmation_handles", node_id)
            if "edit" in handles and not setting.get("allowEdit", False):
                _fail("confirmation_handles", node_id)
        elif kind == "option_picker":
            default_only = len(exits) == 1 and not exits[0].source_handle
            if ("selected" not in handles and not default_only) or handles - {"selected", "fallback", None}:
                _fail("option_picker_handles", node_id)
        elif kind in {"api_request", "capability"}:
            if handles - {"success", "error", "not_found", "auth_error", None}:
                _fail("api_handles", node_id)
        elif kind not in {"end", "transfer"} and handles - {None}:
            _fail("node_handles", node_id)

    # All nodes (including terminal end nodes) must be connected to the selected start.
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge.source].append(edge.target)
    reached, queue = {initial_id}, deque([initial_id])
    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target not in reached:
                reached.add(target)
                queue.append(target)
    if reached != set(by_id):
        _fail("unreachable_node", sorted(set(by_id) - reached)[0])

    # Caller-input steps are explicit revisit boundaries. Removing their outgoing
    # transitions detects only cycles that can spin without new caller input.
    automatic_graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = by_id[edge.source]
        if _caller_wait_boundary(source):
            continue
        automatic_graph[edge.source].append(edge.target)
    state: dict[str, int] = {}

    def visit(node_id: str):
        status = state.get(node_id, 0)
        if status == 1:
            _fail("automatic_cycle", node_id)
        if status == 2:
            return
        state[node_id] = 1
        for target in automatic_graph[node_id]:
            visit(target)
        state[node_id] = 2

    for node_id in by_id:
        visit(node_id)


def _caller_wait_boundary(node: dict) -> bool:
    kind, data = node["type"], node["data"]
    if kind in {"collect_slot", "collect_form", "confirmation", "option_picker"}:
        return True
    return kind in {"initial", "message"} and data.get("waitForResponse", True) is True


def compile_flow(config: dict, identity: PilotIdentity) -> CompiledFlow:
    """Validate and freeze an editor graph without opening external resources."""
    if not isinstance(identity, PilotIdentity):
        _fail("identity")
    if not isinstance(config, dict):
        _fail("definition")
    config_json, config_bytes = _json_snapshot(config)
    snapshot = json.loads(config_json)
    _keys(snapshot, frozenset({
        "nodes", "edges", "variables", "initial_node", "initialNode",
        "globalPrompt", "global_prompt", "version", "schemaVersion",
    }), "definition_field")
    nodes, edges = snapshot.get("nodes"), snapshot.get("edges")
    if not isinstance(nodes, list) or not nodes or len(nodes) > MAX_NODES:
        _fail("graph_size")
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        _fail("graph_size")
    if "globalPrompt" in snapshot and "global_prompt" in snapshot:
        _fail("definition_field")
    declarations, declared = _validate_variable_declarations(snapshot)
    available_variables = declared | _candidate_output_names(nodes)
    for prompt_key in ("globalPrompt", "global_prompt"):
        if prompt_key in snapshot:
            _template(snapshot[prompt_key], declared, "definition", "flow", prompt_key)
    by_id: dict[str, dict] = {}
    starts = []
    caller_slots = []
    compiled_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            _fail("node")
        _keys(node, _NODE_UI_FIELDS, "node_field")
        node_id = _identifier(node.get("id"), _NODE_ID, "node_id")
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in _NODE_TYPES:
            _fail("node_type", node_id)
        if node_id in by_id:
            _fail("duplicate_node", node_id)
        by_id[node_id] = node
        if kind == "initial":
            starts.append(node_id)
        data_bytes = len(json.dumps(node.get("data"), ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")) if "data" in node else 0
        if data_bytes > MAX_NODE_BYTES:
            _fail("node_size", node_id)
        caller_slots.extend(_validate_node(node, declarations, available_variables))
        compiled_nodes.append(CompiledNode(
            node_id, kind,
            json.dumps(node["data"], ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        ))
    if len(starts) != 1:
        _fail("initial_count")
    initial_id = snapshot.get("initial_node", snapshot.get("initialNode"))
    if initial_id != starts[0]:
        _fail("initial_node")
    compiled_edges, outgoing = _validate_edges(edges, by_id)
    _validate_topology(nodes, by_id, compiled_edges, outgoing, initial_id)
    _validate_record_update_bindings(nodes, by_id, compiled_edges)
    total_io = config_bytes + sum(
        len(node._data_json.encode("utf-8")) for node in compiled_nodes
    )
    if total_io > MAX_TOTAL_IO_BYTES:
        _fail("total_io_size")
    return CompiledFlow(
        identity=identity,
        initial_node_id=initial_id,
        nodes=tuple(compiled_nodes),
        edges=compiled_edges,
        caller_slots=tuple(caller_slots),
        variable_declarations=_compiled_variable_declarations(
            declarations, nodes,
        ),
        max_nodes=MAX_NODES,
        max_edges=MAX_EDGES,
        max_revisits=MAX_REVISITS,
        max_config_bytes=MAX_DEFINITION_BYTES,
        max_total_io_bytes=MAX_TOTAL_IO_BYTES,
        _config_json=config_json,
    )


__all__ = [
    "CallerSlot", "CompiledEdge", "CompiledFlow", "CompiledNode",
    "CompiledVariableDeclaration",
    "MAX_DEFINITION_BYTES", "MAX_EDGES", "MAX_NODES", "MAX_REVISITS",
    "MAX_TOTAL_IO_BYTES", "NativeGraphError", "compile_flow",
]

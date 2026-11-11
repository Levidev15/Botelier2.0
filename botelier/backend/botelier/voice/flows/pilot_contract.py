"""Fail-closed, immutable admission for the inactive single-flow pilot.

This is deliberately not a general graph executor. Only the reviewed six-node
read-only shape is admitted, and no production call site imports this module.
"""

from collections import Counter
from dataclasses import dataclass
import json
import re
from uuid import UUID


_NODE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_VARIABLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_RESERVED = {
    "status", "current_node_id", "flow_version_id", "account_id", "property_id",
    "call_sid", "tool_id", "outcome", "success",
}


class PilotAdmissionError(ValueError):
    """A configuration is outside the explicitly supported pilot contract."""


def _require(condition, code):
    if not condition:
        # Codes identify the designer's unsupported setting without echoing PII,
        # private prompts, request bodies, credentials or provider payloads.
        raise PilotAdmissionError(code)


def _text(value, code, *, required=False):
    _require(isinstance(value, str) and len(value) <= 8000, code)
    _require(not required or bool(value.strip()), code)
    return value.strip()


def _template(value, code):
    value = _text(value, code)
    _require("{" not in _TOKEN.sub("", value) and "}" not in _TOKEN.sub("", value), code)
    return value


@dataclass(frozen=True)
class PilotIdentity:
    account_id: str
    property_id: str
    tool_id: str
    flow_version_id: str
    call_sid: str

    def __post_init__(self):
        for value in vars(self).values():
            _require(isinstance(value, str) and bool(value.strip()), "identity")


@dataclass(frozen=True)
class CollectionSpec:
    node_id: str
    variable: str
    prompt: str
    instructions: str

    @property
    def function_name(self):
        return f"collect_{self.node_id}"


@dataclass(frozen=True)
class CompiledPilot:
    identity: PilotIdentity
    query: CollectionSpec
    choice: CollectionSpec
    failure: CollectionSpec
    api_node_id: str
    response_node_id: str
    response_mappings: tuple[tuple[str, str], ...]
    _api_json: str
    _presentation_json: str

    @property
    def native_names(self):
        return frozenset(
            slot.function_name for slot in (self.query, self.choice, self.failure)
        )

    def api_config(self):
        return json.loads(self._api_json)

    def presentation(self):
        return json.loads(self._presentation_json)


def _collection(node, variables):
    data = node["data"]
    _require(set(data) <= {"name", "description", "slot", "instructions"}, "slot")
    slot = data.get("slot")
    _require(isinstance(slot, dict), "slot")
    _require(
        set(slot) <= {"variableKey", "prompt", "required", "validation", "type"}
        and slot.get("required", True) is True
        and not slot.get("validation")
        and slot.get("type", "text") == "text",
        "slot",
    )
    key = slot.get("variableKey")
    _require(isinstance(key, str) and _VARIABLE.fullmatch(key) and key not in _RESERVED, "variables")
    _require(key in variables and variables[key].get("type") == "text", "variables")
    _require(variables[key].get("defaultValue") in (None, ""), "variables")
    prompt = _text(slot.get("prompt"), "slot", required=True)
    _require("{" not in prompt and "}" not in prompt, "slot")
    return CollectionSpec(
        node["id"], key, prompt, _text(data.get("instructions", ""), "slot"),
    )


def _mappings(api, caller_keys):
    explicit = api.get("responseVariables", [])
    mapping = api.get("responseMapping", {})
    _require(isinstance(explicit, list) and isinstance(mapping, dict), "mapping")
    pairs = {}
    for entry in explicit:
        _require(isinstance(entry, dict), "mapping")
        _require(
            set(entry) <= {"variableKey", "jsonPath", "defaultValue"}
            and entry.get("defaultValue") is None,
            "mapping",
        )
        key = entry.get("variableKey")
        _require(isinstance(key, str) and key not in pairs, "mapping")
        pairs[key] = entry.get("jsonPath")
    for key, path in mapping.items():
        pairs.setdefault(key, path)
    for key, path in pairs.items():
        _require(
            isinstance(key, str) and _VARIABLE.fullmatch(key)
            and key not in caller_keys and key not in _RESERVED,
            "mapping",
        )
        _require(isinstance(path, str) and 0 < len(path) <= 256, "mapping")
        normalized = path.removeprefix("$").removeprefix(".").replace("[", ".[")
        parts = normalized.split(".")
        _require(
            all(re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_-]*|\d+|\[(?:\d+|\*)\])", p)
                for p in parts),
            "mapping",
        )
    return tuple(pairs.items())


def compile_pilot(config: dict, identity: PilotIdentity) -> CompiledPilot:
    """Copy and admit exactly the reviewed connected-GET conversation shape."""
    _require(isinstance(identity, PilotIdentity), "identity")
    _require(isinstance(config, dict), "definition")
    try:
        encoded = json.dumps(config, allow_nan=False)
        _require(len(encoded) <= 100_000, "definition_size")
        config = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, PilotAdmissionError):
            raise
        raise PilotAdmissionError("definition_json") from None
    nodes, edges = config.get("nodes"), config.get("edges")
    _require(isinstance(nodes, list) and isinstance(edges, list), "definition")
    _require(all(isinstance(n, dict) for n in nodes), "node_ids")
    ids = [node.get("id") for node in nodes]
    _require(
        all(isinstance(key, str) and _NODE_ID.fullmatch(key) for key in ids)
        and len(ids) == len(set(ids)),
        "node_ids",
    )
    _require(
        all(isinstance(node.get("type"), str) for node in nodes)
        and Counter(node.get("type") for node in nodes) == {
            "initial": 1, "collect_slot": 3, "api_request": 1, "api_response": 1,
        },
        "node_types",
    )
    by_id = {node["id"]: node for node in nodes}
    _require(all(isinstance(node.get("data"), dict) for node in nodes), "node_data")
    outgoing = {}
    for edge in edges:
        _require(isinstance(edge, dict), "edges")
        source, target = edge.get("source"), edge.get("target")
        handle = edge.get("sourceHandle") or ""
        _require(
            isinstance(source, str) and isinstance(target, str) and isinstance(handle, str)
            and source in by_id and target in by_id,
            "edges",
        )
        _require((source, handle) not in outgoing, "edges")
        outgoing[(source, handle)] = target
    _require(len(edges) == 6, "topology")
    initial = next(n for n in nodes if n["type"] == "initial")
    api_node = next(n for n in nodes if n["type"] == "api_request")
    response = next(n for n in nodes if n["type"] == "api_response")
    _require(config.get("initial_node") == initial["id"], "topology")
    initial_data = initial["data"]
    _require(
        set(initial_data) <= {"name", "description", "greeting", "waitForResponse"}
        and not initial_data.get("greeting") and initial_data.get("waitForResponse") is False,
        "initial",
    )
    query_id = outgoing.get((initial["id"], ""))
    choice_id = outgoing.get((response["id"], "has_results"))
    failure_id = outgoing.get((api_node["id"], "error"))
    _require(
        all(key in by_id and by_id[key]["type"] == "collect_slot"
            for key in (query_id, choice_id, failure_id))
        and len({query_id, choice_id, failure_id}) == 3,
        "topology",
    )
    _require(outgoing == {
        (initial["id"], ""): query_id,
        (query_id, ""): api_node["id"],
        (api_node["id"], "success"): response["id"],
        (api_node["id"], "error"): failure_id,
        (response["id"], "has_results"): choice_id,
        (response["id"], "no_results"): failure_id,
    }, "topology")
    declarations = config.get("variables")
    _require(isinstance(declarations, list), "variables")
    variables = {}
    for declaration in declarations:
        _require(isinstance(declaration, dict), "variables")
        key = declaration.get("key")
        _require(isinstance(key, str) and key not in variables, "variables")
        variables[key] = declaration
    query, choice, failure = (
        _collection(by_id[key], variables) for key in (query_id, choice_id, failure_id)
    )
    _require(query.variable != choice.variable and query.variable != failure.variable, "variables")
    for node in (api_node, response):
        _require(not _text(node["data"].get("instructions", ""), "automatic_instructions"),
                 "automatic_instructions")
    _require(
        set(api_node["data"]) <= {"name", "description", "api", "instructions"},
        "api_fields",
    )
    api = api_node["data"].get("api")
    _require(isinstance(api, dict), "connected_get")
    _require(api.get("apiSource") == "integration" and api.get("method") == "GET", "connected_get")
    try:
        UUID(api.get("integrationId", ""))
    except (ValueError, TypeError, AttributeError):
        raise PilotAdmissionError("connected_get") from None
    _require(set(api) <= {
        "apiSource", "integrationId", "method", "path", "thinkingMessage", "onError",
        "onComplete", "onSuccess", "responseInstructions", "responseVariables",
        "responseMapping", "timeout", "retryCount",
    }, "api_fields")
    _require(not any(api.get(key) for key in (
        "onComplete", "onSuccess", "responseInstructions",
    )), "speech")
    path = _template(api.get("path"), "request_template")
    _require(
        path.startswith("/") and not path.startswith("//")
        and not any(char in path for char in ("\\", "#", "\r", "\n", "\x00"))
        and "://" not in path
        and set(_TOKEN.findall(path)) <= {query.variable},
        "request_template",
    )
    _require(
        type(api.get("timeout", 30)) is int and 1 <= api.get("timeout", 30) <= 30
        and type(api.get("retryCount", 2)) is int and 0 <= api.get("retryCount", 2) <= 2,
        "request_limits",
    )
    for key in ("thinkingMessage", "onError"):
        value = _text(api.get(key, ""), "speech", required=True)
        _require("{" not in value and "}" not in value, "speech")
    mappings = _mappings(api, {query.variable, choice.variable, failure.variable})
    _require(
        set(response["data"]) <= {"name", "description", "responsePresentation", "instructions"},
        "presentation",
    )
    presentation = response["data"].get("responsePresentation")
    _require(isinstance(presentation, dict) and set(presentation) <= {
        "arrayVariable", "introText", "itemTemplate", "outroText", "noResultsText",
    }, "presentation")
    _require(
        isinstance(presentation.get("arrayVariable"), str)
        and presentation["arrayVariable"] in dict(mappings),
        "mapping",
    )
    for key in ("introText", "outroText", "noResultsText", "itemTemplate"):
        _template(presentation.get(key, ""), "presentation")
    _text(presentation.get("itemTemplate"), "presentation", required=True)
    _text(presentation.get("noResultsText"), "presentation", required=True)
    _require(
        not presentation.get("outroText", "").strip()
        or " ".join(presentation["outroText"].split()).casefold()
        == " ".join(choice.prompt.split()).casefold(),
        "speech",
    )
    return CompiledPilot(
        identity, query, choice, failure, api_node["id"], response["id"], mappings,
        json.dumps(api, allow_nan=False), json.dumps(presentation, allow_nan=False),
    )

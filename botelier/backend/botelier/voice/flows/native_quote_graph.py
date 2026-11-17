"""Frozen quote-link bindings and private-data checks, without I/O or orchestration."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from botelier.voice.flows.native_quote_actions import (
    NativeQuoteError, validate_quote_configuration,
)
from botelier.services.request_templates import (
    RequestTemplateError, render_json_template,
)
from botelier.voice.flows.native_response_mapping import resolve_response_variables


_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_MARKER = "__BOTELIER_QUOTE_REFERENCE_"
_SPEECH_API_FIELDS = (
    "thinkingMessage", "onSuccess", "onError", "onComplete", "onNotFound",
    "onAuthError", "responseInstructions",
)


def _strings(value):
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            yield current
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)


def _quote_nodes(nodes):
    result = {}
    for node in nodes:
        api = node["data"].get("api", {})
        if (
            node["type"] in {"api_request", "capability"}
            and api.get("apiSource", "capability" if node["type"] == "capability" else "custom")
            == "capability"
            and api.get("capability") == "validate_reservation_quote"
        ):
            result[node["id"]] = (api, validate_quote_configuration(api))
    return result


def _input_references(api):
    """Distinguish a whole unvalidated quote from its private URL input."""
    template = api.get("argumentsTemplate")
    if not isinstance(template, str):
        return {"quote"}, set()
    names = set(_TOKEN.findall(template))
    markers = {name: _MARKER + name + "__" for name in names}
    try:
        arguments = render_json_template(template, markers)
    except (RequestTemplateError, TypeError, ValueError, RecursionError):
        raise NativeQuoteError("quote_arguments") from None
    quote = arguments.get("quote") if isinstance(arguments, dict) else None
    raw = {name for name, marker in markers.items() if quote == marker}
    url = quote.get("checkout_url") if isinstance(quote, dict) else None
    private = {
        name for name, marker in markers.items()
        if isinstance(url, str) and marker in url
    }
    return raw, private


def _sensitive_names(nodes, quotes):
    sensitive, private_values, fingerprints = set(), set(), set()
    for api, policy in quotes.values():
        raw, incoming_url = _input_references(api)
        fingerprints.add(policy.fingerprint_variable)
        private_values.update((policy.private_url_variable, *raw, *incoming_url))
    sensitive.update(private_values | fingerprints)
    # A template alias must not let a private value evade a spoken-field check.
    changed = True
    while changed:
        changed = False
        for node in nodes:
            setting = node["data"].get("setVariable", node["data"].get("set_variable", {}))
            if not isinstance(setting, dict) or setting.get("valueType") != "template":
                continue
            key, value = setting.get("variableKey"), setting.get("value")
            if (
                isinstance(value, str) and set(_TOKEN.findall(value)) & sensitive
                and key not in sensitive
            ):
                sensitive.add(key)
                private_values.add(key)
                changed = True
    return sensitive, private_values, fingerprints


def _speech_fields(node):
    data, kind = node["data"], node["type"]
    yield data.get("instructions")
    if kind == "initial":
        yield data.get("greeting")
        yield data.get("systemPrompt")
    elif kind == "message":
        yield data.get("message")
    elif kind == "collect_slot":
        for key in ("prompt", "retryPrompt", "instructions"):
            yield (data.get("slot") or {}).get(key)
    elif kind == "collect_form":
        yield data.get("introMessage")
        for slot in data.get("slots", []):
            for key in ("prompt", "retryPrompt", "instructions"):
                yield slot.get(key)
    elif kind in {"api_request", "capability"}:
        for key in _SPEECH_API_FIELDS:
            yield (data.get("api") or {}).get(key)
    elif kind == "api_response":
        yield data.get("responsePresentation")
    elif kind == "confirmation":
        confirmation = data["confirmation"]
        for key in ("summaryTemplate", "confirmPrompt", "editPrompt"):
            yield confirmation.get(key)
    elif kind == "option_picker":
        picker = data.get("optionPicker", data.get("option_picker", {}))
        for key in ("prompt", "retryPrompt"):
            yield picker.get(key)
    elif kind == "transfer":
        yield (data.get("transfer") or {}).get("preTransferMessage")
    elif kind == "end":
        yield data.get("closingMessage")


def _origin(value):
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() != "https" or not parts.hostname:
            return None
        return "https://" + parts.hostname.lower() + (
            ":" + str(parts.port) if parts.port not in {None, 443} else ""
        )
    except (ValueError, TypeError):
        return None


def _reachable_without(start, target, outgoing, excluded):
    pending, visited = [start], set()
    while pending:
        current = pending.pop()
        if current in excluded or current in visited:
            continue
        if current == target:
            return True
        visited.add(current)
        pending.extend(outgoing.get(current, ()))
    return False


def validate_quote_graph(nodes, edges, initial_node, *, global_prompt=None):
    """Reject unsafe bindings before any model, provider, or caller interaction."""
    quotes = _quote_nodes(nodes)
    if not quotes and not any(
        isinstance(node["data"].get("api"), dict)
        and "quoteDelivery" in node["data"]["api"] for node in nodes
    ):
        return
    by_id = {node["id"]: node for node in nodes}
    outgoing = {}
    for edge in edges:
        outgoing.setdefault(edge.source, []).append(edge.target)
    sensitive, private_values, _fingerprints = _sensitive_names(nodes, quotes)
    origins = {
        _origin(origin) for _api, policy in quotes.values()
        for origin in policy.allowed_origins
    } - {None}
    speech = [global_prompt]
    for node in nodes:
        speech.extend(_speech_fields(node))
        if node["type"] == "confirmation" and (
            set(node["data"]["confirmation"].get("variablesToConfirm", ())) & private_values
        ):
            raise NativeQuoteError("quote_private_confirmation")
        api = node["data"].get("api")
        if not isinstance(api, dict):
            continue
        entries = resolve_response_variables(api)
        projection = api.get("responseProjection")
        projected = (
            {field["variable"] for field in projection["fields"]}
            if isinstance(projection, dict) else
            {entry.variable_key for entry in entries}
        )
        if projected & sensitive:
            raise NativeQuoteError("quote_private_projection")
        delivery = api.get("quoteDelivery")
        if delivery is None:
            continue
        quote_id = delivery["quoteNodeId"]
        binding = quotes.get(quote_id)
        if binding is None:
            raise NativeQuoteError("quote_delivery_binding")
        _quote_api, policy = binding
        recipient = delivery["recipientVariable"]
        if recipient in sensitive or not policy.require_link:
            raise NativeQuoteError("quote_delivery_recipient")
        required = {
            *policy.public_confirmation_variables, policy.fingerprint_variable, recipient,
        }
        if _reachable_without(initial_node, node["id"], outgoing, {quote_id}):
            raise NativeQuoteError("quote_delivery_order")
        consent_nodes = {
            candidate_id for candidate_id, candidate in by_id.items()
            if candidate["type"] == "confirmation"
            and required <= set(candidate["data"]["confirmation"]["variablesToConfirm"])
            and not _reachable_without(initial_node, candidate_id, outgoing, {quote_id})
        }
        if not consent_nodes or _reachable_without(
            initial_node, node["id"], outgoing, consent_nodes,
        ):
            raise NativeQuoteError("quote_delivery_confirmation")
    for text in _strings(speech):
        if set(_TOKEN.findall(text)) & sensitive or any(
            _origin(match.group()) in origins for match in _URL.finditer(text)
        ):
            raise NativeQuoteError("quote_private_speech")


def private_quote_values(compiled, facts):
    """Find private values even before selection/validation has produced aliases."""
    quotes = _quote_nodes(compiled.config()["nodes"])
    if not quotes:
        return ()
    values, origins = set(), set()
    for api, policy in quotes.values():
        origins.update(filter(None, (_origin(origin) for origin in policy.allowed_origins)))
        for key in (policy.private_url_variable, policy.fingerprint_variable):
            value = facts.get(key)
            if isinstance(value, str) and value:
                values.add(value)
        template = api.get("argumentsTemplate")
        arguments = {"quote": facts.get("quote")}
        if isinstance(template, str):
            # None is only a missing-value sentinel for privacy discovery.
            # This probe is NEVER validated, presented, or used as business data.
            probe = {name: facts.get(name) for name in _TOKEN.findall(template)}
            try:
                arguments = render_json_template(template, probe)
            except (RequestTemplateError, TypeError, ValueError, RecursionError):
                arguments = {}
        quote = arguments.get("quote") if isinstance(arguments, dict) else None
        if isinstance(quote, dict):
            value = quote.get("checkout_url")
            if isinstance(value, str) and value:
                values.add(value)
    # Booking origins are private in this flow. This also protects URLs nested
    # in availability options before a selected quote variable exists.
    for text in _strings(facts):
        for match in _URL.finditer(text):
            if _origin(match.group()) in origins:
                values.add(match.group())
    return tuple(values)


def assert_quote_payload_safe(compiled, facts, payload, *, mapped_variables=None):
    """Fail explicitly; never silently rewrite configured model/speech output."""
    values = private_quote_values(compiled, facts)
    quotes = _quote_nodes(compiled.config()["nodes"])
    if not quotes:
        return
    origins = {
        _origin(origin) for _api, policy in quotes.values()
        for origin in policy.allowed_origins
    } - {None}
    private_hosts = []
    for origin in origins:
        try:
            host = urlsplit(origin).hostname
        except ValueError:
            continue
        if host:
            private_hosts.append(re.compile(
                r"(?<![\w.-])" + re.escape(host) + r"(?::[0-9]{1,5})?[/?#]", re.I,
            ))
    selected_raw = {
        key: mapped_variables[key] for key in payload
        if key in mapped_variables
    } if isinstance(payload, dict) and isinstance(mapped_variables, dict) else {}
    for text in _strings((payload, selected_raw)):
        # Normalize only a bounded detection view, never the mapped business data.
        views = [text]
        for _ in range(2):
            decoded = unquote(html.unescape(unicodedata.normalize("NFKC", views[-1])))
            decoded = "".join(char for char in decoded if unicodedata.category(char) != "Cf")
            if decoded == views[-1]:
                break
            views.append(decoded)
        for view in views:
            if (
                any(value in view for value in values)
                or any(_origin(match.group()) in origins for match in _URL.finditer(view))
                or any(pattern.search(view) for pattern in private_hosts)
            ):
                raise NativeQuoteError("quote_private_projection")

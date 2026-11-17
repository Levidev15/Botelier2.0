"""Bounded request values, encoded for their actual transport context.

No credentials, clients, logging, database access or recursive interpolation.
Secret resolvers, when supplied by the authorized action boundary, only resolve
references present in the original trusted template, never in caller values.
"""

from dataclasses import dataclass
import html
import json
import math
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?)\s*}}")
MAX_REQUEST_BYTES = 256_000


class RequestTemplateError(ValueError):
    """Payload-free failure at a request-construction boundary."""


def _snapshot(value):
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 32 or count > 4096:
            raise RequestTemplateError("request_value_size")
        if isinstance(item, dict):
            if len(item) > 1024 or any(not isinstance(key, str) or len(key) > 256 for key in item):
                raise RequestTemplateError("request_value_type")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > 1024:
                raise RequestTemplateError("request_value_size")
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > 100_000:
                raise RequestTemplateError("request_value_size")
        elif type(item) is int:
            if item.bit_length() > 1024:
                raise RequestTemplateError("request_value_size")
        elif type(item) is float:
            if not math.isfinite(item):
                raise RequestTemplateError("request_value_number")
        elif item is not None and type(item) is not bool:
            raise RequestTemplateError("request_value_type")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise RequestTemplateError("request_value_size")
        return encoded
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise RequestTemplateError("request_value_type") from None


def _text(value):
    encoded = _snapshot(value)
    return value if isinstance(value, str) else encoded


def _template(template):
    if not isinstance(template, str):
        raise RequestTemplateError("request_template_size")
    try:
        if len(template.encode("utf-8")) > 32_000:
            raise RequestTemplateError("request_template_size")
    except UnicodeError:
        raise RequestTemplateError("request_template_encoding") from None
    if "{{" in _TOKEN.sub("", template):
        raise RequestTemplateError("request_template_syntax")
    return template


def referenced_secrets(template):
    """Return only explicit credential names from an original request template."""
    _template(template)
    return frozenset(match[1].split(".", 1)[1] for match in _TOKEN.finditer(template) if match[1].startswith("secrets."))


def _value(name, variables, secret_resolver):
    if name.startswith("secrets."):
        if secret_resolver is None:
            raise RequestTemplateError("request_secret_unavailable")
        try:
            value = secret_resolver(name.split(".", 1)[1])
        except Exception:
            raise RequestTemplateError("request_secret_unavailable") from None
        if value is None:
            raise RequestTemplateError("request_secret_unavailable")
    else:
        if "." in name or name not in variables:
            raise RequestTemplateError("request_variable")
        value = variables[name]
    _snapshot(value)
    return value


def render_json_template(template, variables, *, secret_resolver=None):
    """Parse the configured structure first, then replace values without eval.

    Quoted tokens produce strings; unquoted whole-value tokens retain JSON type.
    Template keys are deliberately static.
    """
    template = _template(template)
    prefix = "BOTELIER_TEMPLATE_VALUE_"
    while prefix in template:
        prefix += "_"
    markers = {}
    parts = []
    quoted = escaped = False
    position = 0
    while position < len(template):
        match = _TOKEN.match(template, position)
        if match:
            marker = f"{prefix}{len(markers)}_END"
            markers[marker] = (match[1], quoted)
            parts.append(marker if quoted else json.dumps(marker))
            position = match.end()
            continue
        character = template[position]
        parts.append(character)
        if character == '"' and not escaped:
            quoted = not quoted
        escaped = quoted and character == "\\" and not escaped
        position += 1
    try:
        parsed = json.loads("".join(parts))
    except (ValueError, RecursionError):
        raise RequestTemplateError("request_json_syntax") from None
    _snapshot(parsed)
    pattern = re.compile("|".join(re.escape(marker) for marker in markers)) if markers else None

    def replace(item):
        if isinstance(item, dict):
            if any(any(marker in key for marker in markers) for key in item):
                raise RequestTemplateError("request_dynamic_key")
            return {key: replace(child) for key, child in item.items()}
        if isinstance(item, list):
            return [replace(child) for child in item]
        if not isinstance(item, str):
            return item
        if item in markers and not markers[item][1]:
            return json.loads(_snapshot(_value(markers[item][0], variables, secret_resolver)))
        # Match the original markers in one pass: inserted values are literal.
        return pattern.sub(lambda match: _text(_value(markers[match[0]][0], variables, secret_resolver)), item) if pattern else item

    return json.loads(_snapshot(replace(parsed)))


@dataclass(frozen=True, init=False)
class PreparedRequestBody:
    """Immutable internal body value; downstream clients must not render again."""

    mode: str
    _json: str

    def __init__(self, mode, value):
        if mode not in {"json", "data", "files", "content"}:
            raise RequestTemplateError("request_body_mode")
        if mode in {"data", "files"} and not isinstance(value, dict):
            raise RequestTemplateError("request_body_type")
        if mode == "content" and not isinstance(value, str):
            raise RequestTemplateError("request_body_type")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "_json", _snapshot(value))

    def value(self):
        return json.loads(self._json)


def prepare_body_headers(body, headers):
    """Keep HTTP media type and internal prepared transport mode consistent."""
    if not isinstance(body, PreparedRequestBody) or not isinstance(headers, dict):
        raise RequestTemplateError("request_body_type")
    content_types = [value for key, value in headers.items() if key.casefold() == "content-type"]
    if any(not isinstance(value, str) for value in content_types) or len(set(content_types)) > 1:
        raise RequestTemplateError("request_content_type")
    declared = content_types[0] if content_types else None
    defaults = {
        "json": "application/json", "data": "application/x-www-form-urlencoded",
        "files": "multipart/form-data", "content": "text/plain",
    }
    declared = declared or defaults[body.mode]
    if "\r" in declared or "\n" in declared:
        raise RequestTemplateError("request_content_type")
    media_type = declared.split(";", 1)[0].strip().casefold()
    compatible = {
        "json": media_type == "application/json" or media_type.endswith("+json"),
        "data": media_type == "application/x-www-form-urlencoded",
        "files": media_type == "multipart/form-data",
        "content": media_type in {"text/plain", "application/xml", "text/xml"} or media_type.endswith("+xml"),
    }[body.mode]
    if not compatible:
        raise RequestTemplateError("request_content_type")
    normalized = {key: value for key, value in headers.items() if key.casefold() != "content-type"}
    if body.mode != "files":
        normalized["Content-Type"] = declared
    # httpx creates the multipart Content-Type together with its actual boundary.
    return normalized


def render_request_url(template, variables, *, allow_insecure=False):
    """Render only path/query values; a caller cannot choose origin or query keys."""
    try:
        _template(template)
        parsed = urlsplit(template)
        if (
            parsed.scheme not in ({"https", "http"} if allow_insecure else {"https"})
            or not parsed.hostname or parsed.username or parsed.password
            or "{{" in parsed.netloc or "#" in template
            or any(character.isspace() or ord(character) < 32 for character in parsed.netloc)
            or "\\" in template
        ):
            raise RequestTemplateError("request_url_shape")
        parsed.port  # Reject malformed/out-of-range ports without exposing the URL.

        def path_value(match):
            value = _value(match[1], variables, None)
            if value is None or isinstance(value, (dict, list)) or _text(value) in {".", ".."}:
                raise RequestTemplateError("request_url_value")
            return quote(_text(value), safe="")

        path = _TOKEN.sub(path_value, parsed.path)
        parameters = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if "{{" in key:
                raise RequestTemplateError("request_url_key")
            value = _TOKEN.sub(lambda match: _text(_value(match[1], variables, None)), value)
            parameters.append((key, value))
        result = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(parameters), ""))
        if len(result.encode("utf-8")) > 16_000:
            raise RequestTemplateError("request_url_size")
        return result
    except (ValueError, TypeError):
        raise RequestTemplateError("request_url_invalid") from None


def render_content_template(template, variables, *, media_type, secret_resolver=None):
    media_type = media_type.split(";", 1)[0].strip().casefold()
    xml = media_type in {"application/xml", "text/xml"} or media_type.endswith("+xml")
    if not xml and media_type != "text/plain":
        raise RequestTemplateError("request_content_type")
    template = _template(template)
    if xml:
        _validate_xml_positions(template)

    def replace(match):
        value = _text(_value(match[1], variables, secret_resolver))
        return html.escape(value, quote=True) if xml else value

    result = _TOKEN.sub(replace, template)
    if len(result.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise RequestTemplateError("request_value_size")
    return result


def _validate_xml_positions(template):
    """Only XML text and quoted attribute values may contain template tokens."""
    from xml.etree import ElementTree

    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", template, re.I):
        raise RequestTemplateError("request_xml_declaration")
    for special in re.finditer(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", template, re.S):
        if _TOKEN.search(special[0]):
            raise RequestTemplateError("request_xml_position")
    marker = "BOTELIER_XML_VALUE_MARKER"
    while marker in template:
        marker += "_"
    try:
        root = ElementTree.fromstring(_TOKEN.sub(marker, template))
    except (ElementTree.ParseError, ValueError):
        raise RequestTemplateError("request_xml_syntax") from None
    for element in root.iter():
        if marker in str(element.tag) or any(marker in key for key in element.attrib):
            raise RequestTemplateError("request_xml_position")

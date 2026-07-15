"""Shared utilities for spec importers."""

import re
import uuid
from typing import Any, Optional

# Botelier integration property-identity key patterns.  Variables matching
# these in path params are tagged ``connection`` ownership — they come from the
# connection config, not from the LLM.
_PROPERTY_IDENTITY_PATTERNS = re.compile(
    r"(?i)(hotel[_-]?id|property[_-]?id|location[_-]?id|site[_-]?id|"
    r"venue[_-]?id|resort[_-]?id|branch[_-]?id|store[_-]?id|unit[_-]?id)"
)

# HTTP methods that are typically read-only
_READ_METHODS = {"get", "head", "options"}

# Risk inference heuristics keyed on normalized path segments / tags
_HIGH_RISK_PATHS = re.compile(
    r"(?i)(payment|charge|refund|billing|invoice|delete|remove|cancel|"
    r"admin|password|credential|token|key|secret|webhook|transfer|auth)"
)
_FINANCIAL_PATHS = re.compile(
    r"(?i)(payment|charge|refund|billing|invoice|price|amount|pay|transaction)"
)
_DESTRUCTIVE_TAGS = re.compile(r"(?i)(delete|destroy|purge|wipe|remove)")


def sanitize_operation_id(operation_id: str, method: str, path: str) -> str:
    """Convert an operationId (or derive one from method+path) to a valid Python
    function name suitable for LLM tool calling.

    Rules:
    * Replace all non-alphanumeric chars with underscores
    * Collapse consecutive underscores
    * Strip leading/trailing underscores
    * Prefix with method if the result starts with a digit
    * Truncate to 60 chars
    """
    if not operation_id:
        # Derive from method + path
        operation_id = f"{method}_{path}"

    # Convert path params {param} to just the param name
    operation_id = re.sub(r"\{(\w+)\}", r"\1", operation_id)
    # Replace non-alphanumeric with underscore
    name = re.sub(r"[^a-zA-Z0-9]", "_", operation_id)
    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    # Must not start with a digit
    if name and name[0].isdigit():
        name = f"{method.lower()}_{name}"
    if not name:
        name = f"{method.lower()}_{uuid.uuid4().hex[:8]}"
    # Truncate to 60
    return name[:60].rstrip("_")


def infer_risk_level(method: str, path: str, tags: list[str]) -> str:
    """Infer a risk level from HTTP method + path + OpenAPI tags.

    Levels (ordered ascending):
        read → write → financial → destructive → admin | sensitive
    """
    m = method.lower()
    p = path.lower()
    t = " ".join(tags or []).lower()
    combined = f"{p} {t}"

    if _DESTRUCTIVE_TAGS.search(t) or m == "delete":
        return "destructive"

    if _FINANCIAL_PATHS.search(combined):
        return "financial"

    if _HIGH_RISK_PATHS.search(combined):
        if m in ("post", "put", "patch", "delete"):
            return "write"

    if m in _READ_METHODS:
        return "read"

    return "write"


def infer_ownership(
    param_name: str,
    param_location: str,
    security_schemes: Optional[list[str]] = None,
) -> str:
    """Infer parameter ownership category.

    ``llm``        — the AI supplies this value at call-time
    ``connection`` — comes from the connection's stored config (e.g. hotel_id)
    ``secret``     — comes from encrypted credentials (auth params)
    ``fixed``      — a constant baked into the operation config
    ``derived``    — computed at runtime (e.g. idempotency keys)

    Rules:
    * Auth / security-scheme parameters → ``secret``
    * Path params matching property-identity patterns → ``connection``
    * All other params → ``llm``
    """
    if security_schemes and param_name.lower() in {
        s.lower() for s in (security_schemes or [])
    }:
        return "secret"

    # Common auth parameter names
    if re.match(
        r"(?i)^(api[_-]?key|apikey|access[_-]?token|authorization|bearer|"
        r"x-api-key|x-auth-token|client[_-]?id|client[_-]?secret|password|"
        r"api[_-]?secret)$",
        param_name,
    ):
        return "secret"

    if param_location == "path" and _PROPERTY_IDENTITY_PATTERNS.match(param_name):
        return "connection"

    return "llm"


def build_variable_schema(
    param_name: str,
    param_schema: dict,
    param_location: str,
    ownership: str,
) -> dict:
    """Build a Botelier endpoint variable descriptor from an OpenAPI parameter.

    Note: ``key`` is the canonical lookup field used by IntegrationClient
    (``_apply_endpoint_defaults`` reads ``var.get("key")``).  ``name`` is kept
    as an alias for display and backward-compatibility.
    """
    oai_type = param_schema.get("type", "string")
    type_map = {
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
    }
    return {
        "key": param_name,
        "name": param_name,
        "type": type_map.get(oai_type, "string"),
        "description": param_schema.get("description") or param_schema.get("title") or "",
        "required": param_schema.get("required", False),
        "location": param_location,
        "ownership": ownership,
        "enum": param_schema.get("enum"),
        "default": param_schema.get("default"),
    }


def extract_base_url(spec_data: dict, override: Optional[str] = None) -> str:
    """Extract the first server base URL from an OpenAPI or Swagger spec."""
    if override:
        return override.rstrip("/")
    # OpenAPI 3.x
    servers = spec_data.get("servers")
    if servers and isinstance(servers, list):
        url = servers[0].get("url", "")
        if url:
            return url.rstrip("/")
    # Swagger 2.x
    host = spec_data.get("host", "")
    scheme = (spec_data.get("schemes") or ["https"])[0]
    base_path = spec_data.get("basePath", "")
    if host:
        return f"{scheme}://{host}{base_path}".rstrip("/")
    return ""


def truncate_spec_endpoints(endpoints: list[dict], max_count: int = 200) -> tuple[list[dict], bool]:
    """Truncate endpoints to ``max_count``.  Returns (truncated_list, was_truncated)."""
    if len(endpoints) <= max_count:
        return endpoints, False
    return endpoints[:max_count], True

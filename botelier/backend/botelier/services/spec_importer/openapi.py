"""OpenAPI 3.x / Swagger 2.x spec importer.

Parses a spec dict into a ``IntegrationType`` row with ``origin=customer_imported``.
Existing rows for the same account + slug are updated in-place so repeated imports
are idempotent (e.g. re-importing an updated spec).
"""

import json
import re
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import IntegrationType

from .utils import (
    build_variable_schema,
    extract_base_url,
    infer_ownership,
    infer_risk_level,
    sanitize_operation_id,
    truncate_spec_endpoints,
)

_MAX_ENDPOINTS = 200


def _parse_security_schemes(spec_data: dict) -> dict:
    """Return a map of {scheme_name: scheme_object} for the spec."""
    # OpenAPI 3.x
    components = spec_data.get("components") or {}
    sec_schemes = components.get("securitySchemes") or {}
    # Swagger 2.x
    if not sec_schemes:
        sec_schemes = spec_data.get("securityDefinitions") or {}
    return sec_schemes


def _detect_auth_strategy(spec_data: dict) -> tuple[str, dict]:
    """Detect the primary auth strategy from security schemes.

    Returns (auth_type, auth_config) for the IntegrationType row.

    Multiple apiKey header schemes → ``custom_headers`` (many APIs require more
    than one header key, e.g. ``X-App-Key`` + ``X-Auth-Token``).
    OAuth2 clientCredentials flow → ``oauth2_client_credentials`` with token URL.
    Single apiKey → ``api_key_header`` or ``api_key_query``.
    HTTP bearer/basic → ``bearer`` / ``basic``.
    Unknown / no schemes → ``none`` (user can change via auth settings).
    """
    schemes = _parse_security_schemes(spec_data)

    # Collect all apiKey-in-header schemes — multiple means custom_headers strategy.
    api_key_header_schemes: list[dict] = []
    for name, scheme in schemes.items():
        scheme_type = (scheme.get("type") or "").lower()
        scheme_in = (scheme.get("in") or "").lower()
        if scheme_type == "apikey" and scheme_in == "header":
            api_key_header_schemes.append(
                {
                    "header_name": scheme.get("name") or name,
                    "credential_key": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                    or "api_key",
                }
            )

    if len(api_key_header_schemes) >= 2:
        return "default", {
            "auth_strategy": "custom_headers",
            "headers": api_key_header_schemes,
        }

    for name, scheme in schemes.items():
        scheme_type = (scheme.get("type") or "").lower()
        scheme_in = (scheme.get("in") or "").lower()

        if scheme_type == "http":
            scheme_subtype = (scheme.get("scheme") or "").lower()
            if scheme_subtype == "bearer":
                return "default", {"auth_strategy": "bearer"}
            if scheme_subtype == "basic":
                return "default", {"auth_strategy": "basic"}

        if scheme_type == "apikey":
            if scheme_in == "header":
                cred_key = (
                    re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "api_key"
                )
                return "default", {
                    "auth_strategy": "api_key_header",
                    "header_name": scheme.get("name") or "X-API-Key",
                    "credential_key": cred_key,
                }
            if scheme_in == "query":
                cred_key = (
                    re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "api_key"
                )
                return "default", {
                    "auth_strategy": "api_key_query",
                    "param_name": scheme.get("name") or "api_key",
                    "credential_key": cred_key,
                }

        if scheme_type == "oauth2":
            # Check for client_credentials flow (machine-to-machine)
            flows = scheme.get("flows") or {}
            cc_flow = flows.get("clientCredentials") or {}
            if cc_flow:
                token_url = (cc_flow.get("tokenUrl") or "").strip()
                scope_map = cc_flow.get("scopes") or {}
                auth_config: dict = {
                    "auth_strategy": "oauth2_client_credentials",
                    "token_url": token_url,
                }
                if scope_map:
                    # Include up to 5 scopes as a default hint
                    auth_config["scope"] = " ".join(list(scope_map.keys())[:5])
                return "default", auth_config
            # Other OAuth2 flows: tell the user it's bearer-based
            return "default", {"auth_strategy": "bearer"}

    # Unknown scheme — default to bearer so the user sees a token prompt
    # rather than silently connecting with no credentials.
    return "default", {"auth_strategy": "bearer"}


def _required_fields_from_strategy(auth_config: dict) -> list[dict]:
    """Build ``required_fields`` from the chosen auth strategy.

    Returns the credential fields a user must fill to connect.  Called at
    import time (from detected scheme) and by the auth-config editor whenever
    the operator changes the strategy.
    """
    strategy = auth_config.get("auth_strategy", "none")

    if strategy == "bearer":
        return [
            {
                "key": "access_token",
                "label": "API Token",
                "type": "password",
                "storage": "credentials",
                "required": True,
            }
        ]

    if strategy == "api_key_header":
        cred_key = auth_config.get("credential_key", "api_key")
        header_name = auth_config.get("header_name", "X-API-Key")
        return [
            {
                "key": cred_key,
                "label": header_name,
                "type": "password",
                "storage": "credentials",
                "placeholder": f"Value for {header_name}",
                "required": True,
            }
        ]

    if strategy == "api_key_query":
        cred_key = auth_config.get("credential_key", "api_key")
        param_name = auth_config.get("param_name", "api_key")
        return [
            {
                "key": cred_key,
                "label": f"API Key ({param_name})",
                "type": "password",
                "storage": "credentials",
                "required": True,
            }
        ]

    if strategy == "custom_headers":
        headers_config = auth_config.get("headers") or []
        if headers_config:
            return [
                {
                    "key": hdr.get("credential_key", "api_key"),
                    "label": hdr.get("header_name", hdr.get("credential_key", "API Key")),
                    "type": "password",
                    "storage": "credentials",
                    "required": True,
                }
                for hdr in headers_config
            ]
        # Fallback if headers list is empty
        return [
            {
                "key": "api_key",
                "label": "API Key",
                "type": "password",
                "storage": "credentials",
                "required": True,
            }
        ]

    if strategy == "basic":
        return [
            {
                "key": "username",
                "label": "Username",
                "type": "text",
                "storage": "credentials",
                "required": True,
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "storage": "credentials",
                "required": True,
            },
        ]

    if strategy == "login_endpoint":
        # Fields come from the body_mapping; fall back to username/password if not set.
        body_mapping: dict = auth_config.get("login_body_mapping") or {
            "username": "username",
            "password": "password",
        }
        fields = []
        for body_key, cred_key in body_mapping.items():
            is_secret = any(
                w in cred_key.lower()
                for w in ("password", "secret", "token", "key", "apikey")
            )
            fields.append(
                {
                    "key": cred_key,
                    "label": body_key.replace("_", " ").replace("-", " ").title(),
                    "type": "password" if is_secret else "text",
                    "storage": "credentials",
                    "required": True,
                }
            )
        return fields

    if strategy == "oauth2_client_credentials":
        fields: list[dict] = [
            {
                "key": "client_id",
                "label": "Client ID",
                "type": "text",
                "storage": "credentials",
                "required": True,
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "type": "password",
                "storage": "credentials",
                "required": True,
            },
        ]
        if auth_config.get("scope"):
            fields.append(
                {
                    "key": "scope",
                    "label": "Scope (optional)",
                    "type": "text",
                    "storage": "credentials",
                    "placeholder": auth_config.get("scope", ""),
                    "required": False,
                }
            )
        return fields

    # "none" or unknown — no credential fields needed
    return []


def _parse_openapi3_parameters(
    params: list[dict],
    components: dict,
    security_scheme_names: list[str],
) -> list[dict]:
    """Parse OpenAPI 3.x ``parameters`` array into Botelier variable descriptors."""
    variables: list[dict] = []
    for param in params or []:
        # Resolve $ref
        if "$ref" in param:
            ref_path = param["$ref"].replace("#/components/parameters/", "")
            param = (components.get("parameters") or {}).get(ref_path, param)

        name = param.get("name", "")
        location = param.get("in", "query")
        required = param.get("required", False)
        schema = param.get("schema") or {}
        description = param.get("description") or schema.get("description") or ""
        ownership = infer_ownership(name, location, security_scheme_names)
        var = build_variable_schema(name, {**schema, "description": description, "required": required}, location, ownership)
        variables.append(var)
    return variables


def _parse_request_body_params(
    request_body: Optional[dict],
    components: dict,
    security_scheme_names: list[str],
) -> list[dict]:
    """Flatten a requestBody's JSON schema properties into variable descriptors."""
    if not request_body:
        return []
    content = request_body.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema") or {}
    if "$ref" in schema:
        ref_path = schema["$ref"].replace("#/components/schemas/", "")
        schema = (components.get("schemas") or {}).get(ref_path, schema)

    properties = schema.get("properties") or {}
    required_list = schema.get("required") or []
    variables: list[dict] = []
    for prop_name, prop_schema in properties.items():
        ownership = infer_ownership(prop_name, "body", security_scheme_names)
        var = build_variable_schema(
            prop_name,
            {**prop_schema, "required": prop_name in required_list},
            "body",
            ownership,
        )
        variables.append(var)
    return variables


def _parse_swagger2_parameters(
    params: list[dict],
    definitions: dict,
    security_scheme_names: list[str],
) -> list[dict]:
    """Parse Swagger 2.x parameters into Botelier variable descriptors."""
    variables: list[dict] = []
    for param in params or []:
        if "$ref" in param:
            ref_path = param["$ref"].replace("#/parameters/", "")
            param = (definitions or {}).get(ref_path, param)
        name = param.get("name", "")
        location = param.get("in", "query")
        required = param.get("required", False)
        if location == "body":
            schema = param.get("schema") or {}
            props = schema.get("properties") or {}
            req_list = schema.get("required") or []
            for prop_name, prop_schema in props.items():
                ownership = infer_ownership(prop_name, "body", security_scheme_names)
                var = build_variable_schema(
                    prop_name,
                    {**prop_schema, "required": prop_name in req_list},
                    "body",
                    ownership,
                )
                variables.append(var)
        else:
            ownership = infer_ownership(name, location, security_scheme_names)
            schema = {k: param.get(k) for k in ("type", "format", "enum", "default", "description") if param.get(k)}
            schema["required"] = required
            var = build_variable_schema(name, schema, location, ownership)
            variables.append(var)
    return variables


def _parse_endpoints(spec_data: dict) -> tuple[list[dict], str, str]:
    """Parse all path operations from OpenAPI 3.x or Swagger 2.x.

    Returns:
        (endpoints, spec_type, spec_version)
        spec_type    — "openapi" or "swagger"
        spec_version — version string from the spec
    """
    is_openapi3 = "openapi" in spec_data
    is_swagger2 = "swagger" in spec_data
    spec_version = spec_data.get("openapi") or spec_data.get("swagger") or "unknown"
    spec_type = "openapi" if is_openapi3 else "swagger"

    components = spec_data.get("components") or {}
    definitions = spec_data.get("definitions") or {}
    security_schemes = _parse_security_schemes(spec_data)
    security_scheme_names = list(security_schemes.keys())

    paths = spec_data.get("paths") or {}
    endpoints: list[dict] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        # Parameters shared across all methods on this path
        path_params = path_item.get("parameters") or []

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not operation or not isinstance(operation, dict):
                continue

            operation_id_raw = operation.get("operationId", "")
            summary = operation.get("summary") or operation.get("description") or ""
            description = operation.get("description") or operation.get("summary") or ""
            tags = operation.get("tags") or []

            fn_name = sanitize_operation_id(operation_id_raw, method, path)
            risk_level = infer_risk_level(method, path, tags)

            # Merge path-level + operation-level parameters
            op_params = path_params + (operation.get("parameters") or [])

            if is_openapi3:
                variables = _parse_openapi3_parameters(op_params, components, security_scheme_names)
                request_body = operation.get("requestBody")
                variables += _parse_request_body_params(request_body, components, security_scheme_names)
            else:
                variables = _parse_swagger2_parameters(op_params, definitions, security_scheme_names)

            # Deduplicate by name (operation params win over path params)
            seen: set = set()
            deduped: list[dict] = []
            for v in variables:
                if v["name"] not in seen:
                    seen.add(v["name"])
                    deduped.append(v)
            variables = deduped

            # Normalize path: OpenAPI uses {param} but IntegrationClient expects {{param}}
            normalized_path = re.sub(r"(?<!\{)\{(\w+)\}(?!\})", r"{{\1}}", path)

            # Build certified query_params format for IntegrationClient._build_url
            query_params = [
                {
                    "key": v["name"],
                    "value": "{{" + v["name"] + "}}",
                    "required": bool(v.get("required", False)),
                }
                for v in variables
                if v.get("location") == "query" and v.get("ownership") == "llm"
            ]

            # Build body_template from body-location LLM variables
            body_vars = [
                v for v in variables
                if v.get("location") == "body" and v.get("ownership") == "llm"
            ]
            body_template = (
                json.dumps({v["name"]: "{{" + v["name"] + "}}" for v in body_vars})
                if body_vars else None
            )

            endpoint: dict = {
                "id": f"{method.upper()}_{fn_name}",
                "method": method.upper(),
                "path": normalized_path,
                "name": fn_name,
                "summary": summary[:255] if summary else "",
                "description": description[:1000] if description else "",
                "category": tags[0] if tags else "general",
                "variables": variables,
                "query_params": query_params,
                "body_template": body_template,
                "risk_level": risk_level,
                "capability": None,
            }
            endpoints.append(endpoint)

    return endpoints, spec_type, str(spec_version)


def import_openapi_spec(
    db: Session,
    spec_data: dict,
    account_id: str,
    base_url_override: Optional[str] = None,
    spec_url: Optional[str] = None,
) -> IntegrationType:
    """Import an OpenAPI 3.x or Swagger 2.x spec into an IntegrationType row.

    Idempotent: an existing row for the same account + derived slug is updated
    in-place.  New row otherwise.

    Args:
        db:               SQLAlchemy session.
        spec_data:        Parsed JSON spec.
        account_id:       Owner account UUID string.
        base_url_override: Override server base URL from spec.
        spec_url:         Original URL (audit only).

    Returns:
        The created or updated ``IntegrationType`` row (not yet committed).
    """
    info = spec_data.get("info") or {}
    title = info.get("title") or "Imported API"
    description = info.get("description") or ""

    base_url = extract_base_url(spec_data, base_url_override)
    auth_type, auth_config = _detect_auth_strategy(spec_data)
    # Persist base_url into auth_config so DefaultAdapter can construct the
    # token acquisition URL at connect time (login_endpoint strategy) without
    # any caller being able to override it via a later PATCH.
    if base_url:
        auth_config["base_url"] = base_url
    required_fields = _required_fields_from_strategy(auth_config)

    endpoints, source_type, spec_version = _parse_endpoints(spec_data)
    if not endpoints:
        raise ValueError(
            f"No endpoints found in this {'OpenAPI' if source_type == 'openapi' else 'Swagger'} spec. "
            "The spec has no 'paths' with operations to import — please check that you "
            "uploaded the full API specification."
        )
    endpoints, was_truncated = truncate_spec_endpoints(endpoints, _MAX_ENDPOINTS)
    if was_truncated:
        logger.warning(
            "import_openapi_spec: spec for account=%s exceeded %d endpoints; truncated.",
            account_id,
            _MAX_ENDPOINTS,
        )

    # Derive a slug: account-scoped so two accounts can import APIs with same name
    safe_title = "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_")[:40]
    slug = f"imported_{safe_title}_{str(account_id)[:8]}"

    # Upsert: update if slug already exists for this account
    existing = db.query(IntegrationType).filter(IntegrationType.slug == slug).first()
    if existing:
        it = existing
    else:
        it = IntegrationType(id=uuid.uuid4())
        db.add(it)

    it.slug = slug
    it.name = title[:255]
    it.description = description[:2000] if description else None
    it.provider = base_url or title[:255]
    it.auth_type = auth_type
    it.set_auth_config(auth_config)
    it.set_required_fields(required_fields)
    it.set_endpoints(endpoints)
    it.is_enabled = True
    it.origin = "customer_imported"
    it.source_type = source_type
    it.spec_version = str(spec_version)[:64]
    it.spec_url = spec_url
    it.created_by_account_id = account_id
    # Store trimmed raw spec (drop paths/components to save space)
    it.raw_spec = {
        "info": spec_data.get("info"),
        "servers": spec_data.get("servers"),
        "host": spec_data.get("host"),
        "basePath": spec_data.get("basePath"),
        "endpoint_count": len(endpoints),
        "was_truncated": was_truncated,
    }

    db.flush()
    return it

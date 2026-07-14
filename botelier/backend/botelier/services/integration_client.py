"""Pure re-export facade for the integration runtime.

The runtime that used to live in this single module now lives in the layered
``services/integration_runtime/`` package (types, jsonpath, redaction, locks,
client, and optional per-vendor adapters). This module re-exports every name
callers historically imported from ``integration_client`` — including the
underscored helpers and tuning constants — so no importer needs to change.

Do NOT add logic here. Add it to the appropriate ``integration_runtime`` module.
"""

from .integration_runtime.adapters import (
    _ORACLE_ALLOWED_SUFFIXES,
    _validate_opera_gateway_url,
)
from .integration_runtime.authparams import build_auth_request_query_params
from .integration_runtime.client import (
    IntegrationClient,
    get_llm_friendly_error_message,
)
from .integration_runtime.jsonpath import extract_json_value
from .integration_runtime.locks import (
    _REFRESH_POLL_INTERVAL_S,
    _REFRESH_WAIT_TIMEOUT_S,
    _TOKEN_REFRESH_SKEW_S,
    _advisory_lock_key,
    _safe_close,
)
from .integration_runtime.redaction import _sanitize_endpoint_for_log
from .integration_runtime.types import (
    APIErrorType,
    APIResponse,
    IntegrationAPIConfig,
    ResponseVariable,
    _MissingRequiredVariables,
)

__all__ = [
    "IntegrationClient",
    "IntegrationAPIConfig",
    "APIResponse",
    "ResponseVariable",
    "APIErrorType",
    "_MissingRequiredVariables",
    "extract_json_value",
    "get_llm_friendly_error_message",
    "build_auth_request_query_params",
    "_sanitize_endpoint_for_log",
    "_advisory_lock_key",
    "_safe_close",
    "_validate_opera_gateway_url",
    "_ORACLE_ALLOWED_SUFFIXES",
    "_TOKEN_REFRESH_SKEW_S",
    "_REFRESH_WAIT_TIMEOUT_S",
    "_REFRESH_POLL_INTERVAL_S",
]

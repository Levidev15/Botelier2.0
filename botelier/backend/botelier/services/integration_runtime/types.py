"""Shared value types for the integration runtime.

Extracted verbatim from the former ``integration_client`` monolith so callers
(and the facade) keep importing the exact same names.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class _MissingRequiredVariables(Exception):
    """Raised when a required endpoint query param cannot be resolved from variables."""

    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(f"Missing required variables: {', '.join(names)}")


class APIErrorType(str, Enum):
    SUCCESS = "success"
    AUTH_ERROR = "auth_error"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


@dataclass
class APIResponse:
    success: bool
    status_code: int
    data: Optional[Any] = None
    error_type: APIErrorType = APIErrorType.UNKNOWN
    error_message: Optional[str] = None
    extracted_variables: dict = field(default_factory=dict)
    raw_response: Optional[str] = None
    # Vendor-agnostic canonical envelope (see integration_runtime/canonical.py).
    # Populated only for endpoints tagged with a ``canonical_entity`` whose adapter
    # returns a normalization; None otherwise. Additive — never replaces ``data``
    # or ``extracted_variables``.
    canonical: Optional[dict] = None


@dataclass
class ResponseVariable:
    variable_key: str
    json_path: str
    default_value: Optional[str] = None


@dataclass
class IntegrationAPIConfig:
    integration_id: str
    endpoint_id: Optional[str] = None
    method: str = "GET"
    path: str = ""
    endpoint_template: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    body_template: Optional[str] = None
    timeout: int = 30
    retry_count: int = 2
    query_param_overrides: dict[str, str] = field(default_factory=dict)
    response_variables: list[ResponseVariable] = field(default_factory=list)
    on_success_message: str = "Request completed successfully"
    on_error_message: str = "There was an issue processing your request"
    on_not_found_message: str = "The requested information was not found"
    on_auth_error_message: str = "There was an authentication issue with the system"

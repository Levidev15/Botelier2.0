"""Log redaction for integration call logs.

Extracted verbatim from the former ``integration_client`` monolith. Strips
query strings and residual ``{{secrets.*}}`` placeholders before a URL/path is
persisted to ``IntegrationCallLog``.
"""

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

_SECRETS_PLACEHOLDER_RE = re.compile(r"\{\{secrets\.[^}]+\}\}")
_COMMON_SECRET_PARAMS = re.compile(
    r"(?i)(api[_-]?key|apikey|token|access[_-]?token|secret|password|passwd|auth|authorization|bearer)=[^&]*",
    re.IGNORECASE,
)


def _sanitize_endpoint_for_log(endpoint: Optional[str]) -> Optional[str]:
    """Sanitize a URL or path before persisting to call logs.

    Steps:
    1. Strip the query string entirely (can contain API keys, secrets, etc.)
    2. Remove any residual {{secrets.*}} placeholders that were not substituted.
    3. Truncate to 500 characters.

    This ensures that even if a secret value was resolved into the URL,
    only the path portion is stored.
    """
    if not endpoint:
        return endpoint
    try:
        parsed = urlparse(endpoint)
        sanitized = urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        sanitized = endpoint
    sanitized = _SECRETS_PLACEHOLDER_RE.sub("[REDACTED]", sanitized)
    return sanitized[:500]

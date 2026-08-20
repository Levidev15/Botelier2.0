"""Log redaction for integration call logs.

Extracted verbatim from the former ``integration_client`` monolith. Strips
query strings and residual ``{{secrets.*}}`` placeholders before a URL/path is
persisted to ``IntegrationCallLog``.

Also contains ``bound_and_redact_response`` for Universal Adapter response
bounding and field-level redaction before data reaches the LLM.
"""

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

_SECRETS_PLACEHOLDER_RE = re.compile(r"\{\{secrets\.[^}]+\}\}")
_COMMON_SECRET_PARAMS = re.compile(
    r"(?i)(api[_-]?key|apikey|token|access[_-]?token|secret|password|passwd|auth|authorization|bearer)=[^&]*",
    re.IGNORECASE,
)

# Key-name patterns that are always stripped from response bodies regardless of
# operator-supplied patterns.  These are conservative (full-word match) to avoid
# false-positives on legitimate keys like "customer_secret_preference".
_ALWAYS_REDACT_KEYS = re.compile(
    r"(?i)^(password|passwd|api[_-]?key|apikey|access[_-]?token|secret[_-]?key|"
    r"client[_-]?secret|authorization|bearer|card[_-]?number|cvv|cvc|"
    r"card[_-]?cvv|card[_-]?cvc|ssn|social[_-]?security|pin)$"
)

_DEFAULT_SIZE_LIMIT = 32_768  # 32 KB


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


def bound_and_redact_response(
    data: Any,
    policy: Optional[dict] = None,
) -> tuple[Any, list[str]]:
    """Bound a response body to a size limit and redact sensitive fields.

    Designed for IMPORTED-kind (Universal Adapter) operations.  Certified
    adapters (Opera Cloud, GuestCentric) are unaffected — they use
    ``response_mapping`` or canonical normalization instead.

    Args:
        data:    Parsed response body (dict, list, str, or None).
        policy:  Optional dict from ``IntegrationAction.response_policy`` or
                 ``ConnectionOperationPolicy``.  Recognised keys:
                   ``size_limit_bytes``  — max serialised JSON size (default 32 KB)
                   ``redact_patterns``   — list of field-name regex strings (case-insensitive)
                   ``strip_secret_keys`` — bool; if False, skip the built-in secret-key
                                           stripping (default True)

    Returns:
        ``(bounded_data, warnings)`` where ``warnings`` is a list of human-readable
        strings describing any truncation or redaction applied.  ``bounded_data``
        is safe to forward to the LLM.

    Guarantees:
    * Always strips ``_ALWAYS_REDACT_KEYS`` patterns from object keys (unless
      ``strip_secret_keys=False``).
    * Operator-supplied ``redact_patterns`` are applied after the built-in strip.
    * If the serialised result exceeds ``size_limit_bytes``, nested containers
      are trimmed recursively so useful prefixes survive (for example, the
      first room types in a large top-level array).
    * Never raises; returns the original data + a warning on unexpected errors.
    """
    warnings: list[str] = []
    if policy is None:
        policy = {}

    size_limit: int = int(policy.get("size_limit_bytes") or _DEFAULT_SIZE_LIMIT)
    redact_patterns: list[str] = policy.get("redact_patterns") or []
    do_strip_secrets: bool = policy.get("strip_secret_keys", True)

    # Compile operator patterns once
    compiled_patterns: list[re.Pattern] = []
    for pat in redact_patterns:
        try:
            compiled_patterns.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            warnings.append(f"Invalid redact_pattern ignored: {pat!r}")

    def _should_redact_key(key: str) -> bool:
        if do_strip_secrets and _ALWAYS_REDACT_KEYS.match(key):
            return True
        return any(p.search(key) for p in compiled_patterns)

    def _redact_obj(obj: Any) -> Any:
        """Recursively redact sensitive keys from dicts; leaves other types unchanged."""
        if isinstance(obj, dict):
            return {
                k: "[REDACTED]" if _should_redact_key(str(k)) else _redact_obj(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact_obj(item) for item in obj]
        return obj

    try:
        redacted = _redact_obj(data)
    except Exception as exc:
        warnings.append(f"Redaction failed ({exc}); returning raw data.")
        return data, warnings

    # Size-bound the redacted object
    try:
        serialised = json.dumps(redacted, default=str)
    except Exception:
        serialised = str(redacted)

    if len(serialised) <= size_limit:
        return redacted, warnings

    # Trim to fit recursively. The old shallow algorithm dropped an entire
    # top-level property when its nested array was large, often returning only
    # {"__truncated__": true}. Preserve useful prefixes at every depth instead.
    warnings.append(
        f"Response body exceeded {size_limit} bytes "
        f"({len(serialised)} bytes); truncated."
    )

    def _json_size(value: Any) -> int:
        return len(json.dumps(value, default=str))

    def _fit(value: Any, budget: int) -> Any:
        if budget <= 2:
            return {} if isinstance(value, dict) else [] if isinstance(value, list) else ""
        if _json_size(value) <= budget:
            return value

        if isinstance(value, dict):
            result: dict = {}
            items = list(value.items())
            for index, (key, child) in enumerate(items):
                marker = index < len(items) - 1
                reserve = _json_size({"__truncated__": True}) + 1 if marker else 0
                # Estimate remaining room from the actual partially-built object.
                base = _json_size(result)
                child_budget = max(2, budget - base - len(json.dumps(str(key))) - reserve - 3)
                fitted_child = _fit(child, child_budget)
                candidate = {**result, key: fitted_child}
                if _json_size(candidate) <= budget - reserve:
                    result[key] = fitted_child
                else:
                    result["__truncated__"] = True
                    break
                if _json_size(child) > _json_size(fitted_child):
                    result["__truncated__"] = True
                    break
            if _json_size(result) > budget:
                result.pop("__truncated__", None)
            return result

        if isinstance(value, list):
            result: list = []
            for child in value:
                remaining = max(2, budget - _json_size(result) - 1)
                fitted_child = _fit(child, remaining)
                candidate = result + [fitted_child]
                if _json_size(candidate) > budget:
                    break
                result.append(fitted_child)
                if _json_size(child) > _json_size(fitted_child):
                    break
            return result

        # JSON-encode a bounded string instead of slicing serialized JSON, which
        # could produce invalid quoted/escaped content.
        text = str(value)
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if _json_size(text[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return text[:low]

    return _fit(redacted, size_limit), warnings

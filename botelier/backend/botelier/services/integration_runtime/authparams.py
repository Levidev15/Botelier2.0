"""Shared helper for auth-request query parameters.

Some providers (e.g. GuestCentric) require credentials such as an API key on
*every* request, including the token login/refresh calls — not just data
requests. Which credential keys to attach is declared per provider via
``auth_config['auth_request_query_params']`` so this stays provider-agnostic
rather than hardcoding a specific field name.

Kept in its own module (rather than inside a single vendor adapter) because it
is imported both by the GuestCentric adapter and by the connect flow in
``api/integrations.py`` (re-exported through the ``integration_client`` facade).
"""


def build_auth_request_query_params(auth_config: dict, credentials: dict) -> dict:
    """Build query params that must be attached to JWT auth (login/refresh) requests.

    Raises ValueError when a declared param has no value in ``credentials`` so the
    caller fails clearly rather than sending an auth request the provider is
    guaranteed to reject.
    """
    declared = auth_config.get("auth_request_query_params") or []
    params: dict[str, str] = {}
    missing: list[str] = []
    for key in declared:
        value = credentials.get(key)
        if value:
            params[key] = str(value)
        else:
            missing.append(key)
    if missing:
        raise ValueError(
            "Missing required credential(s) for authentication: " + ", ".join(missing)
        )
    return params

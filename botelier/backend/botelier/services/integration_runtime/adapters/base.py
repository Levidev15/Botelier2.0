"""Integration adapter interface + the generic, config-driven DefaultAdapter.

An *adapter* isolates the small amount of vendor-specific behavior that cannot be
expressed purely as declarative config (seed JSON): how to authenticate, how to
resolve the base URL, which auth headers/query params a provider expects, and how
to refresh credentials. Everything else (endpoint resolution, variable
substitution, response mapping, retries, logging, the cross-worker advisory-lock
token refresh) lives in the shared runtime and is identical for every provider.

The vast majority of integrations need NO adapter: they are declared entirely in
a seed file and resolve to :class:`DefaultAdapter`, which speaks the generic
"static bearer token + base_url from config" dialect. Adding a per-vendor adapter
is the escape hatch for providers that deviate (custom token dances, extra
scoping headers, per-request credential query params, gateway validation).

Adapters are stateless and safe to share as singletons across accounts/requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from botelier.models.integration import AccountIntegration


@dataclass
class RefreshContext:
    """Everything an adapter needs to perform (and persist) a token refresh.

    The runtime owns DB-session lifecycle policy (reuse an externally-supplied
    session vs. open a short-lived one), so it hands the adapter a factory plus
    an ``owns_session`` flag instead of the adapter reaching back into the client.
    """

    integration: "AccountIntegration"
    credentials: dict
    auth_config: dict
    get_db_session: Callable[[], "Session"]
    owns_session: bool


class BaseIntegrationAdapter:
    """Vendor behavior seams. Defaults implement the generic config-only path."""

    #: Integration-type slug this adapter is registered for (None = fallback).
    slug: Optional[str] = None

    def needs_token(self, credentials: dict) -> bool:
        """Whether a bearer/OAuth token must be fresh before issuing a request.

        The generic default is False: a config-only integration uses whatever
        static credential it was given and performs no token dance.
        """
        return False

    def resolve_base_url(self, auth_config: dict, credentials: dict) -> str:
        """Return the base URL (no trailing slash) requests are built against."""
        return (auth_config.get("base_url", "") or "").rstrip("/")

    def build_auth_headers(self, integration: "AccountIntegration", credentials: dict) -> dict:
        """Auth-specific headers merged onto the base Content-Type/Accept set."""
        headers: dict[str, str] = {}
        access_token = integration.get_access_token()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def build_auth_query_params(
        self, auth_config: dict, credentials: dict, conn_config: dict
    ) -> dict:
        """Credential query params some providers require on every data request."""
        return {}

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        """Refresh + persist credentials. Generic default is a no-op success."""
        return True


class DefaultAdapter(BaseIntegrationAdapter):
    """Generic, config-driven adapter used for any integration without a
    dedicated vendor adapter. Inherits the base's generic behavior verbatim."""

    slug = None

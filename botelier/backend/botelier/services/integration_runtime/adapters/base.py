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

    #: Canonical card variable keys the combined booking+payment endpoints expect
    #: (Task #339). These are forwarded in-memory to the vendor's PCI-certified
    #: gateway and must never be persisted or logged by Botelier.
    CARD_FIELDS: tuple = (
        "card_holder",
        "card_number",
        "card_expiry",
        "card_cvv",
    )

    def validate_card_capture(self, variables: dict) -> None:
        """Fail loudly (ValueError) if any required card field is missing/blank.

        Called by the combined review+pay submit path before a PMS-native
        booking+charge request is issued. Vendor adapters may override to add
        their own required fields (e.g. GuestCentric's rate/policy ids), but the
        base contract guarantees a booking is never sent to a gateway with an
        incomplete card — silently creating an unpaid reservation is worse than a
        clear error.
        """
        missing = [
            key
            for key in self.CARD_FIELDS
            if not str((variables or {}).get(key) or "").strip()
        ]
        if missing:
            raise ValueError(
                "Cannot capture payment: missing card field(s): "
                + ", ".join(missing)
            )

    def normalize(self, entity: str, endpoint_id: Optional[str], raw: object) -> Optional[dict]:
        """Map a raw vendor response into the canonical envelope for ``entity``.

        ``entity`` is the endpoint's ``canonical_entity`` tag (a
        :class:`~botelier.services.integration_runtime.canonical.CanonicalEntity`
        value); ``endpoint_id`` disambiguates vendor endpoints that share an
        entity but wrap it differently; ``raw`` is the already-parsed JSON body.

        Return the envelope from
        :func:`~botelier.services.integration_runtime.canonical.build_envelope`,
        or ``None`` to opt out (no canonicalization). The generic default returns
        ``None`` so config-only integrations and custom endpoints are untouched.

        Contract: normalizers MUST be total — never raise. Return ``None`` on any
        unexpected shape so a normalization bug can never fail a live request.
        """
        return None


class DefaultAdapter(BaseIntegrationAdapter):
    """Generic, config-driven adapter for Universal Adapter (IMPORTED) integrations.

    Auth behaviour is driven entirely by ``auth_config["auth_strategy"]``:

    ``bearer``           — ``Authorization: Bearer {access_token}``  (default)
    ``api_key_header``   — custom header (``auth_config["header_name"]`` or
                           ``X-API-Key``) with value from credentials
    ``api_key_query``    — query param (``auth_config["param_name"]`` or
                           ``api_key``) with value from credentials
    ``basic``            — ``Authorization: Basic base64(username:password)``
                           where ``username``/``password`` come from credentials
    ``none``             — no auth injected (public APIs)

    No new vendor adapter subclass is needed for imported connectors; this
    class handles all config-driven strategies.
    """

    slug = None

    def build_auth_headers(
        self, integration: "AccountIntegration", credentials: dict
    ) -> dict:
        """Inject auth headers according to ``auth_config["auth_strategy"]``."""
        import base64

        try:
            auth_config = integration.integration_type.get_auth_config() or {}
        except Exception:
            auth_config = {}

        strategy = auth_config.get("auth_strategy", "bearer")

        if strategy == "none":
            return {}

        if strategy == "bearer":
            token = credentials.get("access_token") or credentials.get("token") or ""
            if token:
                return {"Authorization": f"Bearer {token}"}
            return {}

        if strategy == "api_key_header":
            header_name = auth_config.get("header_name", "X-API-Key")
            key_field = auth_config.get("credential_key", "api_key")
            key_value = credentials.get(key_field) or credentials.get("api_key") or ""
            if key_value:
                return {header_name: key_value}
            return {}

        if strategy == "basic":
            username = credentials.get("username") or credentials.get("client_id") or ""
            password = credentials.get("password") or credentials.get("client_secret") or ""
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}

        # api_key_query and unknown strategies — no headers needed
        return {}

    def build_auth_query_params(
        self, auth_config: dict, credentials: dict, conn_config: dict
    ) -> dict:
        """Inject query-param auth according to ``auth_config["auth_strategy"]``."""
        strategy = (auth_config or {}).get("auth_strategy", "bearer")
        if strategy == "api_key_query":
            param_name = (auth_config or {}).get("param_name", "api_key")
            key_field = (auth_config or {}).get("credential_key", "api_key")
            key_value = credentials.get(key_field) or credentials.get("api_key") or ""
            if key_value:
                return {param_name: key_value}
        return {}

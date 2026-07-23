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
from datetime import datetime, timedelta
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


@dataclass
class ConnectResult:
    """Result of a connect-time credential validation / token acquisition.

    ``success``      — True when credentials are valid / token obtained.
    ``error``        — Human-readable failure reason (stored in last_error).
    ``access_token`` — Acquired bearer token (token strategies only).
    ``refresh_token`` — Refresh token when the provider issues one.
    ``expires_in``   — Token TTL in seconds; None means no managed expiry.
    ``is_terminal``  — True when the failure is definitively bad credentials
                       (re-connect required); False for transient network blips
                       that are worth retrying automatically.
    """

    success: bool
    error: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    is_terminal: bool = True


class BaseIntegrationAdapter:
    """Vendor behavior seams. Defaults implement the generic config-only path."""

    #: Integration-type slug this adapter is registered for (None = fallback).
    slug: Optional[str] = None

    def needs_token(
        self, credentials: dict, auth_config: Optional[dict] = None
    ) -> bool:
        """Whether a bearer/OAuth token must be fresh before issuing a request.

        The generic default is False: a config-only integration uses whatever
        static credential it was given and performs no token dance.

        ``auth_config`` is passed by the runtime so DefaultAdapter can decide
        based on its ``auth_strategy``; legacy vendor adapters may ignore it.
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

    async def connect(self, credentials: dict, auth_config: dict) -> ConnectResult:
        """Validate credentials and/or acquire tokens at connect time.

        Legacy and certified adapters manage their connect logic in the API layer
        directly, so this default succeeds immediately leaving them unaffected.
        DefaultAdapter overrides this for imported (auth_type=default) integrations
        to handle all eight config-driven auth strategies.

        The API layer persists the ConnectResult's token fields and status; the
        adapter only returns what it found — it never writes to the DB here.
        """
        return ConnectResult(success=True)

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        """Refresh + persist credentials. Generic default is a no-op success."""
        return True

    #: Canonical card variable keys the combined booking+payment endpoints expect.
    #: These are forwarded in-memory to the vendor's PCI-certified gateway and
    #: must never be persisted or logged by Botelier.
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

    ``none``                      — no auth injected (public APIs)
    ``bearer``                    — ``Authorization: Bearer {access_token}``
    ``api_key_header``            — custom header with value from credentials
    ``api_key_query``             — query param with value from credentials
    ``custom_headers``            — multiple credential headers (multi-key APIs)
    ``basic``                     — ``Authorization: Basic base64(username:password)``
    ``login_endpoint``            — POST to a configured login endpoint, cache token
    ``oauth2_client_credentials`` — standard OAuth2 client_credentials grant

    Static strategies (none, bearer, api_key_header, api_key_query,
    custom_headers, basic) involve no token machinery — credentials are stored
    encrypted and injected per-request.  Token strategies (login_endpoint,
    oauth2_client_credentials) acquire a bearer at connect time, store it
    encrypted with an expiry, and auto-refresh before expiry via the shared
    cross-worker advisory-lock refresh path in IntegrationClient.

    No new vendor adapter subclass is needed for imported connectors; this
    class handles all config-driven strategies.
    """

    slug = None

    _TOKEN_STRATEGIES: frozenset = frozenset(
        {"login_endpoint", "oauth2_client_credentials"}
    )

    # ------------------------------------------------------------------
    # Runtime injection
    # ------------------------------------------------------------------

    def needs_token(
        self, credentials: dict, auth_config: Optional[dict] = None
    ) -> bool:
        """Token strategies require a managed bearer; static ones do not."""
        strategy = (auth_config or {}).get("auth_strategy", "bearer")
        return strategy in self._TOKEN_STRATEGIES

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

        if strategy in ("login_endpoint", "oauth2_client_credentials"):
            # Token strategies: use the encrypted access_token refreshed by the runtime.
            token = integration.get_access_token() or ""
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

        if strategy == "custom_headers":
            headers: dict[str, str] = {}
            for hdr in auth_config.get("headers") or []:
                header_name = hdr.get("header_name", "X-Custom-Header")
                cred_key = hdr.get("credential_key", "api_key")
                value = credentials.get(cred_key) or ""
                if value:
                    headers[header_name] = value
            return headers

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
        """Inject query-param auth according to ``auth_config["auth_strategy"]``.

        For ``basic`` strategy, ``basic_auth_query_params`` is a list of
        credential keys (e.g. ["apikey", "hotelId"]) whose values are appended
        as URL query parameters on every request alongside the Basic Auth header.
        """
        strategy = (auth_config or {}).get("auth_strategy", "bearer")
        if strategy == "api_key_query":
            param_name = (auth_config or {}).get("param_name", "api_key")
            key_field = (auth_config or {}).get("credential_key", "api_key")
            key_value = credentials.get(key_field) or credentials.get("api_key") or ""
            if key_value:
                return {param_name: key_value}
        if strategy == "basic":
            params: dict = {}
            for cred_key in (auth_config or {}).get("basic_auth_query_params") or []:
                val = credentials.get(cred_key)
                if val is not None:
                    params[cred_key] = str(val)
            return params
        return {}

    # ------------------------------------------------------------------
    # Connect-time lifecycle
    # ------------------------------------------------------------------

    async def connect(self, credentials: dict, auth_config: dict) -> ConnectResult:
        """Validate credentials and/or acquire a token at connect time.

        Static strategies validate that required credential fields are present
        and return success immediately — no outbound HTTP call needed.

        Token strategies perform a real acquisition call (login POST or OAuth2
        token grant) and return the token + expiry on success.  The API layer
        persists the token to the encrypted column; the adapter never writes to DB.
        """
        strategy = (auth_config or {}).get("auth_strategy", "bearer")

        if strategy == "none":
            return ConnectResult(success=True)

        if strategy == "bearer":
            token = credentials.get("access_token") or credentials.get("token") or ""
            if not str(token).strip():
                return ConnectResult(
                    success=False,
                    error="API token is required",
                    is_terminal=False,
                )
            return ConnectResult(success=True)

        if strategy in ("api_key_header", "api_key_query"):
            key_field = (auth_config or {}).get("credential_key", "api_key")
            key_value = credentials.get(key_field) or credentials.get("api_key") or ""
            if not str(key_value).strip():
                return ConnectResult(
                    success=False, error="API key is required", is_terminal=False
                )
            return ConnectResult(success=True)

        if strategy == "custom_headers":
            for hdr in (auth_config or {}).get("headers") or []:
                cred_key = hdr.get("credential_key", "api_key")
                if not str(credentials.get(cred_key) or "").strip():
                    label = hdr.get("header_name", cred_key)
                    return ConnectResult(
                        success=False,
                        error=f"Required credential for header '{label}' is missing",
                        is_terminal=False,
                    )
            return ConnectResult(success=True)

        if strategy == "basic":
            username = credentials.get("username") or credentials.get("client_id") or ""
            password = credentials.get("password") or credentials.get("client_secret") or ""
            if not str(username).strip():
                return ConnectResult(
                    success=False, error="Username is required", is_terminal=False
                )
            if not str(password).strip():
                return ConnectResult(
                    success=False, error="Password is required", is_terminal=False
                )
            return ConnectResult(success=True)

        if strategy == "login_endpoint":
            return await self._acquire_login_token(credentials, auth_config)

        if strategy == "oauth2_client_credentials":
            return await self._acquire_oauth2_cc_token(credentials, auth_config)

        # Unknown strategy — accept it (future strategy or passthrough)
        return ConnectResult(success=True)

    # ------------------------------------------------------------------
    # Token refresh (reuses same acquisition as connect)
    # ------------------------------------------------------------------

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        """Refresh an expired token for token-based strategies.

        Identical transient-vs-terminal contract as the OAuth2/GuestCentric
        adapters: a network blip keeps the integration CONNECTED so the NEXT
        request retries; a definitive provider rejection is TOKEN_EXPIRED.
        Static strategies return True immediately — no refresh needed.
        """
        from botelier.models.integration import IntegrationStatus

        auth_config = ctx.auth_config or {}
        strategy = auth_config.get("auth_strategy", "bearer")

        if strategy not in self._TOKEN_STRATEGIES:
            return True

        if strategy == "login_endpoint":
            result = await self._acquire_login_token(ctx.credentials, auth_config)
        else:
            result = await self._acquire_oauth2_cc_token(ctx.credentials, auth_config)

        integration = ctx.integration
        db = ctx.get_db_session()
        try:
            if result.success and result.access_token:
                integration.set_access_token(result.access_token)
                if result.refresh_token:
                    integration.set_refresh_token(result.refresh_token)
                if result.expires_in:
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=result.expires_in
                    )
                integration.status = IntegrationStatus.CONNECTED
                integration.last_error = None
                db.add(integration)
                db.commit()
                return True
            else:
                if result.is_terminal:
                    # Definitive provider rejection — re-connect required.
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                # else: keep CONNECTED so the next request auto-retries (transient).
                integration.last_error = (result.error or "Token refresh failed")[:500]
                db.add(integration)
                db.commit()
                return False
        finally:
            if ctx.owns_session:
                db.close()

    # ------------------------------------------------------------------
    # Internal acquisition helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_path_value(data: object, path: str) -> Optional[str]:
        """Extract a value from a nested dict using dot-notation or JSONPath prefix.

        Examples: "token", "data.token", "$.data.token", "$.access_token"
        """
        if not path or not isinstance(data, dict):
            return None
        # Strip JSONPath prefix: "$.data.token" → "data.token", ".token" → "token"
        clean = path.lstrip("$").strip(". ")
        if not clean:
            return None
        cur: object = data
        for part in clean.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        if cur is None:
            return None
        return str(cur)

    async def _acquire_login_token(
        self, credentials: dict, auth_config: dict
    ) -> ConnectResult:
        """POST credentials to the configured login endpoint and extract a bearer token.

        auth_config keys:
          base_url                    — server base URL
          login_endpoint_path         — path to POST to (e.g. /authentication/login)
          login_body_mapping          — {body_field: credential_key}, default username/password
          login_body_static_fields    — {body_field: static_value} always merged into body
          login_body_encoding         — "json" (default) or "form" (x-www-form-urlencoded)
          login_request_headers       — [{header_name, credential_key}] extra headers on login call
          auth_request_query_params   — [credential_key, ...] appended as URL query params
          token_response_path         — dot-path to token in response (default: "token")
          refresh_token_response_path — optional dot-path to refresh token
          token_expiry_seconds        — fallback TTL in seconds (default: 3600)
        """
        import httpx
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport

        base_url = (auth_config.get("base_url") or "").rstrip("/")
        endpoint_path = (auth_config.get("login_endpoint_path") or "").strip()

        if not base_url:
            return ConnectResult(
                success=False,
                error="Base URL is not configured for this integration",
                is_terminal=False,
            )
        if not endpoint_path:
            return ConnectResult(
                success=False,
                error="Login endpoint path is not configured — edit auth settings to set it",
                is_terminal=False,
            )
        if not endpoint_path.startswith("/"):
            endpoint_path = "/" + endpoint_path

        url = f"{base_url}{endpoint_path}"

        # --- Request body (credential-mapped + static fields) ---
        body_mapping: dict = auth_config.get("login_body_mapping") or {
            "username": "username",
            "password": "password",
        }
        body: dict = {}
        for body_key, cred_key in body_mapping.items():
            val = credentials.get(cred_key)
            if val is not None:
                body[body_key] = val
        for field_key, field_val in (auth_config.get("login_body_static_fields") or {}).items():
            if field_key and field_val is not None:
                body[field_key] = field_val

        # --- URL query params on the login call ---
        query_params: dict = {}
        for cred_key in (auth_config.get("auth_request_query_params") or []):
            val = credentials.get(cred_key)
            if val is not None:
                query_params[cred_key] = str(val)

        # --- Body encoding and extra headers ---
        encoding = (auth_config.get("login_body_encoding") or "json").lower()
        content_type = (
            "application/x-www-form-urlencoded" if encoding == "form" else "application/json"
        )
        request_headers: dict = {"Content-Type": content_type, "Accept": "application/json"}
        for hdr in (auth_config.get("login_request_headers") or []):
            hdr_name = (hdr.get("header_name") or "").strip()
            hdr_cred_key = (hdr.get("credential_key") or "").strip()
            if hdr_name and hdr_cred_key:
                val = credentials.get(hdr_cred_key)
                if val is not None:
                    request_headers[hdr_name] = str(val)

        token_path = auth_config.get("token_response_path") or "token"
        refresh_path = auth_config.get("refresh_token_response_path") or ""
        expiry_default = int(auth_config.get("token_expiry_seconds") or 3600)

        try:
            async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                if encoding == "form":
                    response = await client.post(
                        url,
                        data=body,
                        params=query_params or None,
                        headers=request_headers,
                        timeout=30.0,
                    )
                else:
                    response = await client.post(
                        url,
                        json=body,
                        params=query_params or None,
                        headers=request_headers,
                        timeout=30.0,
                    )
        except Exception as exc:
            # Network/timeout — transient; keep CONNECTED so next request retries.
            return ConnectResult(
                success=False,
                error=f"Could not reach login endpoint: {exc}",
                is_terminal=False,
            )

        if response.status_code == 200:
            try:
                data = response.json()
            except Exception:
                return ConnectResult(
                    success=False,
                    error="Login endpoint returned a non-JSON response",
                    is_terminal=True,
                )
            token = self._extract_path_value(data, token_path) or ""
            if not token:
                return ConnectResult(
                    success=False,
                    error=f"Token not found in response at path '{token_path}'",
                    is_terminal=True,
                )
            refresh_token = (
                self._extract_path_value(data, refresh_path) if refresh_path else None
            )
            try:
                expires_in = int(data.get("expires_in") or expiry_default)
            except (TypeError, ValueError):
                expires_in = expiry_default

            return ConnectResult(
                success=True,
                access_token=token,
                refresh_token=refresh_token,
                expires_in=expires_in,
            )

        elif response.status_code in (400, 401, 403):
            return ConnectResult(
                success=False,
                error=f"Login failed: credentials rejected by the API (HTTP {response.status_code})",
                is_terminal=True,
            )
        else:
            return ConnectResult(
                success=False,
                error=f"Login endpoint returned HTTP {response.status_code}",
                is_terminal=True,
            )

    async def _acquire_oauth2_cc_token(
        self, credentials: dict, auth_config: dict
    ) -> ConnectResult:
        """Standard OAuth2 client_credentials grant (RFC 6749 §4.4).

        auth_config keys:
          token_url  — full token endpoint URL (required)
          scope      — optional space-separated scope string
        """
        import httpx
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport

        token_url = (
            auth_config.get("token_url") or auth_config.get("token_endpoint") or ""
        ).strip()
        if not token_url:
            return ConnectResult(
                success=False,
                error="OAuth2 token URL is not configured — edit auth settings to set it",
                is_terminal=False,
            )

        client_id = credentials.get("client_id") or ""
        client_secret = credentials.get("client_secret") or ""
        if not client_id:
            return ConnectResult(
                success=False, error="Client ID is required", is_terminal=False
            )
        if not client_secret:
            return ConnectResult(
                success=False, error="Client Secret is required", is_terminal=False
            )

        form: dict = {"grant_type": "client_credentials"}
        scope = credentials.get("scope") or auth_config.get("scope") or ""
        if scope:
            form["scope"] = scope

        try:
            async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                response = await client.post(
                    token_url,
                    data=form,
                    auth=(client_id, client_secret),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    timeout=30.0,
                )
        except Exception as exc:
            return ConnectResult(
                success=False,
                error=f"Could not reach token endpoint: {exc}",
                is_terminal=False,
            )

        if response.status_code == 200:
            try:
                data = response.json()
            except Exception:
                return ConnectResult(
                    success=False,
                    error="Token endpoint returned a non-JSON response",
                    is_terminal=True,
                )
            token = data.get("access_token") or ""
            if not token:
                return ConnectResult(
                    success=False,
                    error="Token response missing access_token field",
                    is_terminal=True,
                )
            try:
                expires_in = int(data.get("expires_in") or 3600)
            except (TypeError, ValueError):
                expires_in = 3600

            return ConnectResult(
                success=True,
                access_token=token,
                refresh_token=data.get("refresh_token"),
                expires_in=expires_in,
            )

        elif response.status_code in (400, 401, 403):
            return ConnectResult(
                success=False,
                error=f"OAuth2 authentication failed: credentials rejected (HTTP {response.status_code})",
                is_terminal=True,
            )
        else:
            return ConnectResult(
                success=False,
                error=f"OAuth2 token endpoint returned HTTP {response.status_code}",
                is_terminal=True,
            )

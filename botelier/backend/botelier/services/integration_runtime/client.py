"""IntegrationClient runtime engine.

Extracted from the former ``integration_client`` monolith. Holds the per-request
execution flow, the cross-worker advisory-lock token refresh (holder/waiter), the
URL/header/body builders, response processing, and the LLM-friendly error mapper.

Vendor-specific behavior (Opera gateway validation + OAuth refresh, GuestCentric
basic/JWT auth + refresh) lives in ``adapters/``; this engine resolves the right
adapter per integration and calls its hooks, staying provider-agnostic.
"""

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy.orm import Session, joinedload

from botelier.models.integration import (
    AccountIntegration,
    IntegrationCallLog,
    IntegrationStatus,
)
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from .adapters import (
    GUESTCENTRIC_ADAPTER,
    OPERA_ADAPTER,
    RefreshContext,
    resolve_adapter,
)
from .jsonpath import extract_json_value
from .resilience import (
    ResilienceConfig,
    circuit_allow,
    circuit_record_failure,
    circuit_record_success,
    compute_backoff_delay,
    parse_retry_after,
    rate_limit_acquire,
)
from .locks import (
    _REFRESH_POLL_INTERVAL_S,
    _REFRESH_WAIT_TIMEOUT_S,
    _TOKEN_REFRESH_SKEW_S,
    _advisory_lock_key,
    _safe_close,
)
from .redaction import _sanitize_endpoint_for_log
from .types import (
    APIErrorType,
    APIResponse,
    IntegrationAPIConfig,
    ResponseVariable,
    _MissingRequiredVariables,
)

# Per-property isolation (Task #327). These keys identify which property a request
# is scoped to. Their value is authoritative from the connection's own
# connection_config and must never be overridden by caller/LLM-supplied variables,
# which could otherwise redirect a request to a different property's data. Only the
# singular identity keys are listed — multi-hotel selectors (e.g. a plural
# ``hotels`` array) are intentionally excluded so account-global connections can
# still let a flow choose among hotels.
PROPERTY_IDENTITY_KEYS = frozenset(
    {
        "hotel_id",
        "hotelId",
        "property_id",
        "propertyId",
        "hotel_code",
        "property_code",
    }
)

# Task #331 — only idempotent (safe) HTTP methods are retried on a 429/5xx
# response. Non-safe methods (POST/PUT/PATCH/DELETE) keep the historical
# retry-on-transport-error-only behavior so a write is never silently
# re-attempted after the server may have already applied it.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class IntegrationClient:
    def __init__(
        self, account_id: str, db: Session = None, property_id: Optional[str] = None
    ):
        self.account_id = account_id
        self._external_db = db
        # Per-property isolation (Task #327). Resolved once at contact start from
        # the dialed number / assistant and carried through the whole session.
        #   None  → legacy / no-property session: account-only scoping (allow all).
        #   set   → allow integrations bound to this property OR account-global
        #           (property_id NULL); fail closed on any other property.
        self.property_id = str(property_id) if property_id else None
        self._integration_cache: dict[str, AccountIntegration] = {}

    def _is_property_allowed(self, integration: AccountIntegration) -> bool:
        """Fail-closed per-property authorization for a resolved integration.

        Allowed when the session has no property (legacy), or the integration is
        account-global (property_id NULL), or the integration's property matches
        the session property. Any other case is a cross-property access and is
        rejected without issuing the outbound HTTP request.

        Delegates to the shared ``property_access_allowed`` predicate so the
        certified-integration path and the capability resolver enforce one
        identical fail-closed rule.
        """
        from botelier.services.property_scope import property_access_allowed

        return property_access_allowed(
            self.property_id, getattr(integration, "property_id", None)
        )

    def _get_db_session(self) -> Session:
        if self._external_db:
            return self._external_db
        from botelier.database import SessionLocal

        return SessionLocal()

    async def execute_request(
        self, config: IntegrationAPIConfig, variables: dict[str, Any]
    ) -> APIResponse:
        start_ms = int(time.time() * 1000)

        integration = await self._get_integration(config.integration_id)
        if not integration:
            self._write_call_log(
                integration_id=config.integration_id,
                endpoint_called=config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=0,
                error_type=APIErrorType.AUTH_ERROR.value,
                error_message="Integration not found or not connected",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message="Integration not found or not connected",
            )

        # Per-property isolation (Task #327) — fail closed BEFORE any outbound
        # request or credential use if this integration belongs to a different
        # property than the one resolved for this session.
        if not self._is_property_allowed(integration):
            logger.warning(
                "cross-property access rejected: integration "
                f"{integration.id} (property {getattr(integration, 'property_id', None)}) "
                f"requested by session property {self.property_id} "
                f"(account {self.account_id})"
            )
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=0,
                error_type=APIErrorType.AUTH_ERROR.value,
                error_message="Cross-property access rejected",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message="Cross-property access rejected",
            )

        if integration.status != IntegrationStatus.CONNECTED:
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=0,
                error_type=APIErrorType.AUTH_ERROR.value,
                error_message=f"Integration is not connected (status: {integration.status.value})",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message=f"Integration is not connected (status: {integration.status.value})",
            )

        credentials = integration.get_credentials()
        adapter = self._resolve_adapter(integration)

        auth_config_data = integration.integration_type.get_auth_config() or {}
        needs_token = adapter.needs_token(credentials, auth_config=auth_config_data)

        if needs_token and self._token_needs_refresh(integration):
            refresh_success = await self._refresh_token_with_lock(integration)
            if not refresh_success:
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=config.path,
                    method=config.method,
                    status_code=0,
                    success=False,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=APIErrorType.AUTH_ERROR.value,
                    error_message="Failed to refresh authentication token",
                )
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.AUTH_ERROR,
                    error_message="Failed to refresh authentication token",
                )

        endpoint_def = self._resolve_endpoint(integration, config)
        effective_vars = self._apply_endpoint_defaults(variables, endpoint_def, integration)
        try:
            url = self._build_url(integration, config, effective_vars, endpoint_def)
        except _MissingRequiredVariables as exc:
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=config.endpoint_template or config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=int(time.time() * 1000) - start_ms,
                error_type=APIErrorType.VALIDATION_ERROR.value,
                error_message=str(exc)[:500],
            )
            missing_names = ", ".join(exc.names) if exc.names else str(exc)
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.VALIDATION_ERROR,
                error_message=(
                    f"Required information not yet collected: {missing_names}. "
                    "Ask the caller to provide this information, then try again."
                ),
            )
        headers = self._build_headers(integration, config)
        body = self._build_body(config, effective_vars, endpoint_def)
        effective_response_vars = self._effective_response_variables(config, endpoint_def)
        log_endpoint = config.endpoint_template or config.path

        # --- Task #331: cross-worker resilience gates ------------------------
        # Resolved from the integration's auth_config / connection_config, with
        # generous defaults so a healthy single connection is never throttled.
        # Both gates run AFTER property/status/token checks and after _build_url
        # so a rejected (cross-property, unconnected, malformed) request never
        # touches the shared breaker/limiter state.
        rconf = ResilienceConfig.from_integration(integration)

        # Circuit breaker: short-circuit a provider we already know is failing so
        # the caller gets a fast, LLM-friendly "temporarily unavailable" instead
        # of waiting on a request that is almost certain to fail.
        allowed, _cstate = circuit_allow(integration.id, self.account_id, rconf)
        if not allowed:
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=log_endpoint,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=int(time.time() * 1000) - start_ms,
                error_type=APIErrorType.CIRCUIT_OPEN.value,
                error_message="Circuit open: provider temporarily unavailable",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.CIRCUIT_OPEN,
                error_message="Circuit open: provider temporarily unavailable",
            )

        # Rate limiter: consume one token from this integration's bucket.
        if not rate_limit_acquire(integration.id, self.account_id, rconf):
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=log_endpoint,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=int(time.time() * 1000) - start_ms,
                error_type=APIErrorType.RATE_LIMITED.value,
                error_message="Rate limit exceeded for this integration",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.RATE_LIMITED,
                error_message="Rate limit exceeded for this integration",
            )

        attempt = 0
        last_error: Optional[Exception] = None
        safe_method = config.method.upper() in _SAFE_METHODS
        # One-shot flag: allow a single forced token refresh + retry on 401/403
        # for integrations whose auth strategy acquires a bearer token at connect
        # time (login_endpoint / oauth2_client_credentials). Certified adapters
        # already handle this via their own refresh_credentials path.
        _auth_refresh_attempted = False

        while attempt <= config.retry_count:
            try:
                response = await self._make_request(
                    method=config.method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout=config.timeout,
                )

                result = self._process_response(response, config, effective_response_vars)

                # On 401/403: if this is a DefaultAdapter token strategy and we
                # haven't retried yet, force-refresh the token and retry once.
                if (
                    result.status_code in (401, 403)
                    and not _auth_refresh_attempted
                    and auth_config_data.get("auth_strategy") in ("login_endpoint", "oauth2_client_credentials")
                ):
                    _auth_refresh_attempted = True
                    logger.info(
                        f"Token auth 401 for integration {integration.id}; "
                        "forcing refresh and retrying once."
                    )
                    refresh_ok = await self._refresh_token_with_lock(integration)
                    if refresh_ok:
                        fresh = self._read_integration_fresh(integration.id)
                        if fresh is not None:
                            self._sync_cached_integration(integration, fresh)
                        headers = self._build_headers(integration, config)
                    continue

                # Retry throttling (429) and transient server errors (5xx), but
                # only for idempotent methods so a write is never re-applied.
                retryable_status = result.status_code == 429 or result.status_code >= 500
                if retryable_status and safe_method and attempt < config.retry_count:
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))
                    delay = compute_backoff_delay(attempt, rconf, retry_after=retry_after)
                    logger.warning(
                        f"Retryable status {result.status_code} "
                        f"(attempt {attempt + 1}/{config.retry_count + 1}); "
                        f"backing off {delay:.2f}s: {log_endpoint}"
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                self._apply_canonical(result, adapter, endpoint_def)
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=log_endpoint,
                    method=config.method,
                    status_code=result.status_code,
                    success=result.success,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=None if result.success else result.error_type.value,
                    error_message=None if result.success else (result.error_message or "")[:500],
                )
                # One logical execute_request == one breaker outcome. A 429/5xx
                # (even after exhausting retries) is a provider failure; any
                # response the provider actually produced (2xx, or a 4xx client
                # error like auth/not-found/validation) proves the vendor is up
                # and resets the breaker.
                if retryable_status:
                    circuit_record_failure(integration.id, self.account_id, rconf)
                else:
                    circuit_record_success(integration.id, self.account_id, rconf)
                return result

            except httpx.TimeoutException:
                logger.warning(
                    f"Request timeout (attempt {attempt + 1}/{config.retry_count + 1}): {url}"
                )
                last_error = httpx.TimeoutException(f"Request timed out after {config.timeout}s")
                attempt += 1
                if attempt <= config.retry_count:
                    await asyncio.sleep(compute_backoff_delay(attempt - 1, rconf))

            except httpx.NetworkError as e:
                logger.warning(
                    f"Network error (attempt {attempt + 1}/{config.retry_count + 1}): {e}"
                )
                last_error = e
                attempt += 1
                if attempt <= config.retry_count:
                    await asyncio.sleep(compute_backoff_delay(attempt - 1, rconf))

            except Exception as e:
                # An unexpected error here is almost certainly our own bug, not a
                # vendor outage — do NOT trip the breaker on it.
                logger.error(f"Unexpected error during API request: {e}")
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=log_endpoint,
                    method=config.method,
                    status_code=0,
                    success=False,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=APIErrorType.UNKNOWN.value,
                    error_message=str(e)[:500],
                )
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.UNKNOWN,
                    error_message=str(e),
                )

        # Exhausted retries on transport failure — this is a provider outage.
        circuit_record_failure(integration.id, self.account_id, rconf)
        error_type = (
            APIErrorType.TIMEOUT
            if isinstance(last_error, httpx.TimeoutException)
            else APIErrorType.NETWORK_ERROR
        )
        self._write_call_log(
            integration_id=str(integration.id),
            endpoint_called=url,
            method=config.method,
            status_code=0,
            success=False,
            latency_ms=int(time.time() * 1000) - start_ms,
            error_type=error_type.value,
            error_message=str(last_error)[:500] if last_error else "Request failed after retries",
        )
        return APIResponse(
            success=False,
            status_code=0,
            error_type=error_type,
            error_message=str(last_error) if last_error else "Request failed after retries",
        )

    def _write_call_log(
        self,
        integration_id: Optional[str],
        endpoint_called: Optional[str],
        method: str,
        status_code: int,
        success: bool,
        latency_ms: int,
        error_type: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Write an IntegrationCallLog row fire-and-forget; never raises."""
        try:
            db = self._get_db_session()
            try:
                log = IntegrationCallLog(
                    id=uuid.uuid4(),
                    account_id=self.account_id,
                    integration_id=integration_id,
                    endpoint_called=_sanitize_endpoint_for_log(endpoint_called),
                    method=method,
                    status_code=status_code,
                    success=success,
                    latency_ms=latency_ms,
                    error_type=error_type,
                    error_message=error_message,
                    called_at=datetime.utcnow(),
                )
                db.add(log)
                db.commit()
            finally:
                if not self._external_db:
                    db.close()
        except Exception as exc:
            logger.warning(f"Failed to write integration call log (non-fatal): {exc}")

    async def _get_integration(self, integration_id: str) -> Optional[AccountIntegration]:
        if integration_id in self._integration_cache:
            return self._integration_cache[integration_id]

        db = self._get_db_session()
        try:
            integration = (
                db.query(AccountIntegration)
                .options(joinedload(AccountIntegration.integration_type))
                .filter(
                    AccountIntegration.id == integration_id,
                    AccountIntegration.account_id == self.account_id,
                )
                .first()
            )

            if integration:
                self._integration_cache[integration_id] = integration

            return integration
        finally:
            if not self._external_db:
                db.close()

    def _token_needs_refresh(self, integration: AccountIntegration) -> bool:
        """True when the access token is expired or within the proactive skew.

        Refreshing slightly before hard expiry avoids issuing a request that
        races the expiry boundary and comes back 401 mid-call.
        """
        if integration.token_expires_at is None:
            return True
        return datetime.utcnow() >= integration.token_expires_at - timedelta(
            seconds=_TOKEN_REFRESH_SKEW_S
        )

    def _read_integration_fresh(self, integration_id) -> Optional[AccountIntegration]:
        """Read the integration row in its own short-lived session.

        Always uses a fresh SessionLocal() (never the cached object or an
        external session) so it observes token updates committed by another
        worker under READ COMMITTED. integration_type is eager-loaded so the
        returned (detached) object is safe to read after the session closes.
        """
        from botelier.database import SessionLocal

        db = SessionLocal()
        try:
            return (
                db.query(AccountIntegration)
                .options(joinedload(AccountIntegration.integration_type))
                .filter(
                    AccountIntegration.id == integration_id,
                    AccountIntegration.account_id == self.account_id,
                )
                .first()
            )
        finally:
            db.close()

    def _sync_cached_integration(
        self, cached: AccountIntegration, fresh: AccountIntegration
    ) -> None:
        """Copy refreshed token state from a fresh row onto the cached object.

        Only scalar token columns are copied — never the integration_type
        relationship — so the eagerly-loaded relationship on the cached object
        is preserved and no lazy load fires on a detached instance. Without
        this, execute_request would keep sending the stale cached token.
        """
        cached.access_token_encrypted = fresh.access_token_encrypted
        cached.refresh_token_encrypted = fresh.refresh_token_encrypted
        cached.token_expires_at = fresh.token_expires_at
        cached.status = fresh.status

    async def _refresh_token_with_lock(self, integration: AccountIntegration) -> bool:
        """Refresh an expired/expiring token, serialized across all workers.

        A single expired token under concurrent load would otherwise trigger one
        provider login per in-flight request — wasteful, and unsafe for providers
        that rotate the refresh_token on use. We serialize per AccountIntegration
        row with a Postgres advisory lock shared across every stateless replica:

          • Holder  — the worker that wins pg_try_advisory_lock re-reads the row
                      (another worker may have refreshed while it contended) and,
                      if still stale, performs the actual refresh.
          • Waiters — every other worker polls the row until the token is fresh
                      or the refresh is seen to have failed, WITHOUT holding a DB
                      connection while it waits (avoids pool exhaustion under a
                      burst; the provider HTTP call can take tens of seconds).

        The lock is held on a dedicated raw connection — never on the refresh's
        ORM session, whose commit would return its connection to the pool and
        strand a session-level lock. Any lock-infrastructure failure degrades
        gracefully to an unlocked refresh (the pre-existing behavior).
        """
        from sqlalchemy import text as _sql_text

        from botelier.database import engine

        lock_key = _advisory_lock_key(integration.id)

        try:
            conn = engine.connect()
        except Exception as exc:
            logger.warning(
                f"Token refresh: could not open lock connection for integration "
                f"{integration.id} ({exc}); refreshing without cross-worker lock."
            )
            return await self._refresh_token(integration)

        try:
            acquired = conn.execute(
                _sql_text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}
            ).scalar()
        except Exception as exc:
            logger.warning(
                f"Token refresh: advisory-lock acquire failed for integration "
                f"{integration.id} ({exc}); refreshing without cross-worker lock."
            )
            _safe_close(conn)
            return await self._refresh_token(integration)

        if acquired:
            try:
                fresh = self._read_integration_fresh(integration.id)
                if fresh is not None:
                    if (
                        fresh.status == IntegrationStatus.CONNECTED
                        and not self._token_needs_refresh(fresh)
                    ):
                        # Another worker refreshed while we contended for the lock.
                        self._sync_cached_integration(integration, fresh)
                        return True
                    # Adopt the freshest row before refreshing so a rotate-on-use
                    # provider doesn't reuse a refresh token already spent by
                    # another worker since this client cached the integration.
                    self._sync_cached_integration(integration, fresh)
                return await self._refresh_token(integration)
            finally:
                try:
                    conn.execute(
                        _sql_text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key}
                    )
                except Exception as exc:
                    # A stranded lock would block ALL future refreshes for this
                    # connection until the pooled conn recycles — hard-drop it.
                    logger.error(
                        f"Token refresh: advisory-unlock failed for integration "
                        f"{integration.id} ({exc}); invalidating connection."
                    )
                    conn.invalidate()
                finally:
                    _safe_close(conn)

        # Waiter path — release the connection immediately, then poll the row.
        _safe_close(conn)

        deadline = time.monotonic() + _REFRESH_WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(_REFRESH_POLL_INTERVAL_S)
            fresh = self._read_integration_fresh(integration.id)
            if fresh is None:
                continue
            if (
                fresh.status == IntegrationStatus.CONNECTED
                and not self._token_needs_refresh(fresh)
            ):
                self._sync_cached_integration(integration, fresh)
                return True
            if fresh.status in (
                IntegrationStatus.TOKEN_EXPIRED,
                IntegrationStatus.ERROR,
            ):
                logger.warning(
                    f"Token refresh: holder failed to refresh integration "
                    f"{integration.id} (status={fresh.status.value})."
                )
                return False

        logger.warning(
            f"Token refresh: timed out waiting for another worker to refresh "
            f"integration {integration.id}."
        )
        return False

    def _resolve_adapter(self, integration: AccountIntegration):
        """Resolve the vendor adapter for this integration (slug → auth_type → default)."""
        itype = integration.integration_type
        slug = getattr(itype, "slug", None)
        auth_type = getattr(itype, "auth_type", None)
        return resolve_adapter(slug, auth_type)

    def _build_refresh_context(
        self, integration: AccountIntegration, credentials: dict, auth_config: dict
    ) -> RefreshContext:
        return RefreshContext(
            integration=integration,
            credentials=credentials,
            auth_config=auth_config,
            get_db_session=self._get_db_session,
            owns_session=not self._external_db,
        )

    async def _refresh_token(self, integration: AccountIntegration) -> bool:
        credentials = integration.get_credentials()
        auth_config = integration.integration_type.get_auth_config()
        adapter = self._resolve_adapter(integration)
        ctx = self._build_refresh_context(integration, credentials, auth_config)
        return await adapter.refresh_credentials(ctx)

    async def _refresh_oauth_token(
        self, integration: AccountIntegration, credentials: dict, auth_config: dict
    ) -> bool:
        """Delegate OAuth2 (client-credentials / refresh-token) refresh to the
        Opera adapter. Stable private entry point for callers/tests that trigger
        an OAuth refresh directly with explicit credentials."""
        ctx = self._build_refresh_context(integration, credentials, auth_config)
        return await OPERA_ADAPTER.refresh_oauth(ctx)

    async def _refresh_jwt_token(
        self, integration: AccountIntegration, credentials: dict, auth_config: dict
    ) -> bool:
        """Delegate JWT login/refresh to the GuestCentric adapter. Stable private
        entry point for callers/tests that trigger a JWT refresh directly with
        explicit credentials."""
        ctx = self._build_refresh_context(integration, credentials, auth_config)
        return await GUESTCENTRIC_ADAPTER.refresh_jwt(ctx)

    def _resolve_endpoint(
        self, integration: AccountIntegration, config: IntegrationAPIConfig
    ) -> Optional[dict]:
        """Return the certified endpoint definition for config.endpoint_id, if any."""
        if not config.endpoint_id:
            return None
        try:
            endpoints = integration.integration_type.get_endpoints() or []
        except Exception:
            return None
        for endpoint in endpoints:
            if endpoint.get("id") == config.endpoint_id:
                return endpoint
        return None

    def _apply_endpoint_defaults(
        self,
        variables: dict[str, Any],
        endpoint_def: Optional[dict],
        integration: Optional["AccountIntegration"] = None,
    ) -> dict[str, Any]:
        """Merge certified-endpoint variable defaults under caller-provided values.

        Priority (lowest → highest):
        1. Integration connection_config — property-level constants set once per
           connection (e.g. hotel_id, hotel_name, hotel_reservations_email,
           default currency). Stored by the operator when connecting the integration;
           eliminates the need to collect static values from callers each turn.
        2. Endpoint variable defaults (e.g. ``today`` sentinel for arrival dates).
        3. Caller-provided variables (``collected_slots`` from the live flow).
        4. Per-property identity keys (Task #327) — re-forced from connection_config
           ON TOP of caller values so a caller/LLM cannot redirect the request to a
           different property by supplying its own hotel_id/property_id.
        """
        merged: dict[str, Any] = {}
        conn_config: dict[str, Any] = {}
        # 1. Integration connection_config — lowest priority so any explicit value wins
        if integration:
            try:
                conn_config = integration.get_connection_config() or {}
                merged.update(conn_config)
            except Exception:
                conn_config = {}
        # 2. Endpoint-declared variable defaults
        for var in (endpoint_def or {}).get("variables") or []:
            key = var.get("key")
            default = var.get("default")
            if not key or default is None:
                continue
            # "today" is a sentinel default — resolve it to the current date so
            # required date params (e.g. arrivals) are satisfied when no caller
            # value is supplied, instead of being dropped.
            if default == "today":
                merged[key] = datetime.utcnow().date().isoformat()
            else:
                merged[key] = default
        # 3. Caller-provided variables are highest priority
        merged.update(variables or {})
        # 4. Per-property isolation (Task #327): property-identity keys are
        #    authoritative from this connection's connection_config and must NOT be
        #    overridable by caller/LLM-supplied values. Force them back on top so a
        #    supplied hotel_id/property_id can never redirect the call to another
        #    property's data. Only keys actually present in connection_config are
        #    forced, so account-global connections that legitimately let the flow
        #    choose a hotel are unaffected.
        for key in PROPERTY_IDENTITY_KEYS:
            if conn_config.get(key) is not None:
                merged[key] = conn_config[key]
        return merged

    def _effective_response_variables(
        self, config: IntegrationAPIConfig, endpoint_def: Optional[dict]
    ) -> list[ResponseVariable]:
        """Response-extraction precedence: explicit node vars, else certified mapping."""
        if config.response_variables:
            return config.response_variables
        if endpoint_def:
            mapping = endpoint_def.get("response_mapping") or {}
            return [
                ResponseVariable(variable_key=key, json_path=path)
                for key, path in mapping.items()
            ]
        return []

    def _build_url(
        self,
        integration: AccountIntegration,
        config: IntegrationAPIConfig,
        variables: dict[str, Any],
        endpoint_def: Optional[dict] = None,
    ) -> str:
        credentials = integration.get_credentials()
        try:
            conn_config = integration.get_connection_config() or {}
        except Exception:
            conn_config = {}
        auth_config = integration.integration_type.get_auth_config()
        adapter = self._resolve_adapter(integration)

        base_url = adapter.resolve_base_url(auth_config, credentials)

        path = config.path
        if endpoint_def:
            path = endpoint_def.get("path", path)

        path = self._substitute_variables(path, variables)

        # Resolve the property-level hotel id for path templates. Prefer the
        # non-secret connection_config (where connections now store it) and fall
        # back to the encrypted credentials blob for legacy connections that saved
        # it there. Both snake_case and camelCase keys are accepted so the seed
        # field key "hotelId" bridges to the "{{hotel_id}}" path placeholder.
        hotel_id = (
            conn_config.get("hotel_id")
            or conn_config.get("hotelId")
            or credentials.get("hotel_id")
            or credentials.get("hotelId")
        )
        if hotel_id:
            # Double-brace forms MUST be replaced before single-brace forms:
            # "{{hotel_id}}" contains "{hotel_id}" as a substring, so a single-
            # brace replace run first would corrupt it to "{value}" (leaving the
            # outer braces). Order double → single so whole placeholders resolve.
            path = path.replace("{{hotelId}}", hotel_id)
            path = path.replace("{{hotel_id}}", hotel_id)
            path = path.replace("{hotelId}", hotel_id)
            path = path.replace("{hotel_id}", hotel_id)

        # Fail fast: any {{var}} still in the path after all substitutions means a
        # required value (e.g. hotel_id) was never resolved — either missing from
        # credentials/connection_config or not collected by the flow.  Raising here
        # surfaces a clear "Missing required variables: hotel_id" error instead of
        # forwarding a malformed URL to the upstream API and getting a cryptic 422.
        unresolved_in_path = re.findall(r"\{\{(\w+)\}\}", path)
        if unresolved_in_path:
            raise _MissingRequiredVariables(unresolved_in_path)

        url = f"{base_url}{path}"

        # Certified endpoints declare query params separately from the path.
        # Render them with call variables; omit unresolved optional params but
        # fail fast when a required param cannot be resolved.
        if endpoint_def:
            rendered_params: dict[str, str] = {}
            missing_required: list[str] = []
            overrides = config.query_param_overrides or {}
            for qp in endpoint_def.get("query_params") or []:
                key = qp.get("key")
                if not key:
                    continue
                # Node-level override wins over the seed default template. An
                # empty-string override intentionally blanks the param; for a
                # required param that still fails fast below (fails closed).
                template = overrides[key] if key in overrides else qp.get("value", "")
                rendered = self._substitute_variables(str(template), variables)
                if rendered == "" or "{{" in rendered:
                    if qp.get("required"):
                        missing_required.append(key)
                    continue
                rendered_params[key] = rendered
            if missing_required:
                raise _MissingRequiredVariables(missing_required)
            if rendered_params:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}{urlencode(rendered_params)}"

        auth_query_params = adapter.build_auth_query_params(
            auth_config, credentials, conn_config
        )
        if auth_query_params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(auth_query_params)}"

        return url

    def _build_headers(
        self, integration: AccountIntegration, config: IntegrationAPIConfig
    ) -> dict[str, str]:
        credentials = integration.get_credentials()
        adapter = self._resolve_adapter(integration)

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(adapter.build_auth_headers(integration, credentials))

        if config.headers:
            headers.update(config.headers)

        return headers

    def _build_body(
        self,
        config: IntegrationAPIConfig,
        variables: dict[str, Any],
        endpoint_def: Optional[dict] = None,
    ) -> Optional[dict]:
        body_template = config.body_template
        if not body_template and endpoint_def:
            seed_body = endpoint_def.get("body_template")
            if seed_body is not None:
                body_template = (
                    seed_body if isinstance(seed_body, str) else json.dumps(seed_body)
                )

        if not body_template:
            return None

        body_str = self._substitute_variables(body_template, variables)

        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            # NEVER log the rendered body — it may contain card data or other
            # secrets substituted from variables (Task #339). Log only the safe
            # endpoint identity so the failure is still diagnosable.
            logger.error(
                "Failed to parse rendered request body as JSON "
                f"(integration={getattr(config, 'integration_id', '?')} "
                f"endpoint={getattr(config, 'endpoint_id', '?')})"
            )
            return None

    def _substitute_variables(self, template: str, variables: dict[str, Any]) -> str:
        def replace_var(match):
            var_name = match.group(1)
            value = variables.get(var_name)
            if value is None:
                return match.group(0)
            return str(value)

        return re.sub(r"\{\{(\w+)\}\}", replace_var, template)

    async def _make_request(
        self, method: str, url: str, headers: dict, body: Optional[dict], timeout: int
    ) -> httpx.Response:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            if method.upper() == "GET":
                return await client.get(url, headers=headers, timeout=timeout)
            elif method.upper() == "POST":
                return await client.post(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "PUT":
                return await client.put(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "PATCH":
                return await client.patch(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "DELETE":
                return await client.delete(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

    def _apply_canonical(
        self,
        result: APIResponse,
        adapter,
        endpoint_def: Optional[dict],
    ) -> None:
        """Attach the vendor-agnostic canonical envelope to a successful result.

        Opt-in: only endpoints tagged with a ``canonical_entity`` in their seed are
        normalized, and only on success. The adapter owns the vendor-specific
        mapping. Normalization is best-effort and fully isolated — a normalizer
        that raises or returns None simply leaves ``result.canonical`` as None; it
        can never break the underlying request or its per-endpoint mapping.
        """
        if not result.success or not endpoint_def:
            return
        entity = endpoint_def.get("canonical_entity")
        if not entity:
            return
        try:
            result.canonical = adapter.normalize(entity, endpoint_def.get("id"), result.data)
        except Exception:
            logger.exception(
                f"Canonical normalization raised for entity={entity} "
                f"endpoint={endpoint_def.get('id')}; leaving canonical unset"
            )
            result.canonical = None

    def _process_response(
        self,
        response: httpx.Response,
        config: IntegrationAPIConfig,
        response_variables: Optional[list[ResponseVariable]] = None,
    ) -> APIResponse:
        status_code = response.status_code

        if response_variables is None:
            response_variables = config.response_variables

        try:
            data = response.json()
        except json.JSONDecodeError:
            data = response.text

        if 200 <= status_code < 300:
            extracted = self._extract_variables(data, response_variables)
            return APIResponse(
                success=True,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.SUCCESS,
                extracted_variables=extracted,
            )

        elif status_code == 401 or status_code == 403:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.AUTH_ERROR,
                error_message=config.on_auth_error_message,
            )

        elif status_code == 404:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.NOT_FOUND,
                error_message=config.on_not_found_message,
            )

        elif status_code == 400 or status_code == 422:
            error_detail = self._extract_error_message(data)
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.VALIDATION_ERROR,
                error_message=error_detail or config.on_error_message,
            )

        elif status_code >= 500:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.SERVER_ERROR,
                error_message=config.on_error_message,
            )

        else:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.UNKNOWN,
                error_message=config.on_error_message,
            )

    def _extract_variables(
        self, data: Any, response_variables: list[ResponseVariable]
    ) -> dict[str, Any]:
        extracted = {}

        for rv in response_variables:
            value = self._extract_json_value(data, rv.json_path)
            if value is not None:
                extracted[rv.variable_key] = value
            elif rv.default_value is not None:
                extracted[rv.variable_key] = rv.default_value

        return extracted

    def _extract_json_value(self, data: Any, path: str) -> Any:
        return extract_json_value(data, path)

    def _extract_error_message(self, data: Any) -> Optional[str]:
        if isinstance(data, dict):
            for key in ["message", "error", "detail", "error_description", "errorMessage"]:
                if key in data:
                    return str(data[key])
            if "errors" in data and isinstance(data["errors"], list):
                return "; ".join(str(e.get("message", e)) for e in data["errors"][:3])

        return None


def get_llm_friendly_error_message(response: APIResponse, config: IntegrationAPIConfig) -> str:
    if response.success:
        return config.on_success_message

    if response.error_type == APIErrorType.AUTH_ERROR:
        return "I'm having trouble connecting to our system right now. Let me transfer you to someone who can help."

    elif response.error_type == APIErrorType.NOT_FOUND:
        return config.on_not_found_message

    elif response.error_type == APIErrorType.VALIDATION_ERROR:
        if response.error_message:
            return f"There was an issue with the information provided: {response.error_message}"
        return "The information provided doesn't match what we need. Could you please verify and try again?"

    elif response.error_type == APIErrorType.SERVER_ERROR:
        return (
            "Our system is experiencing some difficulties right now. Please try again in a moment."
        )

    elif response.error_type == APIErrorType.TIMEOUT:
        return "I'm taking a bit longer than expected to look that up. Please hold on."

    elif response.error_type == APIErrorType.NETWORK_ERROR:
        return "I'm having trouble connecting to our system. Let me try again."

    return config.on_error_message

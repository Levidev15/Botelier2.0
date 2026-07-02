import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from loguru import logger
from sqlalchemy.orm import Session, joinedload

from botelier.models.integration import (
    AccountIntegration,
    IntegrationCallLog,
    IntegrationStatus,
    IntegrationType,
)
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

# Accepted Oracle hostname suffixes for the OHIP gateway URL.
# Production environments end in .oraclecloud.com or .oracle.com.
# Oracle's self-service sandbox environments end in .ocs.oc-test.com
# (e.g. *.hospitality-api.<region>.ocs.oc-test.com).
_ORACLE_ALLOWED_SUFFIXES = (
    ".oraclecloud.com",
    ".oracle.com",
    ".ocs.oc-test.com",
)


def _validate_opera_gateway_url(gateway_url: str) -> None:
    """Raise ValueError if gateway_url is not a valid Oracle Cloud hostname."""
    if not gateway_url:
        raise ValueError("gateway_url is required")
    try:
        parsed = urlparse(gateway_url)
    except Exception:
        raise ValueError("Invalid gateway_url")
    if parsed.scheme != "https":
        raise ValueError("gateway_url must use HTTPS")
    hostname = (parsed.hostname or "").lower()
    if not any(hostname.endswith(suffix) for suffix in _ORACLE_ALLOWED_SUFFIXES):
        raise ValueError(
            "gateway_url must be an Oracle Cloud hostname "
            "(*.oraclecloud.com, *.oracle.com, or *.ocs.oc-test.com for sandbox)"
        )


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
    response_variables: list[ResponseVariable] = field(default_factory=list)
    on_success_message: str = "Request completed successfully"
    on_error_message: str = "There was an issue processing your request"
    on_not_found_message: str = "The requested information was not found"
    on_auth_error_message: str = "There was an authentication issue with the system"


def extract_json_value(data: Any, path: str) -> Any:
    """Extract a value from parsed JSON using a small JSONPath dialect.

    Shared by IntegrationClient and the flow executor so every integration and
    flow node resolves response paths identically.

    Supported syntax:
      - ``$`` / ``$.`` root prefix (optional)
      - dot keys: ``a.b.c``
      - bracket index: ``a[0].b``
      - legacy dot index: ``a.0.b``
      - wildcard: ``a[*].b`` expands across list elements and flattens

    Returns a single value when the path has no wildcard, or a flattened list
    (order-preserving, deduped) when a wildcard is used. ``None`` is returned
    when the path resolves to nothing, so callers can apply default values.
    """
    if not path:
        return data

    if path.startswith("$"):
        path = path[1:]
    # Normalize bracket segments into dot segments so a single split handles
    # ``a[0].b`` and ``a[*].b`` alongside ``a.b`` and legacy ``a.0.b``.
    normalized = path.replace("[", ".[")
    parts = [p for p in normalized.split(".") if p != ""]

    # The "frontier" is the set of live values being resolved. A wildcard
    # expands it; every other token narrows each entry to a single child.
    frontier: list[Any] = [data]
    used_wildcard = False

    for part in parts:
        if part == "[*]":
            used_wildcard = True
            expanded: list[Any] = []
            for item in frontier:
                if isinstance(item, list):
                    expanded.extend(item)
            frontier = expanded
            continue

        index: Optional[int] = None
        if part.startswith("[") and part.endswith("]"):
            inner = part[1:-1]
            index = int(inner) if inner.isdigit() else None
        elif part.isdigit():
            index = int(part)

        next_frontier: list[Any] = []
        for item in frontier:
            if index is not None:
                if isinstance(item, list) and 0 <= index < len(item):
                    next_frontier.append(item[index])
            elif isinstance(item, dict):
                child = item.get(part)
                if child is not None:
                    next_frontier.append(child)
        frontier = next_frontier

    results = [v for v in frontier if v is not None]

    if used_wildcard:
        deduped: list[Any] = []
        for v in results:
            if v not in deduped:
                deduped.append(v)
        return deduped or None

    return results[0] if results else None


def _advisory_lock_key(integration_id) -> int:
    """Derive a stable signed 64-bit Postgres advisory-lock key for a connection.

    Python's built-in hash() is randomized per process (PYTHONHASHSEED), so it
    would produce a different key on every replica and the lock would serialize
    nothing.  We use a namespaced BLAKE2b digest of the integration UUID so the
    key is identical across all workers, and reserve the namespace prefix in
    case advisory locks are used for other purposes later.
    """
    if isinstance(integration_id, uuid.UUID):
        id_bytes = integration_id.bytes
    else:
        id_bytes = uuid.UUID(str(integration_id)).bytes
    digest = hashlib.blake2b(
        b"integ-token-refresh:" + id_bytes, digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _safe_close(conn) -> None:
    """Return a raw connection to the pool, swallowing any close error."""
    try:
        conn.close()
    except Exception:
        pass


# Proactively refresh a token this many seconds BEFORE its hard expiry so a
# request never races the expiry boundary and comes back 401 mid-call.
_TOKEN_REFRESH_SKEW_S = 60

# Waiter (non-holder) settings for the cross-worker refresh lock. The timeout
# comfortably exceeds a normal provider login while a burst of waiters poll the
# row (rather than each pinning a DB connection) until the holder finishes.
_REFRESH_WAIT_TIMEOUT_S = 45.0
_REFRESH_POLL_INTERVAL_S = 0.2


class IntegrationClient:
    def __init__(self, account_id: str, db: Session = None):
        self.account_id = account_id
        self._external_db = db
        self._integration_cache: dict[str, AccountIntegration] = {}

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
        auth_method = credentials.get("auth_method", "")
        auth_type = integration.integration_type.auth_type

        needs_token = not (auth_type == "basic_or_jwt" and auth_method == "basic_auth")

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
        effective_vars = self._apply_endpoint_defaults(variables, endpoint_def)
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
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.VALIDATION_ERROR,
                error_message=config.on_error_message,
            )
        headers = self._build_headers(integration, config)
        body = self._build_body(config, effective_vars, endpoint_def)
        effective_response_vars = self._effective_response_variables(config, endpoint_def)
        log_endpoint = config.endpoint_template or config.path

        attempt = 0
        last_error: Optional[Exception] = None

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
                return result

            except httpx.TimeoutException:
                logger.warning(
                    f"Request timeout (attempt {attempt + 1}/{config.retry_count + 1}): {url}"
                )
                last_error = httpx.TimeoutException(f"Request timed out after {config.timeout}s")
                attempt += 1

            except httpx.NetworkError as e:
                logger.warning(
                    f"Network error (attempt {attempt + 1}/{config.retry_count + 1}): {e}"
                )
                last_error = e
                attempt += 1

            except Exception as e:
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

    async def _refresh_token(self, integration: AccountIntegration) -> bool:
        credentials = integration.get_credentials()
        integration_type = integration.integration_type
        auth_config = integration_type.get_auth_config()
        auth_type = integration_type.auth_type
        auth_method = credentials.get("auth_method", "")

        if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
            return True

        if auth_type == "basic_or_jwt" and auth_method == "jwt":
            return await self._refresh_jwt_token(integration, credentials, auth_config)

        return await self._refresh_oauth_token(integration, credentials, auth_config)

    def _compute_jwt_expires_in(self, token_data: dict, max_lifetime_hours: int) -> int:
        expired_time_str = token_data.get("expired_time")
        if expired_time_str:
            try:
                expired_dt = datetime.strptime(expired_time_str, "%Y-%m-%d %H:%M:%S")
                seconds_remaining = int((expired_dt - datetime.utcnow()).total_seconds())
                if seconds_remaining > 0:
                    return seconds_remaining
            except (ValueError, TypeError):
                pass
        return token_data.get("expires_in", max_lifetime_hours * 3600)

    async def _refresh_jwt_token(
        self, integration: AccountIntegration, credentials: dict, auth_config: dict
    ) -> bool:
        base_url = auth_config.get("base_url", "").rstrip("/")
        refresh_endpoint = auth_config.get("jwt_refresh_endpoint", "/authentication/refresh")
        login_endpoint = auth_config.get("jwt_login_endpoint", "/authentication/login")
        max_lifetime_hours = auth_config.get("jwt_max_lifetime_hours", 3)

        refresh_token = integration.get_refresh_token()
        expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        db = self._get_db_session()
        try:
            if refresh_token:
                try:
                    async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                        response = await client.post(
                            f"{base_url}{refresh_endpoint}",
                            json={"refresh_token": refresh_token, "expired_time": expired_time},
                            headers={
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            },
                            timeout=30.0,
                        )

                        if response.status_code == 200:
                            token_data = response.json()
                            integration.set_access_token(
                                token_data.get("token") or token_data.get("access_token")
                            )
                            if token_data.get("refresh_token"):
                                integration.set_refresh_token(token_data["refresh_token"])
                            expires_in = self._compute_jwt_expires_in(
                                token_data, max_lifetime_hours
                            )
                            integration.token_expires_at = datetime.utcnow() + timedelta(
                                seconds=expires_in
                            )
                            integration.status = IntegrationStatus.CONNECTED
                            integration.last_error = None
                            db.add(integration)
                            db.commit()
                            logger.info(
                                f"Successfully refreshed JWT token for integration {integration.id}"
                            )
                            return True
                except Exception as e:
                    logger.error(f"JWT refresh failed, falling back to login: {e}")

            username = credentials.get("username")
            password = credentials.get("password")

            if not all([base_url, username, password]):
                logger.error("Missing credentials for JWT login")
                return False

            try:
                async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                    response = await client.post(
                        f"{base_url}{login_endpoint}",
                        json={
                            "username": username,
                            "password": password,
                            "expired_time": expired_time,
                        },
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                        timeout=30.0,
                    )

                    if response.status_code == 200:
                        token_data = response.json()
                        integration.set_access_token(
                            token_data.get("token") or token_data.get("access_token")
                        )
                        if token_data.get("refresh_token"):
                            integration.set_refresh_token(token_data["refresh_token"])
                        expires_in = self._compute_jwt_expires_in(token_data, max_lifetime_hours)
                        integration.token_expires_at = datetime.utcnow() + timedelta(
                            seconds=expires_in
                        )
                        integration.status = IntegrationStatus.CONNECTED
                        integration.last_error = None
                        db.add(integration)
                        db.commit()
                        logger.info(
                            f"Successfully re-authenticated JWT for integration {integration.id}"
                        )
                        return True
                    else:
                        logger.error(f"JWT login failed: {response.status_code} - {response.text}")
                        integration.status = IntegrationStatus.TOKEN_EXPIRED
                        integration.last_error = f"JWT login failed: {response.status_code}"
                        db.add(integration)
                        db.commit()
                        return False
            except Exception as e:
                # Transient failure (network blip, timeout): keep the integration
                # CONNECTED so the NEXT request retries the refresh automatically.
                # Persisting ERROR here would trip the status gate at the top of
                # execute_request() and permanently disable auto-refresh until a
                # manual reconnect. Only a definitive provider rejection (the
                # non-200 branch above) is terminal (TOKEN_EXPIRED).
                logger.error(f"JWT login exception: {e}")
                integration.last_error = str(e)
                db.add(integration)
                db.commit()
                return False
        finally:
            if not self._external_db:
                db.close()

    async def _refresh_oauth_token(
        self, integration: AccountIntegration, credentials: dict, auth_config: dict
    ) -> bool:
        raw_gateway = credentials.get("gateway_url", "")
        try:
            _validate_opera_gateway_url(raw_gateway)
        except ValueError as exc:
            logger.error(f"Invalid gateway_url for token refresh: {exc}")
            return False
        gateway_url = raw_gateway.rstrip("/")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        # OHIP sandbox does not issue a separate app_key — the client_id is used
        # as the x-app-key header value. Production accounts may supply a distinct
        # app_key; use it when present, otherwise fall back to client_id.
        app_key = credentials.get("app_key") or client_id

        if not all([gateway_url, client_id, client_secret]):
            logger.error("Missing credentials for token refresh")
            return False

        enterprise_id = credentials.get("enterprise_id")
        token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "x-app-key": app_key,
            "enterpriseId": enterprise_id,
        }

        refresh_token = integration.get_refresh_token()
        if refresh_token:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        else:
            data = {
                "grant_type": "client_credentials",
                "scope": auth_config.get("scope", "urn:opc:hgbu:ws:__myscopes__"),
            }

        db = self._get_db_session()
        try:
            async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                response = await client.post(
                    token_url,
                    headers=headers,
                    data=data,
                    auth=(client_id, client_secret),
                    timeout=30.0,
                )

                if response.status_code == 200:
                    token_data = response.json()
                    integration.set_access_token(token_data.get("access_token"))
                    if token_data.get("refresh_token"):
                        integration.set_refresh_token(token_data["refresh_token"])
                    if token_data.get("expires_in"):
                        integration.token_expires_at = datetime.utcnow() + timedelta(
                            seconds=token_data["expires_in"]
                        )

                    integration.status = IntegrationStatus.CONNECTED
                    integration.last_error = None
                    db.add(integration)
                    db.commit()

                    logger.info(f"Successfully refreshed token for integration {integration.id}")
                    return True
                else:
                    logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                    integration.last_error = f"Token refresh failed: {response.status_code}"
                    db.add(integration)
                    db.commit()
                    return False

        except Exception as e:
            # Transient failure (network blip, timeout): keep the integration
            # CONNECTED so the NEXT request retries the refresh automatically.
            # Persisting ERROR here would trip the status gate at the top of
            # execute_request() and permanently disable auto-refresh until a
            # manual reconnect. Only a definitive provider rejection (the
            # non-200 branch above) is terminal (TOKEN_EXPIRED).
            logger.error(f"Token refresh exception: {e}")
            integration.last_error = str(e)
            db.add(integration)
            db.commit()
            return False
        finally:
            if not self._external_db:
                db.close()

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
        self, variables: dict[str, Any], endpoint_def: Optional[dict]
    ) -> dict[str, Any]:
        """Merge certified-endpoint variable defaults under caller-provided values."""
        if not endpoint_def:
            return variables
        merged: dict[str, Any] = {}
        for var in endpoint_def.get("variables") or []:
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
        merged.update(variables or {})
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
        auth_type = integration.integration_type.auth_type
        auth_config = integration.integration_type.get_auth_config()

        if auth_type == "basic_or_jwt":
            base_url = auth_config.get("base_url", "").rstrip("/")
        else:
            raw_gateway = credentials.get("gateway_url", "")
            _validate_opera_gateway_url(raw_gateway)
            base_url = raw_gateway.rstrip("/")

        path = config.path
        if endpoint_def:
            path = endpoint_def.get("path", path)

        path = self._substitute_variables(path, variables)

        hotel_id = credentials.get("hotel_id") or credentials.get("hotelId")
        if hotel_id:
            path = path.replace("{hotelId}", hotel_id)
            path = path.replace("{{hotelId}}", hotel_id)
            path = path.replace("{hotel_id}", hotel_id)
            path = path.replace("{{hotel_id}}", hotel_id)

        url = f"{base_url}{path}"

        # Certified endpoints declare query params separately from the path.
        # Render them with call variables; omit unresolved optional params but
        # fail fast when a required param cannot be resolved.
        if endpoint_def:
            rendered_params: dict[str, str] = {}
            missing_required: list[str] = []
            for qp in endpoint_def.get("query_params") or []:
                key = qp.get("key")
                if not key:
                    continue
                rendered = self._substitute_variables(str(qp.get("value", "")), variables)
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

        if auth_type == "basic_or_jwt":
            basic_auth_query_params = auth_config.get("basic_auth_query_params", [])
            if basic_auth_query_params:
                params = {}
                for param_key in basic_auth_query_params:
                    param_value = credentials.get(param_key)
                    if param_value:
                        params[param_key] = param_value
                if params:
                    separator = "&" if "?" in url else "?"
                    url = f"{url}{separator}{urlencode(params)}"

        return url

    def _build_headers(
        self, integration: AccountIntegration, config: IntegrationAPIConfig
    ) -> dict[str, str]:
        credentials = integration.get_credentials()
        auth_type = integration.integration_type.auth_type
        auth_method = credentials.get("auth_method", "")

        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {basic_token}"
        else:
            access_token = integration.get_access_token()
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"

        if auth_type == "oauth2_client_credentials":
            # OHIP sandbox uses client_id as the app_key; production accounts may
            # supply a distinct app_key field — prefer it when present.
            app_key = credentials.get("app_key") or credentials.get("client_id")
            if app_key:
                headers["x-app-key"] = app_key
            hotel_id = credentials.get("hotel_id")
            if hotel_id:
                headers["x-hotelid"] = hotel_id
            # chain_code is required by some OHIP endpoints (sent as x-chainid).
            chain_code = credentials.get("chain_code")
            if chain_code:
                headers["x-chainid"] = chain_code

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
            logger.error(f"Failed to parse body template as JSON: {body_str}")
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

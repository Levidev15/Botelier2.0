"""GuestCentric CRS adapter (auth_type ``basic_or_jwt``).

Vendor specifics isolated here: HTTP Basic vs. JWT bearer auth selection, the
per-request credential query params (apikey / hotelId) that GuestCentric wants
on every data call, and the JWT login/refresh dance (which also carries an
``apikey`` query param on the auth requests themselves).
"""

import base64
from datetime import datetime, timedelta

import httpx
from loguru import logger

from botelier.models.integration import IntegrationStatus
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from ..authparams import build_auth_request_query_params
from .base import BaseIntegrationAdapter, RefreshContext


class GuestCentricAdapter(BaseIntegrationAdapter):
    slug = "guestcentric-crs"

    def needs_token(self, credentials: dict) -> bool:
        # Basic auth carries the credential on every request, so no token dance.
        return credentials.get("auth_method", "") != "basic_auth"

    def resolve_base_url(self, auth_config: dict, credentials: dict) -> str:
        return (auth_config.get("base_url", "") or "").rstrip("/")

    def build_auth_headers(self, integration, credentials: dict) -> dict:
        auth_method = credentials.get("auth_method", "")
        headers: dict[str, str] = {}
        if auth_method == "basic_auth":
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {basic_token}"
        else:
            access_token = integration.get_access_token()
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def build_auth_query_params(
        self, auth_config: dict, credentials: dict, conn_config: dict
    ) -> dict:
        params: dict[str, str] = {}
        basic_auth_query_params = auth_config.get("basic_auth_query_params", [])
        for param_key in basic_auth_query_params:
            # Non-secret scoping params (e.g. hotelId) now live in
            # connection_config. Source it FIRST — same precedence as the
            # path substitution — so a stale credentials copy can't make the
            # query param disagree with the resolved path. Secret params (e.g.
            # apikey) are never in connection_config and fall through to credentials.
            param_value = conn_config.get(param_key) or credentials.get(param_key)
            if param_value:
                params[param_key] = param_value
        return params

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        if ctx.credentials.get("auth_method", "") == "basic_auth":
            return True
        return await self.refresh_jwt(ctx)

    @staticmethod
    def _compute_jwt_expires_in(token_data: dict, max_lifetime_hours: int) -> int:
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

    async def refresh_jwt(self, ctx: RefreshContext) -> bool:
        integration = ctx.integration
        credentials = ctx.credentials
        auth_config = ctx.auth_config

        base_url = auth_config.get("base_url", "").rstrip("/")
        refresh_endpoint = auth_config.get("jwt_refresh_endpoint", "/authentication/refresh")
        login_endpoint = auth_config.get("jwt_login_endpoint", "/authentication/login")
        max_lifetime_hours = auth_config.get("jwt_max_lifetime_hours", 3)

        refresh_token = integration.get_refresh_token()
        expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        db = ctx.get_db_session()
        try:
            try:
                auth_query_params = build_auth_request_query_params(auth_config, credentials)
            except ValueError as e:
                logger.error(f"JWT auth misconfigured for integration {integration.id}: {e}")
                integration.status = IntegrationStatus.TOKEN_EXPIRED
                integration.last_error = str(e)
                db.add(integration)
                db.commit()
                return False

            if refresh_token:
                try:
                    async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                        response = await client.post(
                            f"{base_url}{refresh_endpoint}",
                            params=auth_query_params or None,
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
                        params=auth_query_params or None,
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
            if ctx.owns_session:
                db.close()

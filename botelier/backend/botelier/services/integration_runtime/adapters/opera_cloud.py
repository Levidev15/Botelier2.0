"""Oracle Opera Cloud / OHIP adapter (auth_type ``oauth2_client_credentials``).

Vendor specifics isolated here: the Oracle gateway-URL SSRF allow-list, the
OAuth2 token refresh (client_credentials + refresh_token grants), and the
OHIP scoping headers (x-app-key / x-hotelid / x-chainid).
"""

from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from loguru import logger

from botelier.models.integration import IntegrationStatus
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from .base import BaseIntegrationAdapter, RefreshContext

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


class OperaCloudAdapter(BaseIntegrationAdapter):
    slug = "opera-cloud"

    def needs_token(self, credentials: dict) -> bool:
        return True

    def resolve_base_url(self, auth_config: dict, credentials: dict) -> str:
        raw_gateway = credentials.get("gateway_url", "")
        _validate_opera_gateway_url(raw_gateway)
        return raw_gateway.rstrip("/")

    def build_auth_headers(self, integration, credentials: dict) -> dict:
        headers: dict[str, str] = {}
        access_token = integration.get_access_token()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
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
        return headers

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        return await self.refresh_oauth(ctx)

    async def refresh_oauth(self, ctx: RefreshContext) -> bool:
        integration = ctx.integration
        credentials = ctx.credentials
        auth_config = ctx.auth_config

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

        db = ctx.get_db_session()
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
            if ctx.owns_session:
                db.close()

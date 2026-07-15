"""GuestCentric CRS adapter (auth_type ``basic_or_jwt``).

Vendor specifics isolated here: HTTP Basic vs. JWT bearer auth selection, the
per-request credential query params (apikey / hotelId) that GuestCentric wants
on every data call, and the JWT login/refresh dance (which also carries an
``apikey`` query param on the auth requests themselves).
"""

import base64
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger

from botelier.models.integration import IntegrationStatus
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from ..authparams import build_auth_request_query_params
from ..canonical import (
    CanonicalAvailability,
    CanonicalEntity,
    CanonicalReservation,
    ReservationStatus,
    build_envelope,
    coerce_float,
    coerce_int,
    coerce_str,
)
from .base import BaseIntegrationAdapter, RefreshContext

# GuestCentric status strings mapped onto the vendor-neutral vocabulary.
_GUESTCENTRIC_RESERVATION_STATUS = {
    "confirmed": ReservationStatus.CONFIRMED,
    "booked": ReservationStatus.CONFIRMED,
    "reserved": ReservationStatus.CONFIRMED,
    "inhouse": ReservationStatus.IN_HOUSE,
    "checkedin": ReservationStatus.IN_HOUSE,
    "checkedout": ReservationStatus.CHECKED_OUT,
    "departed": ReservationStatus.CHECKED_OUT,
    "cancelled": ReservationStatus.CANCELLED,
    "canceled": ReservationStatus.CANCELLED,
    "noshow": ReservationStatus.NO_SHOW,
    "waitlisted": ReservationStatus.WAITLISTED,
}


def _guestcentric_status(raw_status) -> str:
    key = (raw_status or "").strip().lower().replace(" ", "").replace("_", "")
    return _GUESTCENTRIC_RESERVATION_STATUS.get(key, ReservationStatus.UNKNOWN).value


class GuestCentricAdapter(BaseIntegrationAdapter):
    slug = "guestcentric-crs"

    #: GuestCentric booking is not perfectly vendor-neutral (Task #339): a paid
    #: booking needs the rate/cancellation-policy/meal-plan ids that only exist
    #: after an availability lookup. A combined submit lacking them must fail
    #: loudly, never silently create a broken/unpaid reservation.
    EXTRA_BOOKING_FIELDS: tuple = (
        "room_type_code",
        "rate_plan_code",
        "room_rate_code",
        "total_price",
        "cancellation_policy_id",
        "meal_plan_id",
    )

    def validate_card_capture(self, variables: dict) -> None:
        super().validate_card_capture(variables)
        missing = [
            key
            for key in self.EXTRA_BOOKING_FIELDS
            if not str((variables or {}).get(key) or "").strip()
        ]
        if missing:
            raise ValueError(
                "Cannot book with payment: GuestCentric requires field(s) from a "
                "prior availability lookup: " + ", ".join(missing)
            )

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

    # ------------------------------------------------------------------
    # Canonical normalization (GuestCentric shapes -> vendor-neutral entities).
    # Every normalizer is total: it returns None on an unexpected shape and
    # never raises, so a normalization bug can never fail a live CRS request.
    # ------------------------------------------------------------------
    def normalize(self, entity, endpoint_id, raw):
        if not isinstance(raw, dict):
            return None
        try:
            if entity == CanonicalEntity.RESERVATION.value:
                items = self._normalize_reservations(raw)
            elif entity == CanonicalEntity.AVAILABILITY.value:
                items = self._normalize_availability(raw)
            else:
                return None
        except Exception:  # pragma: no cover - defensive; normalizers are total
            logger.exception(
                f"GuestCentric canonical normalization failed "
                f"(entity={entity}, endpoint={endpoint_id})"
            )
            return None
        # None → expected wrapper key absent (shape we don't recognize, "not
        # canonicalized"); [] → wrapper present but empty. Keep them distinct.
        if items is None:
            return None
        return build_envelope(entity, items)

    @staticmethod
    def _reservation_from_record(res: dict) -> CanonicalReservation:
        # crs_reservation_code is the guest-facing confirmation reference;
        # hotel_reservation_code is the internal PMS identifier.
        guest = res.get("guest") if isinstance(res.get("guest"), dict) else {}
        room_type = res.get("room_type") if isinstance(res.get("room_type"), dict) else {}
        rate_plan = res.get("rate_plan") if isinstance(res.get("rate_plan"), dict) else {}
        room_rate = res.get("room_rate") if isinstance(res.get("room_rate"), dict) else {}
        # Prefer the nested room_rate.total_price, falling back to a top-level
        # total_price — but only when the nested value is truly absent, so a
        # legitimate 0.0 (comp/free stay) is preserved rather than coalesced away.
        total_price = room_rate.get("total_price")
        if total_price is None:
            total_price = res.get("total_price")
        return CanonicalReservation(
            reservation_id=coerce_str(res.get("hotel_reservation_code")),
            confirmation_number=coerce_str(res.get("crs_reservation_code")),
            status=_guestcentric_status(res.get("status")),
            guest_first_name=guest.get("first_name"),
            guest_last_name=guest.get("last_name"),
            arrival_date=res.get("checkin"),
            departure_date=res.get("checkout"),
            room_type_code=room_type.get("room_type_code") or res.get("room_type_code"),
            rate_plan_code=rate_plan.get("rate_plan_code") or res.get("rate_plan_code"),
            adults=coerce_int(res.get("number_of_adults")),
            children=coerce_int(res.get("number_of_children")),
            total_amount=coerce_float(total_price),
            currency=room_rate.get("currency") or res.get("currency"),
        )

    def _normalize_reservations(self, raw: dict) -> Optional[list]:
        if "reservations" not in raw:
            return None
        records = raw.get("reservations")
        if not isinstance(records, list):
            return []
        return [self._reservation_from_record(r) for r in records if isinstance(r, dict)]

    def _normalize_availability(self, raw: dict) -> list:
        # GuestCentric splits availability across parallel arrays: `rooms` holds the
        # room-type catalog (code -> name), `room_rates` holds the priced room+rate
        # combinations. The check-in/check-out dates are echoed once at the top
        # level. Build the name lookup first, then map each room_rate.
        room_names = {}
        for room in raw.get("rooms") or []:
            if isinstance(room, dict) and room.get("room_type_code"):
                room_names[room["room_type_code"]] = room.get("name")
        if "room_rates" not in raw:
            return None
        checkin = raw.get("checkin")
        checkout = raw.get("checkout")
        room_rates = raw.get("room_rates")
        if not isinstance(room_rates, list):
            return []
        items = []
        for rr in room_rates:
            if not isinstance(rr, dict):
                continue
            room_type_code = rr.get("room_type_code")
            available = rr.get("available")
            items.append(
                CanonicalAvailability(
                    room_type_code=room_type_code,
                    room_name=room_names.get(room_type_code),
                    rate_plan_code=rr.get("rate_plan_code"),
                    arrival_date=rr.get("checkin") or checkin,
                    departure_date=rr.get("checkout") or checkout,
                    available=bool(available) if available is not None else None,
                    total_amount=coerce_float(rr.get("total_price")),
                    currency=rr.get("currency"),
                )
            )
        return items

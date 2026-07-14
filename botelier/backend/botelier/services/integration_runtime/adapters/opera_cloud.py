"""Oracle Opera Cloud / OHIP adapter (auth_type ``oauth2_client_credentials``).

Vendor specifics isolated here: the Oracle gateway-URL SSRF allow-list, the
OAuth2 token refresh (client_credentials + refresh_token grants), and the
OHIP scoping headers (x-app-key / x-hotelid / x-chainid).
"""

from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from botelier.models.integration import IntegrationStatus
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from ..canonical import (
    CanonicalAvailability,
    CanonicalEntity,
    CanonicalGuest,
    CanonicalRatePlan,
    CanonicalReservation,
    CanonicalRoom,
    ReservationStatus,
    build_envelope,
    coerce_float,
    coerce_int,
    coerce_str,
)
from .base import BaseIntegrationAdapter, RefreshContext

# OHIP reservationStatus strings mapped onto the vendor-neutral vocabulary.
_OPERA_RESERVATION_STATUS = {
    "reserved": ReservationStatus.CONFIRMED,
    "confirmed": ReservationStatus.CONFIRMED,
    "inhouse": ReservationStatus.IN_HOUSE,
    "checkedin": ReservationStatus.IN_HOUSE,
    "checkedout": ReservationStatus.CHECKED_OUT,
    "departed": ReservationStatus.CHECKED_OUT,
    "cancelled": ReservationStatus.CANCELLED,
    "canceled": ReservationStatus.CANCELLED,
    "noshow": ReservationStatus.NO_SHOW,
    "waitlisted": ReservationStatus.WAITLISTED,
    "waitlist": ReservationStatus.WAITLISTED,
}


def _opera_status(raw_status) -> str:
    key = (raw_status or "").strip().lower().replace(" ", "").replace("_", "")
    return _OPERA_RESERVATION_STATUS.get(key, ReservationStatus.UNKNOWN).value


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

    # ------------------------------------------------------------------
    # Canonical normalization (OHIP shapes -> vendor-neutral entities).
    # Every normalizer is total: it returns None on an unexpected shape and
    # never raises, so a normalization bug can never fail a live OHIP request.
    # ------------------------------------------------------------------
    def normalize(self, entity, endpoint_id, raw):
        if not isinstance(raw, dict):
            return None
        try:
            if entity == CanonicalEntity.RESERVATION.value:
                items = self._normalize_reservations(raw)
            elif entity == CanonicalEntity.GUEST.value:
                items = self._normalize_guests(raw)
            elif entity == CanonicalEntity.AVAILABILITY.value:
                items = self._normalize_availability(raw)
            elif entity == CanonicalEntity.ROOM.value:
                items = self._normalize_rooms(raw)
            elif entity == CanonicalEntity.RATE_PLAN.value:
                items = self._normalize_rate_plans(raw)
            else:
                return None
        except Exception:  # pragma: no cover - defensive; normalizers are total
            logger.exception(
                f"Opera canonical normalization failed (entity={entity}, endpoint={endpoint_id})"
            )
            return None
        # A helper returns None when the expected top-level wrapper key is absent
        # (shape we don't recognize → "not canonicalized"); an empty list means the
        # wrapper was present but held no records. Keep those two states distinct.
        if items is None:
            return None
        return build_envelope(entity, items)

    @staticmethod
    def _reservation_from_info(info: dict) -> CanonicalReservation:
        # reservationIdList carries several typed ids; the "Confirmation" id is the
        # guest-facing number, any other typed id (e.g. "Reservation") is the
        # internal PMS identifier.
        reservation_id = None
        confirmation_number = None
        for entry in info.get("reservationIdList") or []:
            if not isinstance(entry, dict):
                continue
            id_type = (entry.get("type") or "").strip().lower()
            if id_type == "confirmation":
                confirmation_number = confirmation_number or entry.get("id")
            elif reservation_id is None:
                reservation_id = entry.get("id")
        room_stay = info.get("roomStay") if isinstance(info.get("roomStay"), dict) else {}
        counts = room_stay.get("guestCounts") if isinstance(room_stay.get("guestCounts"), dict) else {}
        total = room_stay.get("total") if isinstance(room_stay.get("total"), dict) else {}
        guest_name = info.get("guestName") if isinstance(info.get("guestName"), dict) else {}
        return CanonicalReservation(
            reservation_id=coerce_str(reservation_id),
            confirmation_number=coerce_str(confirmation_number),
            status=_opera_status(info.get("reservationStatus")),
            guest_first_name=guest_name.get("givenName"),
            guest_last_name=guest_name.get("surname"),
            arrival_date=info.get("arrivalDate") or room_stay.get("arrivalDate"),
            departure_date=info.get("departureDate") or room_stay.get("departureDate"),
            room_type_code=room_stay.get("roomType") or info.get("roomType"),
            rate_plan_code=room_stay.get("ratePlanCode") or info.get("ratePlanCode"),
            adults=coerce_int(counts.get("adults")),
            children=coerce_int(counts.get("children")),
            total_amount=coerce_float(total.get("amountBeforeTax")),
            currency=total.get("currencyCode"),
        )

    def _normalize_reservations(self, raw: dict) -> Optional[list]:
        if "reservations" not in raw:
            return None
        reservations = raw.get("reservations")
        info_list = reservations.get("reservationInfo") if isinstance(reservations, dict) else None
        if not isinstance(info_list, list):
            return []
        return [self._reservation_from_info(i) for i in info_list if isinstance(i, dict)]

    @staticmethod
    def _guest_from_profile(details: dict) -> CanonicalGuest:
        profile_id = details.get("profileId")
        if isinstance(profile_id, dict):
            profile_id = profile_id.get("id")
        customer = details.get("customer") if isinstance(details.get("customer"), dict) else {}
        names = customer.get("personName") if isinstance(customer.get("personName"), list) else []
        name = names[0] if names and isinstance(names[0], dict) else {}
        emails = details.get("emails") if isinstance(details.get("emails"), list) else []
        email = emails[0].get("email") if emails and isinstance(emails[0], dict) else None
        phones = details.get("phones") if isinstance(details.get("phones"), list) else []
        phone = phones[0].get("phoneNumber") if phones and isinstance(phones[0], dict) else None
        return CanonicalGuest(
            guest_id=coerce_str(profile_id),
            first_name=name.get("givenName"),
            last_name=name.get("surname"),
            email=email,
            phone=phone,
        )

    def _normalize_guests(self, raw: dict) -> Optional[list]:
        if "profileDetails" not in raw and "profileSummaries" not in raw:
            return None
        details = raw.get("profileDetails")
        if isinstance(details, dict):
            return [self._guest_from_profile(details)]
        summaries = raw.get("profileSummaries")
        info_list = summaries.get("profileInfo") if isinstance(summaries, dict) else None
        if not isinstance(info_list, list):
            return []
        guests = []
        for info in info_list:
            if not isinstance(info, dict):
                continue
            # A summary may itself wrap the fields under profileDetails.
            details = info.get("profileDetails") if isinstance(info.get("profileDetails"), dict) else info
            guests.append(self._guest_from_profile(details))
        return guests

    def _normalize_availability(self, raw: dict) -> Optional[list]:
        if "hotelAvailability" not in raw:
            return None
        hotel_avail = raw.get("hotelAvailability")
        if not isinstance(hotel_avail, list):
            return []
        items = []
        for hotel in hotel_avail:
            if not isinstance(hotel, dict):
                continue
            for stay in hotel.get("roomStays") or []:
                if not isinstance(stay, dict):
                    continue
                arrival = stay.get("arrivalDate")
                departure = stay.get("departureDate")
                for rate in stay.get("roomRates") or []:
                    if not isinstance(rate, dict):
                        continue
                    total = rate.get("total") if isinstance(rate.get("total"), dict) else {}
                    units = coerce_int(rate.get("numberOfUnits"))
                    items.append(
                        CanonicalAvailability(
                            room_type_code=rate.get("roomType") or stay.get("roomType"),
                            room_name=rate.get("roomTypeName") or stay.get("roomTypeName"),
                            rate_plan_code=rate.get("ratePlanCode"),
                            arrival_date=arrival,
                            departure_date=departure,
                            available=(units > 0) if units is not None else None,
                            total_amount=coerce_float(total.get("amountBeforeTax")),
                            currency=total.get("currencyCode"),
                        )
                    )
        return items

    def _normalize_rooms(self, raw: dict) -> Optional[list]:
        if "listOfValues" not in raw:
            return None
        lov = raw.get("listOfValues") if isinstance(raw.get("listOfValues"), dict) else {}
        items = lov.get("items") if isinstance(lov.get("items"), list) else []
        rooms = []
        for item in items:
            if not isinstance(item, dict):
                continue
            description = item.get("description")
            rooms.append(
                CanonicalRoom(
                    room_type_code=item.get("code") or item.get("roomType"),
                    name=item.get("name") or description,
                    description=description,
                    max_occupancy=coerce_int(item.get("maxOccupancy")),
                )
            )
        return rooms

    def _normalize_rate_plans(self, raw: dict) -> Optional[list]:
        if "ratePlans" not in raw:
            return None
        plans = raw.get("ratePlans")
        if not isinstance(plans, list):
            return []
        result = []
        for plan in plans:
            if not isinstance(plan, dict):
                continue
            description = plan.get("description")
            result.append(
                CanonicalRatePlan(
                    rate_plan_code=plan.get("ratePlanCode"),
                    name=plan.get("ratePlanName") or description,
                    description=description,
                    currency=plan.get("currencyCode"),
                )
            )
        return result

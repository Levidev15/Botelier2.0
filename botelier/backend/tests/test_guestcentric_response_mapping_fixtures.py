"""
Fixture-based tests that verify every new/corrected response_mapping JSONPath
in the GuestCentric seed resolves to a non-null value against a representative
API response shaped to match GuestCentric's published OpenAPI schema.

Each fixture mirrors the structure documented in swagger.yaml; any path that
yields None here would yield None in a real flow and silently break the
variable that depends on it.
"""
import re
import pytest

from botelier.seeds.guestcentric_integration import GUESTCENTRIC_INTEGRATION


# ---------------------------------------------------------------------------
# Minimal JSONPath resolver (covers the subset used in GC mappings)
# Handles: $ | $.f | $[0] | $.a[0].b | $.a[0].b.c | $[0].f | $[0].f[0].g
# ---------------------------------------------------------------------------

def _resolve(data, path: str):
    """Resolve a simple JSONPath against *data* and return the value or None."""
    if path == "$":
        return data

    # Tokenise: strip leading "$", then split on "." or "[" boundaries
    tokens = []
    remainder = path.lstrip("$").lstrip(".")
    for part in re.split(r"\.(?!\d)", remainder):
        if not part:
            continue
        # e.g. "cancellation_rules[0]" or "cancellation_rules[0].type"
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[(\d+)\])?$", part)
        if m:
            tokens.append(("key", m.group(1)))
            if m.group(2) is not None:
                tokens.append(("idx", int(m.group(2))))
        elif part.startswith("[") and part.endswith("]"):
            tokens.append(("idx", int(part[1:-1])))
        else:
            # Fallback: split on "[" to handle camelCase + index
            subparts = re.split(r"\[", part)
            tokens.append(("key", subparts[0]))
            for sp in subparts[1:]:
                tokens.append(("idx", int(sp.rstrip("]"))))

    current = data
    for kind, val in tokens:
        if current is None:
            return None
        if kind == "key":
            if not isinstance(current, dict):
                return None
            current = current.get(val)
        else:
            if not isinstance(current, list) or len(current) <= val:
                return None
            current = current[val]
    return current


def _endpoint(slug: str) -> dict:
    """Return the seed endpoint dict for *slug*, or raise clearly."""
    for ep in GUESTCENTRIC_INTEGRATION["endpoints"]:
        if ep["id"] == slug:
            return ep
    raise KeyError(f"endpoint {slug!r} not found in GC seed")


def _assert_all_paths(fixture, response_mapping, context: str):
    """Assert every path in *response_mapping* resolves to a truthy value."""
    failures = []
    for var, path in response_mapping.items():
        val = _resolve(fixture, path)
        if val is None or val == [] or val == {}:
            failures.append(f"  {var}: path {path!r} → {val!r}")
    if failures:
        raise AssertionError(
            f"{context}: {len(failures)} path(s) resolved to empty/None:\n"
            + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HOTEL_ROOMS_FIXTURE = {
    "rooms": [
        {
            "room_type_code": "DBL",
            "name": "Deluxe Double",
            "description": "Spacious room with garden view.",
            "max_persons": "3",
            "max_adults": "2",
            "max_children": "1",
            "amenities": ["Air conditioning", "Free WiFi"],
            "images": ["https://example.com/room.jpg"],
        }
    ],
    "rates": [
        {
            "rate_plan_code": "BB",
            "name": "Bed & Breakfast",
            "description": "Includes breakfast for two.",
            "cancellation_policy": {
                "id": "cp1",
                "name": "Flexible",
                "cancellationPoliciesText": "Free cancellation until 24h before.",
            },
        }
    ],
    "room_rates": [
        {
            "room_type_code": "DBL",
            "rate_plan_code": "BB",
            "room_rate_code": "DBL_BB",
            "total_price": 320.0,
            "net_price": 280.0,
            "pay_now": 0.0,
            "pay_at_checkout": 320.0,
            "currency": "EUR",
            "daily_rates": [{"day": "2025-06-01", "rate": "160.00"}],
            "meal_plan_prices": {
                "included": {"id": "MP_BB", "name": "Breakfast"},
                "upgrades": [],
            },
        }
    ],
    "promotions": [
        {"rate_plan_code": "EARLY10", "name": "Early Bird 10%", "description": "10% off"}
    ],
}

CANCELLATION_POLICIES_FIXTURE = [
    {
        "id": "cp_flex",
        "name": "Flexible Rate",
        "teaser": "Cancel up to 24 hours before arrival.",
        "cancellationPoliciesText": (
            "Free cancellation is allowed up to 24 hours before arrival. "
            "After that, 1 night will be charged."
        ),
        "guarantee_text": "No deposit required.",
        "max_installments": "1",
        "cancellation_rules": [
            {
                "value": "1",
                "type": "Nights",
                "text": "1 night charged if cancelled within 24 hours of arrival.",
                "hours": "24",
                "hours_pm_am": "12:00 PM",
                "before_days": "1",
            }
        ],
        "deposit_rules": [],
    }
]

GUARANTEE_POLICIES_FIXTURE = [
    {
        "id": "gp_cc",
        "name": "Credit Card Guarantee",
        "teaser": "A valid credit card is required to guarantee the reservation.",
        "cancellationPoliciesText": (
            "A credit card guarantee is required. "
            "The card will not be charged unless the guest fails to arrive."
        ),
        "guarantee_text": "Credit card required at booking.",
        "cancellation_rules": [],
        "deposit_rules": [
            {
                "value": "50",
                "type": "Percentage",
                "text": "50% deposit charged at booking.",
                "before_days": "0",
            }
        ],
    }
]

RESERVATION_FIXTURE = {
    "reservations": [
        {
            "crs_reservation_code": "CRS-00123",
            "reservation_code": "HRS-456",
            "status": "confirmed",
            "checkin": "2025-06-15",
            "checkout": "2025-06-18",
            "number_of_adults": 2,
            "number_of_children": 1,
            "hotel": {
                "hotel_id": "cf5223be901bf",
                "hotel_name": "Hotel Botelier",
                "hotel_reservations_email": "reservations@botelier.com",
            },
            "guest": {
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "phone": "+351912345678",
            },
            "room_rate": {
                "room_type_code": "DBL",
                "rate_plan_code": "BB",
                "room_rate_code": "DBL_BB",
                "total_price": 320.0,
                "net_price": 280.0,
                "pay_now": 0.0,
                "pay_at_checkout": 320.0,
                "currency": "EUR",
                "daily_rates": [{"day": "2025-06-15", "rate": "106.67"}],
            },
        }
    ]
}


# ---------------------------------------------------------------------------
# Tests — hotel_rooms
# ---------------------------------------------------------------------------


class TestHotelRoomsMapping:
    EP = _endpoint("hotel_rooms")

    def test_all_paths_resolve(self):
        _assert_all_paths(
            HOTEL_ROOMS_FIXTURE,
            self.EP["response_mapping"],
            "hotel_rooms",
        )

    def test_first_room_max_persons(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.rooms[0].max_persons") == "3"

    def test_first_room_max_adults(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.rooms[0].max_adults") == "2"

    def test_first_room_amenities(self):
        amenities = _resolve(HOTEL_ROOMS_FIXTURE, "$.rooms[0].amenities")
        assert isinstance(amenities, list) and len(amenities) > 0

    def test_first_rate_description(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.rates[0].description") == "Includes breakfast for two."

    def test_first_total_price(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.room_rates[0].total_price") == 320.0

    def test_first_net_price(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.room_rates[0].net_price") == 280.0

    def test_first_pay_now(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.room_rates[0].pay_now") == 0.0

    def test_first_currency(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.room_rates[0].currency") == "EUR"

    def test_meal_plan_id(self):
        assert _resolve(HOTEL_ROOMS_FIXTURE, "$.room_rates[0].meal_plan_prices.included.id") == "MP_BB"

    def test_promotions(self):
        promos = _resolve(HOTEL_ROOMS_FIXTURE, "$.promotions")
        assert isinstance(promos, list) and len(promos) > 0

    # Verify the rejected nonexistent paths are NOT in the mapping
    def test_no_beds_path(self):
        assert "first_room_beds" not in self.EP["response_mapping"]

    def test_no_per_night_price_path(self):
        assert "first_per_night_price" not in self.EP["response_mapping"]

    def test_no_number_of_nights_path(self):
        assert "first_number_of_nights" not in self.EP["response_mapping"]

    def test_no_refundable_path(self):
        assert "first_refundable" not in self.EP["response_mapping"]

    def test_no_max_occupancy_path(self):
        # max_occupancy was a wrong name; correct is max_persons
        assert "first_room_max_occupancy" not in self.EP["response_mapping"]


# ---------------------------------------------------------------------------
# Tests — hotel_cancellation_policies
# ---------------------------------------------------------------------------


class TestCancellationPoliciesMapping:
    EP = _endpoint("hotel_cancellation_policies")

    def test_all_paths_resolve(self):
        _assert_all_paths(
            CANCELLATION_POLICIES_FIXTURE,
            self.EP["response_mapping"],
            "hotel_cancellation_policies",
        )

    def test_full_text_uses_camel_case_field(self):
        path = self.EP["response_mapping"]["first_policy_full_text"]
        assert "cancellationPoliciesText" in path, (
            "Must use GC's camelCase field name 'cancellationPoliciesText', not 'description'"
        )
        val = _resolve(CANCELLATION_POLICIES_FIXTURE, path)
        assert "cancellation" in val.lower()

    def test_rule_type(self):
        path = self.EP["response_mapping"]["first_policy_rule_type"]
        assert _resolve(CANCELLATION_POLICIES_FIXTURE, path) == "Nights"

    def test_rule_value(self):
        path = self.EP["response_mapping"]["first_policy_rule_value"]
        assert _resolve(CANCELLATION_POLICIES_FIXTURE, path) == "1"

    def test_rule_text(self):
        path = self.EP["response_mapping"]["first_policy_rule_text"]
        val = _resolve(CANCELLATION_POLICIES_FIXTURE, path)
        assert isinstance(val, str) and len(val) > 0

    def test_no_description_key(self):
        assert "first_policy_description" not in self.EP["response_mapping"]

    def test_no_penalty_keys(self):
        assert "first_policy_penalty_amount" not in self.EP["response_mapping"]
        assert "first_policy_penalty_type" not in self.EP["response_mapping"]


# ---------------------------------------------------------------------------
# Tests — hotel_guarantee_policies
# ---------------------------------------------------------------------------


class TestGuaranteePoliciesMapping:
    EP = _endpoint("hotel_guarantee_policies")

    def test_all_paths_resolve(self):
        _assert_all_paths(
            GUARANTEE_POLICIES_FIXTURE,
            self.EP["response_mapping"],
            "hotel_guarantee_policies",
        )

    def test_full_text_uses_camel_case_field(self):
        path = self.EP["response_mapping"]["first_policy_full_text"]
        assert "cancellationPoliciesText" in path
        val = _resolve(GUARANTEE_POLICIES_FIXTURE, path)
        assert "credit card" in val.lower()

    def test_guarantee_text(self):
        path = self.EP["response_mapping"]["first_policy_guarantee_text"]
        val = _resolve(GUARANTEE_POLICIES_FIXTURE, path)
        assert isinstance(val, str) and len(val) > 0

    def test_deposit_type(self):
        path = self.EP["response_mapping"]["first_policy_deposit_type"]
        assert _resolve(GUARANTEE_POLICIES_FIXTURE, path) == "Percentage"

    def test_deposit_text(self):
        path = self.EP["response_mapping"]["first_policy_deposit_text"]
        val = _resolve(GUARANTEE_POLICIES_FIXTURE, path)
        assert "deposit" in val.lower()

    def test_no_guarantee_type_key(self):
        assert "first_policy_guarantee_type" not in self.EP["response_mapping"]

    def test_no_description_key(self):
        assert "first_policy_description" not in self.EP["response_mapping"]


# ---------------------------------------------------------------------------
# Tests — update_reservation
# ---------------------------------------------------------------------------


class TestUpdateReservationMapping:
    EP = _endpoint("update_reservation")

    def test_all_paths_resolve(self):
        _assert_all_paths(
            RESERVATION_FIXTURE,
            self.EP["response_mapping"],
            "update_reservation",
        )

    def test_total_price_nested_in_room_rate(self):
        path = self.EP["response_mapping"]["total_price"]
        assert "room_rate.total_price" in path, (
            "total_price must be sourced from room_rate.total_price, not from the reservation root"
        )
        assert _resolve(RESERVATION_FIXTURE, path) == 320.0

    def test_currency_nested_in_room_rate(self):
        path = self.EP["response_mapping"]["currency"]
        assert "room_rate.currency" in path
        assert _resolve(RESERVATION_FIXTURE, path) == "EUR"

    def test_checkin(self):
        assert _resolve(RESERVATION_FIXTURE, "$.reservations[0].checkin") == "2025-06-15"

    def test_checkout(self):
        assert _resolve(RESERVATION_FIXTURE, "$.reservations[0].checkout") == "2025-06-18"

    def test_crs_code(self):
        assert _resolve(RESERVATION_FIXTURE, "$.reservations[0].crs_reservation_code") == "CRS-00123"


# ---------------------------------------------------------------------------
# Tests — modify_reservation
# ---------------------------------------------------------------------------


class TestModifyReservationMapping:
    EP = _endpoint("modify_reservation")

    def test_all_paths_resolve(self):
        _assert_all_paths(
            RESERVATION_FIXTURE,
            self.EP["response_mapping"],
            "modify_reservation",
        )

    def test_quoted_total_price_nested_in_room_rate(self):
        path = self.EP["response_mapping"]["quoted_total_price"]
        assert "room_rate.total_price" in path, (
            "quoted_total_price must come from room_rate.total_price, not reservation root"
        )
        assert _resolve(RESERVATION_FIXTURE, path) == 320.0

    def test_quoted_currency_nested_in_room_rate(self):
        path = self.EP["response_mapping"]["quoted_currency"]
        assert "room_rate.currency" in path
        assert _resolve(RESERVATION_FIXTURE, path) == "EUR"

    def test_quoted_checkin(self):
        assert _resolve(RESERVATION_FIXTURE, "$.reservations[0].checkin") == "2025-06-15"

    def test_quoted_checkout(self):
        assert _resolve(RESERVATION_FIXTURE, "$.reservations[0].checkout") == "2025-06-18"

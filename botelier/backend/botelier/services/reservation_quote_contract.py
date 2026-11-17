"""Validate a mapped, provider-authoritative reservation quote without I/O.

This is an optional data contract, not a booking engine or permission grant.
``subtotal`` is the provider's stay subtotal after discounts. Tax/fee treatment
states which components that subtotal already includes; ``total`` is the
provider's final stay total. Components and totals are checked, never invented,
converted, rounded or overwritten. Per-night data requires a separate,
authoritative stay-total mapping.

Callers must supply expected selection from trusted flow state, a server clock,
and literal approved link origins from published configuration. Neither a
fingerprint nor this result replaces NativeConfirmation or endpoint policy.
No payment/session creation, URL fetching, logging or messaging occurs here.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit


_QUOTE_REQUIRED = frozenset({
    "quote_id", "room_id", "check_in", "check_out", "adults", "children", "pricing",
})
_QUOTE_OPTIONAL = frozenset({
    "rate_id", "offer_id", "hotel_id", "expires_at", "checkout_url", "terms",
})
_PRICING_REQUIRED = frozenset({
    "basis", "currency", "subtotal", "tax_total", "fees_total",
    "tax_treatment", "fees_treatment", "total",
})
_PRICING_OPTIONAL = frozenset({
    "tax_lines", "fee_lines", "due_now", "pay_at_property",
    "discount_total", "rounding_adjustment",
})
_IDENTITY = (
    "quote_id", "room_id", "rate_id", "offer_id", "hotel_id",
    "check_in", "check_out", "adults", "children",
)
_EXPECTED_REQUIRED = frozenset({
    "room_id", "check_in", "check_out", "adults", "children", "currency",
})
_ZERO_DECIMAL = frozenset({
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
})
_THREE_DECIMAL = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})
_MONEY = re.compile(r"-?\d{1,12}(?:\.\d{1,4})?\Z", re.ASCII)
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}\Z", re.ASCII)


class QuoteContractError(ValueError):
    """A stable reason/path containing no provider values or bearer links."""

    def __init__(self, code, path="quote"):
        self.code = code
        self.path = path
        super().__init__(f"{code}:{path}")


@dataclass(frozen=True, slots=True)
class ValidatedReservationQuote:
    """Detached data and a business-snapshot fingerprint, not authorization."""

    _data_json: str = field(repr=False)
    fingerprint: str

    def data(self):
        """Return a fresh copy for explicitly scoped delivery/storage."""
        return json.loads(self._data_json)

    def model_data(self):
        """Return the pricing snapshot without the checkout bearer URL."""
        data = self.data()
        data["checkout_link_available"] = bool(data.pop("checkout_url", None))
        return data


def _fail(code, path="quote"):
    raise QuoteContractError(code, path) from None


def _bounded_copy(value):
    seen = set()
    nodes = 0

    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 4096:
            _fail("quote_payload")
        kind = type(item)
        if kind in (dict, list):
            marker = id(item)
            if marker in seen or len(item) > 256:
                _fail("quote_payload")
            seen.add(marker)
            if kind is dict:
                for key, nested in item.items():
                    if type(key) is not str or len(key) > 128:
                        _fail("quote_payload")
                    walk(nested, depth + 1)
            else:
                for nested in item:
                    walk(nested, depth + 1)
            seen.remove(marker)
        elif kind is str:
            if len(item) > 8192:
                _fail("quote_payload")
        elif kind is int:
            if abs(item) > 10 ** 24:
                _fail("quote_payload")
        elif kind not in (float, bool, type(None)):
            _fail("quote_payload")

    walk(value, 0)
    if type(value) is not dict:
        _fail("quote_fields")
    return deepcopy(value)


def _identity(data, path):
    for key in ("room_id", "quote_id", "rate_id", "offer_id", "hotel_id"):
        if key in data and (
            type(data[key]) is not str
            or not data[key].strip() or len(data[key]) > 256
        ):
            _fail("quote_identity", f"{path}.{key}")
    for key in ("adults", "children"):
        value = data.get(key)
        if type(value) is not int or not (0 <= value <= 100):
            _fail("quote_identity", f"{path}.{key}")
        if key == "adults" and value == 0:
            _fail("quote_identity", f"{path}.{key}")
    dates = {}
    for key in ("check_in", "check_out"):
        value = data.get(key)
        if type(value) is not str or not _DAY.fullmatch(value):
            _fail("quote_identity", f"{path}.{key}")
        try:
            dates[key] = date.fromisoformat(value)
        except ValueError:
            _fail("quote_identity", f"{path}.{key}")
    if dates["check_out"] <= dates["check_in"]:
        _fail("quote_identity", path)


def _minor_unit(currency):
    digits = 0 if currency in _ZERO_DECIMAL else (
        3 if currency in _THREE_DECIMAL else (
            4 if currency in {"CLF", "UYW"} else 2
        )
    )
    return Decimal(10) ** -digits


def _money(value, path, unit, *, negative=False):
    if type(value) not in (str, int, float):
        _fail("money", path)
    if type(value) is float and not math.isfinite(value):
        _fail("money", path)
    text = str(value)
    if not _MONEY.fullmatch(text) or (text.startswith("-") and not negative):
        _fail("money", path)
    try:
        amount = Decimal(text)
        if amount % unit:
            _fail("money_precision", path)
    except InvalidOperation:
        _fail("money", path)
    return amount


def _component(pricing, key, amount, currency, unit):
    path = f"pricing.{key}"
    treatment_key = "tax_treatment" if key == "tax_lines" else "fees_treatment"
    treatment = pricing[treatment_key]
    if type(treatment) is not str or treatment not in {
        "inclusive", "exclusive", "mixed", "none",
    }:
        _fail("pricing_treatment", f"pricing.{treatment_key}")
    lines = pricing.get(key)
    if lines is not None:
        if type(lines) is not list or len(lines) > 64:
            _fail("pricing_lines", path)
        amounts, excluded = [], Decimal(0)
        for line in lines:
            if type(line) is not dict or (
                set(line) - {"name", "amount", "currency", "included"}
            ) or not {"amount", "included"} <= set(line):
                _fail("pricing_lines", path)
            if type(line["included"]) is not bool:
                _fail("pricing_lines", path)
            if "currency" in line and line["currency"] != currency:
                _fail("currency_mismatch", path)
            if "name" in line and (
                type(line["name"]) is not str or len(line["name"]) > 256
            ):
                _fail("pricing_lines", path)
            part = _money(line["amount"], path, unit)
            amounts.append(part)
            if not line["included"]:
                excluded += part
            if treatment in {"inclusive", "exclusive"} and (
                line["included"] != (treatment == "inclusive")
            ):
                _fail("pricing_inconsistent", path)
        if sum(amounts, Decimal(0)) != amount:
            _fail("pricing_inconsistent", path)
    elif treatment == "mixed":
        _fail("pricing_lines", path)
    if treatment == "none" and amount != 0:
        _fail("pricing_inconsistent", path)
    if treatment == "exclusive":
        return amount
    return excluded if treatment == "mixed" else Decimal(0)


def _pricing(pricing, expected_currency):
    if type(pricing) is not dict:
        _fail("pricing_required", "pricing")
    for key in sorted(_PRICING_REQUIRED):
        if key not in pricing:
            _fail("pricing_required", f"pricing.{key}")
    if set(pricing) - _PRICING_REQUIRED - _PRICING_OPTIONAL:
        _fail("quote_fields", "pricing")
    if pricing["basis"] != "stay":
        _fail("pricing_basis", "pricing.basis")
    currency = pricing["currency"]
    if type(currency) is not str or not _CURRENCY.fullmatch(currency):
        _fail("currency_mismatch", "pricing.currency")
    if currency != expected_currency:
        _fail("currency_mismatch", "pricing.currency")
    unit = _minor_unit(currency)
    amounts = {
        key: _money(pricing[key], f"pricing.{key}", unit)
        for key in ("subtotal", "tax_total", "fees_total", "total")
    }
    tax = _component(pricing, "tax_lines", amounts["tax_total"], currency, unit)
    fees = _component(pricing, "fee_lines", amounts["fees_total"], currency, unit)
    rounding = Decimal(0)
    if "rounding_adjustment" in pricing:
        rounding = _money(
            pricing["rounding_adjustment"], "pricing.rounding_adjustment",
            unit, negative=True,
        )
        if abs(rounding) > unit * 5:
            _fail("pricing_inconsistent", "pricing.rounding_adjustment")
    if amounts["subtotal"] + tax + fees + rounding != amounts["total"]:
        _fail("pricing_inconsistent", "pricing.total")
    for key in ("due_now", "pay_at_property", "discount_total"):
        if key in pricing:
            amounts[key] = _money(pricing[key], f"pricing.{key}", unit)
            if key != "discount_total" and amounts[key] > amounts["total"]:
                _fail("pricing_inconsistent", f"pricing.{key}")
    if {"due_now", "pay_at_property"} <= set(amounts) and (
        amounts["due_now"] + amounts["pay_at_property"] != amounts["total"]
    ):
        _fail("pricing_inconsistent", "pricing")
    return amounts


def _origin(value, *, policy):
    code, path = ("checkout_origin", "allowed_checkout_origins") if policy else (
        "checkout_link", "checkout_url"
    )
    if type(value) is not str or not value or len(value) > 4096 or any(
        char.isspace() or unicodedata.category(char).startswith("C") or char == "\\"
        for char in value
    ):
        _fail(code, path)
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (
            parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or "%" in parsed.netloc
            or (port is not None and not 1 <= port <= 65535)
            or (policy and (
                parsed.path not in ("", "/") or parsed.query or parsed.fragment
            ))
        ):
            _fail(code, path)
        host = host.encode("idna").decode("ascii").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (
                len(host) > 253 or host.endswith(".") or "." not in host
                or host.endswith((".localhost", ".local", ".internal"))
                or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                # WHATWG clients also interpret hexadecimal/octal spellings
                # as IPs; do not approve them as apparently public DNS names.
                or re.search(r"(?:^|\.)(?:[0-9]+|0x[0-9a-f]+)$", host)
                or any(
                    label.startswith("-") or label.endswith("-")
                    for label in host.split(".")
                )
            ):
                _fail(code, path)
        else:
            if not address.is_global:
                _fail(code, path)
            if address.version == 6:
                host = f"[{address.compressed}]"
        return f"https://{host}" + (f":{port}" if port not in (None, 443) else "")
    except (ValueError, UnicodeError):
        _fail(code, path)


def _expiry(value, now):
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        _fail("quote_clock", "now")
    if value is None:
        return
    if type(value) is not str or len(value) > 64 or "T" not in value:
        _fail("quote_expiry", "expires_at")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            _fail("quote_expiry", "expires_at")
    except ValueError:
        _fail("quote_expiry", "expires_at")
    if instant <= now:
        _fail("quote_expired", "expires_at")


def validate_reservation_quote(
    quote, *, expected, allowed_checkout_origins=(), require_checkout_link=False,
    confirmed_fingerprint=None, now=None,
):
    """Check a mapped provider snapshot; failures have safe code/path only."""
    data = _bounded_copy(quote)
    if not _QUOTE_REQUIRED <= set(data) or (
        set(data) - _QUOTE_REQUIRED - _QUOTE_OPTIONAL
    ):
        _fail("quote_fields")
    _identity(data, "quote")
    if (
        type(expected) is not dict or not _EXPECTED_REQUIRED <= set(expected)
        or set(expected) - set(_IDENTITY) - {"currency"}
    ):
        _fail("selection_required", "expected")
    _identity(expected, "expected")
    for key in _IDENTITY:
        if key in expected and data.get(key) != expected[key]:
            _fail("selection_mismatch", key)
    amounts = _pricing(data["pricing"], expected["currency"])
    if "terms" in data and (type(data["terms"]) is not str or len(data["terms"]) > 4096):
        _fail("quote_fields", "terms")
    _expiry(
        data.get("expires_at"),
        now if now is not None else datetime.now(timezone.utc),
    )
    if (
        type(allowed_checkout_origins) not in (tuple, list)
        or len(allowed_checkout_origins) > 16
    ):
        _fail("checkout_origin", "allowed_checkout_origins")
    approved = {_origin(origin, policy=True) for origin in allowed_checkout_origins}
    link = data.get("checkout_url")
    if link is not None:
        if not approved:
            _fail("checkout_origin", "allowed_checkout_origins")
        if _origin(link, policy=False) not in approved:
            _fail("checkout_link", "checkout_url")
    elif require_checkout_link:
        _fail("checkout_link", "checkout_url")
    meaning = {
        key: data[key] for key in (*_IDENTITY, "terms") if key in data
    }
    meaning["pricing"] = deepcopy(data["pricing"])
    for key, amount in amounts.items():
        fixed = format(amount, "f")
        meaning["pricing"][key] = fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
    try:
        fingerprint = hashlib.sha256(json.dumps(
            meaning, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        encoded = json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
    except (ValueError, TypeError, OverflowError):
        _fail("quote_payload")
    if len(encoded.encode("utf-8")) > 250_000:
        _fail("quote_payload")
    if confirmed_fingerprint is not None and confirmed_fingerprint != fingerprint:
        _fail("quote_changed")
    return ValidatedReservationQuote(encoded, fingerprint)

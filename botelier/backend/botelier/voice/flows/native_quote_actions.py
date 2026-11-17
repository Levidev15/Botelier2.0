"""Pure quote preparation for the native broker, not a sender or controller."""

from dataclasses import dataclass, field
from datetime import datetime
import ipaddress
import json
import re
import unicodedata

from botelier.services.request_templates import RequestTemplateError, render_json_template
from botelier.services.reservation_quote_contract import (
    QuoteContractError, ValidatedReservationQuote, _origin, validate_reservation_quote,
)
from botelier.voice.flows.native_execution import (
    NativeActionResult, NativeConfirmation, copy_native_json,
)
from botelier.voice.flows.native_response_mapping import (
    NativeResponseMappingError, map_project_response, resolve_response_variables,
)


_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_OTHER_SCHEME = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*:\S")
_RELATIVE_URL = re.compile(r"(?<![:/\w])//[^\s/]")
_BARE_HOST = re.compile(
    r"(?<![\w@.-])(?:[^\W_](?:[^\W_]|-){0,62}\.)+"
    r"(?:[^\W\d_]{2,63}|xn--[a-z0-9-]{2,59})(?![\w.@-])", re.I,
)
_IPV4 = re.compile(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\d.])")
_IPV6 = re.compile(r"\[([0-9A-Fa-f:]+)\]")
_POLICY_FIELDS = frozenset({
    "allowedCheckoutOrigins", "requireCheckoutLink", "providerSelectedDimensions",
    "fingerprintVariable", "privateUrlVariable", "publicConfirmationFields",
})
_REQUIRED_PUBLIC_FIELDS = frozenset({
    "room_id", "check_in", "check_out", "adults", "children",
    "pricing.basis", "pricing.currency", "pricing.subtotal", "pricing.tax_total",
    "pricing.tax_treatment", "pricing.fees_total", "pricing.fees_treatment",
    "pricing.total",
})
_PUBLIC_FIELDS = _REQUIRED_PUBLIC_FIELDS | frozenset({
    "quote_id", "hotel_id", "rate_id", "offer_id", "terms", "expires_at",
    "pricing.tax_lines", "pricing.fee_lines", "pricing.rounding_adjustment",
    "pricing.discount_total", "pricing.due_now", "pricing.pay_at_property",
})


class NativeQuoteError(ValueError):
    """A fixed, value-free quote preparation diagnostic."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _key(value):
    if (
        type(value) is not str or not _KEY.fullmatch(value)
        or value.startswith("__native")
    ):
        raise NativeQuoteError("quote_policy_variable")
    return value


@dataclass(frozen=True)
class NativeQuotePolicy:
    """Literal published configuration, never runtime/model-selected authority."""

    allowed_origins: tuple[str, ...]
    require_link: bool
    provider_selected_dimensions: tuple[str, ...]
    fingerprint_variable: str
    private_url_variable: str
    public_confirmation_fields: tuple[tuple[str, str], ...]

    @property
    def public_confirmation_variables(self):
        return tuple(variable for _, variable in self.public_confirmation_fields)

    @classmethod
    def from_config(cls, config):
        value = config.get("quotePolicy") if type(config) is dict else None
        if type(value) is not dict or set(value) != _POLICY_FIELDS:
            raise NativeQuoteError("quote_policy_fields")
        origins = value["allowedCheckoutOrigins"]
        dimensions = value["providerSelectedDimensions"]
        fields = value["publicConfirmationFields"]
        required = value["requireCheckoutLink"]
        if (
            type(origins) is not list or len(origins) > 16
            or type(required) is not bool or required and not origins
            or type(dimensions) is not list or len(dimensions) > 2
            or any(type(item) is not str for item in dimensions)
            or len(set(dimensions)) != len(dimensions)
            or not set(dimensions) <= {"rate_id", "offer_id"}
            or type(fields) is not dict
            or not _REQUIRED_PUBLIC_FIELDS <= set(fields) <= _PUBLIC_FIELDS
        ):
            raise NativeQuoteError("quote_policy_values")
        try:
            # Reuse the quote contract's exact origin checks; no DNS or URL fetch.
            normalized = tuple(_origin(item, policy=True) for item in origins)
        except QuoteContractError:
            raise NativeQuoteError("quote_policy_origins") from None
        fingerprint = _key(value["fingerprintVariable"])
        private_url = _key(value["privateUrlVariable"])
        public_fields = tuple((path, _key(item)) for path, item in fields.items())
        public_variables = tuple(variable for _, variable in public_fields)
        if (
            len(set(normalized)) != len(normalized)
            or fingerprint == private_url
            or len(set(public_variables)) != len(public_variables)
            or {fingerprint, private_url} & set(public_variables)
        ):
            raise NativeQuoteError("quote_policy_variables")
        return cls(
            normalized, required, tuple(dimensions), fingerprint, private_url,
            public_fields,
        )


@dataclass(frozen=True)
class PreparedNativeQuote:
    policy: NativeQuotePolicy
    validated: ValidatedReservationQuote = field(repr=False)
    result: NativeActionResult = field(repr=False)


@dataclass(frozen=True)
class PreparedQuoteDelivery:
    """Preparation only; the broker must still apply its real consent/ledger."""

    validated: ValidatedReservationQuote = field(repr=False)
    exempt_references: frozenset[str]
    required_references: frozenset[str]


def _contains(value, secret):
    if not secret:
        return False
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and secret in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _arguments(config, facts):
    if (
        type(config) is not dict
        or config.get("apiSource", "capability") != "capability"
        or config.get("capability") != "validate_reservation_quote"
        or type(facts) is not dict
    ):
        raise NativeQuoteError("quote_arguments")
    template = config.get("argumentsTemplate")
    try:
        if template is None:
            # Retain the existing capability convention; bodyTemplate stays inert.
            arguments = {key: facts[key] for key in ("quote", "expected") if key in facts}
        elif isinstance(template, str):
            arguments = render_json_template(template, facts)
        else:
            raise NativeQuoteError("quote_arguments")
    except (RequestTemplateError, TypeError, ValueError, KeyError):
        raise NativeQuoteError("quote_arguments") from None
    if type(arguments) is not dict or set(arguments) != {"quote", "expected"}:
        raise NativeQuoteError("quote_arguments")
    return arguments


def validate_quote_configuration(config, *, variable_declarations=()):
    """Check literal public roles and exact mapper precedence before execution."""
    policy = NativeQuotePolicy.from_config(config)
    projection = config.get("responseProjection")
    if type(projection) is not dict or type(projection.get("fields")) is not list:
        raise NativeQuoteError("quote_projection_required")
    try:
        entries = {
            item.variable_key: item for item in resolve_response_variables(
                config, variable_declarations=variable_declarations,
            )
        }
    except (NativeResponseMappingError, TypeError, ValueError):
        raise NativeQuoteError("quote_projection_mapping") from None
    paths = {
        variable: "public." + path
        for path, variable in policy.public_confirmation_fields
    }
    paths[policy.fingerprint_variable] = "fingerprint"
    paths[policy.private_url_variable] = "private.checkout_url"
    for key, path in paths.items():
        entry = entries.get(key)
        if (
            entry is None or entry.has_default
            or entry.json_path not in {path, "$." + path}
        ):
            raise NativeQuoteError("quote_policy_output_binding")
    return policy


def prepare_quote(
    config, facts, *, variable_declarations=(), now: datetime | None = None,
    confirmed_fingerprint=None,
):
    """Validate, map and project without provider, payment, ledger or message I/O."""
    policy = validate_quote_configuration(
        config, variable_declarations=variable_declarations,
    )
    arguments = _arguments(config, facts)
    projection = config["responseProjection"]
    try:
        validated = validate_reservation_quote(
            arguments["quote"], expected=arguments["expected"],
            allowed_checkout_origins=policy.allowed_origins,
            require_checkout_link=policy.require_link,
            provider_selected_dimensions=policy.provider_selected_dimensions,
            confirmed_fingerprint=confirmed_fingerprint,
            now=now,
        )
    except QuoteContractError as exc:
        raise NativeQuoteError("quote_" + exc.code) from None
    private_url = validated.data().get("checkout_url")
    response = {
        "public": validated.model_data(),
        "fingerprint": validated.fingerprint,
        "private": {"checkout_url": private_url},
    }
    try:
        variables, model_data = map_project_response(
            config, response, variable_declarations=variable_declarations,
        )
    except (NativeResponseMappingError, TypeError, ValueError):
        raise NativeQuoteError("quote_projection_mapping") from None
    if (
        variables.get(policy.fingerprint_variable) != validated.fingerprint
        or variables.get(policy.private_url_variable) != private_url
        or any(key not in variables for key in policy.public_confirmation_variables)
    ):
        raise NativeQuoteError("quote_policy_output_binding")
    selected = (entry["variable"] for entry in projection["fields"])
    if any(
        key in {policy.fingerprint_variable, policy.private_url_variable}
        or _contains(variables.get(key), private_url)
        or _contains(variables.get(key), validated.fingerprint)
        for key in selected
    ):
        # Inspect the untouched mapped value too: clean_text can decode HTML
        # entities in a URL, disguising it from a post-cleanup exact-value scan.
        raise NativeQuoteError("quote_projection_private")
    if (
        _contains(model_data, private_url)
        or _contains(model_data, validated.fingerprint)
        or "private" in model_data
    ):
        raise NativeQuoteError("quote_projection_private")
    try:
        # Mapping aliases can duplicate a bounded public subtree. Enforce the
        # final native boundary too, before building the detached action result.
        copy_native_json(variables)
        copy_native_json(model_data)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise NativeQuoteError("quote_result_limits") from None
    return PreparedNativeQuote(
        policy, validated,
        NativeActionResult(True, variables=variables, llm_data=model_data),
    )


def _same(left, right):
    try:
        return json.dumps(left, sort_keys=True, ensure_ascii=False, allow_nan=False) == (
            json.dumps(right, sort_keys=True, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError, RecursionError):
        return False


def _has_other_link(text):
    """Recognize extra navigable forms without changing any message data."""
    probe = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "\u3002": ".", "\uff0e": ".", "\uff61": ".",
    }))
    probe = "".join(char for char in probe if unicodedata.category(char) != "Cf")
    if _OTHER_SCHEME.search(probe) or _RELATIVE_URL.search(probe) or _BARE_HOST.search(probe):
        return True
    candidates = [match.group() for match in _IPV4.finditer(probe)]
    candidates.extend(match.group(1) for match in _IPV6.finditer(probe))
    for candidate in candidates:
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def prepare_quote_delivery(
    validator_config, facts, confirmation, arguments, *, recipient_variable,
    variable_declarations=(), now=None,
):
    """Return the only permitted private reference exception after fresh checks.

    The caller must resolve validator_config from the same immutable compiled
    graph, verify the quoteDelivery node reference, and then use the existing
    broker confirmation and effect-ledger path. This function cannot send.
    """
    recipient_variable = _key(recipient_variable)
    if not isinstance(confirmation, NativeConfirmation):
        raise NativeQuoteError("quote_confirmation_required")
    policy = NativeQuotePolicy.from_config(validator_config)
    required = frozenset((
        *policy.public_confirmation_variables,
        policy.fingerprint_variable, recipient_variable,
    ))
    if (
        type(facts) is not dict
        or not required <= set(confirmation.confirmed_fields)
    ):
        raise NativeQuoteError("quote_confirmation_fields")
    confirmed = confirmation.values()
    if (
        policy.private_url_variable in confirmation.confirmed_fields
        or policy.private_url_variable in confirmed
    ):
        raise NativeQuoteError("quote_confirmation_private")
    if any(
        key not in facts or key not in confirmed or not _same(facts[key], confirmed[key])
        for key in required
    ):
        raise NativeQuoteError("quote_confirmation_changed")
    prepared = prepare_quote(
        validator_config, facts, variable_declarations=variable_declarations,
        now=now, confirmed_fingerprint=confirmed[policy.fingerprint_variable],
    )
    values = prepared.result.variables
    if (
        facts[policy.fingerprint_variable] != prepared.validated.fingerprint
        or any(
            key not in values or not _same(facts[key], values[key])
            for key in policy.public_confirmation_variables
        )
    ):
        raise NativeQuoteError("quote_confirmation_changed")
    if (
        type(arguments) is not dict
        or set(arguments) - {"recipient", "body", "subject"}
        or type(arguments.get("recipient")) is not str
        or arguments["recipient"] != facts[recipient_variable]
        or type(arguments.get("body")) is not str
        or type(arguments.get("subject", "")) is not str
    ):
        raise NativeQuoteError("quote_delivery_arguments")
    private_url = prepared.validated.data().get("checkout_url")
    if _contains(confirmed, private_url):
        raise NativeQuoteError("quote_confirmation_private")
    if (
        type(private_url) is not str or not private_url
        or facts.get(policy.private_url_variable) != private_url
        or _URL.findall(arguments["body"]) != [private_url]
        or _contains(arguments.get("subject", ""), private_url)
        or _has_other_link(arguments["body"].replace(private_url, "", 1))
        or _has_other_link(arguments.get("subject", ""))
    ):
        raise NativeQuoteError("quote_delivery_url")
    return PreparedQuoteDelivery(
        prepared.validated, frozenset({policy.private_url_variable}), required,
    )


__all__ = [
    "NativeQuoteError", "NativeQuotePolicy", "PreparedNativeQuote",
    "PreparedQuoteDelivery", "prepare_quote", "prepare_quote_delivery",
    "validate_quote_configuration",
]

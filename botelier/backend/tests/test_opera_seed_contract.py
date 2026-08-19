import json
import re

from botelier.seeds.opera_integration import OPERA_CLOUD_INTEGRATION
from botelier.services.operation_publisher import (
    _build_llm_input_schema,
    normalize_operation_variables,
)


ENDPOINTS = OPERA_CLOUD_INTEGRATION["endpoints"]
CONNECTION_OWNED_TOKENS = {"hotel_id"}


def _template_tokens(endpoint: dict) -> set[str]:
    request_shape = {
        key: endpoint.get(key)
        for key in ("path", "query_params", "body_template")
    }
    return set(re.findall(r"\{\{(\w+)\}\}", json.dumps(request_shape)))


def test_all_opera_template_tokens_are_declared_or_connection_owned():
    failures = {}
    for endpoint in ENDPOINTS:
        variables = normalize_operation_variables(endpoint.get("variables"))
        declared = {variable["name"] for variable in variables}
        missing = _template_tokens(endpoint) - declared - CONNECTION_OWNED_TOKENS
        if missing:
            failures[endpoint["id"]] = sorted(missing)

    assert failures == {}


def test_all_opera_variables_have_unique_canonical_names_and_help_text():
    failures = {}
    for endpoint in ENDPOINTS:
        variables = normalize_operation_variables(endpoint.get("variables"))
        names = [variable["name"] for variable in variables]
        if len(names) != len(set(names)):
            failures.setdefault(endpoint["id"], []).append("duplicate names")
        for variable in variables:
            if not variable.get("description"):
                failures.setdefault(endpoint["id"], []).append(
                    f"{variable['name']}: missing description"
                )

    assert failures == {}


def test_required_query_templates_have_a_required_variable_or_default():
    failures = {}
    for endpoint in ENDPOINTS:
        variables = {
            variable["name"]: variable
            for variable in normalize_operation_variables(endpoint.get("variables"))
        }
        for query_param in endpoint.get("query_params") or []:
            if not query_param.get("required"):
                continue
            tokens = re.findall(r"\{\{(\w+)\}\}", str(query_param.get("value", "")))
            for token in tokens:
                variable = variables.get(token)
                if token in CONNECTION_OWNED_TOKENS:
                    continue
                if not variable or (
                    not variable.get("required") and variable.get("default") is None
                ):
                    failures.setdefault(endpoint["id"], []).append(token)

    assert failures == {}


def test_payment_card_fields_are_not_exposed_to_the_llm_schema():
    payment = next(
        endpoint
        for endpoint in ENDPOINTS
        if endpoint["id"] == "create_reservation_with_payment"
    )
    schema = _build_llm_input_schema(payment["variables"])

    for sensitive_name in ("card_holder", "card_number", "card_expiry", "card_cvv"):
        assert sensitive_name not in schema["properties"]


def test_availability_capability_maps_every_supported_input():
    availability = next(
        endpoint for endpoint in ENDPOINTS if endpoint["id"] == "check_availability"
    )
    assert availability["capability_params"] == {
        "check_in_date": "check_in_date",
        "check_out_date": "check_out_date",
        "guest_count": "guest_count",
        "children": "children",
        "room_type": "room_type",
    }
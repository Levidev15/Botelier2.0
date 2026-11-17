from urllib.parse import parse_qsl, urlsplit


def test_legacy_path_binding_requires_one_enabled_owned_endpoint():
    from botelier.voice.flows.native_actions import NativeActionRunner

    config = {"method": "GET", "path": "/search?query={{query}}"}
    parsed = urlsplit(config["path"])
    query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    endpoints = [
        {
            "id": "search-v1", "method": "GET", "path": "/search",
            "query_params": [{"key": "query", "required": True}],
        },
        {
            "id": "disabled", "method": "GET", "path": "/search",
            "enabled": False, "query_params": [{"key": "query"}],
        },
        {"id": "wrong-method", "method": "POST", "path": "/search"},
        {"id": "wrong-path", "method": "GET", "path": "/other"},
    ]

    matches = NativeActionRunner._matching_integration_endpoints(
        endpoints, config, "GET", parsed, query,
    )
    assert [item["id"] for item in matches] == ["search-v1"]

    ambiguous = endpoints + [{
        "id": "search-v2", "method": "GET", "path": "/search",
        "query_params": [{"key": "query", "required": True}],
    }]
    assert len(NativeActionRunner._matching_integration_endpoints(
        ambiguous, config, "GET", parsed, query,
    )) == 2

    arbitrary_query = urlsplit("/search?admin=true")
    assert NativeActionRunner._matching_integration_endpoints(
        endpoints, config, "GET", arbitrary_query,
        parse_qsl(arbitrary_query.query, keep_blank_values=True),
    ) == []


def test_legacy_path_binding_can_be_further_pinned_by_endpoint_id():
    from botelier.voice.flows.native_actions import NativeActionRunner

    config = {
        "method": "GET", "path": "/search?query={{query}}",
        "endpointId": "search-v2",
    }
    parsed = urlsplit(config["path"])
    query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    endpoints = [
        {
            "id": "search-v1", "method": "GET", "path": "/search",
            "query_params": [{"key": "query"}],
        },
        {
            "id": "search-v2", "method": "GET", "path": "/search",
            "query_params": [{"key": "query"}],
        },
    ]
    assert [
        item["id"] for item in NativeActionRunner._matching_integration_endpoints(
            endpoints, config, "GET", parsed, query,
        )
    ] == ["search-v2"]


def test_public_response_helper_preserves_falsy_values_and_projection():
    from botelier.voice.flows.native_actions import map_project_response

    mapped, projected = map_project_response(
        {
            "responseMapping": {
                "amount": "$.amount", "tax_included": "$.tax_included",
            },
            "responseProjection": {"fields": [{"variable": "amount"}]},
        },
        {"amount": 0, "tax_included": False},
        declared_variables={"amount", "tax_included"},
    )
    assert mapped == {"amount": 0, "tax_included": False}
    assert projected == {"amount": 0}


def test_mcp_schema_validation_preserves_falsy_values_and_rejects_unknown_fields():
    from botelier.voice.flows.native_actions import NativeActionRunner

    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "minimum": 0},
            "enabled": {"type": "boolean"},
        },
        "required": ["amount", "enabled"],
    }
    assert NativeActionRunner._validate_mcp_schema(
        schema, {"amount": 0, "enabled": False},
    ) is None
    result = NativeActionRunner._json_safe_mcp_value({
        "isError": False,
        "structuredContent": {"items": [0, False]},
        "content": [{"type": "image", "data": "base64"}],
    })
    assert result["structuredContent"] == {"items": [0, False]}
    assert result["content"] == [{"type": "image", "data": "base64"}]
    for invalid in (
        {"amount": 0},
        {"amount": "0", "enabled": False},
        {"amount": 1, "enabled": False, "unexpected": True},
        {"amount": 1, "enabled": 0},
    ):
        try:
            NativeActionRunner._validate_mcp_schema(schema, invalid)
        except ValueError:
            continue
        raise AssertionError(f"Invalid MCP args accepted: {invalid!r}")

import os

import pytest

os.environ.setdefault("NEXTAUTH_SECRET", "test-nextauth-secret")

from botelier.api import api_tester
from botelier.api.api_tester import ApiTestRequest
from botelier.api.flow_versions import validate_flow_config
from botelier.models.integration import IntegrationStatus
from botelier.services.integration_client import (
    APIErrorType,
    IntegrationAPIConfig,
    IntegrationClient,
    _MissingRequiredVariables,
)


ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class FakeResult:
    success = True
    status_code = 200
    data = {"guest": {"room": "214"}}
    latency_ms = 17
    error_message = None
    error_type = APIErrorType.SUCCESS
    extracted_variables = {"room": "214"}
    request_id = "req123"


@pytest.mark.asyncio
async def test_account_api_tester_uses_action_executor(monkeypatch):
    captured = {}

    def allow_access(*_args, **_kwargs):
        return None

    async def fake_execute_and_log(self, request):
        captured["request"] = request
        return FakeResult()

    monkeypatch.setattr(api_tester, "check_account_permission", allow_access)
    monkeypatch.setattr(api_tester.ActionExecutor, "execute_and_log", fake_execute_and_log)

    response = await api_tester.test_api_request(
        ApiTestRequest(
            account_id=ACCOUNT_ID,
            method="PATCH",
            url="https://api.example.com/guest",
            bodyTemplate='{"name": "{{guest_name}}"}',
            variables={"guest_name": "Ada"},
            responseMapping={"room": "guest.room"},
            sourceLabel="Guest lookup",
            nodeId="node_api",
            flowToolId="11111111-1111-1111-1111-111111111111",
        ),
        current_user=object(),
        db=object(),
    )

    request = captured["request"]
    assert request.context.account_id == ACCOUNT_ID
    assert request.context.channel == "test"
    assert request.context.node_id == "node_api"
    assert request.context.source_label == "Guest lookup"
    assert request.legacy_config["method"] == "PATCH"
    assert request.legacy_config["responseMapping"] == {"room": "guest.room"}
    assert response.success is True
    assert response.extracted_variables == {"room": "214"}


@pytest.mark.asyncio
async def test_integration_api_tester_preserves_headers_and_body(monkeypatch):
    captured = {}

    def allow_access(*_args, **_kwargs):
        return None

    class _Endpoint:
        id = "connection-id"
        status = IntegrationStatus.CONNECTED
        integration_type = type(
            "Type",
            (),
            {"get_endpoints": lambda _self: [{"id": "send", "method": "DELETE", "path": "/send"}]},
        )()

    class _Query:
        def filter(self, *_args):
            return self

        def first(self):
            return _Endpoint()

    class _Db:
        def query(self, *_args):
            return _Query()

    async def fake_execute_and_log(self, request):
        captured["request"] = request
        return FakeResult()

    monkeypatch.setattr(api_tester, "check_account_permission", allow_access)
    monkeypatch.setattr(api_tester.ActionExecutor, "execute_and_log", fake_execute_and_log)

    await api_tester.test_api_request(
        ApiTestRequest(
            account_id=ACCOUNT_ID,
            apiSource="integration",
            integrationId="connection-id",
            endpointId="send",
            url="https://api.example.test/send",
            headers={"Content-Type": "application/xml", "X-Trace": "test"},
            body="<remove id='7'/>",
            queryParamOverrides={"mode": "hard"},
        ),
        current_user=object(),
        db=_Db(),
    )

    config = captured["request"].integration_config
    assert config.method == "DELETE"
    assert config.body_template == "<remove id='7'/>"
    assert config.headers == {"Content-Type": "application/xml", "X-Trace": "test"}
    assert config.query_param_overrides == {"mode": "hard"}


def test_flow_validation_accepts_patch_without_requiring_successful_api_test():
    valid_flow = {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "api",
                "type": "api_request",
                "data": {
                    "name": "Patch guest",
                    "api": {
                        "method": "PATCH",
                        "url": "https://api.example.com/guest",
                        "bodyTemplate": '{"name": "{{guest_name}}"}',
                        "timeout": 8,
                        "retryCount": 0,
                        "responseMapping": {"room": "guest.room"},
                    },
                },
            },
        ],
        "edges": [{"source": "start", "target": "api"}],
        "variables": [
            {"key": "guest_name", "type": "text"},
            {"key": "room", "type": "text"},
        ],
    }

    is_valid, errors, _ = validate_flow_config(valid_flow)

    assert is_valid is True
    assert errors == []


def test_flow_validation_rejects_invalid_api_node_config():
    invalid_flow = {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "api",
                "type": "api_request",
                "data": {
                    "name": "Broken call",
                    "api": {
                        "method": "PATCH",
                        "url": "not-a-url",
                        "bodyTemplate": '{"bad":',
                        "timeout": 0,
                        "retryCount": 4,
                        "responseMapping": {"": ""},
                    },
                },
            },
        ],
        "edges": [{"source": "start", "target": "api"}],
    }

    is_valid, errors, _ = validate_flow_config(invalid_flow)

    assert is_valid is False
    assert any("invalid HTTP/HTTPS URL" in error for error in errors)
    assert any("request body must be valid JSON" in error for error in errors)
    assert any("timeout must be 1-60 seconds" in error for error in errors)
    assert any("retry count must be 0-3" in error for error in errors)
    assert any("incomplete response mapping" in error for error in errors)


def _publishable_branching_flow():
    return {
        "initial_node": "start",
        "variables": [
            {"key": "choice", "type": "text"},
            {"key": "name", "type": "text"},
            {"key": "result", "type": "text"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "collect",
                "type": "collect_slot",
                "data": {
                    "name": "Name",
                    "slot": {"variableKey": "name", "prompt": "What is your name?"},
                },
            },
            {
                "id": "condition",
                "type": "condition",
                "data": {
                    "name": "Has name",
                    "condition": {
                        "variable": "name",
                        "operator": "is_not_empty",
                        "value": "",
                        "trueTarget": "router",
                        "falseTarget": "done",
                    },
                },
            },
            {
                "id": "router",
                "type": "router",
                "data": {
                    "name": "Route",
                    "router": {
                        "variable": "choice",
                        "options": [
                            {"id": "book", "value": "book", "label": "Book"},
                            {"id": "stop", "value": "stop", "label": "Stop"},
                        ],
                    },
                },
            },
            {
                "id": "api",
                "type": "api_request",
                "data": {
                    "name": "Book",
                    "api": {
                        "method": "GET",
                        "url": "https://example.com/{{name}}",
                        "responseMapping": {"result": "$.result"},
                    },
                },
            },
            {"id": "done", "type": "end", "data": {"name": "Done"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect"},
            {"id": "e2", "source": "collect", "target": "condition"},
            {
                "id": "e3",
                "source": "condition",
                "sourceHandle": "true",
                "target": "router",
            },
            {
                "id": "e4",
                "source": "condition",
                "sourceHandle": "false",
                "target": "done",
            },
            {
                "id": "e5",
                "source": "router",
                "sourceHandle": "book",
                "target": "api",
            },
            {
                "id": "e6",
                "source": "router",
                "sourceHandle": "stop",
                "target": "done",
            },
            {"id": "e7", "source": "api", "target": "done"},
        ],
    }


def test_publish_validation_accepts_complete_declared_branching_flow():
    valid, errors, node_ids = validate_flow_config(_publishable_branching_flow())
    assert valid is True
    assert errors == []
    assert node_ids == []


def test_publish_validation_rejects_undeclared_references_and_broken_branches():
    flow = _publishable_branching_flow()
    flow["nodes"][1]["data"]["slot"]["variableKey"] = "missing_collect"
    flow["nodes"][2]["data"]["condition"]["variable"] = "missing_condition"
    flow["nodes"][3]["data"]["router"]["variable"] = "missing_router"
    flow["nodes"][4]["data"]["api"]["responseMapping"] = {
        "missing_mapping": "$.result"
    }
    flow["nodes"][4]["data"]["api"]["responseInstructions"] = (
        "Result: {{missing_template}}"
    )
    flow["edges"][2]["sourceHandle"] = "false"
    flow["edges"][4]["sourceHandle"] = "missing_option"

    valid, errors, node_ids = validate_flow_config(flow)

    assert valid is False
    assert any("missing_collect" in error for error in errors)
    assert any("missing_condition" in error for error in errors)
    assert any("missing_router" in error for error in errors)
    assert any("missing_mapping" in error for error in errors)
    assert any("missing_template" in error for error in errors)
    assert any("exactly one 'true' branch" in error for error in errors)
    assert any("invalid or missing branch sourceHandle" in error for error in errors)
    assert {"collect", "condition", "router", "api"}.issubset(set(node_ids))


def test_publish_validation_rejects_incoherent_confirmation_edit_config():
    flow = {
        "initial_node": "start",
        "variables": [{"key": "name", "type": "text"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "confirm",
                "type": "confirmation",
                "data": {
                    "name": "Confirm",
                    "confirmation": {
                        "summaryTemplate": "Name: {{name}}",
                        "confirmPrompt": "Is that correct?",
                        "variablesToConfirm": ["name", "missing"],
                        "allowEdit": True,
                    },
                },
            },
            {"id": "done", "type": "end", "data": {"name": "Done"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "confirm"},
            {"id": "e2", "source": "confirm", "target": "done"},
        ],
    }

    valid, errors, node_ids = validate_flow_config(flow)

    assert valid is False
    assert any("undeclared variable 'missing'" in error for error in errors)
    assert any("allows edits but has no edit prompt" in error for error in errors)
    assert "confirm" in node_ids


def test_publish_validation_accepts_one_legacy_confirmation_edge():
    flow = {
        "initial_node": "start",
        "variables": [{"key": "name", "type": "text"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "confirm",
                "type": "confirmation",
                "data": {
                    "name": "Confirm",
                    "confirmation": {
                        "summaryTemplate": "Name: {{name}}",
                        "confirmPrompt": "Correct?",
                        "editPrompt": "What should change?",
                        "variablesToConfirm": ["name"],
                        "allowEdit": True,
                    },
                },
            },
            {"id": "done", "type": "end", "data": {"name": "Done"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "confirm"},
            {"id": "legacy", "source": "confirm", "target": "done"},
        ],
    }

    valid, errors, _ = validate_flow_config(flow)

    assert valid is True
    assert errors == []

    # A second unlabelled destination makes the legacy intent ambiguous.
    flow["nodes"].append(
        {"id": "other", "type": "end", "data": {"name": "Other"}}
    )
    flow["edges"].append(
        {"id": "ambiguous", "source": "confirm", "target": "other"}
    )
    valid, errors, _ = validate_flow_config(flow)
    assert valid is False
    assert any("exactly one 'confirmed' branch" in error for error in errors)
    assert any("invalid or duplicate branch sourceHandles" in error for error in errors)

    # No outgoing path is not a legacy shape and must remain invalid.
    flow["edges"] = [edge for edge in flow["edges"] if edge["source"] != "confirm"]
    valid, errors, _ = validate_flow_config(flow)
    assert valid is False
    assert any("exactly one 'confirmed' branch" in error for error in errors)


def test_every_shipped_flow_template_has_structurally_declared_references():
    """Statically audit every built-in template listed by the editor store."""
    import pathlib
    import re

    store_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "frontend/components/flow-editor/store.ts"
    )
    source = store_path.read_text()
    registry = source[
        source.index("const TEMPLATES:") : source.index(
            "export const useFlowStore", source.index("const TEMPLATES:")
        )
    ]
    template_names = re.findall(
        r'^\s*"[^"]+":\s*([A-Z][A-Z0-9_]+_TEMPLATE)',
        registry,
        flags=re.MULTILINE,
    )
    assert template_names

    for template_name in template_names:
        start = source.index(f"const {template_name} =")
        end = source.index("\nconst ", start + 1)
        template = source[start:end]
        variables_block = template[
            template.index("variables: [") : template.index("nodes: [")
        ]
        declared = set(
            re.findall(
                r'{\s*key:\s*"([A-Za-z_][A-Za-z0-9_]*)"', variables_block
            )
        )
        assert len(declared) == len(
            re.findall(r'{\s*key:\s*"', variables_block)
        ), f"{template_name} has duplicate variable keys"

        mapping_blocks = re.findall(
            r"responseMapping:\s*{(.*?)}\s*,\s*autoMappingSource:",
            template,
            flags=re.DOTALL,
        )
        mapped = set()
        for block in mapping_blocks:
            mapped.update(
                re.findall(
                    r"^\s*([A-Za-z_][A-Za-z0-9_]*):",
                    block,
                    flags=re.MULTILINE,
                )
            )
        assert mapped <= declared, (
            f"{template_name} response mappings write undeclared variables: "
            f"{sorted(mapped - declared)}"
        )

        collected = set(re.findall(r'variableKey:\s*"([^"]+)"', template))
        routed = set(
            re.findall(
                r'(?:condition|router):\s*{.*?variable:\s*"([^"]+)"',
                template,
                flags=re.DOTALL,
            )
        )
        confirmed = set(
            re.findall(r'^\s{12}"([A-Za-z_][A-Za-z0-9_]*)",?$', template, re.MULTILINE)
        )
        placeholders = set(
            re.findall(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", template)
        )
        referenced = collected | routed | confirmed | placeholders
        assert referenced <= declared, (
            f"{template_name} references undeclared variables: "
            f"{sorted(referenced - declared)}"
        )

        node_ids = re.findall(r'^\s{6}id:\s*"([^"]+)"', template, re.MULTILINE)
        assert node_ids and len(node_ids) == len(set(node_ids)), (
            f"{template_name} has missing or duplicate node IDs"
        )
        edge_pairs = re.findall(
            r'source:\s*"([^"]+)".*?target:\s*"([^"]+)"', template
        )
        assert edge_pairs, f"{template_name} has no edges"
        assert all(
            source_id in node_ids and target_id in node_ids
            for source_id, target_id in edge_pairs
        ), f"{template_name} has an edge referencing a missing node"


class _FakeIntegrationType:
    auth_type = "basic_or_jwt"

    def get_auth_config(self):
        return {
            "base_url": "https://api.example.com",
            "basic_auth_query_params": [],
        }


class _FakeIntegration:
    def __init__(self, credentials=None):
        self.integration_type = _FakeIntegrationType()
        self._credentials = credentials or {}

    def get_credentials(self):
        return self._credentials


def _endpoint_def(query_params):
    return {"path": "/hotel_rooms", "query_params": query_params}


def _build_url(query_param_overrides, variables, query_params):
    client = IntegrationClient(ACCOUNT_ID, db=None)
    config = IntegrationAPIConfig(
        integration_id="int_1",
        endpoint_id="hotel_rooms",
        method="GET",
        path="/hotel_rooms",
        query_param_overrides=query_param_overrides,
    )
    return client._build_url(
        _FakeIntegration(),
        config,
        variables,
        endpoint_def=_endpoint_def(query_params),
    )


def test_query_param_override_replaces_seed_default():
    url = _build_url(
        query_param_overrides={"checkin": "2026-01-01"},
        variables={},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-01-01" in url


def test_query_param_seed_default_used_when_no_override():
    url = _build_url(
        query_param_overrides={},
        variables={"checkin": "2026-02-02"},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-02-02" in url


def test_empty_override_on_required_param_fails_fast():
    with pytest.raises(_MissingRequiredVariables) as exc:
        _build_url(
            query_param_overrides={"checkin": ""},
            variables={"checkin": "2026-02-02"},
            query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
        )
    assert "checkin" in str(exc.value)


def test_empty_override_on_optional_param_is_omitted():
    url = _build_url(
        query_param_overrides={"promo": ""},
        variables={"checkin": "2026-02-02"},
        query_params=[
            {"key": "checkin", "value": "{{checkin}}", "required": True},
            {"key": "promo", "value": "{{promo}}", "required": False},
        ],
    )
    assert "checkin=2026-02-02" in url
    assert "promo" not in url


def test_override_for_unknown_param_key_is_ignored():
    url = _build_url(
        query_param_overrides={"nonexistent": "ignored"},
        variables={"checkin": "2026-02-02"},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-02-02" in url
    assert "nonexistent" not in url
    assert "ignored" not in url


def test_connection_base_url_override_is_used_and_must_be_a_safe_origin():
    integration = _FakeIntegration()
    integration.get_connection_config = lambda: {"base_url": "https://sandbox.example.test"}
    client = IntegrationClient(ACCOUNT_ID, db=None)
    config = IntegrationAPIConfig(integration_id="int_1", method="GET", path="/ping")

    assert client._build_url(integration, config, {}) == "https://sandbox.example.test/ping"

    integration.get_connection_config = lambda: {
        "base_url": "https://user:pass@example.test?unsafe=yes"
    }
    with pytest.raises(ValueError, match="base URL"):
        client._build_url(integration, config, {})

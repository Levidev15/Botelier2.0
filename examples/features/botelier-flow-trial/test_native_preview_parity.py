"""Preview provider doubles must preserve the live broker's result contracts."""

import asyncio
from types import SimpleNamespace

import pytest

from botelier.voice.flows.native_action_preview import NativeActionPreview, NativePreviewResponse
from botelier.voice.flows.native_actions import NativeActionRunner


def _runner():
    runner = NativeActionRunner.__new__(NativeActionRunner)
    runner.preview = NativeActionPreview()
    return runner


@pytest.mark.parametrize("source", ["http", "integration"])
@pytest.mark.parametrize("status", [0, 500, 503])
@pytest.mark.parametrize("writing", [False, True])
def test_preview_preserves_unknown_write_outcomes_without_a_real_ledger(source, status, writing):
    runner = _runner()
    result = runner._map_preview_response(
        SimpleNamespace(node_id="lookup"), {}, NativePreviewResponse(status_code=status, data={}),
        {}, source, writing=writing,
    )
    prefix = "api" if source == "http" else "integration"
    assert not result.success
    assert result.failure_reason == ("effect_outcome_unknown" if writing else prefix + "_rejected")
    assert result.branch == "error"


@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("sample,read_reason", [
    (NativePreviewResponse(data={"isError": True, "content": []}), "mcp_tool_error"),
    (NativePreviewResponse(status_code=0, data={}), "mcp_request_failed"),
    (NativePreviewResponse(data={"isError": "false", "content": {}}), "mcp_request_failed"),
])
def test_mcp_preview_uses_the_same_protocol_and_unknown_write_boundary(writing, sample, read_reason):
    result = _runner()._map_preview_mcp_response(
        SimpleNamespace(node_id="lookup"), {}, sample, {}, writing=writing,
    )
    assert not result.success
    assert result.failure_reason == ("effect_outcome_unknown" if writing else read_reason)


def test_mcp_preview_keeps_the_actual_sdk_envelope_and_typed_mapping():
    result = _runner()._map_preview_mcp_response(
        SimpleNamespace(node_id="lookup"),
        {"responseProjection": {"fields": [{"variable": "rows"}]}},
        NativePreviewResponse(data={
            "isError": False, "structuredContent": {"rows": [{"price": 0, "available": False}]},
            "content": [{"type": "text", "text": "Read-only fixture"}],
        }),
        (SimpleNamespace(
            variable_key="rows", json_path="$.structuredContent.rows",
            has_default=False, required=True,
        ),), writing=False,
    )
    assert result.success
    assert result.variables == {"rows": [{"price": 0, "available": False}]}
    assert result.llm_data == {"rows": [{"price": 0, "available": False}]}


def test_message_preview_uses_the_canonical_receipt_not_arbitrary_sample_data():
    result = _runner()._map_preview_message_response(
        NativePreviewResponse(data={"status": "untrusted-provider-text", "private": "not-model-data"}),
        {"delivery_status": "accepted"}, {"delivery_status": "accepted"},
    )
    assert result.success
    assert result.variables == {"delivery_status": "accepted"}
    assert result.llm_data == {"delivery_status": "accepted"}
    result = _runner()._map_preview_message_response(
        NativePreviewResponse(status_code=0, data={}), {}, {},
    )
    assert result.failure_reason == "effect_outcome_unknown"


@pytest.mark.parametrize("source_kind", ["send_sms", "send_email"])
def test_delivery_preview_has_an_explicit_outcome_only_source_kind(source_kind):
    async def scenario():
        preview = NativeActionPreview()
        task = asyncio.create_task(preview.request(
            node_id="delivery", source_kind=source_kind, scope=("flow", "version", "visit"),
        ))
        await asyncio.sleep(0)
        pending = preview.snapshot()
        assert pending["source_kind"] == source_kind
        preview.submit(pending["request_id"], NativePreviewResponse(data={}))
        assert (await task).success
        preview.close()
    asyncio.run(scenario())


def test_preview_record_sources_are_scoped_by_flow_identity_not_just_node_name():
    preview = NativeActionPreview()
    first = ("account", "property", "flow-a", "version-a", "call")
    second = ("account", "property", "flow-b", "version-b", "call")
    preview.save_record("save", "type", {"guest": "A", "zero": 0}, "confirmed", scope=first)
    assert preview.get_record("save", scope=second) is None
    preview.save_record("save", "type", {"guest": "B", "zero": 0}, "confirmed", scope=second)
    assert preview.get_record("save", scope=first)["data"]["guest"] == "A"
    assert preview.get_record("save", scope=second)["data"]["guest"] == "B"
    preview.close()
    assert preview.get_record("save", scope=first) is None

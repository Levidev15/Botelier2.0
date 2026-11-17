"""The simulator's source-bound provider samples are not tool-call injection."""

import asyncio
import json

import pytest

from botelier.voice.flows.native_action_preview import (
    NativeActionPreview, NativePreviewError, NativePreviewResponse,
)


def test_sample_preserves_detached_json_types_and_status():
    data = {"rows": [{"children": 0, "available": False, "tax": "20.00"}], "missing": None}
    result = NativePreviewResponse(status_code=200, data=data)
    data["rows"].clear()
    assert result.success is True
    assert result.data == {"rows": [{"children": 0, "available": False, "tax": "20.00"}], "missing": None}
    result.data["rows"].clear()
    assert len(result.data["rows"]) == 1
    assert NativePreviewResponse(status_code=401, data={}).error_type == "auth_error"
    assert NativePreviewResponse(status_code=404, data={}).error_type == "not_found"
    assert NativePreviewResponse(status_code=0, data={}).error_type == "network_error"


def test_raw_json_sample_preserves_large_integer_ids_and_is_depth_bounded():
    result = NativePreviewResponse(
        status_code=200, data_json='{"reservation_id":9007199254740993}',
    )
    assert result.data["reservation_id"] == 9007199254740993
    assert type(result.data["reservation_id"]) is int
    deep = "[" * 65 + "0" + "]" * 65
    with pytest.raises(NativePreviewError):
        NativePreviewResponse(status_code=200, data_json=deep)


@pytest.mark.parametrize("kwargs", [
    {"status_code": True}, {"status_code": 100}, {"status_code": 600},
    {"status_code": 404, "success": True}, {"success": "true"},
    {"error_type": "arbitrary-provider-error"}, {"success": True, "error_type": "timeout"},
    {"data": {"number": float("nan")}}, {"data": {"large": "x" * 65_536}},
    {"data": {"not_json": object()}},
    {"data_json": "not-json"}, {"data_json": '{"value":NaN}'},
    {"data_json": '{"value":1e400}'}, {"data_json": "x" * 65_537},
    {"data": {}, "data_json": "{}"},
    {},
])
def test_invalid_samples_are_rejected_without_provider_access(kwargs):
    with pytest.raises(NativePreviewError):
        NativePreviewResponse(**kwargs)


def test_one_use_sample_is_bound_to_the_exact_waiting_action_and_session():
    async def scenario():
        changes = []
        preview = NativeActionPreview(on_change=lambda: changes.append(True))
        other = NativeActionPreview()
        first = asyncio.create_task(preview.request(
            node_id="availability", source_kind="http", scope=("flow-a", "version-a"),
        ))
        second = asyncio.create_task(other.request(
            node_id="availability", source_kind="http", scope=("flow-a", "version-a"),
        ))
        await asyncio.sleep(0)
        pending = preview.snapshot()
        assert set(pending) == {"request_id", "node_id", "source_kind", "expires_in_seconds"}
        assert pending["node_id"] == "availability" and not first.done()
        assert "version-a" not in json.dumps(pending)
        with pytest.raises(NativePreviewError, match="preview_request_mismatch"):
            other.submit(pending["request_id"], NativePreviewResponse(data={}))
        with pytest.raises(NativePreviewError, match="preview_request_mismatch"):
            preview.submit("old-request", NativePreviewResponse(data={}))
        assert not first.done()
        preview.submit(pending["request_id"], NativePreviewResponse(data={"rooms": []}))
        assert (await first).data == {"rooms": []}
        assert preview.snapshot() is None
        with pytest.raises(NativePreviewError, match="preview_request_mismatch"):
            preview.submit(pending["request_id"], NativePreviewResponse(data={}))
        next_request = asyncio.create_task(preview.request(
            node_id="availability", source_kind="http", scope=("flow-a", "version-a"),
        ))
        await asyncio.sleep(0)
        assert preview.snapshot()["request_id"] != pending["request_id"]
        preview.close()
        other.close()
        for task in (next_request, second):
            with pytest.raises(asyncio.CancelledError):
                await task
        assert changes and preview.snapshot() is None

    asyncio.run(scenario())


def test_close_busy_timeout_and_budget_do_not_leave_a_pending_future():
    async def scenario():
        preview = NativeActionPreview(timeout=0.02, max_requests=1)
        task = asyncio.create_task(preview.request(
            node_id="rooms", source_kind="mcp", scope=("flow", "version"),
        ))
        await asyncio.sleep(0)
        with pytest.raises(NativePreviewError, match="preview_busy"):
            await preview.request(node_id="other", source_kind="http", scope=("flow", "version"))
        with pytest.raises(NativePreviewError, match="preview_expired"):
            await task
        assert preview.snapshot() is None
        with pytest.raises(NativePreviewError, match="preview_budget"):
            await preview.request(node_id="rooms", source_kind="mcp", scope=("flow", "version"))
        preview.close()
        preview.close()
        with pytest.raises(NativePreviewError, match="preview_closed"):
            await preview.request(node_id="rooms", source_kind="mcp", scope=("flow", "version"))

    asyncio.run(scenario())


def test_preview_effects_are_metadata_only_detached_and_bounded():
    preview = NativeActionPreview()
    preview.record_effect("send_sms", "delivery")
    preview.record_effect("record_create", "save")
    assert preview.effects == [
        {"kind": "send_sms", "node_id": "delivery", "simulated": True},
        {"kind": "record_create", "node_id": "save", "simulated": True},
    ]
    preview.effects.clear()
    assert len(preview.effects) == 2
    with pytest.raises(NativePreviewError):
        preview.record_effect("send_real_payment", "pay")
    preview.close()
    assert preview.effects == []

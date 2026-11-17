"""Fast reference-graph validation before running the full SDK/ORM journey."""

import pytest

from native_booking_io import booking_definition


@pytest.mark.parametrize("mcp", [False, True])
@pytest.mark.parametrize("delivery", ["SEND_SMS", "SEND_EMAIL"])
def test_booking_reference_graph_uses_the_actual_current_compiler(mcp, delivery):
    from botelier.voice.flows.native_graph import compile_flow
    from test_native_graph import identity

    compiled = compile_flow(booking_definition(
        "synthetic-message-tool", "synthetic-record-type", delivery,
        mcp_id="synthetic-mcp" if mcp else None,
    ), identity())
    assert compiled.node("validate_quote").data()["api"]["capability"] == "validate_reservation_quote"
    assert compiled.node("delivery").data()["api"]["quoteDelivery"]["quoteNodeId"] == "validate_quote"
    assert compiled.node("save").data()["saveRecord"]["status"] == "link_accepted"

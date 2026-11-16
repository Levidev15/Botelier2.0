"""Characterize the legacy public flow-template builder and outputs."""

import hashlib
import json

import pytest

from botelier.voice.flows.engine import FlowNodeBuilder
from botelier.voice.flows import FlowTemplates as PublicFlowTemplates
from botelier.voice.flows.templates import FlowTemplates


TEMPLATE_IDS = ("faq_bot", "booking_flow", "transfer_flow", "concierge_flow")


def canonical_digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_flow_node_builder_preserves_fluent_node_shape():
    node = (
        FlowNodeBuilder("collect_guest", "Collect Guest")
        .with_role_message("Use the hotel knowledge base.")
        .with_task_message("Ask for the guest name.")
        .with_function(
            "save_guest",
            "Save a guest name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            transition_to="confirmation",
        )
        .with_function("continue", "Continue without arguments.")
        .build()
    )
    assert node == {
        "name": "Collect Guest",
        "role_messages": [
            {"role": "system", "content": "Use the hotel knowledge base."},
        ],
        "task_messages": [
            {"role": "system", "content": "Ask for the guest name."},
        ],
        "functions": [
            {
                "name": "save_guest",
                "description": "Save a guest name.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "transition_to": "confirmation",
            },
            {
                "name": "continue",
                "description": "Continue without arguments.",
                "parameters": {
                    "type": "object", "properties": {}, "required": [],
                },
            },
        ],
    }
    assert (
        FlowNodeBuilder("end", "End")
        .as_end_node()
        .build()
    ) == {
        "name": "End",
        "role_messages": [],
        "task_messages": [],
        "functions": [],
        "is_end_node": True,
    }


def test_flow_template_list_and_every_route_configuration_keep_their_baseline():
    metadata = FlowTemplates.list_templates()
    assert [item["id"] for item in metadata] == list(TEMPLATE_IDS)
    assert [item["nodes_count"] for item in metadata] == [2, 5, 3, 7]

    # These checksums cover every field, node, edge, function, and position in
    # each config returned by the public template getter, not just its shape.
    expected_config_digests = {
        "faq_bot": "81127629e5837d74254333c63bab553eba61805d74e6f319572fe50b65516fd4",
        "booking_flow": "6c4999c76e249dfb1f8aef278bafd214d81587065253cade96c25deca9d84843",
        "transfer_flow": "fd39e9d5901e934cd92629bf1db1ad04a37d84825c7aa06a6e98120381b229cf",
        "concierge_flow": "12ec89ce577ff5de193c90e7513c9434d0b4424a59f7d7f8c3c48871cad2d235",
    }
    actual_config_digests = {
        template_id: canonical_digest(FlowTemplates.get_template(template_id))
        for template_id in TEMPLATE_IDS
    }
    assert actual_config_digests == expected_config_digests

    # The list endpoint returns this metadata verbatim; the detail endpoint
    # merges the matching metadata with the complete getter result.
    expected_metadata_digest = "21fe7129fb0a67b2c55c0ba8c5743341eb676080645a18c1916a1c8f81014203"
    expected_detail_digests = {
        "faq_bot": "060c6f6fc23638030625e0145703bebcf5d1da09848676a403816aac84863846",
        "booking_flow": "6b42d0a71985074cb3f25e20e07e0aacedb3bb19adcf8523365bae2d2fcf03bb",
        "transfer_flow": "c770cb0e5fba0c3f22a794dcc7836c7e7bad8e6f928868fe3d511372c8901d20",
        "concierge_flow": "ac999e93ae276177cf6d3acca4af812b09fd97ee236d32b7c447b5c2d96f3268",
    }
    assert canonical_digest(metadata) == expected_metadata_digest
    actual_detail_digests = {
        item["id"]: canonical_digest({
            **item, "flow_config": FlowTemplates.get_template(item["id"]),
        })
        for item in metadata
    }
    assert actual_detail_digests == expected_detail_digests


@pytest.mark.parametrize("unknown_name", ["", "unknown", "FAQ_BOT"])
def test_unknown_template_names_keep_the_faq_fallback(unknown_name):
    assert FlowTemplates.get_template(unknown_name) == FlowTemplates.faq_bot()


def test_package_export_keeps_the_public_templates_without_the_retired_controller():
    import botelier.voice.flows as flows

    assert PublicFlowTemplates is FlowTemplates
    assert flows.__all__ == ["FlowTemplates"]
    assert not hasattr(flows, "BoteilerFlowEngine")

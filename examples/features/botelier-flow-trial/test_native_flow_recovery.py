"""Persisted native-flow recovery tests against the actual scoped ORM model."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest

from native_effect_io import NativeEffectsFixture


def test_native_flow_snapshot_orm_roundtrip_scope_and_stale_update():
    async def scenario():
        from botelier.services.native_flow_recovery import (
            NativeFlowRecoveryError, NativeFlowSnapshotStore,
        )

        async with NativeEffectsFixture() as fixture:
            model = fixture.effect_models["FlowSession"]
            store = NativeFlowSnapshotStore(fixture.factory, model)
            identity = {
                "account_id": str(fixture.account_id),
                "property_id": str(fixture.property_id),
                "tool_id": "00000000-0000-0000-0000-000000000104",
                "flow_version_id": str(fixture.models["version_id"]),
                "call_sid": "CAoffline-native-recovery",
            }
            snapshot = {
                "schema_version": 1,
                "root": deepcopy(identity),
                "active": {
                    **identity,
                    "source_digest": "a" * 64,
                },
                "source_digest": "b" * 64,
                "current_node_id": "collect_guest",
                "node_revision": 4,
                "state": "active",
                "catalog_active": False,
                "awaiting_flow_choice": False,
                "caller_facts": {"guest": "Avery"},
                "fact_provenance": {"guest": "caller"},
            }
            assert store.save(snapshot, 0) == 1
            loaded = store.load_pinned(
                call_sid=identity["call_sid"],
                account_id=identity["account_id"],
                property_id=identity["property_id"],
                assigned_tool_ids=[identity["tool_id"]],
            )
            assert loaded["revision"] == 1
            assert loaded["current_node_id"] == "collect_guest"
            assert loaded["fact_provenance"] == {"guest": "caller"}

            changed = deepcopy(loaded)
            changed["current_node_id"] = "confirm"
            changed["node_revision"] = 5
            assert store.save(changed, 1) == 2
            with pytest.raises(NativeFlowRecoveryError, match="stale_update"):
                store.save(loaded, 1)

            with pytest.raises(NativeFlowRecoveryError, match="scope_mismatch"):
                store.load_pinned(
                    call_sid=identity["call_sid"],
                    account_id=str(UUID("00000000-0000-0000-0000-000000000999")),
                    property_id=identity["property_id"],
                    assigned_tool_ids=[identity["tool_id"]],
                )
            with pytest.raises(NativeFlowRecoveryError, match="scope_mismatch"):
                store.load_pinned(
                    call_sid=identity["call_sid"],
                    account_id=identity["account_id"],
                    property_id=identity["property_id"],
                    assigned_tool_ids=["00000000-0000-0000-0000-000000000999"],
                )
            terminal = deepcopy(changed)
            terminal["state"] = "complete"
            terminal["terminal_state"] = {
                "status": "completed", "outcome": "completed",
                "failure_reason": None,
            }
            assert store.save(terminal, 2) == 3
            db = fixture.factory()
            try:
                rows = db.query(model).all()
                assert len(rows) == 1
                assert rows[0].flow_version_id == UUID(identity["flow_version_id"])
                assert rows[0].current_node_id == "confirm"
                assert rows[0].status == "complete"
            finally:
                db.close()

    asyncio.run(scenario())

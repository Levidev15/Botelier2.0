import asyncio
import uuid


def test_legacy_connection_resolves_unique_enabled_endpoint_from_owned_metadata():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.integration import (
                AccountIntegration, IntegrationStatus, IntegrationType,
            )
            from botelier.models.operation_policy import ConnectionOperationPolicy
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow

            connection_id = uuid.uuid4()
            integration_type_id = uuid.uuid4()
            db = fixture.factory()
            integration_type = IntegrationType(
                id=integration_type_id, slug="owned-search",
                name="Owned search", provider="fixture", auth_type="none",
                is_enabled=True, origin="customer_imported",
            )
            integration_type.set_endpoints([
                {
                    "id": "search-enabled", "method": "GET", "path": "/search",
                    "query_params": [{"key": "query", "required": True}],
                },
                {
                    "id": "search-disabled", "method": "GET", "path": "/search",
                    "query_params": [{"key": "query", "required": True}],
                },
            ])
            connection = AccountIntegration(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                integration_type_id=integration_type_id,
                property_id=uuid.UUID(fixture.property_id),
                status=IntegrationStatus.CONNECTED,
                connection_config='{"base_url":"https://api.fixture.invalid"}',
            )
            db.add_all([integration_type, connection])
            db.add_all([
                ConnectionOperationPolicy(
                    account_integration_id=connection_id,
                    operation_id="search-enabled", enabled=True,
                    risk_level="read", allowed_channels=["voice"],
                    test_status="passed", test_passed=True,
                    response_mapping={"price": "$.price"},
                ),
                ConnectionOperationPolicy(
                    account_integration_id=connection_id,
                    operation_id="search-disabled", enabled=False,
                    risk_level="read", allowed_channels=["voice"],
                    test_status="passed", test_passed=True,
                ),
            ])
            db.commit()
            db.close()

            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "query", "type": "text"},
                    {"key": "price", "type": "number"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "lookup", "type": "api_request", "data": {"api": {
                        "apiSource": "integration", "integrationId": str(connection_id),
                        "method": "GET", "path": "/search?query={{query}}",
                        "responseMapping": {"price": "$.price"},
                    }}},
                ],
                "edges": [
                    {"id": "start-lookup", "source": "start", "target": "lookup"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            api = compiled.node("lookup").data()["api"]
            resolved, response_policy, risk, mapping, confirm_required = (
                runner._resolve_integration_config(api, "GET", {}, None)
            )
            assert resolved.endpoint_id == "search-enabled"
            assert resolved.path == "/search"
            assert resolved.query_param_overrides == {"query": "{{query}}"}
            assert response_policy["enabled"] is True
            assert risk == "read"
            assert mapping == {"price": "$.price"}
            assert confirm_required is False
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview = await preview_runner.execute(
                compiled.node("lookup"), {"query": "standard"},
            )
            assert preview.failure_reason == "preview_required"
            simulation_runner = NativeActionRunner(
                compiled, fixture.factory, channel="simulation",
            )
            simulation = await simulation_runner.execute(
                compiled.node("lookup"), {"query": "standard"},
            )
            assert simulation.failure_reason == "integration_policy_rejected"

            db = fixture.factory()
            second_policy = db.query(ConnectionOperationPolicy).filter(
                ConnectionOperationPolicy.account_integration_id == connection_id,
                ConnectionOperationPolicy.operation_id == "search-disabled",
            ).first()
            second_policy.enabled = True
            db.add(second_policy)
            db.commit()
            db.close()
            try:
                runner._resolve_integration_config(api, "GET", {}, None)
            except PermissionError:
                pass
            else:
                raise AssertionError("Ambiguous enabled endpoint binding was accepted")

    asyncio.run(scenario())

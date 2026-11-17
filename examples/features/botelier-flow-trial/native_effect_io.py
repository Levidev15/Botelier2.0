"""Explicit disposable storage for native action/record contract tests.

Only editor_guard's in-memory SQLite storage is used. Authentication, model
definitions and business methods remain actual source; there is no live DB.
"""

from editor_fixture import EditorASGIFixture


class NativeEffectsFixture(EditorASGIFixture):
    async def __aenter__(self):
        await super().__aenter__()
        from botelier import database
        from botelier.models.call_log import CallLog
        from botelier.models.integration import (
            AccountIntegration, AccountSecret, IntegrationAction,
            IntegrationActionInvocation, IntegrationActionVersion,
            IntegrationCallLog, IntegrationType,
        )
        from botelier.models.mcp_connection import MCPConnection
        from botelier.models.operation_idempotency import OperationIdempotency
        from botelier.models.operation_policy import ConnectionOperationPolicy
        from botelier.models.record import Record
        from botelier.models.record_type import RecordType

        self.effect_models = {
            cls.__name__: cls for cls in (
                CallLog, AccountIntegration, AccountSecret, IntegrationAction,
                IntegrationActionInvocation, IntegrationActionVersion,
                IntegrationCallLog, IntegrationType, MCPConnection,
                OperationIdempotency, ConnectionOperationPolicy, Record, RecordType,
            )
        }
        database.Base.metadata.create_all(
            self.engine, tables=[model.__table__ for model in self.effect_models.values()],
        )
        return self

    @property
    def identity(self):
        from botelier.voice.flows.pilot_contract import PilotIdentity

        return PilotIdentity(
            account_id=self.account_id, property_id=self.property_id,
            tool_id=self.tool_id, flow_version_id=str(self.models["version_id"]),
            call_sid="CAoffline-native-effects",
        )

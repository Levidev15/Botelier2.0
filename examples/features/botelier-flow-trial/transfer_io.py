"""Synthetic carrier HTTP/storage boundaries; real mapper, SDK and worker.

These fixtures do not certify database billing, authenticated callbacks or
actual carrier behavior. All telephone numbers and credentials are synthetic.
"""

import asyncio
import base64
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import guard
import requests

from application_support import load_function_mapper
from lifecycle_io import CALL_SID, STREAM_SID, Records
from lifecycle_support import OfflineCall
from transcript_io import TranscriptProviders
from transcript_tools import tool_reply
from transfer_storage import MemoryTransferStorage


ACCOUNT_SID = "AC" + "0" * 32
RECORDING_SID = "RE" + "0" * 32
TOKEN = "offline-not-a-credential"
DESTINATION = "+15555550123"
CALLER_ID = "+15555550124"
BASE_URL = "https://offline.invalid"
ANNOUNCEMENT = "Please hold while I connect you to the fixture team."
RESUME_ANSWER = "I can help with another fixture request."


class TransferRecords(Records):
    def __init__(self, *, recording, entitled):
        super().__init__()
        self.assistant.call_settings = {"call_recording_enabled": recording}
        self.rows["Account"] = SimpleNamespace(
            name="Fixture account", twilio_sub_account_sid=ACCOUNT_SID,
            twilio_sub_auth_token=TOKEN, subscription_tier="free",
            feature_flags={"call_recording": entitled},
        )
        self.call.has_transfer = False
        self.call.flow_name = None
        self.call.flow_id = None
        self.call.tool_name = None
        self.rows["Tool"] = None
        # Deliberately disabled external ACW/extraction boundaries. No real
        # account is eligible for background business processing in this fixture.
        self.call.assistant_id = None
        self.call.account_id = None
        self.transfers = []
        self.timeline = []
        self.fail_transfer_write = False

    def record_transfer(self, **values):
        assert values["call_sid"] == CALL_SID
        assert values["transfer_to"] == DESTINATION
        assert values["transfer_type"] in ("warm", "cold", "external")
        if self.fail_transfer_write:
            raise RuntimeError("Synthetic transfer persistence failure")
        self.timeline.append("record-transfer")
        self.transfers.append(values)
        self.call.has_transfer = True
        return True

    def complete_call(self, logger, **values):
        self.timeline.append("save-transcript")
        return super().complete_call(logger, **values)


class CarrierHTTP:
    """Intercept requests only at Session.send; SDK encoding/parsing stays real."""

    def __init__(
        self, records, *, outcome=200, stop_outcome=200, start_outcome=201,
        hold_start=False, hold_transfer=False,
    ):
        self.records = records
        self.outcome = outcome
        self.stop_outcome = stop_outcome
        self.start_outcome = start_outcome
        self.start_gate = threading.Event()
        self.transfer_gate = threading.Event()
        if not hold_start:
            self.start_gate.set()
        if not hold_transfer:
            self.transfer_gate.set()
        self.started = threading.Event()
        self.updated = threading.Event()
        self.requests = []
        self.timeouts = []
        self.loop_thread = threading.get_ident()

    def send(self, request, **kwargs):
        assert threading.get_ident() != self.loop_thread, "Carrier HTTP blocked the event loop"
        prefix = (
            f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}"
            f"/Calls/{CALL_SID}"
        )
        if request.method != "POST" or not request.url.startswith(prefix):
            guard.deny("unexpected_transfer_http_destination")
        expected_auth = "Basic " + base64.b64encode(
            f"{ACCOUNT_SID}:{TOKEN}".encode()
        ).decode()
        assert request.headers["Authorization"] == expected_auth
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        data = parse_qs(body)
        self.requests.append((request.url, data))
        self.timeouts.append(kwargs.get("timeout"))
        payload = {
            "account_sid": ACCOUNT_SID, "call_sid": CALL_SID,
            "api_version": "2010-04-01", "sid": CALL_SID,
            "status": "in-progress", "direction": "inbound",
            "from": CALLER_ID, "to": DESTINATION, "duration": None,
        }
        if request.url == prefix + "/Recordings.json":
            assert data == {
                "RecordingChannels": ["dual"],
                "RecordingStatusCallback": [BASE_URL + "/api/calls/recording-status"],
                "RecordingStatusCallbackMethod": ["POST"],
            }
            assert kwargs["timeout"] == 10
            self.records.timeline.append("start-recording")
            self.started.set()
            assert self.start_gate.wait(8), "Fixture recording gate was never released"
            status = self.start_outcome
            payload.update(sid=RECORDING_SID, channels=2, status="in-progress")
            if status == "timeout":
                raise requests.Timeout("Synthetic recording timeout")
            if status == "invalid-json":
                status = 201
                payload = None
        elif request.url == prefix + f"/Recordings/{RECORDING_SID}.json":
            assert data == {"Status": ["stopped"]}
            self.records.timeline.append("stop-recording")
            status = self.stop_outcome
            payload.update(sid=RECORDING_SID, channels=2, status="stopped")
        elif request.url == prefix + ".json":
            assert set(data) == {"Twiml"}
            self.records.timeline.append("update-transfer")
            assert self.transfer_gate.wait(8), "Fixture transfer gate was never released"
            status = self.outcome
            if status == "timeout":
                self.updated.set()
                raise requests.Timeout("Synthetic carrier update timeout")
            self.records.timeline.append("transfer-http-result")
            self.updated.set()
        else:
            guard.deny("unexpected_transfer_http_operation")
        if status >= 400:
            payload = {
                "status": status, "code": 20001,
                "message": "Synthetic carrier rejected the request.",
                "more_info": "https://offline.invalid/carrier-error",
            }
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = b"not-json" if payload is None else json.dumps(payload).encode()
        return response

    def release(self):
        # Emergency cleanup only; passing ordering tests release explicitly.
        self.start_gate.set()
        self.transfer_gate.set()


class TransferCall(OfflineCall):
    def __init__(
        self, *, mode="warm", source="tool", recording=False, entitled=True,
        outcome=200, stop_outcome=200, start_outcome=201,
        hold_start=False, hold_transfer=False, hold_announcement=False,
        with_preface=True,
        credentials=True,
        transfer_storage=None,
    ):
        name = "transfer_fixture" if source == "tool" else "transfer_handoff"
        providers = TranscriptProviders(
            [
                tool_reply(name, text=ANNOUNCEMENT if source == "flow" and with_preface else None),
                RESUME_ANSWER,
            ],
            hold_tts_turn=2 if hold_announcement else None,
        )
        super().__init__(providers=providers, tool_setup=self.transfer_tools)
        self.mode, self.source = mode, source
        self.credentials = credentials
        self.records = TransferRecords(recording=recording, entitled=entitled)
        self.http = CarrierHTTP(
            self.records, outcome=outcome, stop_outcome=stop_outcome,
            start_outcome=start_outcome, hold_start=hold_start,
            hold_transfer=hold_transfer,
        )
        self.mapper = None
        self.transfer_storage = transfer_storage or MemoryTransferStorage()

    def transfer_tools(self, call):
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        module = load_function_mapper()
        mapper = module.FunctionMapper(
            call_sid=CALL_SID, stream_sid=STREAM_SID,
            to_number=CALLER_ID, from_number=CALLER_ID,
            twilio_account_sid=ACCOUNT_SID, twilio_auth_token=TOKEN,
            call_handler=self.handler, account_id="00000000-0000-0000-0000-000000000001",
            session_factory=self.transfer_storage,
        )
        self.mapper = mapper
        if not self.credentials:
            mapper.twilio_client = None
        self.handler.call_mappers[CALL_SID] = mapper
        if self.source == "tool":
            tool = module.Tool(
                name="transfer_fixture", description="Transfer to the fixture team.",
                config={
                    "phone_number": DESTINATION, "transfer_mode": self.mode,
                    "pre_transfer_message": ANNOUNCEMENT,
                },
            )
            schema, handler = mapper._map_transfer_call(tool)
            schemas, handlers = [schema], {schema["name"]: handler}
        else:
            from botelier.flow_executor import FlowExecutor, parse_flow_config

            config = {
                "initial_node": "handoff", "variables": [], "edges": [],
                "nodes": [{
                    "id": "handoff", "type": "transfer",
                    "data": {"transfer": {
                        "phoneNumber": DESTINATION, "transferMode": self.mode,
                        "preTransferMessage": ANNOUNCEMENT,
                    }},
                }],
            }
            executor = FlowExecutor(parse_flow_config(config))
            # A synthetic flow already positioned at its handoff. This is not
            # evidence of controller ordering or graph-start authorization.
            executor.state.advance_to("handoff")
            mapper._flow_executors["fixture"] = executor
            raw, handlers = mapper.get_flow_functions(SimpleNamespace(
                id="offline-flow", name="fixture", config=config, description="Handoff fixture",
            ))
            schemas = [item["function"] for item in raw]
        return [
            FunctionSchema(
                name=item["name"], description=item["description"],
                properties=item["parameters"].get("properties", {}),
                required=item["parameters"].get("required", []),
            )
            for item in schemas
        ], {
            name: mapper.wrap_with_timestamp(name, handler)
            for name, handler in handlers.items()
        }

    async def __aenter__(self):
        module = load_function_mapper()
        from botelier.config import domain

        def send(session, request, **kwargs):
            return self.http.send(request, **kwargs)

        self.patches.enter_context(patch.object(requests.Session, "send", send))
        self.patches.enter_context(patch.object(
            self.module.CallLogger, "record_transfer",
            lambda logger, **values: self.records.record_transfer(**values),
        ))
        self.patches.enter_context(patch.object(domain, "get_public_base_url", lambda: BASE_URL))
        self.patches.enter_context(patch.object(module, "get_public_base_url", lambda: BASE_URL))
        return await super().__aenter__()

    def acknowledge(self, name):
        self.carrier.incoming.put_nowait({
            "type": "websocket.receive",
            "text": json.dumps({
                "event": "mark", "streamSid": STREAM_SID, "mark": {"name": name},
            }),
        })

    def marks(self):
        return [
            item for item in self.carrier.wire_messages()
            if item.get("event") == "mark"
        ]

    async def __aexit__(self, *exc):
        self.http.release()
        await super().__aexit__(*exc)

"""Synthetic frame/context boundaries for the general native graph adapter."""

from copy import deepcopy
import json

from pipecat.frames.frames import LLMMessagesAppendFrame, LLMMessagesUpdateFrame, LLMSetToolsFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams


class _Events:
    def __init__(self):
        self.events = {}

    def event_handler(self, name):
        def register(handler):
            self.events.setdefault(name, []).append(handler)
            return handler
        return register

    def install_context_admission(self, admission):
        self.context_admission = admission


class _User(_Events):
    def __init__(self, context):
        super().__init__()
        self._context = self.context = context


class _ContextAggregator(_Events):
    def __init__(self):
        super().__init__()
        self._context = LLMContext()
        self._user = _User(self._context)

    def user(self):
        return self._user

    def assistant(self):
        return self

    @property
    def has_function_calls_in_progress(self):
        return False


class _Worker(_Events):
    def __init__(self):
        super().__init__()
        self.context = LLMContext()
        self.tools = {}
        self.frames = []
        self.finished = False
        self.filters = []

    def set_reached_downstream_filter(self, frame_types):
        self.filters = [frame_types]

    def add_reached_downstream_filter(self, frame_types):
        self.filters.append(frame_types)

    def has_finished(self):
        return self.finished

    async def queue_frame(self, frame, direction=None):
        self.frames.append(frame)
        if isinstance(frame, LLMMessagesUpdateFrame):
            self.context.set_messages(deepcopy(frame.messages))
        elif isinstance(frame, LLMMessagesAppendFrame):
            self.context.add_messages(deepcopy(frame.messages))
        elif isinstance(frame, LLMSetToolsFrame):
            self.context.set_tools(frame.tools)
            self.tools = {
                item.name: item for item in getattr(frame.tools, "standard_tools", ())
            }

    async def queue_frames(self, frames, direction=None):
        for frame in frames:
            await self.queue_frame(frame, direction)


class GraphCall:
    """A real FlowManager over a deterministic frame/context boundary."""

    def __init__(self, compiled, **adapter_args):
        from botelier.voice.flows.native_adapter import NativeFlowAdapter

        self.worker = _Worker()
        self.llm = _Events()
        self.context_aggregator = _ContextAggregator()
        self.adapter = NativeFlowAdapter(
            compiled, llm=self.llm, worker=self.worker,
            context_aggregator=self.context_aggregator, **adapter_args,
        )
        self.results = []
        self._call_count = 0

    async def invoke(self, name, arguments):
        schema = self.worker.tools[name]
        return await self.invoke_schema(schema, arguments)

    async def invoke_schema(self, schema, arguments):
        call_id = f"graph-call-{self._call_count}"
        self._call_count += 1

        async def result_callback(result, *, properties=None):
            self.results.append(deepcopy(result))
            self.context_aggregator._context.add_message({
                "role": "tool", "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            })
            if properties and properties.on_context_updated:
                await properties.on_context_updated()

        await schema.handler(FunctionCallParams(
            function_name=schema.name, tool_call_id=call_id, arguments=arguments,
            llm=self.llm, pipeline_worker=self.worker,
            context=self.context_aggregator._context, result_callback=result_callback,
        ))
        return self.results[-1]

    def user_turn(self, text):
        self.context_aggregator._context.add_message({"role": "user", "content": text})


def simple_flow_config():
    return {
        "initial_node": "start",
        "variables": [{"key": "name", "type": "text"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {
                "systemPrompt": "Keep the greeting private guidance.",
                "greeting": "Welcome to the fixture.", "waitForResponse": False,
            }},
            {"id": "name", "type": "collect_slot", "data": {
                "slot": {"variableKey": "name", "prompt": "What is your name?",
                         "maxRetries": 1},
            }},
            {"id": "done", "type": "end", "data": {
                "closingMessage": "Thanks, {{name}}.",
            }},
        ],
        "edges": [
            {"id": "start-name", "source": "start", "target": "name"},
            {"id": "name-done", "source": "name", "target": "done"},
        ],
    }


def compile_simple_flow():
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    return compile_flow(simple_flow_config(), PilotIdentity(
        account_id="fixture-account", property_id="fixture-property",
        tool_id="fixture-flow", flow_version_id="fixture-version",
        call_sid="fixture-call",
    ))


def full_catalog_config():
    """Connected fixture exercising the catalog, branch, form and action paths."""
    def node(node_id, kind, data):
        return {"id": node_id, "type": kind, "data": data}

    def edge(source, target, handle=None):
        item = {"id": f"{source}-{handle or 'default'}-{target}",
                "source": source, "target": target}
        if handle is not None:
            item["sourceHandle"] = handle
        return item

    return {
        "initial_node": "start",
        "globalPrompt": "Private fixture policy; do not quote it.",
        "variables": [
            {"key": "query", "type": "text"},
            {"key": "name", "type": "text"},
            {"key": "email", "type": "email"},
            {"key": "channel", "type": "choice", "choices": ["lookup", "skip"]},
            {"key": "derived", "type": "text"},
            {"key": "items", "type": "text"},
            {"key": "selected_name", "type": "text"},
            {"key": "selected_price", "type": "number"},
        ],
        "nodes": [
            node("start", "initial", {
                "systemPrompt": "Private initial policy.", "greeting": "Welcome.",
                "waitForResponse": False,
            }),
            node("query", "collect_slot", {"slot": {
                "variableKey": "query", "prompt": "What should I search for?",
            }}),
            node("form", "collect_form", {"introMessage": "A few details.",
                "slots": [
                    {"id": "form-name", "order": 0, "variableKey": "name",
                     "prompt": "Your name?", "type": "text"},
                    {"id": "form-email", "order": 1, "variableKey": "email",
                     "prompt": "Your email?", "type": "email"},
                ]}),
            node("derive", "set_variable", {"setVariable": {
                "variableKey": "derived", "valueType": "template", "value": "{{name}}",
            }}),
            node("channel", "set_variable", {"setVariable": {
                "variableKey": "channel", "valueType": "static", "value": "lookup",
            }}),
            node("check_name", "condition", {"condition": {
                "variable": "name", "operator": "is_not_empty", "value": "",
            }}),
            node("router", "router", {"router": {
                "variable": "channel", "options": [
                    {"id": "search", "value": "lookup", "label": "Search"},
                    {"id": "skip", "value": "skip", "label": "Skip"},
                ],
            }}),
            node("lookup", "api_request", {"api": {
                "apiSource": "custom", "method": "GET",
                "url": "https://fixture.invalid/items",
                "thinkingMessage": "Checking fixture options.",
                "onSuccess": "The lookup succeeded.",
                "onError": "The lookup could not complete.",
                "onAuthError": "The fixture rejected authorization.",
                "responseInstructions": "Privately present results for {{name}}.",
                "responseMapping": {"items": "$.items"},
                "timeout": 2, "retryCount": 0,
            }}),
            node("present", "api_response", {"responsePresentation": {
                "arrayVariable": "items", "introText": "Available options.",
                "itemTemplate": "{{index}}. {{name}} costs {{price}}.",
                "outroText": "", "noResultsText": "No fixture options.",
            }}),
            node("picker", "option_picker", {"optionPicker": {
                "sourceVariable": "items", "labelPath": "name",
                "prompt": "Which room?", "retryPrompt": "Choose one listed room.",
                "maxRetries": 2, "writes": [
                    {"variableKey": "selected_name", "path": "name"},
                    {"variableKey": "selected_price", "path": "price"},
                ],
            }}),
            node("confirm", "confirmation", {"confirmation": {
                "summaryTemplate": "Choose {{selected_name}} for {{selected_price}}.",
                "confirmPrompt": "Should I proceed?", "editPrompt": "What name should I use?",
                "variablesToConfirm": ["name", "selected_price"],
                "allowEdit": True, "deliveryMode": "static",
            }}),
            node("correct", "collect_slot", {"slot": {
                "variableKey": "name", "prompt": "What is the corrected name?",
            }}),
            node("capability", "capability", {"api": {
                "apiSource": "capability", "capability": "fixture.reserve",
                "onSuccess": "The synthetic action succeeded.",
                "onError": "The synthetic action failed.",
            }}),
            node("save", "save_record", {"saveRecord": {
                "recordTypeId": "fixture-record-type",
                "mapping": {
                    "guest_name": "{{name}}", "selected_room": "{{selected_name}}",
                    "price": "{{selected_price}}",
                },
                "status": "confirmed",
            }}),
            node("fail", "message", {
                "message": "The fixture path could not continue.",
                "deliveryMode": "static", "waitForResponse": False,
            }),
            node("transfer", "transfer", {"transfer": {
                "phoneNumber": "+15555550100",
                "preTransferMessage": "I will connect you to the fixture team.",
                "transferMode": "warm",
            }}),
            node("end", "end", {"closingMessage": "Thanks, {{name}}."}),
        ],
        "edges": [
            edge("start", "query"), edge("query", "form"),
            edge("form", "derive"), edge("derive", "channel"),
            edge("channel", "check_name"),
            edge("check_name", "router", "true"),
            edge("check_name", "transfer", "false"),
            edge("router", "lookup", "search"), edge("router", "fail", "skip"),
            edge("router", "fail", "fallback"),
            edge("lookup", "present", "success"),
            edge("lookup", "fail", "error"),
            edge("lookup", "fail", "not_found"),
            edge("lookup", "fail", "auth_error"),
            edge("present", "picker", "has_results"),
            edge("present", "fail", "no_results"),
            edge("picker", "confirm", "selected"),
            edge("picker", "fail", "fallback"),
            edge("confirm", "capability", "confirmed"),
            edge("confirm", "correct", "edit"),
            edge("correct", "end"),
            edge("capability", "save", "success"),
            edge("capability", "fail", "error"),
            edge("save", "end"),
            edge("fail", "end"),
        ],
    }


def compile_full_catalog_flow():
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    return compile_flow(full_catalog_config(), PilotIdentity(
        account_id="fixture-account", property_id="fixture-property",
        tool_id="fixture-flow", flow_version_id="fixture-version",
        call_sid="fixture-full-call",
    ))


def guided_flow_config():
    return {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {
                "greeting": "Static opening.", "waitForResponse": False,
            }},
            {"id": "guided", "type": "message", "data": {
                "message": "The guided message.", "deliveryMode": "guided",
                "waitForResponse": False,
            }},
            {"id": "end", "type": "end", "data": {
                "closingMessage": "Guided message finished.",
            }},
        ],
        "edges": [
            {"id": "start-guided", "source": "start", "target": "guided"},
            {"id": "guided-end", "source": "guided", "target": "end"},
        ],
    }


def compile_guided_flow():
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    return compile_flow(guided_flow_config(), PilotIdentity(
        account_id="fixture-account", property_id="fixture-property",
        tool_id="fixture-flow", flow_version_id="fixture-version",
        call_sid="fixture-guided-call",
    ))


def transfer_flow_config():
    return {
        "initial_node": "start",
        "variables": [{"key": "request", "type": "text"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {
                "greeting": "", "waitForResponse": False,
            }},
            {"id": "request", "type": "collect_slot", "data": {
                "slot": {"variableKey": "request", "prompt": "What do you need?"},
            }},
            {"id": "route", "type": "condition", "data": {
                "condition": {
                    "variable": "request", "operator": "equals", "value": "human",
                },
            }},
            {"id": "transfer", "type": "transfer", "data": {
                "transfer": {
                    "phoneNumber": "+15555550100",
                    "preTransferMessage": "Connecting you to the fixture team.",
                    "transferMode": "warm",
                },
            }},
            {"id": "end", "type": "end", "data": {"closingMessage": "Goodbye."}},
        ],
        "edges": [
            {"id": "start-request", "source": "start", "target": "request"},
            {"id": "request-route", "source": "request", "target": "route"},
            {"id": "route-transfer", "source": "route", "target": "transfer",
             "sourceHandle": "true"},
            {"id": "route-end", "source": "route", "target": "end",
             "sourceHandle": "false"},
        ],
    }


def compile_transfer_flow():
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    return compile_flow(transfer_flow_config(), PilotIdentity(
        account_id="fixture-account", property_id="fixture-property",
        tool_id="fixture-flow", flow_version_id="fixture-version",
        call_sid="fixture-transfer-call",
    ))


class GraphProviders:
    """Named locally to defer importing the call host until a lifecycle-guarded test."""

    def __new__(cls, replies):
        from pilot_io import PilotProviders
        import httpx

        class Providers(PilotProviders):
            async def http(self, request):
                response = await super().http(request)
                if response.headers.get("content-type") != "text/event-stream":
                    return response
                try:
                    advertised = [
                        tool["function"]["name"]
                        for tool in json.loads(request.content).get("tools", [])
                        if tool.get("type") == "function"
                        and tool["function"]["name"].startswith("native_")
                    ]
                except (KeyError, TypeError, ValueError):
                    advertised = []
                if not advertised:
                    return response
                lines = []
                for line in response.text.splitlines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        lines.append(line)
                        continue
                    chunk = json.loads(line[6:])
                    choices = chunk.get("choices", [])
                    calls = choices[0].get("delta", {}).get("tool_calls", []) if choices else []
                    for tool in calls:
                        function = tool.get("function", {})
                        if function.get("name") not in advertised:
                            function["name"] = advertised[0]
                    lines.append("data: " + json.dumps(chunk))
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    content="\n\n".join(lines) + "\n\n", request=request,
                )

        return Providers(replies, bind_native_names=False)


class NativeGraphPipelineCall:
    """Actual application-created Pipecat worker plus an injected graph adapter."""

    def __new__(cls, compiled, *, providers, execute_action=None, terminal_handler=None):
        from lifecycle_support import OfflineCall
        from botelier.voice.flows.native_adapter import NativeFlowAdapter
        from test_application_transcripts import start_conversation

        class Call(OfflineCall):
            async def activate(self):
                await self.wait_until(lambda: self.started.is_set())
                await start_conversation(self)
                self.adapter = NativeFlowAdapter(
                    compiled, llm=self.created[2], worker=self.created[1],
                    context_aggregator=self.created[3],
                    execute_action=execute_action, terminal_handler=terminal_handler,
                )
                await self.adapter.start()

            def assert_clean(self, **kwargs):
                super().assert_clean(**kwargs)
                assert self.adapter.closed

        call = Call(providers=providers)
        call.adapter = None
        return call

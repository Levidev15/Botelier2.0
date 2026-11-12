"""Inactive, bounded adapter to native Pipecat Flows.

Only an explicitly constructed test host attaches this pilot. Native Flows
owns transitions; the existing action service owns authorization, HTTP,
mapping, retry policy and invocation logs. There is no legacy executor here.
"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from uuid import uuid4

from loguru import logger
from pipecat.flows import FlowManager, FlowsFunctionSchema
from pipecat.flows.types import ContextStrategy, ContextStrategyConfig
from pipecat.frames.frames import TTSSpeakFrame

from botelier.services.action_executor import (
    ActionContext, ActionExecutionRequest, ActionExecutor,
)
from botelier.services.integration_client import IntegrationAPIConfig, ResponseVariable
from botelier.voice.flows.pilot_cancellation import reconcile_native_cancellation
from botelier.voice.flows.pilot_contract import CompiledPilot, NATIVE_FUNCTION_PREFIX
from botelier.voice.flows.pilot_queue import InterruptionSafeFlowQueue


_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")


@dataclass(frozen=True)
class _Visit:
    """Call-owned execution revision, not an editable caller fact."""

    revision: int
    function_name: str


def _render(template, values):
    """Render only named scalar values; never stringify a provider object."""
    def replace(match):
        value = values.get(match[1])
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str) and len(value) <= 2048:
            return value
        if type(value) in (int, float) and math.isfinite(value):
            return str(value)
        raise ValueError("presentation_scalar")

    text = _TOKEN.sub(replace, template).strip()
    if len(text) > 8000:
        raise ValueError("presentation_size")
    return text


class NativePilotAdapter:
    """One admitted graph and one call's native manager/owned pending read."""

    def __init__(
        self, compiled: CompiledPilot, *, llm, worker, context_aggregator,
        session_factory, global_functions=(),
    ):
        if not isinstance(compiled, CompiledPilot):
            raise TypeError("A compiled pilot definition is required")
        self.compiled = compiled
        self.worker = worker
        self.context_aggregator = context_aggregator
        self.session_factory = session_factory
        self.closed = False
        self._started = False
        self._revision = 0
        self._visit = None
        self._claim = None
        self._owned_task = None
        self._accepted = set()
        self._guidance = None
        names = [function.name for function in global_functions]
        if len(names) != len(set(names)) or any(
            name in compiled.native_names or name.startswith(NATIVE_FUNCTION_PREFIX)
            for name in names
        ):
            raise ValueError("native_global_collision")
        self.manager = FlowManager(
            llm=llm, worker=InterruptionSafeFlowQueue(worker),
            context_aggregator=context_aggregator,
            global_functions=list(global_functions),
        )
        self.manager.state["facts"] = {}
        reconcile_native_cancellation(
            llm=llm, worker=worker, context_aggregator=context_aggregator,
            names=compiled.native_names | set(names), is_closed=lambda: self.closed,
            native_prefix=NATIVE_FUNCTION_PREFIX,
        )

        @worker.event_handler("on_pipeline_finished")
        async def finished(worker, frame):
            await self.close()

    @property
    def facts(self):
        return deepcopy(self.manager.state["facts"])

    async def start(self):
        if self.closed or self._started or self.worker.has_finished():
            raise RuntimeError("pilot_not_startable")
        self._started = True
        await self.manager.initialize(self._node(
            self.compiled.query, self.compiled.query.prompt,
        ))

    async def close(self):
        """Invalidate ownership before cancelling and awaiting the owned read."""
        self.closed = True
        self._visit = None
        self._claim = None
        task = self._owned_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _enter_node(self, action, manager):
        """Use the current visit's data, not a first-registered closure."""
        if self.closed or self.worker.has_finished():
            raise RuntimeError("pilot_closed")
        source = action.get("source_visit")
        if source is not None and not self._is_current(source):
            # Native transitions run after tool-result context commit. A
            # captured callback must not regain authority after host re-entry.
            raise RuntimeError("pilot_stale_entry")
        slot = action["slot"]
        self._revision += 1
        # <=63 characters even for the longest admitted saved node ID. Names
        # are unique across calls/visits; the UUID is not a secret or a fact.
        visit = _Visit(
            self._revision, f"{NATIVE_FUNCTION_PREFIX}{slot.node_id[:16]}_{uuid4().hex}",
        )
        self._visit = visit

        async def collect(arguments, manager):
            return await self._collect(slot, visit, arguments)

        # Populate the SAME list native Flows reads after this pre-action.
        # The SDK retains an advertised name's first handler until that name
        # leaves the tool set. A fresh name prevents rebinding OR retaining
        # old authority; native schema sync prunes obsolete registrations.
        action["functions"][:] = [FlowsFunctionSchema(
            name=visit.function_name,
            description=f"Record the caller's explicit {slot.variable} at this node.",
            properties={slot.variable: {"type": "string", "minLength": 1, "maxLength": 2048}},
            required=[slot.variable], handler=collect,
            cancel_on_interruption=True,
        )]
        messages = action["task_messages"]
        # Run at native node entry, AFTER the actual assistant aggregator
        # has committed all tool results. Keep original message objects so
        # only our exact prior guidance is removed, not similar host policy.
        messages[:] = [
            message for message in manager.get_current_context()
            if message is not self._guidance
        ]
        self._guidance = {
            "role": "developer",
            "content": (
                f"Current saved flow node: {slot.node_id}. "
                f"Collect {slot.variable} using {visit.function_name}. "
                "Accept only the caller's explicit answer. Do not repeat the "
                "already issued question or invent an action outcome. "
                "The final collection is a pause, not a booking or payment. "
                + slot.instructions
            ),
        }
        messages.append(self._guidance)
        # Built-in tts_say pre-actions wait for an ActionFinishedFrame at
        # the far end of TTS before native context/tools/current_node are
        # updated. A slow or interrupted utterance must not keep the OLD
        # collection node active. Our single speech owner issues the text
        # without making native node entry depend on audio completion.
        await self.worker.queue_frame(TTSSpeakFrame(text=action["utterance"]))
        if not self._is_current(visit):
            raise RuntimeError("pilot_stale_entry")

    def _node(self, slot, utterance, *, source_visit=None):
        messages = []
        functions = []

        return {
            "name": slot.node_id,
            "task_messages": messages,
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.RESET),
            "functions": functions,
            "pre_actions": [
                # Native Flows registers a handler only once per action type.
                # Keep one stable callable and pass this visit's owned data;
                # RESET must consume the very list that this action fills.
                {
                    "type": "pilot_enter", "handler": self._enter_node,
                    "slot": slot, "utterance": utterance, "task_messages": messages,
                    "functions": functions, "source_visit": source_visit,
                },
            ],
            "respond_immediately": False,
        }

    def _is_current(self, visit):
        return (
            not self.closed and not self.worker.has_finished()
            and self._visit is visit
        )

    def _available(self, slot, visit):
        return (
            self._is_current(visit) and self.manager.current_node == slot.node_id
            and slot.node_id not in self._accepted and self._claim is None
        )

    async def _collect(self, slot, visit, arguments):
        if not self._available(slot, visit):
            return {"status": "rejected", "reason": "busy_or_stale"}
        if (
            not isinstance(arguments, dict) or set(arguments) != {slot.variable}
            or not isinstance(arguments[slot.variable], str)
            or not arguments[slot.variable].strip()
            or len(arguments[slot.variable]) > 2048
        ):
            return {"status": "rejected", "reason": "invalid_arguments"}
        # No await before this claim. Competing handlers cannot repeat facts,
        # wait speech or I/O even while the native node remains current.
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        self.manager.state["facts"][slot.variable] = arguments[slot.variable].strip()
        try:
            if slot.node_id != self.compiled.query.node_id:
                self._accepted.add(slot.node_id)
                return {
                    "status": "accepted", "outcome": "paused",
                    "current_node_id": slot.node_id, "booking_completed": False,
                }
            api = self.compiled.api_config()
            await self.worker.queue_frame(TTSSpeakFrame(text=api["thinkingMessage"]))
            try:
                response = await self._read(api)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A safe category is observable, but no private input, provider
                # exception text or raw response is promoted into caller speech.
                logger.warning("native_pilot_action_failure")
                response = None
            # Some transports swallow cancellation and return success. Refuse
            # that late result even if the node ID has not changed.
            if task.cancelling():
                raise asyncio.CancelledError
            if (
                not self._is_current(visit) or self._claim is not claim
                or self.manager.current_node != slot.node_id
            ):
                return {"status": "rejected", "reason": "busy_or_stale"}
            outcome, mapped, next_slot, text = self._presentation(response)
            self.manager.state["facts"].update(mapped)
            self._accepted.add(slot.node_id)
            result = {
                "status": "accepted", "outcome": outcome,
                "action_node_id": self.compiled.api_node_id,
                "presentation_node_id": self.compiled.response_node_id,
                "current_node_id": next_slot.node_id,
                "flow_version_id": self.compiled.identity.flow_version_id,
                "data": deepcopy(mapped),
            }
            return result, self._node(next_slot, text, source_visit=visit)
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    async def _read(self, api):
        identity = self.compiled.identity
        config = IntegrationAPIConfig(
            integration_id=api["integrationId"], method="GET", path=api["path"],
            endpoint_template=api["path"], timeout=api.get("timeout", 30),
            retry_count=api.get("retryCount", 2),
            response_variables=[
                ResponseVariable(variable_key=key, json_path=path)
                for key, path in self.compiled.response_mappings
            ],
            on_error_message=api["onError"],
        )
        session = self.session_factory()
        try:
            # The integration client still owns each retry. This additional
            # total deadline bounds the entire read and its logging boundary.
            async with asyncio.timeout(config.timeout * (config.retry_count + 1) + 1) as deadline:
                result = await ActionExecutor(session).execute_and_log(ActionExecutionRequest(
                    context=ActionContext(
                        account_id=identity.account_id, property_id=identity.property_id,
                        call_sid=identity.call_sid, channel="flow",
                        tool_id=identity.tool_id, flow_tool_id=identity.tool_id,
                        flow_version_id=identity.flow_version_id,
                        node_id=self.compiled.api_node_id, source_label="native-flow-pilot",
                    ),
                    variables=self.facts, integration_config=config,
                ))
            # asyncio.timeout cannot raise on exit when a broken transport
            # swallows its cancellation. An expired deadline still fails closed.
            if deadline.expired():
                raise TimeoutError("pilot_read_deadline")
            return result
        finally:
            session.close()

    def _presentation(self, response):
        api = self.compiled.api_config()
        presentation = self.compiled.presentation()
        fallback = self.compiled.failure
        failure = ("failure", {}, fallback, f"{api['onError']} {fallback.prompt}")
        if response is None or not response.success:
            return failure
        mapped = {
            key: response.extracted_variables[key]
            for key, _ in self.compiled.response_mappings
            if key in response.extracted_variables
        }
        items = mapped.get(presentation["arrayVariable"])
        if not isinstance(items, list) or len(items) > 50:
            return failure
        try:
            # Keep malformed/unbounded provider data out of both facts and
            # speech; real JSON mappings remain owned by the existing client.
            if len(json.dumps(mapped, allow_nan=False)) > 50_000:
                return failure
            if not items:
                text = _render(presentation["noResultsText"], mapped)
                return "no_results", mapped, fallback, f"{text} {fallback.prompt}"
            parts = [_render(presentation.get("introText", ""), mapped)]
            for index, item in enumerate(items, 1):
                values = {**mapped, **(item if isinstance(item, dict) else {"item": item})}
                values["index"] = index
                parts.append(_render(presentation["itemTemplate"], values))
            # Admission proved that the outro is empty/equivalent. Use the
            # canonical next prompt once rather than silently replacing it.
            parts.append(self.compiled.choice.prompt)
            text = " ".join(part for part in parts if part)
            if len(text) > 8000:
                return failure
            return "has_results", mapped, self.compiled.choice, text
        except (ValueError, TypeError, OverflowError):
            return failure

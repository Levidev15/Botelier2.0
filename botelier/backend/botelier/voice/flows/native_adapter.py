"""Full-catalog execution on Pipecat's native FlowManager.

This adapter admits an immutable graph and supplies visit-scoped native tools.
It does not resolve integrations, records, credentials, providers, or hosts:
those effects enter only through the explicitly injected async callbacks.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date
import json
import math
import re
from uuid import uuid4

from pipecat.flows import FlowManager, FlowsFunctionSchema
from pipecat.flows.types import ContextStrategy, ContextStrategyConfig
from pipecat.frames.frames import TTSSpeakFrame

from botelier.voice.flows.native_execution import (
    NativeActionResult, NativeConfirmation, NativeTerminalResult,
)
from botelier.voice.flows.native_values import (
    NativeValueError, evaluate_condition, evaluate_value, present_response,
    render_text, resolve_option, validate_value,
)
from botelier.voice.flows.pilot_cancellation import reconcile_native_cancellation
from botelier.voice.flows.pilot_queue import InterruptionSafeFlowQueue
from botelier.voice.flows.pilot_replacement import NodeReplacementGuard


_MAX_ARGUMENTS = 2048
_MAX_TOTAL_STEPS = 2048
_NATIVE_PREFIX = "native_"
_ACTION_TYPES = frozenset({"api_request", "capability", "save_record"})
_TERMINALS = frozenset({"end", "transfer"})
_ANSWER_TYPES = frozenset({
    "initial", "message", "collect_slot", "collect_form", "option_picker",
    "confirmation",
})


class NativeFlowAdapter:
    """One compiled graph and one call's FlowManager/runtime ownership."""

    def __init__(
        self, compiled, *, llm, worker, context_aggregator, execute_action=None,
        terminal_handler=None, global_functions=(), text_observer=None,
        text_observer_timeout=5.0, today=None,
    ):
        if not callable(getattr(compiled, "node", None)) or not callable(
            getattr(compiled, "next_node", None)
        ):
            raise TypeError("A compiled native flow graph is required")
        global_functions = tuple(global_functions)
        global_names = [getattr(function, "name", None) for function in global_functions]
        if (
            any(not isinstance(name, str) for name in global_names)
            or len(global_names) != len(set(global_names))
            or any(name.startswith(_NATIVE_PREFIX) for name in global_names)
            or any(name in compiled.native_names for name in global_names)
        ):
            raise ValueError("native_global_collision")
        self.compiled = compiled
        self.worker = worker
        self.context_aggregator = context_aggregator
        self.execute_action = execute_action
        self.terminal_handler = terminal_handler
        self.today = today or date.today()
        self.closed = False
        self._started = False
        self._revision = 0
        self._visit = None
        self._claim = None
        self._owned_task = None
        self._pending_entry = None
        self._accepted = set()
        self._guidance = None
        self._active_node_id = None
        self._active_slot = None
        self._active_form_index = 0
        self._active_user_ids = set()
        self._global_guidance = None
        self._owned_guidance = []
        self._retries = {}
        self._visits = {}
        self._total_steps = 0
        self._spent_effects = set()
        self._derived = set()
        self._confirmation = None
        self._status = "not_started"
        self._completed = False
        self._outcome = None
        self._failure_reason = None
        self._llm_data = {}
        self._pending_instructions = []
        self._automatic_calls = 0
        self._auto_advance_tasks = set()

        self.manager = FlowManager(
            llm=llm,
            worker=InterruptionSafeFlowQueue(
                worker, observer=text_observer,
                observer_timeout=text_observer_timeout,
            ),
            context_aggregator=context_aggregator,
            global_functions=list(global_functions),
        )
        self.manager.worker.attach()
        self.manager.state["facts"] = {}
        self.manager.state["native_llm_data"] = {}
        for declaration in compiled.config().get("variables", []):
            if declaration.get("defaultValue") is not None:
                key = declaration["key"]
                self.manager.state["facts"][key] = self._normalize_assignment(
                    key, declaration["defaultValue"],
                )
        self._replacement = NodeReplacementGuard(
            llm=llm, worker=worker, user=context_aggregator.user(),
            assistant=context_aggregator.assistant(),
            is_closed=lambda: self.closed,
            extra_busy=lambda: (
                self._claim is not None or self._owned_task is not None
                or self._pending_is_unentered()
            ),
        )
        self._replacement.attach()
        reconcile_native_cancellation(
            llm=llm, worker=worker, context_aggregator=context_aggregator,
            names=set(compiled.native_names) | set(global_names),
            is_closed=lambda: self.closed, native_prefix=_NATIVE_PREFIX,
        )

        self.manager.register_action("native_enter", self._enter_node)
        self.manager.register_action("native_after_guided", self._after_guided_message)

        @worker.event_handler("on_pipeline_finished")
        async def finished(_, frame):
            await self.close()

    @property
    def facts(self):
        return deepcopy(self.manager.state["facts"])

    def snapshot(self):
        config = self.compiled.config()
        declarations = config.get("variables", [])
        facts = self.manager.state["facts"]
        progress = {}
        for declaration in declarations:
            key = declaration["key"]
            progress[key] = {
                "type": declaration.get("type", "text"),
                "required": declaration.get("required", True),
                "status": "collected" if key in facts and facts[key] is not None else "missing",
            }
        return {
            "current_node": self._active_node_id,
            "status": self._status,
            "retries": deepcopy(self._retries),
            "completed": self._completed,
            "outcome": self._outcome,
            "failure_reason": self._failure_reason,
            "variables": progress,
        }

    async def start(self):
        if self.closed or self._started or self.worker.has_finished():
            raise RuntimeError("native_flow_not_startable")
        self._started = True
        self._status = "running"
        task = asyncio.current_task()
        self._owned_task = task
        try:
            await self.manager.initialize()
            active = await self._resolve_segment(self.compiled.initial_node_id, None)
            if active is not None and self._is_open():
                await self.manager.set_node_from_config(
                    self._node_config(active, source_visit=None),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("runtime_initialization")
            raise
        finally:
            if self._owned_task is task:
                self._owned_task = None

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self._status = "closed"
        self._visit = None
        self._claim = None
        self._pending_entry = None
        self._confirmation = None
        self.manager.worker.close()
        await self._replacement.close()
        for pending in tuple(self._auto_advance_tasks):
            if pending is not asyncio.current_task() and not pending.done():
                pending.cancel()
        task = self._owned_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._auto_advance_tasks:
            await asyncio.gather(*self._auto_advance_tasks, return_exceptions=True)

    def _is_open(self):
        return not self.closed and not self.worker.has_finished()

    def _is_current(self, visit):
        return self._is_open() and self._visit is visit

    def _pending_is_unentered(self, entered_visit=None):
        if self._pending_entry is None:
            return False
        target_id, visit = self._pending_entry
        if (
            entered_visit is not None and visit is entered_visit
            and self.manager.current_node == target_id and self._visit is visit
        ):
            self._pending_entry = None
            return False
        return True

    def _available(self, node_id, visit):
        self._pending_is_unentered(visit)
        return (
            self._is_current(visit)
            and self._active_node_id == node_id
            and self.manager.current_node == node_id
            and self._claim is None
            and self._pending_entry is None
            and self._status == "running"
            and not self._replacement.blocked
        )

    def _fail(self, reason):
        self._status = "failed"
        self._failure_reason = reason
        self._outcome = reason

    def _mark_step(self, node_id):
        self._total_steps += 1
        visits = self._visits.get(node_id, 0) + 1
        self._visits[node_id] = visits
        if visits > self.compiled.max_revisits + 1 or self._total_steps > _MAX_TOTAL_STEPS:
            self._fail("execution_budget")
            return False
        return True

    def _node_data(self, node_id):
        node = self.compiled.node(node_id)
        if node is None:
            raise RuntimeError("native_graph_node_missing")
        return node, node.data()

    async def _resolve_segment(self, node_id, source_visit):
        """Run bounded automatic nodes until FlowManager can enter a wait node."""
        current = node_id
        cursor = source_visit
        while current is not None and self._is_open():
            if not self._mark_step(current):
                return None
            node, data = self._node_data(current)
            kind = node.type
            if kind in _ANSWER_TYPES and self._is_wait_node(kind, data):
                self._active_node_id = current
                self._active_slot = None
                self._active_form_index = 0
                return current
            if kind == "initial":
                self._carry_private(data.get("systemPrompt"))
                if data.get("greeting"):
                    await self._speak(self._render(data["greeting"]))
                current = self._default_next(current)
                continue
            if kind == "message":
                text = self._render(data.get("message", ""))
                if data.get("deliveryMode", "guided") == "guided":
                    self._active_node_id = current
                    self._active_slot = None
                    self._active_form_index = 0
                    return current
                if text:
                    await self._speak(text)
                current = self._default_next(current)
                continue
            if kind == "set_variable":
                config = data.get("setVariable", data.get("set_variable"))
                value = evaluate_value(config, self.facts)
                value = self._normalize_assignment(config["variableKey"], value)
                self.manager.state["facts"][config["variableKey"]] = value
                self._derived.add(config["variableKey"])
                current = self._default_next(current)
                continue
            if kind == "condition":
                try:
                    selected = evaluate_condition(data["condition"], self.facts)
                except NativeValueError:
                    self._fail("condition_value")
                    return None
                current = self._edge_target(current, "true" if selected else "false")
                continue
            if kind == "router":
                router = data["router"]
                actual = self.facts.get(router["variable"])
                matches = [
                    option for option in router["options"]
                    if isinstance(actual, str)
                    and actual.strip().casefold() == option["value"].strip().casefold()
                ]
                if len(matches) == 1:
                    current = self._edge_target(current, matches[0]["id"])
                else:
                    current = self._edge_target(current, "fallback")
                    if current is None:
                        self._fail("router_no_match")
                        return None
                continue
            if kind == "api_response":
                try:
                    text, has_results = present_response(data["responsePresentation"], self.facts)
                except NativeValueError:
                    self._fail("response_presentation")
                    return None
                if text:
                    await self._speak(text)
                current = self._edge_target(
                    current, "has_results" if has_results else "no_results",
                )
                continue
            if kind in _ACTION_TYPES:
                current, branch = await self._run_action(node, data, cursor)
                if current is None:
                    return None
                cursor = self._visit if cursor is None else cursor
                continue
            if kind in _TERMINALS:
                self._active_node_id = current
                await self._run_terminal(node, data)
                return current
            self._fail("unsupported_runtime_node")
            return None
        if current is None and self._status == "running":
            self._fail("dead_end")
        return None

    @staticmethod
    def _is_wait_node(kind, data):
        if kind in {"collect_slot", "collect_form", "option_picker", "confirmation"}:
            return True
        if kind == "initial":
            return data.get("waitForResponse", True) is True
        return kind == "message" and data.get("waitForResponse", True) is True

    def _default_next(self, node_id):
        next_node = self.compiled.next_node(node_id)
        return next_node.node_id if next_node else None

    def _edge_target(self, node_id, handle):
        next_node = self.compiled.next_node(node_id, handle)
        if next_node is None:
            self._fail("missing_transition")
            return None
        return next_node.node_id

    def _carry_private(self, value):
        if isinstance(value, str) and value.strip():
            self._pending_instructions.append(value.strip())

    def _render(self, template, *, speech=True):
        return render_text(template, self.facts, speech=speech)

    async def _speak(self, text):
        if not text:
            return
        if not self._is_open():
            raise RuntimeError("native_flow_closed")
        await self.manager.worker.queue_frame(TTSSpeakFrame(
            text=text, append_to_context=False,
        ))

    def _normalize_assignment(self, key, value):
        declaration = self._declaration(key)
        kind = declaration.get("type", "text")
        slot = {
            "type": kind, "validation": {}, "useBuiltInValidator": False,
            "choices": declaration.get("choices", []),
        }
        try:
            return validate_value(slot, value, self.facts, today=self.today)
        except NativeValueError:
            raise RuntimeError("native_assignment_type") from None

    def _declaration(self, key):
        for declaration in self.compiled.config().get("variables", []):
            if declaration.get("key") == key:
                return declaration
        raise RuntimeError("native_variable_missing")

    def _node_config(self, node_id, *, source_visit, form_index=0):
        node, data = self._node_data(node_id)
        messages = []
        functions = []
        respond_immediately = False
        speech = ""
        guided = False
        if node.type == "initial":
            if data.get("greeting"):
                speech = self._render(data["greeting"])
            self._carry_private(data.get("systemPrompt"))
            if data.get("waitForResponse"):
                functions.append(self._text_response_schema(node_id, source_visit))
                respond_immediately = False
        elif node.type == "collect_slot":
            self._active_slot = data["slot"]
            speech = self._render(data["slot"]["prompt"])
            functions.append(self._slot_schema(node_id, source_visit, data["slot"]))
        elif node.type == "collect_form":
            slots = sorted(data["slots"], key=lambda item: item["order"])
            if form_index >= len(slots):
                raise RuntimeError("native_form_order")
            self._active_form_index = form_index
            self._active_slot = slots[form_index]
            if form_index == 0 and data.get("introMessage"):
                speech = self._render(data["introMessage"])
            prompt = self._render(slots[form_index]["prompt"])
            speech = " ".join(item for item in (speech, prompt) if item)
            functions.append(self._slot_schema(node_id, source_visit, slots[form_index]))
        elif node.type == "message":
            if data.get("deliveryMode", "guided") == "static":
                speech = self._render(data.get("message", ""))
            else:
                guided = True
                respond_immediately = True
                self._carry_private(
                    "Speak this configured message naturally: "
                    + self._render(data.get("message", "")),
                )
            if data.get("waitForResponse", True):
                functions.append(self._text_response_schema(node_id, source_visit))
                if guided:
                    respond_immediately = True
                else:
                    respond_immediately = False
            elif guided:
                respond_immediately = True
        elif node.type == "option_picker":
            picker = data.get("optionPicker", data.get("option_picker"))
            speech = self._render(picker["prompt"])
            functions.append(self._option_schema(node_id, source_visit))
        elif node.type == "confirmation":
            confirmation = data["confirmation"]
            summary = self._render(confirmation["summaryTemplate"])
            prompt = self._render(confirmation["confirmPrompt"])
            if confirmation.get("deliveryMode", "guided") == "guided":
                guided = True
                respond_immediately = True
                self._carry_private(f"Read this exact confirmation summary and prompt: {summary} {prompt}")
            else:
                speech = " ".join(item for item in (summary, prompt) if item)
            functions.append(self._confirmation_schema(node_id, source_visit, confirmation))
        elif node.type in _TERMINALS:
            pass
        else:
            raise RuntimeError("native_wait_node")

        for instruction in self._pending_instructions:
            messages.append({
                "role": "developer",
                "content": self._render(instruction, speech=False),
            })
        self._pending_instructions.clear()
        if data.get("instructions"):
            messages.append({
                "role": "developer",
                "content": self._render(data["instructions"], speech=False),
            })
        if node.type == "initial" and data.get("systemPrompt"):
            messages.append({
                "role": "developer",
                "content": self._render(data["systemPrompt"], speech=False),
            })
        if guided:
            if node.type == "message":
                guidance = "Speak the configured message before waiting for the caller."
            else:
                guidance = "Speak the configured confirmation summary and prompt before listening."
            messages.append({"role": "developer", "content": guidance})

        config = {
            "name": node_id,
            "task_messages": messages,
            "functions": functions,
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.RESET),
            "pre_actions": [{
                "type": "native_enter", "handler": self._enter_node,
                "node_id": node_id, "source_visit": source_visit,
                "functions": functions, "task_messages": messages,
                "speech": speech, "form_index": form_index,
                "respond_immediately": respond_immediately,
            }],
            "respond_immediately": respond_immediately,
        }
        if guided and node.type == "message" and not data.get("waitForResponse", True):
            config["post_actions"] = [{
                "type": "native_after_guided", "handler": self._after_guided_message,
                "node_id": node_id, "source_visit": None,
            }]
        return config

    def _next_user_ids(self):
        messages = self.manager.get_current_context()
        return {
            id(message) for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        }

    async def _enter_node(self, action, manager):
        if not self._is_open():
            raise RuntimeError("native_flow_closed")
        source = action.get("source_visit")
        if source is not None and not self._is_current(source):
            raise RuntimeError("native_stale_entry")
        if self._pending_entry is not None and source is not None:
            pending_target, pending_visit = self._pending_entry
            if pending_target != action["node_id"]:
                raise RuntimeError("native_pending_transition")
        node, data = self._node_data(action["node_id"])
        self._confirmation = None
        self._revision += 1
        visit = object()
        self._visit = visit
        self._active_node_id = node.node_id
        if node.type == "collect_form":
            self._active_form_index = action["form_index"]
        task_messages = action["task_messages"]
        owned_ids = {id(message) for message in self._owned_guidance}
        configured_messages = [
            message for message in task_messages
            if id(message) not in owned_ids
        ]
        prior_messages = [
            message for message in manager.get_current_context()
            if id(message) not in owned_ids
        ]
        task_messages[:] = prior_messages
        self._owned_guidance = []
        global_prompt = self.compiled.config().get(
            "globalPrompt", self.compiled.config().get("global_prompt", ""),
        )
        if global_prompt:
            self._global_guidance = {
                "role": "developer",
                "content": self._render(global_prompt, speech=False),
            }
            task_messages.append(self._global_guidance)
            self._owned_guidance.append(self._global_guidance)
        task_messages.extend(configured_messages)
        self._owned_guidance.extend(configured_messages)
        if task_messages:
            self._guidance = {
                "role": "developer",
                "content": (
                    f"Current saved flow node: {node.node_id}, revision {self._revision}. "
                    "Use only the currently advertised native function when the caller "
                    "has explicitly supplied its required answer. Do not invent facts, "
                    "branch choices, confirmations, or action outcomes."
                ),
            }
            task_messages.append(self._guidance)
            self._owned_guidance.append(self._guidance)
        functions = action["functions"]
        functions[:] = self._functions_for_visit(node, data, visit, action["form_index"])
        self._active_user_ids = self._next_user_ids()
        if action.get("speech"):
            self.manager.worker.node_speech_started(
                action["speech"], append_to_context=False,
            )
            await self._speak(action["speech"])
        if self._pending_entry is not None and source is not None:
            self._pending_entry = (action["node_id"], visit)
        if not self._is_current(visit):
            raise RuntimeError("native_stale_entry")

    def _functions_for_visit(self, node, data, visit, form_index):
        node_id = node.node_id
        if node.type == "initial":
            if not data.get("waitForResponse", True):
                return []
            return [self._text_response_schema(node_id, visit)]
        if node.type == "collect_slot":
            return [self._slot_schema(node_id, visit, data["slot"])]
        if node.type == "collect_form":
            slots = sorted(data["slots"], key=lambda item: item["order"])
            return [self._slot_schema(node_id, visit, slots[form_index])]
        if node.type == "message" and data.get("waitForResponse", True):
            return [self._text_response_schema(node_id, visit)]
        if node.type == "option_picker":
            return [self._option_schema(node_id, visit)]
        if node.type == "confirmation":
            return [self._confirmation_schema(node_id, visit, data["confirmation"])]
        return []

    def _schema(self, node_id, visit, description, properties, required, handler):
        del visit
        name = f"{_NATIVE_PREFIX}{node_id[:16]}_{uuid4().hex}"
        if len(name) > 63:
            raise RuntimeError("native_function_name")
        return FlowsFunctionSchema(
            name=name, description=description[:512], properties=properties,
            required=list(required), handler=handler, cancel_on_interruption=True,
        )

    def _slot_schema(self, node_id, visit, slot):
        variable = slot["variableKey"]
        declaration = self._declaration(variable)
        slot_type = slot.get("type", declaration.get("type", "text"))
        if slot_type == "number":
            schema = {"type": "number"}
            for key in ("min", "max"):
                if key in slot.get("validation", {}):
                    schema[key] = slot["validation"][key]
        else:
            schema = {"type": "string", "minLength": 1, "maxLength": _MAX_ARGUMENTS}
            if slot_type == "choice":
                schema["enum"] = declaration.get("choices", [])

        async def collect(arguments, manager):
            return await self._collect_slot(node_id, visit, slot, arguments)

        return self._schema(
            node_id, visit, "Record the caller's explicit answer for this current field.",
            {variable: schema},
            [variable], collect,
        )

    def _text_response_schema(self, node_id, visit):
        async def response(arguments, manager):
            return await self._collect_response(node_id, visit, arguments)

        return self._schema(
            node_id, visit, "Record the caller's current response to this message.",
            {"response": {"type": "string", "minLength": 1, "maxLength": _MAX_ARGUMENTS}},
            ["response"], response,
        )

    def _option_schema(self, node_id, visit):
        async def choose(arguments, manager):
            return await self._choose_option(node_id, visit, arguments)

        return self._schema(
            node_id, visit, "Select one currently offered option by ordinal or unique label.",
            {
                "ordinal": {"type": "integer", "minimum": 1},
                "label": {"type": "string", "minLength": 1, "maxLength": _MAX_ARGUMENTS},
            },
            [], choose,
        )

    def _confirmation_schema(self, node_id, visit, configuration):
        options = ["yes", "no"]
        if configuration.get("allowEdit"):
            options.append("edit")

        async def confirm(arguments, manager):
            return await self._confirm(node_id, visit, configuration, arguments)

        return self._schema(
            node_id, visit, "Record the caller's explicit current confirmation or edit choice.",
            {"response": {"type": "string", "enum": options}},
            ["response"], confirm,
        )

    def _new_user_turn(self, visit):
        if not self._is_current(visit):
            return False
        return bool(self._next_user_ids() - self._active_user_ids)

    def _arguments(self, arguments, expected):
        if not isinstance(arguments, dict) or set(arguments) != set(expected):
            return False
        return all(
            isinstance(value, str) and value.strip() and len(value) <= _MAX_ARGUMENTS
            for value in arguments.values()
        )

    async def _collect_slot(self, node_id, visit, slot, arguments):
        if not self._available(node_id, visit):
            return self._rejected("busy_or_stale")
        key = slot["variableKey"]
        declaration = self._declaration(key)
        slot_type = slot.get("type", declaration.get("type", "text"))
        valid_args = (
            isinstance(arguments, dict) and set(arguments) == {key}
            and (
                type(arguments[key]) is int and abs(arguments[key]) <= 10 ** 100
                or type(arguments[key]) is float
                and math.isfinite(arguments[key]) and abs(arguments[key]) <= 1e100
                if slot_type == "number"
                else isinstance(arguments[key], str) and arguments[key].strip()
                and len(arguments[key]) <= _MAX_ARGUMENTS
            )
        )
        raw = arguments.get(key) if isinstance(arguments, dict) else None
        latest = self._latest_user_text()
        if (
            not valid_args or not self._new_user_turn(visit) or latest is None
            or not self._same_answer(latest, str(raw))
        ):
            return self._rejected("invalid_arguments")
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        try:
            slot_config = {**slot, "type": slot_type}
            if slot_config["type"] == "choice":
                slot_config["choices"] = declaration.get("choices", [])
            try:
                value = validate_value(
                    slot_config, arguments[key], self.facts, today=self.today,
                )
            except NativeValueError:
                return await self._retry(node_id, visit, slot, key, claim)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            self.manager.state["facts"][key] = value
            self._derived.discard(key)
            self._confirmation = None
            next_index = None
            node, data = self._node_data(node_id)
            if node.type == "collect_form":
                slots = sorted(data["slots"], key=lambda item: item["order"])
                next_index = self._active_form_index + 1
                if next_index < len(slots):
                    target_config = self._node_config(
                        node_id, source_visit=visit, form_index=next_index,
                    )
                    result = {"status": "accepted", "current_node": node_id}
                    self._pending_entry = (node_id, None)
                    return result, target_config
            self._accepted.add(visit)
            active = await self._resolve_segment(self._default_next(node_id), visit)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            if active is None:
                self._pending_entry = None
                return self._terminal_or_error({
                    "status": "accepted", "current_node": node_id,
                })
            self._pending_entry = (active, None)
            result = {
                "status": "accepted", "current_node": node_id,
                "facts": {key: value},
            }
            if self._llm_data:
                result["data"] = deepcopy(self._llm_data)
            return result, self._node_config(active, source_visit=visit)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("collection_runtime")
            return {"status": "error", "reason": "collection_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    async def _retry(self, node_id, visit, slot, key, claim):
        retry_key = f"{node_id}.{key}"
        count = self._retries.get(retry_key, 0) + 1
        self._retries[retry_key] = count
        maximum = slot.get("maxRetries", 3)
        if count > maximum:
            self._fail("retry_exhausted")
            return {"status": "rejected", "reason": "retry_exhausted"}
        if not self._is_current(visit) or self._claim is not claim:
            return self._rejected("busy_or_stale")
        prompt = slot.get("retryPrompt") or slot.get("prompt")
        try:
            await self._speak(self._render(prompt))
        except Exception:
            self._fail("retry_prompt")
            return {"status": "error", "reason": "retry_prompt"}
        return self._rejected("validation")

    def _owned(self, node_id, visit, claim, task):
        return (
            not task.cancelling() and self._is_current(visit)
            and self._claim is claim
        )

    async def _collect_response(self, node_id, visit, arguments):
        if not self._available(node_id, visit):
            return self._rejected("busy_or_stale")
        if not self._arguments(arguments, ["response"]) or not self._new_user_turn(visit):
            return self._rejected("invalid_arguments")
        node, data = self._node_data(node_id)
        latest = self._latest_user_text()
        response = arguments["response"].strip()
        if latest is not None and not self._same_answer(latest, response):
            return self._rejected("caller_response_mismatch")
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        try:
            if node.type == "initial":
                target = self._default_next(node_id)
                if target is None:
                    self._fail("dead_end")
                    return self._rejected("dead_end")
            else:
                target = self._default_next(node_id)
            active = await self._resolve_segment(target, visit)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            result = {"status": "accepted", "current_node": node_id}
            if self._llm_data:
                result["data"] = deepcopy(self._llm_data)
            if active is None:
                return self._terminal_or_error(result)
            self._pending_entry = (active, None)
            return result, self._node_config(active, source_visit=visit)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("message_runtime")
            return {"status": "error", "reason": "message_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    def _latest_user_text(self):
        messages = self.manager.get_current_context()
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                return content if isinstance(content, str) else None
        return None

    @staticmethod
    def _same_answer(caller, response):
        left, right = " ".join(caller.casefold().split()), " ".join(response.casefold().split())
        return left == right or bool(
            right and re.search(
                rf"(?<!\w){re.escape(right)}(?!\w)", left,
            ),
        )

    async def _choose_option(self, node_id, visit, arguments):
        if not self._available(node_id, visit):
            return self._rejected("busy_or_stale")
        if not self._new_user_turn(visit):
            return self._rejected("invalid_arguments")
        node, data = self._node_data(node_id)
        picker = data.get("optionPicker", data.get("option_picker"))
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        try:
            valid = (
                isinstance(arguments, dict) and bool(arguments)
                and not (set(arguments) - {"ordinal", "label"})
                and ("ordinal" in arguments or "label" in arguments)
                and (
                    "ordinal" not in arguments
                    or type(arguments["ordinal"]) is int and arguments["ordinal"] > 0
                )
                and (
                    "label" not in arguments
                    or isinstance(arguments["label"], str)
                    and bool(arguments["label"].strip())
                    and len(arguments["label"]) <= _MAX_ARGUMENTS
                )
            )
            if not valid:
                return await self._option_retry(
                    node_id, visit, picker, "selection_arguments", claim, task,
                )
            latest = self._latest_user_text()
            if latest is None or not self._explicit_selection(latest, arguments):
                return await self._option_retry(
                    node_id, visit, picker, "selection_mismatch", claim, task,
                )
            selected = resolve_option(picker, self.facts, arguments)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            facts = self.manager.state["facts"]
            writes = {}
            for key, value in selected.writes.items():
                if value is not None:
                    value = self._normalize_assignment(key, value)
                writes[key] = value
            facts.update(writes)
            self._derived.update(writes)
            self._confirmation = None
            self._accepted.add(visit)
            active = await self._resolve_segment(self._edge_target(node_id, "selected"), visit)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            result = {"status": "accepted", "selected": selected.index + 1}
            if active is None:
                return self._terminal_or_error(result)
            self._pending_entry = (active, None)
            return result, self._node_config(active, source_visit=visit)
        except NativeValueError:
            return await self._option_retry(
                node_id, visit, picker, "selection_invalid", claim, task,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("selection_runtime")
            return {"status": "error", "reason": "selection_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    @staticmethod
    def _explicit_selection(caller, arguments):
        text = " ".join(caller.casefold().split())
        ordinal = arguments.get("ordinal")
        label = arguments.get("label")
        if ordinal is not None and not re.search(rf"(?<!\d){ordinal}(?!\d)", text):
            number_words = {
                1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
            }
            word = number_words.get(ordinal)
            if word is None or not re.search(rf"\b{word}\b", text):
                return False
        if (
            label is not None and ordinal is None
            and str(label).strip().casefold() not in text
        ):
            return False
        return True

    async def _option_retry(self, node_id, visit, picker, reason, claim, task):
        if not self._owned(node_id, visit, claim, task):
            return self._rejected("busy_or_stale")
        retry_key = f"{node_id}.selection"
        count = self._retries.get(retry_key, 0) + 1
        self._retries[retry_key] = count
        if count > picker.get("maxRetries", 3):
            self._fail("retry_exhausted")
            return {"status": "rejected", "reason": "retry_exhausted"}
        prompt = picker.get("retryPrompt") or picker["prompt"]
        try:
            await self._speak(self._render(prompt))
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("selection_retry_prompt")
            return {"status": "error", "reason": "selection_retry_prompt"}
        if not self._owned(node_id, visit, claim, task):
            return self._rejected("busy_or_stale")
        return self._rejected(reason)

    async def _confirm(self, node_id, visit, configuration, arguments):
        if not self._available(node_id, visit):
            return self._rejected("busy_or_stale")
        if not self._arguments(arguments, ["response"]) or not self._new_user_turn(visit):
            return self._rejected("invalid_arguments")
        response = arguments["response"].strip().casefold()
        latest = self._latest_user_text()
        if latest is not None and not self._same_answer(latest, response):
            return self._rejected("caller_response_mismatch")
        if response not in ({"yes", "no", "edit"} if configuration.get("allowEdit") else {"yes", "no"}):
            return self._rejected("invalid_confirmation")
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        try:
            if response != "yes":
                if response == "edit" or response == "no" and configuration.get("allowEdit"):
                    if not self._owned(node_id, visit, claim, task):
                        return self._rejected("busy_or_stale")
                    self._clear_stale_for_edit(configuration)
                    target = self._edge_target(node_id, "edit")
                else:
                    return self._rejected("not_confirmed")
            else:
                selected = {
                    key: deepcopy(self.manager.state["facts"].get(key))
                    for key in configuration["variablesToConfirm"]
                }
                confirmation = NativeConfirmation(
                    node_id, self._revision,
                    json.dumps(selected, ensure_ascii=False, allow_nan=False),
                    tuple(configuration["variablesToConfirm"]),
                )
                if not self._owned(node_id, visit, claim, task):
                    return self._rejected("busy_or_stale")
                self._confirmation = confirmation
                target = self._edge_target(node_id, "confirmed")
            self._accepted.add(visit)
            active = await self._resolve_segment(target, visit)
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            result = {
                "status": "accepted",
                "confirmed": response == "yes",
            }
            if active is None:
                return self._terminal_or_error(result)
            self._pending_entry = (active, None)
            return result, self._node_config(active, source_visit=visit)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("confirmation_runtime")
            return {"status": "error", "reason": "confirmation_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    def _clear_stale_for_edit(self, configuration):
        facts = self.manager.state["facts"]
        for key in configuration["variablesToConfirm"]:
            facts.pop(key, None)
        for key in tuple(self._derived):
            facts.pop(key, None)
        self._derived.clear()
        self._confirmation = None
        self._llm_data = {}
        self.manager.state["native_llm_data"] = {}
        self._pending_instructions.clear()

    def _terminal_or_error(self, result):
        if self._status == "failed":
            return {"status": "error", "reason": self._failure_reason or "runtime_failure"}
        if self._status == "terminal_failed":
            return {
                "status": "terminal_failed",
                "reason": self._failure_reason or "terminal_rejected",
            }
        return result

    async def _run_action(self, node, data, source_visit):
        if not self._is_open() or source_visit is not None and not self._is_current(source_visit):
            self._fail("stale_action")
            return None, "error"
        node_id, kind = node.node_id, node.type
        if node_id in self._spent_effects:
            self._fail("effect_already_spent")
            return None, "error"
        self._spent_effects.add(node_id)
        self._automatic_calls += 1
        if self._automatic_calls > 128:
            self._fail("action_budget")
            return None, "error"
        configuration = data.get("api", {}) if kind in {"api_request", "capability"} else data.get(
            "saveRecord", data.get("save_record", {}),
        )
        if kind in {"api_request", "capability"} and configuration.get("thinkingMessage"):
            await self._speak(self._render(configuration["thinkingMessage"]))
        result = None
        if callable(self.execute_action):
            try:
                result = await self.execute_action(node, self.facts, confirmation=self._confirmation)
            except asyncio.CancelledError:
                raise
            except Exception:
                result = None
        if (
            not self._is_open()
            or source_visit is not None and not self._is_current(source_visit)
            or asyncio.current_task().cancelling()
        ):
            raise asyncio.CancelledError
        if not isinstance(result, NativeActionResult):
            result = NativeActionResult(
                False, branch="error", failure_reason="action_unavailable",
            )
        mapped_values = result.variables if result.success else {}
        valid_keys = {
            entry["key"] for entry in self.compiled.config().get("variables", [])
        }
        if set(mapped_values) - valid_keys:
            self._fail("action_mapping")
            return None, "error"
        self.manager.state["facts"].update(mapped_values)
        self._derived.update(mapped_values)
        self._llm_data = result.llm_data if result.success else {}
        self.manager.state["native_llm_data"] = deepcopy(self._llm_data)
        self._carry_private(configuration.get("responseInstructions"))
        handle = result.branch
        if result.success:
            handle = "success"
        branch_text = {
            "success": configuration.get("onSuccess"),
            "error": configuration.get("onError"),
            "not_found": configuration.get("onNotFound"),
            "auth_error": configuration.get("onAuthError"),
        }.get(handle)
        if branch_text:
            await self._speak(self._render(branch_text))
        if kind == "save_record" and result.success:
            target = self._default_next(node_id)
            if target is None:
                self._fail("save_record_transition")
                return None, handle
        else:
            target = self._edge_target(node_id, handle)
        if target is None:
            self._fail(result.failure_reason or "action_branch_unhandled")
            return None, handle
        # onComplete is a spoken bridge only when no explicit presentation follows.
        if result.success and configuration.get("onComplete"):
            target_node = self.compiled.node(target)
            if target_node is None or target_node.type != "api_response":
                await self._speak(self._render(configuration["onComplete"]))
        return target, handle

    async def _run_terminal(self, node, data):
        node_id = node.node_id
        text = ""
        if node.type == "end":
            template = data.get("closingMessage", "")
        else:
            template = data.get("transfer", {}).get("preTransferMessage", "")
        if template:
            try:
                text = self._render(template)
            except NativeValueError:
                self._fail("terminal_message")
                return
        if text:
            await self._speak(text)
        if not callable(self.terminal_handler):
            result = NativeTerminalResult(False, failure_reason="terminal_unavailable")
        else:
            try:
                result = await self.terminal_handler(node, self.facts)
            except asyncio.CancelledError:
                raise
            except Exception:
                result = NativeTerminalResult(False, failure_reason="terminal_error")
        if not self._is_open():
            return
        if not isinstance(result, NativeTerminalResult):
            result = NativeTerminalResult(False, failure_reason="terminal_result")
        self._completed = result.accepted and result.completed
        if self._completed:
            self._status = "completed"
            self._outcome = "completed"
            self._failure_reason = None
        elif result.accepted:
            self._status = "terminal_pending"
            self._outcome = "accepted_pending"
            self._failure_reason = result.failure_reason
        else:
            self._status = "terminal_failed"
            self._outcome = "failed"
            self._failure_reason = result.failure_reason or "terminal_rejected"

    async def _after_guided_message(self, action, manager):
        node_id = action.get("node_id")
        if (
            not self._is_open() or self._active_node_id != node_id
            or manager.current_node != node_id or self._status != "running"
        ):
            return
        visit = self._visit
        task = asyncio.current_task()
        self._owned_task = task
        try:
            target = self._default_next(node_id)
            active = await self._resolve_segment(target, visit)
            if not self._is_current(visit):
                return
            if active is not None:
                self._pending_entry = (active, None)
                await manager.set_node_from_config(
                    self._node_config(active, source_visit=visit),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("guided_transition")
        finally:
            if self._owned_task is task:
                self._owned_task = None

    @staticmethod
    def _rejected(reason):
        return {"status": "rejected", "reason": reason}


__all__ = ["NativeFlowAdapter"]

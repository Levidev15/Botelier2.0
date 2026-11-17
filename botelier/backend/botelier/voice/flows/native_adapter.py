"""Full-catalog execution on Pipecat's native FlowManager.

This adapter admits an immutable graph and supplies visit-scoped native tools.
It does not resolve integrations, records, credentials, providers, or hosts:
those effects enter only through the explicitly injected async callbacks.
"""

from __future__ import annotations

import asyncio
import inspect
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
    NativeActionResult, NativeConfirmation, NativeTerminalResult, copy_native_json,
)
from botelier.voice.flows.native_grounding import caller_value_is_grounded
from botelier.voice.flows.native_values import (
    NativeValueError, evaluate_condition, evaluate_value, present_response,
    render_text, resolve_option, validate_value,
)
from botelier.services.native_flow_recovery import (
    NativeFlowRecoveryError, native_flow_identity, native_flow_source_digest,
)
from botelier.voice.flows.pilot_cancellation import reconcile_native_cancellation
from botelier.voice.flows.pilot_queue import InterruptionSafeFlowQueue
from botelier.voice.flows.pilot_replacement import NodeReplacementGuard


_MAX_ARGUMENTS = 2048
_MAX_TOTAL_STEPS = 2048
_NATIVE_PREFIX = "native_"
_YES_PHRASES = frozenset({
    "yes", "yes please", "yes, please", "yes, that's correct",
    "yes that's correct", "that's correct", "correct", "absolutely",
    "sure", "okay", "ok", "go ahead", "please do",
})
_NO_PHRASES = frozenset({
    "no", "no thanks", "no, thanks", "no thank you", "no, thank you",
})
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
        text_observer_timeout=5.0, today=None, direct_speech_observer=None,
        available_flows=None, action_runners=None, recovery_snapshot=None,
        snapshot_handler=None,
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
        if available_flows is None:
            available_flows = {}
        if not isinstance(available_flows, dict):
            raise ValueError("native_flow_catalogue")
        flow_catalogue = {}
        for flow_id, entry in available_flows.items():
            if (
                not isinstance(flow_id, str) or not isinstance(entry, dict)
                or set(entry) != {"compiled", "name", "description"}
            ):
                raise ValueError("native_flow_catalogue")
            flow = entry["compiled"]
            identity = getattr(flow, "identity", None)
            if (
                not callable(getattr(flow, "node", None))
                or not callable(getattr(flow, "next_node", None))
                or str(getattr(identity, "tool_id", "")) != flow_id
                or str(getattr(identity, "account_id", ""))
                != str(compiled.identity.account_id)
                or str(getattr(identity, "property_id", ""))
                != str(compiled.identity.property_id)
                or str(getattr(identity, "call_sid", ""))
                != str(compiled.identity.call_sid)
                or not isinstance(entry["name"], str)
                or not isinstance(entry["description"], str)
            ):
                raise ValueError("native_flow_catalogue")
            flow_catalogue[flow_id] = {
                "compiled": flow,
                "name": entry["name"][:128],
                "description": entry["description"][:256],
            }
        selected_flow = flow_catalogue.get(str(compiled.identity.tool_id))
        if selected_flow is None:
            flow_catalogue[str(compiled.identity.tool_id)] = {
                "compiled": compiled, "name": "", "description": "",
            }
        self.compiled = compiled
        self._root_compiled = compiled
        self._flow_catalogue = flow_catalogue
        self._catalog_active = False
        self._awaiting_flow_choice = False
        self._suppress_initial_greeting = False
        if snapshot_handler is not None and not callable(snapshot_handler):
            raise ValueError("native_recovery_storage_unavailable")
        self._snapshot_handler = snapshot_handler
        self._recovery_snapshot = recovery_snapshot
        self._recovery_revision = (
            recovery_snapshot.get("revision", 0)
            if isinstance(recovery_snapshot, dict) else 0
        )
        self._resume_after_effect_commit = False
        self.worker = worker
        self.context_aggregator = context_aggregator
        self._default_execute_action = execute_action
        self._action_runners = None
        if action_runners is not None:
            if not isinstance(action_runners, dict):
                raise ValueError("native_action_runners")
            validated_runners = {}
            for flow_id, runner in action_runners.items():
                entry = flow_catalogue.get(flow_id)
                if (
                    not isinstance(flow_id, str) or entry is None
                    or getattr(runner, "compiled", None) is not entry["compiled"]
                    or not callable(getattr(runner, "execute", None))
                ):
                    raise ValueError("native_action_runner_scope")
                validated_runners[flow_id] = runner
            for flow_id, entry in flow_catalogue.items():
                if any(node.type in _ACTION_TYPES for node in entry["compiled"].nodes):
                    if flow_id not in validated_runners:
                        raise ValueError("native_action_runner_missing")
            self._action_runners = validated_runners
        self.execute_action = self._action_callback_for(compiled)
        self.terminal_handler = terminal_handler
        if direct_speech_observer is not None and not callable(direct_speech_observer):
            raise ValueError("native_speech_observer")
        self._direct_speech_observer = direct_speech_observer
        self._node_respond_immediately = False
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
        self._caller_values = {}
        self._edit_recollect = False
        self._confirmation = None
        self._status = "not_started"
        self._completed = False
        self._outcome = None
        self._failure_reason = None
        self._llm_data = {}
        self._pending_instructions = []
        self._automatic_calls = 0
        self._auto_advance_tasks = set()

        if len(self._flow_catalogue) > 1:
            flow_functions = (
                self._flow_select_function(),
                self._flow_exit_function(),
            )
            global_functions += flow_functions
            global_names.extend(function.name for function in flow_functions)

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
        self._declarations_by_key = {
            entry.key: entry for entry in compiled.variable_declarations
        }
        for entry in compiled.variable_declarations:
            declaration = entry.data()
            if entry.origin != "explicit":
                # A response fallback is not a fact before its API node runs.
                continue
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

    @property
    def execution_busy(self):
        """Executing work, not the separate consumer-acknowledgment marker."""
        return bool(
            self._claim is not None or self._owned_task is not None
            or self._replacement.in_progress or self._replacement.calls_in_flight
        )

    def acknowledge_consumed_node(self):
        """Host-only acknowledgment after real context/tool consumer fences."""
        if self.execution_busy:
            return False
        return not self._pending_is_unentered(self._visit)

    def snapshot(self):
        facts = self.manager.state["facts"]
        progress = {}
        for entry in self.compiled.variable_declarations:
            declaration = entry.data()
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
            "respond_immediately": self._node_respond_immediately,
        }

    def _restore_recovery_snapshot(self):
        snapshot = self._recovery_snapshot
        if snapshot is None:
            return self.compiled.initial_node_id
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 1
            or type(snapshot.get("revision")) is not int
            or snapshot["revision"] < 1
        ):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        state = snapshot.get("state")
        if state in {"pending_effect", "terminal_pending", "complete", "failed", "closed"}:
            raise NativeFlowRecoveryError("native_recovery_pending")
        if state not in {"active", "effect_committed"}:
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")

        root = snapshot.get("root")
        if (
            root != native_flow_identity(self._root_compiled)
            or snapshot.get("source_digest")
            != native_flow_source_digest(self._root_compiled)
        ):
            raise NativeFlowRecoveryError("native_recovery_source")
        active = snapshot.get("active")
        if not isinstance(active, dict):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        active_id = active.get("tool_id")
        entry = self._flow_catalogue.get(active_id)
        if entry is None:
            raise NativeFlowRecoveryError("native_recovery_source")
        compiled = entry["compiled"]
        active_identity = {
            key: value for key, value in active.items()
            if key != "source_digest"
        }
        if (
            active_identity != native_flow_identity(compiled)
            or active.get("source_digest") != native_flow_source_digest(compiled)
        ):
            raise NativeFlowRecoveryError("native_recovery_source")

        current = snapshot.get("current_node_id")
        if not isinstance(current, str) or compiled.node(current) is None:
            raise NativeFlowRecoveryError("native_recovery_node")
        self.compiled = compiled
        self.execute_action = self._action_callback_for(compiled)
        self._declarations_by_key = {
            declaration.key: declaration
            for declaration in compiled.variable_declarations
        }
        self.manager.state["facts"] = {}
        self.manager.state["native_llm_data"] = {}
        for declaration in compiled.variable_declarations:
            data = declaration.data()
            if declaration.origin == "explicit" and data.get("defaultValue") is not None:
                self.manager.state["facts"][declaration.key] = (
                    self._normalize_assignment(declaration.key, data["defaultValue"])
                )

        facts = snapshot.get("facts")
        provenance = snapshot.get("fact_provenance")
        callers = snapshot.get("caller_facts")
        if (
            not isinstance(facts, dict) or len(facts) > 128
            or not isinstance(provenance, dict) or set(provenance) != set(facts)
            or not isinstance(callers, dict) or len(callers) > 128
            or set(callers) != {key for key, origin in provenance.items() if origin == "caller"}
        ):
            raise NativeFlowRecoveryError("native_recovery_facts")
        allowed_provenance = {"caller", "default", "derived", "action"}
        self._caller_values = {}
        self._derived = set()
        for key, value in facts.items():
            declaration = self._declarations_by_key.get(key)
            origin = provenance.get(key)
            if (
                declaration is None or origin not in allowed_provenance
                or (origin == "caller" and declaration.origin != "explicit")
            ):
                raise NativeFlowRecoveryError("native_recovery_facts")
            try:
                if origin in {"caller", "default"}:
                    normalized = self._normalize_assignment(key, value)
                else:
                    normalized = copy_native_json(value)
            except (RuntimeError, NativeValueError):
                raise NativeFlowRecoveryError("native_recovery_facts") from None
            except ValueError:
                raise NativeFlowRecoveryError("native_recovery_facts") from None
            self.manager.state["facts"][key] = normalized
            if origin == "caller":
                if callers[key] != normalized:
                    raise NativeFlowRecoveryError("native_recovery_facts")
                self._caller_values[key] = deepcopy(normalized)
            else:
                self._derived.add(key)

        llm_data = snapshot.get("llm_data", {})
        if not isinstance(llm_data, dict):
            raise NativeFlowRecoveryError("native_recovery_projection")
        try:
            self._llm_data = copy_native_json(llm_data)
        except ValueError:
            raise NativeFlowRecoveryError("native_recovery_projection") from None
        self.manager.state["native_llm_data"] = deepcopy(self._llm_data)

        self._catalog_active = snapshot.get("catalog_active")
        self._awaiting_flow_choice = snapshot.get("awaiting_flow_choice")
        if (
            type(self._catalog_active) is not bool
            or type(self._awaiting_flow_choice) is not bool
            or (self._awaiting_flow_choice and (
                active_id != str(self._root_compiled.identity.tool_id)
                or current != self._root_compiled.initial_node_id
            ))
        ):
            raise NativeFlowRecoveryError("native_recovery_state")
        node_revision = snapshot.get("node_revision")
        total_steps = snapshot.get("total_steps")
        if (
            type(node_revision) is not int or node_revision < 0
            or type(total_steps) is not int or not 1 <= total_steps <= _MAX_TOTAL_STEPS
        ):
            raise NativeFlowRecoveryError("native_recovery_revision")
        self._revision = node_revision
        self._total_steps = total_steps

        effect = snapshot.get("effect")
        if state == "effect_committed":
            if (
                not isinstance(effect, dict)
                or effect.get("status") != "committed"
                or effect.get("node_id") != current
                or effect.get("branch") not in {"success", "error", "not_found", "auth_error"}
                or compiled.node(current).type not in _ACTION_TYPES
                or effect.get("action_type") != compiled.node(current).type
                or effect.get("flow_version_id") != compiled.identity.flow_version_id
            ):
                raise NativeFlowRecoveryError("native_recovery_effect")
            target = compiled.next_node(current, effect["branch"])
            if target is None:
                raise NativeFlowRecoveryError("native_recovery_effect")
            current = target.node_id
            self._total_steps = min(_MAX_TOTAL_STEPS, self._total_steps + 1)
            self._resume_after_effect_commit = True
        elif effect is not None:
            raise NativeFlowRecoveryError("native_recovery_effect")
        self._active_node_id = current
        self._visits = {current: 1}
        return current

    async def _persist_recovery(
        self, *, current_node_id=None, state="active", effect=None,
    ):
        if self._snapshot_handler is None:
            return
        facts = deepcopy(self.manager.state["facts"])
        provenance = {}
        callers = {}
        for key, value in facts.items():
            if key in self._caller_values:
                provenance[key] = "caller"
                callers[key] = deepcopy(value)
            elif key in self._derived:
                provenance[key] = "derived"
            else:
                declaration = self._declarations_by_key.get(key)
                default = (
                    declaration.data().get("defaultValue")
                    if declaration is not None and declaration.origin == "explicit"
                    else None
                )
                provenance[key] = "default" if default == value else "action"
        payload = {
            "schema_version": 1,
            "revision": self._recovery_revision,
            "root": native_flow_identity(self._root_compiled),
            "source_digest": native_flow_source_digest(self._root_compiled),
            "active": {
                **native_flow_identity(self.compiled),
                "source_digest": native_flow_source_digest(self.compiled),
            },
            "current_node_id": current_node_id or self._active_node_id,
            "node_revision": self._revision,
            "total_steps": self._total_steps,
            "state": state,
            "terminal_state": {
                "status": self._status,
                "outcome": self._outcome,
                "failure_reason": self._failure_reason,
            },
            "catalog_active": self._catalog_active,
            "awaiting_flow_choice": self._awaiting_flow_choice,
            "facts": facts,
            "caller_facts": callers,
            "fact_provenance": provenance,
            "llm_data": deepcopy(self._llm_data),
            "effect": deepcopy(effect),
        }
        try:
            self._recovery_revision = await asyncio.to_thread(
                self._snapshot_handler, payload, self._recovery_revision,
            )
        except NativeFlowRecoveryError:
            self._fail("native_recovery_write_failed")
            raise
        except Exception:
            self._fail("native_recovery_write_failed")
            raise NativeFlowRecoveryError("native_recovery_write_failed") from None

    async def start(self):
        if self.closed or self._started or self.worker.has_finished():
            raise RuntimeError("native_flow_not_startable")
        self._started = True
        self._status = "running"
        task = asyncio.current_task()
        self._owned_task = task
        try:
            await self.manager.initialize()
            active = self._restore_recovery_snapshot()
            if self._recovery_snapshot is None:
                active = await self._resolve_segment(active, None)
            elif self._resume_after_effect_commit:
                active = await self._resolve_segment(active, None)
            elif self.compiled.node(active).type in (_ACTION_TYPES | _TERMINALS):
                raise NativeFlowRecoveryError("native_recovery_pending")
            if active is not None and self._is_open():
                await self.manager.set_node_from_config(
                    self._node_config(active, source_visit=None),
                )
                await self._persist_recovery(current_node_id=active)
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
            self._active_node_id = current
            await self._persist_recovery(current_node_id=current)
            node, data = self._node_data(current)
            kind = node.type
            if kind in _ANSWER_TYPES and self._is_wait_node(kind, data):
                self._active_node_id = current
                self._active_slot = None
                self._active_form_index = 0
                return current
            if kind == "initial":
                self._carry_private(data.get("systemPrompt"))
                if data.get("greeting") and not self._suppress_initial_greeting:
                    await self._speak(self._render(data["greeting"]))
                if len(self._flow_catalogue) > 1 and not self._catalog_active:
                    self._active_node_id = current
                    self._active_slot = None
                    self._active_form_index = 0
                    return current
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
                if self._status == "pending_effect":
                    return None
                if current is None:
                    return None
                cursor = self._visit if cursor is None else cursor
                continue
            if kind in _TERMINALS:
                self._active_node_id = current
                if kind == "end" and self._catalog_active:
                    return await self._return_to_flow_root(
                        node, data, cursor,
                    )
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
            from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

            assert_quote_payload_safe(self.compiled, self.facts, value)
            self._pending_instructions.append(value.strip())

    def _render(self, template, *, speech=True):
        from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

        text = render_text(template, self.facts, speech=speech)
        assert_quote_payload_safe(self.compiled, self.facts, text)
        return text

    async def _speak(self, text):
        if not text:
            return
        from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

        assert_quote_payload_safe(self.compiled, self.facts, text)
        if not self._is_open():
            raise RuntimeError("native_flow_closed")
        if self._direct_speech_observer is not None:
            observed = self._direct_speech_observer(text)
            if inspect.isawaitable(observed):
                observed = await observed
            if observed is False or not self._is_open():
                raise RuntimeError("native_speech_context_closed")
        self.manager.worker.node_speech_started(text, append_to_context=True)
        await self.manager.worker.queue_frame(TTSSpeakFrame(
            text=text, append_to_context=True,
        ))

    def _normalize_assignment(self, key, value):
        declaration = self._declaration(key)
        kind = declaration.get("type", "text")
        if kind is None:
            try:
                return copy_native_json(value)
            except ValueError:
                raise RuntimeError("native_assignment_type") from None
        slot = {
            "type": kind, "validation": {}, "useBuiltInValidator": False,
            "choices": declaration.get("choices", []),
        }
        try:
            return validate_value(slot, value, self.facts, today=self.today)
        except NativeValueError:
            raise RuntimeError("native_assignment_type") from None

    def _declaration(self, key):
        entry = self._declarations_by_key.get(key)
        if entry is None:
            raise RuntimeError("native_variable_missing")
        return entry.data()

    def _node_config(self, node_id, *, source_visit, form_index=0):
        node, data = self._node_data(node_id)
        messages = []
        functions = []
        respond_immediately = False
        speech = ""
        guided = False
        if node.type == "initial":
            if self._awaiting_flow_choice:
                speech = "Would you like another task, or should I end the call?"
                self._suppress_initial_greeting = False
            elif data.get("greeting"):
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
            form_index = next(
                (
                    index for index, slot in enumerate(slots)
                    if slot["variableKey"] not in self.facts
                ),
                len(slots),
            )
            if form_index >= len(slots):
                raise RuntimeError("native_form_order")
            self._active_form_index = form_index
            self._active_slot = slots[form_index]
            if form_index == 0 and data.get("introMessage"):
                speech = self._render(data["introMessage"])
            prompt = self._render(slots[form_index]["prompt"])
            speech = " ".join(item for item in (speech, prompt) if item)
            future_slots = [
                slot for slot in slots[form_index + 1:]
                if slot["variableKey"] not in self.facts
            ]
            functions.append(self._slot_schema(
                node_id, source_visit, slots[form_index], form_slots=future_slots,
            ))
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
        from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

        assert_quote_payload_safe(self.compiled, self.facts, messages)
        for function in functions:
            assert_quote_payload_safe(
                self.compiled, self.facts, (
                    getattr(function, "description", None),
                    getattr(function, "properties", None),
                ),
            )
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
        self._node_respond_immediately = bool(action["respond_immediately"])
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
        if self._edit_recollect:
            slot = None
            if node.type == "collect_slot":
                slot = data["slot"]
            elif node.type == "collect_form":
                slot = sorted(data["slots"], key=lambda item: item["order"])[action["form_index"]]
            elif node.type == "confirmation":
                self._edit_recollect = False
            if slot is not None:
                self.manager.state["facts"].pop(slot["variableKey"], None)
        self._active_user_ids = self._next_user_ids()
        if action.get("speech"):
            await self._speak(action["speech"])
        if self._pending_entry is not None and source is not None:
            self._pending_entry = (action["node_id"], visit)
        if not self._is_current(visit):
            raise RuntimeError("native_stale_entry")

    def _functions_for_visit(self, node, data, visit, form_index):
        node_id = node.node_id
        if node.type == "initial":
            functions = []
            root_selection = (
                len(self._flow_catalogue) > 1
                and not self._catalog_active
                and (self._total_steps == 1 or self._awaiting_flow_choice)
            )
            if (
                not self._awaiting_flow_choice
                and (data.get("waitForResponse", True) or root_selection)
            ):
                functions.append(self._text_response_schema(node_id, visit))
            return functions
        if node.type == "collect_slot":
            return [self._slot_schema(node_id, visit, data["slot"])]
        if node.type == "collect_form":
            slots = sorted(data["slots"], key=lambda item: item["order"])
            current = slots[form_index]
            future_slots = [
                slot for slot in slots[form_index + 1:]
                if slot["variableKey"] not in self.facts
            ]
            return [self._slot_schema(
                node_id, visit, current, form_slots=future_slots,
            )]
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

    def _flow_select_function(self):
        ids = sorted(self._flow_catalogue)
        choices = "; ".join(
            f"{self._flow_catalogue[flow_id]['name'] or flow_id} ({flow_id})"
            for flow_id in ids
        )

        async def select_flow(arguments, manager):
            if self._visit is None or self._active_node_id is None:
                return self._rejected("flow_selection_unavailable")
            return await self._select_assigned_flow(
                self._active_node_id, self._visit, arguments,
            )

        return FlowsFunctionSchema(
            name=f"{_NATIVE_PREFIX}select_flow_{uuid4().hex}",
            description=(
                "Before entering a flow step, select one currently assigned and "
                "published flow by tool_id. Available flows: " + choices
            )[:512],
            properties={"tool_id": {"type": "string", "enum": ids}},
            required=["tool_id"],
            handler=select_flow,
            cancel_on_interruption=True,
        )

    def _flow_exit_function(self):
        async def exit_call(arguments, manager):
            return await self._exit_at_flow_root(arguments, manager)

        return FlowsFunctionSchema(
            name="native_exit_call",
            description=(
                "End this call from the native flow-selection root when the caller "
                "explicitly asks to finish."
            ),
            properties={},
            required=[],
            handler=exit_call,
            cancel_on_interruption=True,
        )

    def _at_flow_root(self):
        return (
            self.compiled.identity.tool_id == self._root_compiled.identity.tool_id
            and self._active_node_id == self._root_compiled.initial_node_id
            and self.manager.current_node == self._root_compiled.initial_node_id
            and (self._total_steps == 1 or self._awaiting_flow_choice)
        )

    def _action_callback_for(self, compiled):
        if self._action_runners is None:
            return self._default_execute_action
        tool_id = str(compiled.identity.tool_id)
        entry = self._flow_catalogue.get(tool_id)
        runner = self._action_runners.get(tool_id)
        if entry is None or entry["compiled"] is not compiled:
            raise RuntimeError("native_action_runner_scope")
        if any(node.type in _ACTION_TYPES for node in compiled.nodes):
            if runner is None:
                raise RuntimeError("native_action_runner_missing")
            return runner.execute
        return runner.execute if runner is not None else None

    def _replace_compiled_flow(self, compiled, caller_values):
        action_callback = self._action_callback_for(compiled)
        old_declarations = self._declarations_by_key
        old_types = {
            key: entry.data().get("type")
            for key, entry in old_declarations.items()
        }
        self.compiled = compiled
        self._declarations_by_key = {
            entry.key: entry for entry in compiled.variable_declarations
        }
        self.manager.state["facts"] = {}
        self.manager.state["native_llm_data"] = {}
        for entry in compiled.variable_declarations:
            declaration = entry.data()
            if entry.origin == "explicit" and declaration.get("defaultValue") is not None:
                self.manager.state["facts"][entry.key] = self._normalize_assignment(
                    entry.key, declaration["defaultValue"],
                )
        carried = {}
        for key, value in caller_values.items():
            entry = self._declarations_by_key.get(key)
            if (
                entry is None or entry.origin != "explicit"
                or old_types.get(key) != entry.data().get("type")
            ):
                continue
            try:
                normalized = self._normalize_assignment(key, value)
            except (RuntimeError, NativeValueError):
                continue
            self.manager.state["facts"][key] = normalized
            carried[key] = deepcopy(normalized)
        self._caller_values = carried
        self.execute_action = action_callback
        self._derived.clear()
        self._llm_data = {}
        self._confirmation = None
        self._edit_recollect = False
        self._pending_instructions.clear()
        self._retries = {}
        self._visits = {}
        self._accepted.clear()
        self._spent_effects.clear()
        self._active_node_id = None
        self._active_slot = None
        self._active_form_index = 0
        self.manager.state["native_llm_data"] = {}

    async def _select_assigned_flow(self, node_id, visit, arguments):
        if (
            not self._available(node_id, visit)
            or not self._at_flow_root()
            or not self._new_user_turn(visit)
            or not self._arguments(arguments, ["tool_id"])
        ):
            return self._rejected("flow_selection_unavailable")
        flow_id = arguments["tool_id"]
        target = self._flow_catalogue.get(flow_id)
        if target is None:
            return self._rejected("flow_selection_invalid")

        claim = object()
        task = asyncio.current_task()
        self._claim = claim
        self._owned_task = task
        try:
            self._awaiting_flow_choice = False
            self._suppress_initial_greeting = False
            if flow_id == self.compiled.identity.tool_id:
                self._catalog_active = True
                next_node = self._default_next(node_id)
                if next_node is None:
                    self._fail("flow_selection_dead_end")
                    return {"status": "error", "reason": "flow_selection_dead_end"}
                active = await self._resolve_segment(next_node, visit)
            else:
                caller_values = deepcopy(self._caller_values)
                self._replace_compiled_flow(target["compiled"], caller_values)
                self._catalog_active = True
                active = await self._resolve_segment(
                    self.compiled.initial_node_id, visit,
                )
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            if active is None:
                self._pending_entry = None
                return self._terminal_or_error({
                    "status": "accepted", "current_node": node_id,
                })
            self._pending_entry = (active, None)
            return (
                {"status": "selected", "flow_id": flow_id, "current_node": active},
                self._node_config(active, source_visit=visit),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("flow_selection_runtime")
            return {"status": "error", "reason": "flow_selection_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    async def _return_to_flow_root(self, node, data, source_visit):
        closing = data.get("closingMessage", "")
        if closing:
            await self._speak(self._render(closing))
        caller_values = deepcopy(self._caller_values)
        self._replace_compiled_flow(self._root_compiled, caller_values)
        self._catalog_active = False
        self._awaiting_flow_choice = True
        self._suppress_initial_greeting = True
        return await self._resolve_segment(
            self._root_compiled.initial_node_id, source_visit,
        )

    async def _exit_at_flow_root(self, arguments, manager):
        visit = self._visit
        node_id = self._active_node_id
        if (
            not isinstance(arguments, dict) or arguments
            or visit is None or node_id is None
            or not self._available(node_id, visit)
            or not self._at_flow_root()
            or not self._new_user_turn(visit)
        ):
            return self._rejected("flow_exit_unavailable")
        end_node = next(
            (node for node in self.compiled.nodes if node.type == "end"),
            None,
        )
        if end_node is None:
            return self._rejected("flow_exit_unavailable")
        claim = object()
        task = asyncio.current_task()
        self._claim = claim
        self._owned_task = task
        try:
            await self._run_terminal(end_node, end_node.data())
            return {
                "status": self._status,
                "outcome": self._outcome,
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail("flow_exit_runtime")
            return {"status": "error", "reason": "flow_exit_runtime"}
        finally:
            if self._claim is claim:
                self._claim = None
            if self._owned_task is task:
                self._owned_task = None

    def _slot_schema(self, node_id, visit, slot, *, form_slots=()):
        slots = (slot, *tuple(form_slots))
        properties = {}
        for current in slots:
            variable = current["variableKey"]
            declaration = self._declaration(variable)
            slot_type = current.get("type", declaration.get("type", "text"))
            validation = current.get("validation", {})
            if slot_type == "number":
                schema = {"type": "number"}
                for key in ("min", "max"):
                    if key in validation:
                        schema[key] = validation[key]
            else:
                schema = {
                    "type": "string", "minLength": 1,
                    "maxLength": _MAX_ARGUMENTS,
                }
                for key in ("minLength", "maxLength", "pattern"):
                    value = validation.get(key)
                    if value is not None:
                        if key in {"minLength", "maxLength"} and (
                            type(value) is not int
                        ):
                            continue
                        schema[key] = max(1, value) if key == "minLength" else value
                if slot_type == "choice":
                    schema["enum"] = validation.get(
                        "choices", declaration.get("choices", []),
                    )
            properties[variable] = schema

        async def collect(arguments, manager):
            return await self._collect_slot(
                node_id, visit, slot, arguments, form_slots=form_slots,
            )

        return self._schema(
            node_id, visit,
            "Record explicit caller-provided values for the current form fields.",
            properties,
            [slot["variableKey"]], collect,
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

    async def _collect_slot(self, node_id, visit, slot, arguments, *, form_slots=()):
        if not self._available(node_id, visit):
            return self._rejected("busy_or_stale")
        key = slot["variableKey"]
        node, data = self._node_data(node_id)
        candidate_slots = (slot, *tuple(form_slots))
        if node.type != "collect_form":
            candidate_slots = (slot,)
        allowed_keys = {item["variableKey"] for item in candidate_slots}
        latest = self._latest_user_text()
        if (
            not isinstance(arguments, dict)
            or key not in arguments
            or not set(arguments).issubset(allowed_keys)
            or not self._new_user_turn(visit)
            or latest is None
        ):
            return self._rejected("invalid_arguments")
        for candidate in candidate_slots:
            variable = candidate["variableKey"]
            if variable not in arguments:
                continue
            raw = arguments[variable]
            declaration = self._declaration(variable)
            slot_type = candidate.get("type", declaration.get("type", "text"))
            valid_value_type = (
                type(raw) is int and abs(raw) <= 10 ** 100
                or type(raw) is float and math.isfinite(raw) and abs(raw) <= 1e100
                if slot_type == "number"
                else isinstance(raw, str) and raw.strip()
                and len(raw) <= _MAX_ARGUMENTS
            )
            if not valid_value_type:
                return self._rejected("invalid_arguments")
            evidence_slot = {**candidate, "type": slot_type}
            if slot_type == "choice":
                evidence_slot["choices"] = declaration.get("choices", [])
            if not caller_value_is_grounded(
                evidence_slot, latest, raw, today=self.today,
            ):
                return self._rejected("caller_response_mismatch")
        claim = object()
        self._claim = claim
        task = asyncio.current_task()
        self._owned_task = task
        try:
            candidate_facts = self.facts
            collected = {}
            for candidate in candidate_slots:
                variable = candidate["variableKey"]
                if variable not in arguments:
                    continue
                declaration = self._declaration(variable)
                slot_type = candidate.get("type", declaration.get("type", "text"))
                slot_config = {**candidate, "type": slot_type}
                if slot_type == "choice":
                    slot_config["choices"] = declaration.get("choices", [])
                try:
                    value = validate_value(
                        slot_config, arguments[variable], candidate_facts,
                        today=self.today,
                    )
                except NativeValueError:
                    if variable == key:
                        return await self._retry(node_id, visit, candidate, variable, claim)
                    return self._rejected("form_answer_invalid")
                collected[variable] = value
                candidate_facts[variable] = value
            if not self._owned(node_id, visit, claim, task):
                return self._rejected("busy_or_stale")
            self.manager.state["facts"].update(collected)
            for variable, value in collected.items():
                self._caller_values[variable] = deepcopy(value)
                self._derived.discard(variable)
            self._confirmation = None
            if node.type == "collect_form":
                slots = sorted(data["slots"], key=lambda item: item["order"])
                next_index = next(
                    (
                        index for index, item in enumerate(slots)
                        if item["variableKey"] not in self.manager.state["facts"]
                    ),
                    len(slots),
                )
                if next_index < len(slots):
                    target_config = self._node_config(
                        node_id, source_visit=visit, form_index=next_index,
                    )
                    result = {
                        "status": "accepted", "current_node": node_id,
                        "facts": deepcopy(collected),
                    }
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
                "facts": deepcopy(collected),
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

    @staticmethod
    def _same_confirmation(caller, response):
        """Whole affirmative phrases authorize; an edit never grants consent."""
        def normalize(value):
            value = re.sub(r"[.!?]+$", "", value.casefold().strip().replace("’", "'"))
            return " ".join(value.split())

        caller, response = normalize(caller), normalize(response)
        if response == "yes":
            return caller in _YES_PHRASES
        if response == "no":
            return caller in _NO_PHRASES
        # The model may classify a natural correction request only when the
        # node explicitly enables its edit branch. This clears confirmation
        # and prepared results; it can never authorize a write.
        return response == "edit" and bool(caller)

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
        if latest is None or not self._same_confirmation(latest, response):
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
        # Confirmation is invalidated, not every unrelated caller answer.
        # The configured edit route still has to collect a fresh answer;
        # per-entry/user-turn guards prohibit reusing the previous answer.
        for key in tuple(self._derived):
            if key in self._caller_values:
                facts[key] = deepcopy(self._caller_values[key])
            else:
                facts.pop(key, None)
        self._derived.clear()
        self._edit_recollect = True
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
        await self._persist_recovery(
            current_node_id=node_id,
            state="pending_effect",
            effect={
                "status": "pending",
                "node_id": node_id,
                "action_type": kind,
                "flow_version_id": self.compiled.identity.flow_version_id,
            },
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
        if result.failure_reason == "effect_outcome_unknown":
            self._status = "pending_effect"
            self._failure_reason = "effect_outcome_unknown"
            self._outcome = "effect_outcome_unknown"
            await self._persist_recovery(
                current_node_id=node_id,
                state="pending_effect",
                effect={
                    "status": "pending",
                    "node_id": node_id,
                    "action_type": kind,
                    "flow_version_id": self.compiled.identity.flow_version_id,
                },
            )
            return None, "error"
        mapped_values = result.variables if result.success else {}
        valid_keys = set(self._declarations_by_key)
        if set(mapped_values) - valid_keys:
            self._fail("action_mapping")
            return None, "error"
        from botelier.voice.flows.native_quote_actions import NativeQuoteError
        from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

        try:
            assert_quote_payload_safe(
                self.compiled, {**self.facts, **mapped_values},
                result.llm_data if result.success else {},
                mapped_variables=mapped_values,
            )
        except NativeQuoteError as exc:
            self._llm_data = {}
            self.manager.state["native_llm_data"] = {}
            self._fail(exc.code)
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
        await self._persist_recovery(
            current_node_id=node_id,
            state="effect_committed",
            effect={
                "status": "committed",
                "node_id": node_id,
                "action_type": kind,
                "flow_version_id": self.compiled.identity.flow_version_id,
                "branch": handle,
            },
        )
        # onComplete is a spoken bridge only when no explicit presentation follows.
        if result.success and configuration.get("onComplete"):
            target_node = self.compiled.node(target)
            if target_node is None or target_node.type != "api_response":
                await self._speak(self._render(configuration["onComplete"]))
        return target, handle

    async def _run_terminal(self, node, data):
        node_id = node.node_id
        await self._persist_recovery(
            current_node_id=node_id,
            state="terminal_pending",
            effect={
                "status": "pending",
                "node_id": node_id,
                "terminal_type": node.type,
                "flow_version_id": self.compiled.identity.flow_version_id,
            },
        )
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
        if text and getattr(self.terminal_handler, "owns_speech", False) is not True:
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
        await self._persist_recovery(
            current_node_id=node_id,
            state=(
                "complete" if self._completed
                else "terminal_pending" if result.accepted
                else "failed"
            ),
            effect={
                "status": "pending" if result.accepted and not result.completed else "settled",
                "node_id": node_id,
                "terminal_type": node.type,
                "flow_version_id": self.compiled.identity.flow_version_id,
            },
        )

    def observe_terminal_result(self, node_id, result):
        """Record only a matching deferred host result for the active terminal.

        A transfer's immediate Twilio acceptance is not proof that the human
        destination answered. Unconfirmed outcomes also remain pending so the
        host cannot present them as safely retryable or completed.
        """
        if (
            not self._is_open()
            or self._active_node_id != node_id
            or self._status != "terminal_pending"
            or not isinstance(result, dict)
        ):
            return False
        status = result.get("status")
        if status == "transferred":
            self._outcome = "carrier_accepted_pending"
            self._failure_reason = None
        elif status == "unconfirmed":
            self._outcome = "unconfirmed"
            self._failure_reason = None
        elif status in {"failed", "skipped", "error"}:
            self._status = "terminal_failed"
            self._outcome = "failed"
            self._failure_reason = "transfer_failed"
        else:
            return False
        return True

    async def observe_terminal_result_and_persist(self, node_id, result):
        if not self.observe_terminal_result(node_id, result):
            return False
        await self._persist_recovery(
            current_node_id=node_id,
            state="terminal_pending" if self._status == "terminal_pending" else "failed",
            effect={
                "status": "pending" if self._status == "terminal_pending" else "settled",
                "node_id": node_id,
                "terminal_type": "transfer",
                "flow_version_id": self.compiled.identity.flow_version_id,
            },
        )
        return True

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

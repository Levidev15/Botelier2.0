"""Bounded text-only host for the full admitted native flow graph."""

import asyncio
from copy import deepcopy
import inspect
import math

from pipecat.frames.frames import (
    FunctionCallCancelFrame,
    FunctionCallResultFrame,
    FunctionCallsStartedFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from botelier.voice.agent import VoiceAgentConfig
from botelier.voice.engine import (
    AssistantLocalTimeContextUpdater,
    VoiceEngineFactory,
)
from botelier.voice.flows.native_adapter import NativeFlowAdapter
from botelier.voice.flows.native_execution import NativeTerminalResult
from botelier.voice.flows.native_graph import CompiledFlow
from botelier.voice.flows.native_text_observer import (
    NativeTextObserver,
    NativeTextTurnBarrier,
)
from botelier.voice.flows.native_action_preview import (
    NativeActionPreview, NativePreviewError,
)


_START_TIMEOUT = 10.0
_CLOSE_TIMEOUT = 5.0
_MAX_TURN_TIMEOUT = 300.0
_MAX_OUTPUT_MESSAGE = 8000
_MAX_TURN_OUTPUT = 16000
_MAX_TURN_MESSAGES = 16


class NativeTextHostError(RuntimeError):
    """Payload-free error with a stable application-facing category."""

    _CODES = {
        "invalid", "busy", "closed", "timeout",
        "unsupported_provider", "initialization",
    }

    def __init__(self, code):
        self.code = code if code in self._CODES else "initialization"
        super().__init__(self.code)


class NativeTextHost:
    """One real native FlowManager and PipelineWorker without audio services."""

    error_type = NativeTextHostError

    def __init__(
        self,
        compiled: CompiledFlow,
        *,
        config: VoiceAgentConfig,
        api_keys: dict[str, str],
        session_factory,
        turn_timeout: float = 120.0,
        execution_mode: str = "preview",
        global_functions=(),
        available_flows=None,
        preview=None,
    ):
        if not isinstance(compiled, CompiledFlow) or not isinstance(config, VoiceAgentConfig):
            raise NativeTextHostError("invalid")
        if (
            not isinstance(turn_timeout, (int, float))
            or isinstance(turn_timeout, bool)
            or not math.isfinite(turn_timeout)
            or turn_timeout <= 0
            or turn_timeout > _MAX_TURN_TIMEOUT
            or not isinstance(api_keys, dict)
            or not callable(session_factory)
            or execution_mode not in {"execute", "preview"}
        ):
            raise NativeTextHostError("invalid")
        self.compiled = compiled
        self.config = config
        self._session_factory = session_factory
        self._turn_timeout = float(turn_timeout)
        self._execution_mode = execution_mode
        if preview is not None and not isinstance(preview, NativeActionPreview):
            raise NativeTextHostError("invalid")
        self.preview = preview
        self._global_functions = tuple(global_functions)
        self._available_flows = available_flows
        self._action_runner = None
        self._action_runners = {}
        self._adapter_close_timeout = _CLOSE_TIMEOUT
        self._expected_model_ends = 0
        self._api_keys = dict(api_keys)
        self.closed = False
        self.adapter = None
        self._llm = None
        self._context = None
        self._context_aggregator = None
        self._capture = None
        self._time_updater = None
        self._pipeline_processors = None
        self._worker = None
        self._runner = None
        self._runner_task = None
        self._start_task = None
        self._started_event = asyncio.Event()
        self._changed = asyncio.Event()
        if self.preview is not None:
            self.preview.set_on_change(self._changed.set)
            self.preview.set_context_provider(self._active_preview_context)
        self._close_lock = asyncio.Lock()
        self._close_complete = asyncio.Event()
        self._send_task = None
        self._turn = None
        self._adapter_start_task = None
        self._adapter_start_settled = False
        self._active_generation = 0
        self._response_starts = 0
        self._response_ends = 0
        self._model_inflight = 0
        self._model_parts = []
        self._model_length = 0
        self._model_generation = None
        self._active_calls = {}
        self._function_called = None
        self._function_result = None
        self._transition_expected = 0
        self._outputs = []
        self._output_start = 0
        self._failure = None
        self._turn_barriers = {}
        self._consumer_ack_pending = False
        self._observer = NativeTextObserver(self)

    @property
    def context(self):
        """The host-owned LLMContext, exposed for app integration and tests."""
        return self._context

    async def start(self):
        if self.closed:
            raise NativeTextHostError("closed")
        if self._worker is not None:
            raise NativeTextHostError("busy")
        provider = getattr(self.config, "llm_provider", "")
        if not isinstance(provider, str) or provider.lower() not in {
            "openai", "google_gemini",
        }:
            await self.close()
            raise NativeTextHostError("unsupported_provider")
        greeting = self.config.greeting_message or ""
        if self.compiled.node(self.compiled.initial_node_id).data().get("greeting", "").strip():
            greeting = ""
        if not isinstance(greeting, str) or len(greeting) > _MAX_OUTPUT_MESSAGE:
            await self.close()
            raise NativeTextHostError("initialization")

        self._start_task = asyncio.current_task()
        try:
            async with asyncio.timeout(_START_TIMEOUT):
                self._build_pipeline()
                self._runner = WorkerRunner(
                    handle_sigint=False,
                    handle_sigterm=False,
                )
                await self._runner.add_workers(self._worker)
                self._runner_task = asyncio.create_task(
                    self._runner.run(), name="native-text-host-runner",
                )
                self._runner_task.add_done_callback(self._runner_done)
                await self._started_event.wait()
                self._raise_if_failed()

                if greeting:
                    await self._worker.queue_frame(TTSSpeakFrame(text=greeting))
                    await self._ack_output()
                self._turn = {
                    "kind": "start", "generation": self._active_generation,
                    "response_ends": self._response_ends, "output_start": 0,
                }
                self._adapter_start_task = asyncio.create_task(
                    self.adapter.start(), name="native-text-adapter-start",
                )
                self._adapter_start_task.add_done_callback(
                    self._adapter_start_done,
                )
                pending = await self._await_start_idle()
                if pending:
                    result = self._pending_result()
                    return result
                await self._adapter_start_task
                if await self._await_start_idle():
                    return self._pending_result()
                self._raise_if_failed()
                result = self._result(0)
                self._outputs.clear()
                self._turn = None
                return result
        except TimeoutError:
            await self.close()
            raise NativeTextHostError("timeout") from None
        except NativeTextHostError:
            if not self.closed:
                await self.close()
            raise
        except asyncio.CancelledError:
            if self.closed:
                raise NativeTextHostError("closed") from None
            await self.close()
            raise
        except Exception:
            await self.close()
            raise NativeTextHostError("initialization") from None
        finally:
            if self._start_task is asyncio.current_task():
                self._start_task = None

    def _build_pipeline(self):
        self._llm = VoiceEngineFactory.create_llm_service(
            self.config, self._api_keys,
        )
        self._api_keys = {}
        self._context = LLMContext(messages=[
            {"role": "system", "content": self.config.system_prompt},
        ])
        self._context_aggregator = LLMContextAggregatorPair(
            self._context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=ExternalUserTurnStrategies(),
            ),
            realtime_service_mode=False,
        )
        self._capture = self._observer.processor
        self._time_updater = AssistantLocalTimeContextUpdater(
            self._context, self.config,
        )
        self._pipeline_processors = [
            self._context_aggregator.user(),
            self._time_updater,
            self._llm,
            self._capture,
            self._context_aggregator.assistant(),
        ]
        pipeline = Pipeline(self._pipeline_processors)
        self._worker = PipelineWorker(
            pipeline,
            enable_rtvi=False,
            enable_turn_tracking=False,
            idle_timeout_secs=None,
            name="native-text-host",
        )

        @self._worker.event_handler("on_pipeline_started")
        async def started(_, frame):
            self._started_event.set()
            self._changed.set()

        @self._worker.event_handler("on_pipeline_finished")
        async def finished(_, frame):
            self.closed = True
            self._changed.set()

        @self._worker.event_handler("on_pipeline_error")
        async def failed(_, frame):
            self._pipeline_error()

        @self._llm.event_handler("on_before_push_frame")
        async def starting(_, frame):
            if isinstance(frame, FunctionCallsStartedFrame):
                for call in frame.function_calls:
                    self._active_calls[call.tool_call_id] = {
                        "name": call.function_name,
                        "arguments": deepcopy(call.arguments),
                        "generation": self._active_generation,
                    }
                self._changed.set()

        assistant = self._context_aggregator.assistant()

        @assistant.event_handler("on_before_process_frame")
        async def transition_expected(_, frame):
            properties = getattr(frame, "properties", None)
            if (
                isinstance(frame, FunctionCallResultFrame)
                and (properties is None or properties.is_final)
                and properties is not None
                and properties.on_context_updated is not None
            ):
                # Track the SDK callback's actual lifetime. It may complete
                # without queueing any node frames; the observer separately
                # counts and acknowledges only real message/tool updates.
                self._transition_expected += 1
                callback = properties.on_context_updated

                async def context_update_finished():
                    try:
                        result = callback()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        if not self.closed:
                            self._pipeline_error()
                        raise
                    finally:
                        self._transition_expected = max(
                            0, self._transition_expected - 1,
                        )
                        self._changed.set()

                properties.on_context_updated = context_update_finished
                self._changed.set()

        @assistant.event_handler("on_after_process_frame")
        async def completed(_, frame):
            if isinstance(frame, FunctionCallCancelFrame):
                self._active_calls.pop(frame.tool_call_id, None)
            elif isinstance(frame, FunctionCallResultFrame):
                properties = frame.properties
                if properties is not None and not properties.is_final:
                    return
                called = self._active_calls.pop(
                    frame.tool_call_id,
                    {
                        "name": frame.function_name,
                        "arguments": deepcopy(frame.arguments),
                        "generation": self._active_generation,
                    },
                )
                if not self.closed and called["generation"] == self._active_generation:
                    self._function_called = called["name"]
                    self._function_result = deepcopy(frame.result)
            self._changed.set()

        from botelier.voice.flows.native_actions import NativeActionRunner

        compiled_flows = {
            str(self.compiled.identity.tool_id): self.compiled,
            **{
                flow_id: entry["compiled"]
                for flow_id, entry in (self._available_flows or {}).items()
            },
        }
        self._action_runners = {
            flow_id: NativeActionRunner(
                compiled, self._session_factory,
                execution_mode=self._execution_mode, channel="simulation",
                preview=self.preview,
                preview_scope=lambda node, flow_id=flow_id: self._preview_scope(
                    flow_id, node,
                ),
            )
            for flow_id, compiled in compiled_flows.items()
        }
        self._action_runner = self._action_runners[
            str(self.compiled.identity.tool_id)
        ]
        execute_action = self._action_runner.execute
        self.adapter = NativeFlowAdapter(
            self.compiled,
            llm=self._llm,
            worker=self._worker,
            context_aggregator=self._context_aggregator,
            execute_action=execute_action,
            terminal_handler=self._simulate_terminal,
            global_functions=self._global_functions,
            available_flows=self._available_flows,
            action_runners=self._action_runners,
            text_observer=self._observer,
            text_observer_timeout=min(5.0, self._turn_timeout),
        )
        self._worker.add_reached_downstream_filter((NativeTextTurnBarrier,))

        @self._worker.event_handler("on_frame_reached_downstream")
        async def turn_barrier(_, frame):
            future = self._turn_barriers.get(id(frame))
            if future is not None and not future.done():
                future.set_result(None)

    def _node_update_consumer_acknowledged(self):
        if self.adapter is not None and self.adapter.snapshot().get("respond_immediately"):
            self._expected_model_ends = max(self._expected_model_ends, self._response_ends + 1)
        self._changed.set()

    async def _simulate_terminal(self, node, facts):
        if node.type == "end":
            return NativeTerminalResult(True, completed=True)
        # Transfer is a simulated effect; no carrier is ever contacted.
        if self.preview is None:
            return NativeTerminalResult(False, failure_reason="preview_only_transfer")
        node_id = getattr(node, "node_id", None)
        if not isinstance(node_id, str) or not node_id:
            return NativeTerminalResult(False, failure_reason="preview_only_transfer")
        try:
            scope = self._preview_scope(str(self.compiled.identity.tool_id), node)
            sample = await self.preview.request(
                node_id=node_id, source_kind="transfer", scope=scope,
                current_scope=lambda: self._preview_scope(
                    str(self.compiled.identity.tool_id), node,
                ),
            )
        except NativePreviewError as exc:
            return NativeTerminalResult(False, failure_reason=exc.code)
        self.preview.record_effect("transfer", node.node_id)
        if not sample.success:
            return NativeTerminalResult(False, failure_reason="preview_transfer_rejected")
        return NativeTerminalResult(True, completed=True)

    def _preview_scope(self, flow_id, node):
        adapter = self.adapter
        revision = getattr(adapter, "_revision", 0)
        visit = getattr(adapter, "_visit", None)
        identity = self._action_runners.get(flow_id)
        compiled = getattr(identity, "compiled", self.compiled)
        return (
            str(compiled.identity.tool_id),
            str(compiled.identity.flow_version_id),
            str(node.node_id),
            str(self._active_generation),
            str(revision),
            str(id(visit)) if visit is not None else "no-visit",
        )

    def _active_preview_context(self):
        if self.closed or self.adapter is None:
            raise NativePreviewError("preview_scope_invalid")
        adapter = self.adapter
        state = adapter.snapshot()
        visit = getattr(adapter, "_visit", None)
        return adapter.compiled, adapter.facts, (
            str(adapter.compiled.identity.tool_id),
            str(adapter.compiled.identity.flow_version_id),
            str(self._active_generation),
            str(getattr(adapter, "_revision", 0)),
            str(id(visit)) if visit is not None else "no-visit",
            str(state.get("current_node") or "no-node"),
        )

    def _pending_result(self):
        result = self._result(self._turn["output_start"] if self._turn else 0)
        if self._turn is not None:
            # Publish each output occurrence once without resetting the original
            # model-response baseline or deduplicating legitimate repeated text.
            self._turn["output_start"] = len(self._outputs)
        result["pending_preview"] = self.preview.snapshot() if self.preview else None
        result["safe_preview_effects"] = self.preview.effects if self.preview else []
        result["execution_mode"] = "preview"
        return result

    def pending_preview(self):
        return self.preview.snapshot() if self.preview else None

    def turn_pending(self):
        return self._turn is not None

    def submit_preview(self, request_id, response):
        if self.preview is None:
            raise NativePreviewError("preview_closed")
        self.preview.submit(request_id, response)

    async def resume_preview(self):
        if self._turn is None or self.preview is None:
            raise NativePreviewError("preview_request_mismatch")
        if self._send_task is not None:
            raise NativeTextHostError("busy")
        task = asyncio.current_task()
        self._send_task = task
        try:
            async with asyncio.timeout(self._turn_timeout):
                if self._turn["kind"] == "start":
                    if self._adapter_start_task is None:
                        raise NativeTextHostError("initialization")
                    if await self._await_start_idle():
                        return self._pending_result()
                    await self._adapter_start_task
                    if await self._await_start_idle():
                        return self._pending_result()
                else:
                    await self._await_turn(self._turn["response_ends"])
                if self.preview.snapshot() is not None:
                    return self._pending_result()
                result = self._result(self._turn["output_start"])
                self._outputs.clear()
                self._turn = None
                return result
        except TimeoutError:
            await self.close()
            raise NativeTextHostError("timeout") from None
        finally:
            if self._send_task is task:
                self._send_task = None
                self._changed.set()

    def _native_idle(self):
        if self.adapter is None or self._model_inflight or self._active_calls:
            return False
        start_task = getattr(self, "_adapter_start_task", None)
        if start_task is not None and not start_task.done():
            return False
        if self._transition_expected or self._observer.node_updates:
            return False
        if self._response_ends < self._expected_model_ends or self.adapter.execution_busy:
            return False
        if self._consumer_ack_pending:
            return False
        state = self.adapter.snapshot()
        node = self.adapter.compiled.node(state["current_node"]) if state["current_node"] else None
        return not (
            node is not None and node.type == "message"
            and node.data().get("deliveryMode", "static") == "guided"
            and not node.data().get("waitForResponse", True)
            and state["status"] == "running"
        )

    async def _drain_native_output(self):
        await self._ack_output()
        if self._observer.has_pending_speech and not self._observer.node_updates:
            await self._observer.commit_pending_speech()
            await self._ack_output()
        if (
            self.adapter is not None and not self._transition_expected
            and not self._observer.node_updates
        ):
            acknowledged = self.adapter.acknowledge_consumed_node()
            self._consumer_ack_pending = not acknowledged
            if acknowledged:
                self._changed.set()

    async def _await_start_idle(self):
        while True:
            self._raise_if_failed()
            if self.preview is not None and self.preview.snapshot() is not None:
                return True
            if (
                self._adapter_start_task is not None
                and self._adapter_start_task.done()
                and not self._adapter_start_settled
            ):
                self._adapter_start_settled = True
                await asyncio.sleep(0)
                continue
            await self._drain_native_output()
            if self._native_idle():
                return False
            self._changed.clear()
            if self.preview is not None and self.preview.snapshot() is not None:
                return True
            if self._native_idle():
                continue
            await self._changed.wait()

    async def _await_turn(self, initial_response_ends):
        while True:
            self._raise_if_failed()
            if self.preview is not None and self.preview.snapshot() is not None:
                return True
            if self._turn_ready(initial_response_ends):
                await self._drain_native_output()
                self._raise_if_failed()
                if self.preview is not None and self.preview.snapshot() is not None:
                    return True
                if self._turn_ready(initial_response_ends):
                    return False
            self._changed.clear()
            if (
                self._failure is not None or self.closed
                or self._turn_ready(initial_response_ends)
                or self.preview is not None and self.preview.snapshot() is not None
            ):
                continue
            await self._changed.wait()

    def node_update_failed(self):
        if not self.closed:
            self._failure = NativeTextHostError("timeout")
        self._changed.set()

    def _record_output(self, text):
        if self.closed or not isinstance(text, str) or not text:
            return
        turn_total = sum(
            len(item["content"]) for item in self._outputs[self._output_start:]
        )
        if (
            len(text) > _MAX_OUTPUT_MESSAGE
            or len(self._outputs) >= _MAX_TURN_MESSAGES
            or turn_total + len(text) > _MAX_TURN_OUTPUT
        ):
            self._failure = NativeTextHostError("initialization")
            self._changed.set()
            return
        self._outputs.append({"role": "assistant", "content": text})
        self._changed.set()

    def _model_started(self):
        if self.closed:
            return
        self._response_starts += 1
        self._model_inflight += 1
        self._model_parts = []
        self._model_length = 0
        self._model_generation = self._active_generation
        self._changed.set()

    def _model_text(self, text):
        if self.closed or self._model_generation != self._active_generation:
            return
        if not isinstance(text, str):
            return
        if self._model_length + len(text) > _MAX_OUTPUT_MESSAGE:
            self._failure = NativeTextHostError("initialization")
            self._changed.set()
            return
        if text:
            self._model_parts.append(text)
            self._model_length += len(text)

    def _model_ended(self):
        if self.closed or self._model_generation != self._active_generation:
            self._model_parts = []
            self._model_length = 0
            self._model_generation = None
            return
        self._response_ends += 1
        self._model_inflight = max(0, self._model_inflight - 1)
        text = "".join(self._model_parts)
        self._model_parts = []
        self._model_length = 0
        self._model_generation = None
        if text.strip():
            self._record_output(text)
        self._changed.set()

    def _pipeline_error(self):
        if self._failure is None:
            self._failure = NativeTextHostError("initialization")
        self._changed.set()

    def _runner_done(self, task):
        if not self._started_event.is_set():
            self._pipeline_error()
            self._started_event.set()
        elif not task.cancelled():
            try:
                if task.exception() is not None:
                    self._pipeline_error()
            except asyncio.CancelledError:
                pass

    def _adapter_start_done(self, task):
        if task.cancelled():
            self._changed.set()
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            error = None
        if error is not None and not self.closed:
            self._pipeline_error()
        else:
            self._changed.set()

    def _raise_if_failed(self):
        if self._failure is not None:
            raise NativeTextHostError(self._failure.code)
        if self.closed:
            raise NativeTextHostError("closed")

    def _turn_ready(self, initial_response_ends):
        return (
            self._response_ends > initial_response_ends
            and self._native_idle()
            and self._context_aggregator is not None
            and not self._context_aggregator.assistant().has_function_calls_in_progress
        )

    async def _ack_output(self):
        if self._worker is None or self.closed:
            raise NativeTextHostError("closed")
        frame = NativeTextTurnBarrier()
        future = asyncio.get_running_loop().create_future()
        self._turn_barriers[id(frame)] = future
        try:
            async with asyncio.timeout(min(5.0, self._turn_timeout)):
                await self._worker.queue_frame(frame)
                await future
        finally:
            self._turn_barriers.pop(id(frame), None)

    async def send(self, message):
        if self.closed or (self.adapter is not None and self.snapshot()["is_ended"]):
            raise NativeTextHostError("closed")
        if self._worker is None or not self._started_event.is_set():
            raise NativeTextHostError("initialization")
        if self._send_task is not None or self._turn is not None:
            raise NativeTextHostError("busy")
        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > 2048
        ):
            raise NativeTextHostError("invalid")

        task = asyncio.current_task()
        self._send_task = task
        self._active_generation += 1
        generation = self._active_generation
        self._function_called = None
        self._function_result = None
        self._outputs.clear()
        self._output_start = 0
        initial_response_ends = self._response_ends
        self._turn = {
            "kind": "message", "generation": generation,
            "response_ends": initial_response_ends, "output_start": 0,
        }
        try:
            async with asyncio.timeout(self._turn_timeout):
                self._raise_if_failed()
                from pipecat.frames.frames import LLMMessagesAppendFrame

                await self._worker.queue_frame(LLMMessagesAppendFrame(
                    messages=[{"role": "user", "content": message}],
                    run_llm=True,
                ))
                pending = await self._await_turn(initial_response_ends)
                if pending:
                    return self._pending_result()
                result = self._result(self._output_start)
                self._outputs.clear()
                self._turn = None
                return result
        except TimeoutError:
            await self.close()
            raise NativeTextHostError("timeout") from None
        except NativeTextHostError:
            if self.closed:
                raise NativeTextHostError("closed") from None
            await self.close()
            raise
        except asyncio.CancelledError:
            if self.closed:
                raise NativeTextHostError("closed") from None
            await self.close()
            raise
        except Exception:
            await self.close()
            raise NativeTextHostError("initialization") from None
        finally:
            if self._send_task is task and self._active_generation == generation:
                self._send_task = None
                self._changed.set()

    def _result(self, start):
        return {
            "messages": deepcopy(self._outputs[start:]),
            "function_called": deepcopy(self._function_called),
            "function_result": deepcopy(self._function_result),
        }

    def snapshot(self):
        if self.adapter is None:
            current = None
            facts = {}
        else:
            current = self.adapter.snapshot()["current_node"]
            facts = self.adapter.facts
        slots = (self.adapter.compiled if self.adapter is not None else self.compiled).caller_slots
        caller_variables = tuple(dict.fromkeys(
            slot.variable for slot in slots
        ))
        collected = {
            variable: facts[variable]
            for variable in caller_variables
            if variable in facts
        }
        current_slot = next(
            (slot for slot in slots if slot.node_id == current and slot.variable not in collected),
            None,
        )
        pending = (
            current_slot.variable
            if current_slot is not None and current_slot.variable not in collected
            else None
        )
        total = len(caller_variables)
        count = len(collected)
        return {
            "collected_slots": collected,
            "current_node": current,
            "pending_slot": pending,
            "is_complete": self.adapter is not None and self.adapter.snapshot()["completed"],
            "is_ended": self.closed or (
                self.adapter is not None and self.adapter.snapshot()["status"] in {
                    "completed", "terminal_pending", "terminal_failed", "failed",
                }
            ),
            "progress": {
                "collected": count,
                "total": total,
                "percentage": round(count * 100 / total) if total else 0,
            },
            "pending_preview": self.preview.snapshot() if self.preview else None,
            "safe_preview_effects": self.preview.effects if self.preview else [],
            "execution_mode": "preview",
        }

    async def close(self):
        if self._close_complete.is_set():
            return
        async with self._close_lock:
            if self._close_complete.is_set():
                return
            self.closed = True
            self._api_keys = {}
            self._turn = None
            self._outputs.clear()
            if self.preview is not None:
                self.preview.close()
            self._observer.close()
            self._active_generation += 1
            self._changed.set()
            current = asyncio.current_task()
            active = self._send_task
            if active is not None and active is not current and not active.done():
                active.cancel()
            start_task = self._start_task
            if start_task is not None and start_task is not current and not start_task.done():
                start_task.cancel()
            adapter_start_task = self._adapter_start_task
            if (
                adapter_start_task is not None
                and adapter_start_task is not current and not adapter_start_task.done()
            ):
                adapter_start_task.cancel()
            if self.adapter is not None:
                try:
                    async with asyncio.timeout(self._adapter_close_timeout):
                        await self.adapter.close()
                except BaseException:
                    pass
            for action_runner in self._action_runners.values():
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await action_runner.close()
                except Exception:
                    pass
            try:
                if self._runner is not None:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await self._runner.cancel("native_text_host_closed")
                        if self._runner_task is not None:
                            await asyncio.gather(
                                self._runner_task, return_exceptions=True,
                            )
                elif self._worker is not None and not self._worker.has_finished():
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await self._worker.cancel()
                elif self._llm is not None:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await self._llm.cleanup()
            except BaseException:
                if self._runner_task is not None and not self._runner_task.done():
                    self._runner_task.cancel()
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT):
                            await asyncio.gather(
                                self._runner_task, return_exceptions=True,
                            )
                    except BaseException:
                        pass
            if active is not None and active is not current and not active.done():
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await asyncio.gather(active, return_exceptions=True)
                except TimeoutError:
                    active.cancel()
            if start_task is not None and start_task is not current and not start_task.done():
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await asyncio.gather(start_task, return_exceptions=True)
                except TimeoutError:
                    start_task.cancel()
            if (
                adapter_start_task is not None and adapter_start_task is not current
                and not adapter_start_task.done()
            ):
                try:
                    async with asyncio.timeout(_CLOSE_TIMEOUT):
                        await asyncio.gather(
                            adapter_start_task, return_exceptions=True,
                        )
                except TimeoutError:
                    adapter_start_task.cancel()
            self._close_complete.set()

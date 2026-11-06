"""Use real coordinator/factory/runner; isolate only external I/O and storage."""

import asyncio
from contextlib import ExitStack, suppress
import importlib
from unittest.mock import AsyncMock, patch

import httpx

from application_support import API_KEYS, load_function_mapper
from lifecycle_io import CALL_SID, STREAM_SID, Carrier, Providers, Records


class OfflineCall:
    def __init__(self):
        load_function_mapper()
        self.module = importlib.import_module("botelier.voice.call_handler")
        self.handler = self.module.CallHandler()
        self.records = Records()
        self.carrier = Carrier()
        self.providers = Providers()
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.created = None
        self.queue = None
        self.run_task = None
        self.baseline_tasks = set(asyncio.all_tasks())
        self.patches = ExitStack()

    async def __aenter__(self):
        module = self.module
        database = importlib.import_module("botelier.database")
        flux = importlib.import_module("pipecat.services.deepgram.flux.stt")
        initial_session = self.records.session()
        real_factory = module.VoiceEngineFactory.create_pipeline

        def factory(*args, **kwargs):
            assert initial_session.closed, "Setup DB session survived into the worker"
            result = real_factory(*args, **kwargs)
            self.created = result

            @result[1].event_handler("on_pipeline_started")
            async def started(worker, frame):
                assert self.handler.call_tasks[CALL_SID] is worker
                assert self.handler.call_contexts[CALL_SID] is result[4]
                assert result[3].user()._context is result[4]
                assert result[3].assistant()._context is result[4]
                self.queue = self.handler.call_event_queues[CALL_SID]
                self.started.set()

            @result[1].event_handler("on_pipeline_finished")
            async def finished(worker, frame):
                self.finished.set()

            return result

        async def http_boundary(transport, request):
            return await self.providers.http(request)

        # complete_call is synchronous; preserve its worker-thread boundary.
        def complete(logger, **kwargs):
            return self.records.complete_call(logger, **kwargs)

        for target, name, replacement in (
            (database, "SessionLocal", self.records.session),
            (module, "SessionLocal", self.records.session),
            (module.CallHandler, "_get_api_keys", lambda _: dict(API_KEYS)),
            (module.CallLogger, "complete_call", complete),
            (module, "get_or_generate_greeting_audio", AsyncMock(return_value=None)),
            (module.VoiceEngineFactory, "create_pipeline", factory),
            (flux, "websocket_connect", self.providers.connect_stt),
            (httpx.AsyncHTTPTransport, "handle_async_request", http_boundary),
        ):
            self.patches.enter_context(patch.object(target, name, replacement))
        self.patches.enter_context(patch(
            "websockets.asyncio.client.connect", self.providers.connect_tts,
        ))
        self.patches.enter_context(patch(
            "platform.platform", return_value="Linux-offline-test",
        ))
        await self.carrier.websocket.accept()
        self.run_task = asyncio.create_task(
            self.handler.handle_call(
                self.carrier.websocket, "offline-destination", STREAM_SID,
                CALL_SID, initial_session, from_number="offline-caller",
            ),
            name="offline-real-call-coordinator",
        )
        return self

    async def wait_until(self, predicate, timeout=4.0):
        async def wait():
            while not predicate():
                if self.run_task.done():
                    await self.run_task
                    raise AssertionError(
                        "Real call coordinator returned before the expected call stage"
                    )
                await asyncio.sleep(0.005)
        await asyncio.wait_for(wait(), timeout)

    async def finish(self, ending):
        if ending == "caller_hangup":
            self.carrier.disconnect()
            # Simulate the external status webhook invoking its actual public
            # cancellation entry point; no FastAPI startup or endpoint bypass.
            await self.handler.cancel_call_pipeline(CALL_SID)
        elif ending == "graceful_end":
            await self.created[1].stop_when_done()
        else:
            raise AssertionError(f"Unsupported synthetic termination: {ending}")
        await asyncio.wait_for(asyncio.shield(self.run_task), timeout=5.0)

    def remaining_tasks(self):
        return [
            task.get_name() for task in asyncio.all_tasks()
            if task not in self.baseline_tasks and not task.done()
        ]

    async def __aexit__(self, *exc):
        try:
            if self.carrier.stream_task is not None:
                self.carrier.stream_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.carrier.stream_task
            if self.run_task is not None and not self.run_task.done():
                await self.handler.cancel_call_pipeline(CALL_SID)
                try:
                    await asyncio.wait_for(asyncio.shield(self.run_task), timeout=5.0)
                except TimeoutError:
                    # Failed-start diagnostics must not restore the database
                    # boundary while a real coordinator finally block still runs.
                    self.run_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self.run_task
            if self.created is not None:
                await self.created[2]._client.close()
        finally:
            self.patches.close()

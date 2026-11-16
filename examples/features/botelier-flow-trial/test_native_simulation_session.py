"""Bookkeeping-only tests for the native simulator session wrapper.

The controlled host below is a protocol fixture for lifecycle tests, not a
FlowManager/native-engine substitute or proof of SDK/runtime integration.
"""

import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from botelier.services.native_simulation_session import (
    NativeSimulationError,
    NativeSimulationRegistry,
    NativeSimulationSession,
)
from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy


def make_policy(enabled=True):
    return NativeFlowDevPolicy("development", "1" if enabled else "0")


class ControlledHost:
    def __init__(self, *, start_result=None, send_result=None):
        self.start_result = start_result or {
            "messages": [{"role": "assistant", "content": "Ready."}],
            "function_called": None,
            "function_result": None,
        }
        self.send_result = send_result or {
            "messages": [{"role": "assistant", "content": "Accepted."}],
            "function_called": None,
            "function_result": None,
        }
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.send_entered = asyncio.Event()
        self.send_release = asyncio.Event()
        self.block_start = False
        self.block_send = False
        self.translate_start_cancellation = False
        self.translate_send_cancellation = False
        self.start_error = None
        self.send_error = None
        self.start_calls = 0
        self.send_calls = []
        self.close_calls = 0
        self.closed = False
        self.state = {
            "collected_slots": {},
            "current_node": "actual-host-node",
            "pending_slot": "guest_name",
            "is_complete": False,
            "is_ended": False,
            "progress": {"collected": 0, "total": 1, "percentage": 0},
        }

    async def start(self):
        self.start_calls += 1
        self.start_entered.set()
        if self.block_start:
            try:
                await self.start_release.wait()
            except asyncio.CancelledError:
                if self.translate_start_cancellation:
                    error = RuntimeError("host cancellation translation")
                    error.code = "closed"
                    raise error
                raise
        if self.start_error:
            raise self.start_error
        return deepcopy(self.start_result)

    async def send(self, text):
        self.send_calls.append(text)
        self.send_entered.set()
        if self.block_send:
            try:
                await self.send_release.wait()
            except asyncio.CancelledError:
                if self.translate_send_cancellation:
                    error = RuntimeError("host cancellation translation")
                    error.code = "closed"
                    raise error
                raise
        if self.send_error:
            raise self.send_error
        return deepcopy(self.send_result)

    def snapshot(self):
        return deepcopy(self.state)

    async def close(self):
        self.close_calls += 1
        self.closed = True
        self.start_release.set()
        self.send_release.set()


def make_session(
    *,
    registry=None,
    owner="user-1",
    session_map=None,
    host=None,
    policy=None,
    max_turns=30,
    min_turn_interval=0,
    idle_timeout=300,
    max_lifetime=900,
):
    registry = registry or NativeSimulationRegistry()
    session_map = session_map if session_map is not None else {}
    session_id = registry.reserve(owner)
    host = host or ControlledHost()
    session = NativeSimulationSession(
        session_id=session_id,
        owner_user_id=owner,
        account_id="account-1",
        runtime={"engine": "native_pilot", "source": "published"},
        variables_to_collect=[
            {"key": "guest_name", "type": "text", "required": True},
        ],
        host=host,
        registry=registry,
        session_map=session_map,
        policy_provider=policy or make_policy,
        max_turns=max_turns,
        min_turn_interval=min_turn_interval,
        idle_timeout=idle_timeout,
        max_lifetime=max_lifetime,
    )
    return session, registry, session_map, host


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_reservations_count_against_global_and_per_owner_limits(self):
        registry = NativeSimulationRegistry(max_sessions=2, max_sessions_per_owner=1)
        registry.reserve("alice")
        with self.assertRaises(NativeSimulationError) as per_owner:
            registry.reserve("alice")
        self.assertEqual(per_owner.exception.code, "native_simulation_owner_limit")
        registry.reserve("bob")
        with self.assertRaises(NativeSimulationError) as global_limit:
            registry.reserve("carol")
        self.assertEqual(global_limit.exception.code, "native_simulation_capacity")
        self.assertEqual(registry.active_count, 0)
        self.assertEqual(registry.pending_count, 2)

    def test_start_rate_limit_survives_abandoned_reservation(self):
        registry = NativeSimulationRegistry(starts_per_minute=1)
        reserved = registry.reserve("alice")
        registry.abandon(reserved, "alice")
        with self.assertRaises(NativeSimulationError) as limited:
            registry.reserve("alice")
        self.assertEqual(limited.exception.code, "native_simulation_start_rate")

    def test_owner_start_buckets_are_globally_bounded(self):
        registry = NativeSimulationRegistry(max_sessions=1, starts_per_minute=1)
        for number in range(5):
            reserved = registry.reserve(f"owner-{number}")
            registry.abandon(reserved, f"owner-{number}")
        with self.assertRaises(NativeSimulationError) as limited:
            registry.reserve("another-owner")
        self.assertEqual(limited.exception.code, "native_simulation_capacity")

    def test_wrong_owner_cannot_release_a_reservation(self):
        registry = NativeSimulationRegistry(max_sessions=1)
        reserved = registry.reserve("alice")
        registry.abandon(reserved, "bob")
        self.assertEqual(registry.pending_count, 1)

    async def test_pending_owner_isolation_and_foreign_map_entry_are_preserved(self):
        session, registry, shared, _ = make_session()
        with self.assertRaises(NativeSimulationError) as hidden:
            session.check_owner("other-user")
        self.assertEqual(hidden.exception.status_code, 404)
        self.assertEqual(hidden.exception.code, "native_simulation_not_found")
        other = object()
        shared[session.session_id] = other
        registry.abandon(session.session_id, "user-1")
        self.assertIs(shared[session.session_id], other)
        await session.close()

    async def test_registry_releases_only_its_owned_session_entry(self):
        session, registry, shared, _ = make_session()
        await session.start()
        foreign = object()
        shared[session.session_id] = foreign
        await session.close()
        self.assertIs(shared[session.session_id], foreign)
        self.assertEqual(registry.active_count, 0)

    async def test_duplicate_publish_is_rejected(self):
        session, registry, shared, _ = make_session()
        await session.start()
        with self.assertRaises(NativeSimulationError):
            registry.publish(session, shared)
        await session.close()

    async def test_foreign_map_collision_is_not_overwritten_or_deleted(self):
        session, registry, shared, _ = make_session()
        foreign = object()
        shared[session.session_id] = foreign
        with self.assertRaises(NativeSimulationError):
            await session.start()
        self.assertIs(shared[session.session_id], foreign)
        self.assertEqual(registry.pending_count, 0)

    async def test_invalid_server_runtime_releases_its_unbound_reservation(self):
        registry = NativeSimulationRegistry()
        session_id = registry.reserve("user")
        with self.assertRaises(NativeSimulationError):
            NativeSimulationSession(
                session_id=session_id,
                owner_user_id="user",
                account_id="account",
                runtime={"system_prompt": "private"},
                variables_to_collect=[],
                host=ControlledHost(),
                registry=registry,
                session_map={},
                policy_provider=make_policy,
            )
        self.assertEqual(registry.pending_count, 0)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_liveness_checks_schedule_only_one_cleanup(self):
        session, registry, shared, host = make_session()
        await session.start()
        host.closed = True
        baseline = asyncio.all_tasks()
        try:
            for _ in range(3):
                with self.assertRaises(NativeSimulationError):
                    session.get_state_snapshot()
            scheduled = asyncio.all_tasks() - baseline
            self.assertEqual(len(scheduled), 1)
        finally:
            await session.close()
        self.assertEqual(host.close_calls, 1)
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)

    async def test_start_publishes_only_after_host_ready_and_returns_compatible_shape(self):
        host = ControlledHost(start_result={
            "messages": [
                {"role": "system", "content": "private"},
                {"role": "assistant", "content": "Hello."},
            ],
            "function_called": None,
            "function_result": None,
        })
        host.block_start = True
        session, registry, shared, _ = make_session(host=host)
        task = asyncio.create_task(session.start())
        await host.start_entered.wait()
        self.assertNotIn(session.session_id, shared)
        host.start_release.set()
        result = await task
        self.assertEqual(
            set(result),
            {"session_id", "greeting", "variables_to_collect", "state", "messages", "runtime"},
        )
        self.assertEqual(result["greeting"], "Hello.")
        self.assertEqual([m["content"] for m in result["messages"]], ["Hello."])
        self.assertEqual(result["state"], host.snapshot())
        self.assertIs(shared[session.session_id], session)
        self.assertEqual(registry.active_count, 1)
        await session.close()

    async def test_start_failure_is_sanitized_and_releases_reservation(self):
        host = ControlledHost()
        host.start_error = RuntimeError("private prompt and credential")
        session, registry, shared, _ = make_session(host=host)
        with self.assertRaises(NativeSimulationError) as caught:
            await session.start()
        self.assertEqual(caught.exception.code, "native_simulation_failed")
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(registry.pending_count, 0)
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_start_cancellation_releases_and_closes(self):
        host = ControlledHost()
        host.block_start = True
        host.translate_start_cancellation = True
        session, registry, shared, _ = make_session(host=host)
        task = asyncio.create_task(session.start())
        await host.start_entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await session.close()
        self.assertEqual(registry.pending_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_start_timeout_is_safe_and_releases_reservation(self):
        host = ControlledHost()
        host.block_start = True
        host.translate_start_cancellation = True
        session, registry, shared, _ = make_session(host=host)
        with patch(
            "botelier.services.native_simulation_session._START_TIMEOUT_SECONDS",
            0.01,
        ):
            with self.assertRaises(NativeSimulationError) as caught:
                await session.start()
        self.assertEqual(caught.exception.code, "native_simulation_timeout")
        self.assertEqual(registry.pending_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_close_during_start_cannot_publish_late(self):
        host = ControlledHost()
        host.block_start = True
        session, registry, shared, _ = make_session(host=host)
        task = asyncio.create_task(session.start())
        await host.start_entered.wait()
        await session.close()
        await asyncio.gather(task, return_exceptions=True)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(registry.pending_count, 0)
        self.assertEqual(registry.active_count, 0)
        self.assertEqual(host.close_calls, 1)

    async def test_manual_function_injection_rejected_before_host_or_history_change(self):
        session, _, _, host = make_session()
        await session.start()
        before = deepcopy(session.messages)
        for kwargs in (
            {"function_call": "collect_guest_name"},
            {"function_args": {"guest_name": "forged"}},
        ):
            with self.assertRaises(NativeSimulationError) as caught:
                await session.send("hello", **kwargs)
            self.assertEqual(caught.exception.code, "native_simulation_manual_calls_disabled")
        self.assertEqual(host.send_calls, [])
        self.assertEqual(session.messages, before)
        await session.close()

    async def test_input_limits_and_whitespace_rejection(self):
        session, _, _, host = make_session()
        await session.start()
        for message in ("", "  ", "x" * 2049):
            with self.assertRaises(NativeSimulationError):
                await session.send(message)
        self.assertEqual(host.send_calls, [])
        await session.close()

    async def test_host_output_and_snapshot_are_deep_copied_and_host_only(self):
        host = ControlledHost(send_result={
            "messages": [
                {"role": "user", "content": "not public output"},
                {"role": "system", "content": "private system"},
                {"role": "assistant", "content": "Actual answer."},
            ],
            "function_called": "collect_guest_name",
            "function_result": {"collected": {"guest_name": "Ada"}},
        })
        session, _, _, _ = make_session(host=host)
        await session.start()
        result = await session.send("Ada")
        self.assertEqual(result["response"], "Actual answer.")
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(
            result["messages"][-1]["metadata"],
            {
                "function_called": "collect_guest_name",
                "function_result": {"collected": {"guest_name": "Ada"}},
            },
        )
        self.assertEqual(result["suggested_functions"], [])
        self.assertIsNone(result["error"])
        result["messages"][-1]["content"] = "mutated"
        snapshot = session.get_state_snapshot()
        self.assertEqual(snapshot, host.snapshot())
        snapshot["collected_slots"]["evil"] = "mutation"
        self.assertNotIn("evil", host.snapshot()["collected_slots"])
        self.assertNotIn("private system", str(session.messages))
        await session.close()

    async def test_public_messages_and_runtime_are_copied(self):
        session, _, _, _ = make_session()
        await session.start()
        messages = session.messages
        messages[0]["content"] = "caller mutation"
        runtime = session.runtime
        runtime["source"] = "caller mutation"
        self.assertEqual(session.messages[0]["content"], "Ready.")
        self.assertEqual(session.runtime["source"], "published")
        await session.close()

    async def test_no_speech_still_carries_actual_function_metadata_without_fake_result(self):
        host = ControlledHost(send_result={
            "messages": [],
            "function_called": "collect_guest_name",
            "function_result": None,
        })
        session, _, _, _ = make_session(host=host)
        await session.start()
        result = await session.send("Ada")
        self.assertEqual(result["response"], "")
        self.assertEqual(result["function_result"], None)
        self.assertEqual(
            result["messages"][-1],
            {
                "role": "assistant",
                "content": "",
                "metadata": {
                    "function_called": "collect_guest_name",
                    "function_result": None,
                },
            },
        )
        await session.close()

    async def test_native_host_dict_function_metadata_is_normalized_without_result_invention(self):
        host = ControlledHost(send_result={
            "messages": [],
            "function_called": {"name": "collect_guest_name", "arguments": {"value": "Ada"}},
            "function_result": None,
        })
        session, _, _, _ = make_session(host=host)
        await session.start()
        result = await session.send("Ada")
        self.assertEqual(result["function_called"], "collect_guest_name")
        self.assertIsNone(result["function_result"])
        await session.close()

    async def test_concurrent_turn_rejected_not_queued(self):
        host = ControlledHost()
        host.block_send = True
        host.translate_send_cancellation = True
        session, _, _, _ = make_session(host=host)
        await session.start()
        first = asyncio.create_task(session.send("first"))
        await host.send_entered.wait()
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("second")
        self.assertEqual(caught.exception.code, "native_simulation_busy")
        self.assertEqual(host.send_calls, ["first"])
        host.send_release.set()
        await first
        await session.close()

    async def test_turn_budget_and_minimum_interval(self):
        session, _, _, _ = make_session(max_turns=1, min_turn_interval=0)
        await session.start()
        await session.send("first")
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("second")
        self.assertEqual(caught.exception.code, "native_simulation_turn_limit")
        await session.close()

        session, _, _, _ = make_session(min_turn_interval=60)
        await session.start()
        await session.send("first")
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("second")
        self.assertEqual(caught.exception.code, "native_simulation_rate_limit")
        await session.close()

    async def test_host_failure_closes_and_translates_only_safe_code(self):
        class SafeError(Exception):
            code = "timeout"

        host = ControlledHost()
        session, registry, shared, _ = make_session(host=host)
        await session.start()
        host.send_error = SafeError("raw vendor output with secret")
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("hello")
        self.assertEqual(caught.exception.code, "native_simulation_timeout")
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_unknown_host_error_is_generic_and_disposes(self):
        class UnsafeError(Exception):
            code = "api_key=private"

        host = ControlledHost()
        session, _, _, _ = make_session(host=host)
        await session.start()
        host.send_error = UnsafeError("provider body")
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("hello")
        self.assertEqual(caught.exception.code, "native_simulation_failed")
        self.assertNotIn("provider", str(caught.exception))
        self.assertEqual(host.close_calls, 1)

    async def test_oversized_result_is_rejected_and_disposed(self):
        host = ControlledHost(send_result={
            "messages": [{"role": "assistant", "content": "ok"}],
            "function_called": "collect_guest_name",
            "function_result": {"large": "x" * (512 * 1024)},
        })
        session, registry, _, _ = make_session(host=host)
        await session.start()
        with self.assertRaises(NativeSimulationError) as caught:
            await session.send("hello")
        self.assertEqual(caught.exception.code, "native_simulation_output_limit")
        self.assertEqual(registry.active_count, 0)
        self.assertEqual(host.close_calls, 1)

    async def test_send_timeout_closes_without_fallback(self):
        host = ControlledHost()
        host.block_send = True
        host.translate_send_cancellation = True
        session, registry, shared, _ = make_session(host=host)
        await session.start()
        with patch(
            "botelier.services.native_simulation_session._TURN_TIMEOUT_SECONDS",
            0.01,
        ):
            with self.assertRaises(NativeSimulationError) as caught:
                await session.send("hang")
        self.assertEqual(caught.exception.code, "native_simulation_timeout")
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_disabled_policy_closes_and_refuses_snapshot(self):
        denied_policy = make_policy(enabled=False)
        session, registry, shared, host = make_session(
            policy=lambda: denied_policy,
        )
        with self.assertRaises(NativeSimulationError) as caught:
            await session.start()
        self.assertEqual(caught.exception.code, "native_simulation_disabled")
        self.assertEqual(registry.pending_count, 0)
        self.assertEqual(host.close_calls, 1)
        self.assertNotIn(session.session_id, shared)

    async def test_enabled_boolean_without_exact_policy_type_is_refused(self):
        class IncorrectPolicy:
            enabled = True

        session, registry, shared, host = make_session(
            policy=lambda: IncorrectPolicy(),
        )
        with self.assertRaises(NativeSimulationError) as caught:
            await session.start()
        self.assertEqual(caught.exception.code, "native_simulation_disabled")
        self.assertEqual(registry.pending_count, 0)
        self.assertEqual(host.start_calls, 0)
        self.assertNotIn(session.session_id, shared)

    async def test_lifetime_and_idle_expiry_remove_published_sessions(self):
        session, registry, shared, host = make_session(max_lifetime=0.03)
        await session.start()
        await asyncio.sleep(0.08)
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

        session, registry, shared, host = make_session(idle_timeout=0.03)
        await session.start()
        await asyncio.sleep(0.08)
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_close_during_send_cancels_turn_and_prevents_late_result(self):
        host = ControlledHost()
        host.block_send = True
        session, registry, shared, _ = make_session(host=host)
        await session.start()
        task = asyncio.create_task(session.send("in flight"))
        await host.send_entered.wait()
        await session.close()
        result = await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(isinstance(result[0], (asyncio.CancelledError, NativeSimulationError)))
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertTrue(session.is_ended)

    async def test_caller_cancellation_disposes_session_without_late_result(self):
        host = ControlledHost()
        host.block_send = True
        session, registry, shared, _ = make_session(host=host)
        await session.start()
        task = asyncio.create_task(session.send("cancel me"))
        await host.send_entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_host_cancellation_translation_preserves_caller_cancellation(self):
        host = ControlledHost()
        host.block_send = True
        host.translate_send_cancellation = True
        session, registry, shared, _ = make_session(host=host)
        await session.start()
        task = asyncio.create_task(session.send("cancel me"))
        await host.send_entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(registry.active_count, 0)
        self.assertNotIn(session.session_id, shared)
        self.assertEqual(host.close_calls, 1)

    async def test_close_is_idempotent_and_clears_history(self):
        session, _, _, host = make_session()
        await session.start()
        await session.send("hello")
        await asyncio.gather(session.close(), session.close(), session.close())
        self.assertEqual(host.close_calls, 1)
        self.assertEqual(session.messages, [])
        self.assertTrue(session.is_ended)

    async def test_registry_shutdown_closes_published_and_pending_sessions(self):
        registry = NativeSimulationRegistry(max_sessions=3, max_sessions_per_owner=2)
        active, _, active_map, active_host = make_session(registry=registry, owner="a")
        await active.start()
        pending_host = ControlledHost()
        pending_host.block_start = True
        pending, _, pending_map, _ = make_session(
            registry=registry, owner="b", host=pending_host,
        )
        pending_start = asyncio.create_task(pending.start())
        await pending_host.start_entered.wait()
        await registry.shutdown()
        await asyncio.gather(pending_start, return_exceptions=True)
        self.assertEqual(registry.active_count, 0)
        self.assertEqual(registry.pending_count, 0)
        self.assertEqual(active_host.close_calls, 1)
        self.assertNotIn(active.session_id, active_map)
        self.assertNotIn(pending.session_id, pending_map)
        with self.assertRaises(NativeSimulationError):
            registry.reserve("later")


if __name__ == "__main__":
    unittest.main()

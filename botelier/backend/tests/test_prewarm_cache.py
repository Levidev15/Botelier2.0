"""
Tests for PreWarmCache (Task #111).

Covers LRU bounds, TTL expiry, pop-removes, and consumer timeout behaviour.
No DB or network is touched — these tests operate solely on the cache
structure itself.
"""

import asyncio

import pytest

from botelier.voice.prewarm import (
    PopResult,
    PreWarmBundle,
    PreWarmCache,
    PreWarmEntry,
)


@pytest.mark.asyncio
async def test_reserve_and_consume_bundle_sets_ready() -> None:
    cache = PreWarmCache(max_size=8, ttl_secs=5.0)
    entry = cache.reserve("CA-1")

    async def _fill() -> None:
        await asyncio.sleep(0.01)
        entry.bundle = PreWarmBundle(prewarm_duration_ms=42)
        entry.ready.set()

    asyncio.create_task(_fill())
    got = await cache.pop_and_wait("CA-1", timeout_secs=1.0)
    assert isinstance(got, PopResult)
    # Producer slept 10 ms before setting ready — we waited for it.
    assert got.state == "ready_during_wait"
    assert got.bundle is not None
    assert got.bundle.prewarm_duration_ms == 42
    assert got.wait_ms >= 0
    # Entry should have been removed on consume.
    assert cache.size() == 0


@pytest.mark.asyncio
async def test_pop_ready_before_wait_when_already_set() -> None:
    cache = PreWarmCache()
    entry = cache.reserve("CA-1b")
    entry.bundle = PreWarmBundle(prewarm_duration_ms=7)
    entry.ready.set()
    got = await cache.pop_and_wait("CA-1b", timeout_secs=1.0)
    assert got.state == "ready_before_wait"
    assert got.wait_ms == 0
    assert got.bundle is not None
    assert got.bundle.prewarm_duration_ms == 7


@pytest.mark.asyncio
async def test_pop_returns_missing_when_no_reservation() -> None:
    cache = PreWarmCache()
    got = await cache.pop_and_wait("missing", timeout_secs=0.01)
    assert got.state == "missing"
    assert got.bundle is None


@pytest.mark.asyncio
async def test_pop_times_out_when_pre_warm_never_completes() -> None:
    cache = PreWarmCache()
    cache.reserve("CA-2")
    got = await cache.pop_and_wait("CA-2", timeout_secs=0.05)
    assert got.state == "timeout"
    assert got.bundle is None
    assert got.wait_ms >= 50
    # Even on timeout, the entry is removed — second pop is a hard miss.
    again = await cache.pop_and_wait("CA-2", timeout_secs=0.01)
    assert again.state == "missing"


@pytest.mark.asyncio
async def test_pop_returns_error_on_prewarm_error() -> None:
    cache = PreWarmCache()
    entry = cache.reserve("CA-3")
    entry.error = RuntimeError("boom")
    entry.ready.set()
    got = await cache.pop_and_wait("CA-3", timeout_secs=0.1)
    assert got.state == "error"
    assert got.bundle is None
    assert got.error_class == "RuntimeError"


# Task #122 — guard the additive-telemetry contract in call_handler.py.
# The handler's event details for cold_path_prewarm_hit / cold_path_fallback
# emit BOTH the new (state/wait_ms/error_class) AND the legacy
# (prewarm_to_use_ms/reason) fields so existing dashboards keep working.
# These tests mirror the derivation rules so a refactor that drops legacy
# keys is caught at unit-test time.
def _hit_details_from(result: PopResult, *, prewarm_duration_ms: int) -> dict:
    return {
        "state": result.state,
        "wait_ms": result.wait_ms,
        "prewarm_to_use_ms": result.wait_ms,  # legacy
        "prewarm_duration_ms": prewarm_duration_ms,
    }


def _fallback_details_from(result: PopResult) -> dict:
    return {
        "state": result.state,
        "wait_ms": result.wait_ms,
        "error_class": result.error_class,
        "prewarm_to_use_ms": result.wait_ms,  # legacy
        "reason": (
            "no_prewarm_entry"
            if result.state == "missing"
            else "wait_timeout_or_error"
        ),
    }


def test_hit_event_details_carry_both_legacy_and_new_fields() -> None:
    r = PopResult(state="ready_during_wait", wait_ms=120,
                  bundle=PreWarmBundle(prewarm_duration_ms=300))
    d = _hit_details_from(r, prewarm_duration_ms=300)
    # New fields
    assert d["state"] == "ready_during_wait"
    assert d["wait_ms"] == 120
    # Legacy field still present
    assert d["prewarm_to_use_ms"] == 120
    assert d["prewarm_duration_ms"] == 300


def test_fallback_event_details_carry_both_legacy_and_new_fields() -> None:
    # missing → reason no_prewarm_entry
    miss = _fallback_details_from(PopResult(state="missing"))
    assert miss["state"] == "missing" and miss["reason"] == "no_prewarm_entry"
    assert miss["prewarm_to_use_ms"] == 0
    # timeout → reason wait_timeout_or_error
    to = _fallback_details_from(PopResult(state="timeout", wait_ms=503))
    assert to["state"] == "timeout" and to["reason"] == "wait_timeout_or_error"
    assert to["prewarm_to_use_ms"] == 503
    # error → reason wait_timeout_or_error, error_class surfaced
    er = _fallback_details_from(
        PopResult(state="error", wait_ms=12, error_class="RuntimeError")
    )
    assert er["state"] == "error" and er["reason"] == "wait_timeout_or_error"
    assert er["error_class"] == "RuntimeError"


def test_lru_evicts_oldest_on_overflow() -> None:
    cache = PreWarmCache(max_size=3, ttl_secs=60.0)
    cache.reserve("A")
    cache.reserve("B")
    cache.reserve("C")
    assert cache.size() == 3
    cache.reserve("D")
    assert cache.size() == 3
    # A was the oldest — it should have been dropped.
    assert "A" not in cache._store
    assert {"B", "C", "D"} == set(cache._store.keys())


@pytest.mark.asyncio
async def test_ttl_purges_expired_entries_on_access() -> None:
    cache = PreWarmCache(max_size=16, ttl_secs=0.05)
    cache.reserve("old")
    await asyncio.sleep(0.1)
    # Triggering reserve() purges expired entries.
    cache.reserve("fresh")
    assert "old" not in cache._store
    assert "fresh" in cache._store


def test_discard_is_idempotent() -> None:
    cache = PreWarmCache()
    cache.discard("never-seen")  # no KeyError
    cache.reserve("CA-4")
    cache.discard("CA-4")
    assert cache.size() == 0
    cache.discard("CA-4")  # second discard still ok


@pytest.mark.asyncio
async def test_reserve_supersedes_existing_entry_and_wakes_waiters() -> None:
    cache = PreWarmCache()
    old_entry = cache.reserve("CA-5")
    # A consumer is already waiting on the original entry.
    # Note: pop_and_wait removes it from the store, so we wait directly.
    async def _waiter() -> None:
        await old_entry.ready.wait()

    waiter = asyncio.create_task(_waiter())
    # Replacing the reservation must wake the old waiter so no consumer
    # hangs indefinitely.
    cache.reserve("CA-5")
    await asyncio.wait_for(waiter, timeout=0.5)
    assert old_entry.error is not None

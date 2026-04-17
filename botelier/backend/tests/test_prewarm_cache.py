"""
Tests for PreWarmCache (Task #111).

Covers LRU bounds, TTL expiry, pop-removes, and consumer timeout behaviour.
No DB or network is touched — these tests operate solely on the cache
structure itself.
"""

import asyncio

import pytest

from botelier.voice.prewarm import PreWarmBundle, PreWarmCache, PreWarmEntry


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
    assert got is not None
    assert got.prewarm_duration_ms == 42
    # Entry should have been removed on consume.
    assert cache.size() == 0


@pytest.mark.asyncio
async def test_pop_returns_none_when_missing() -> None:
    cache = PreWarmCache()
    got = await cache.pop_and_wait("missing", timeout_secs=0.01)
    assert got is None


@pytest.mark.asyncio
async def test_pop_times_out_when_pre_warm_never_completes() -> None:
    cache = PreWarmCache()
    cache.reserve("CA-2")
    got = await cache.pop_and_wait("CA-2", timeout_secs=0.05)
    assert got is None
    # Even on timeout, the entry is removed — second pop is a hard miss.
    again = await cache.pop_and_wait("CA-2", timeout_secs=0.01)
    assert again is None


@pytest.mark.asyncio
async def test_pop_returns_none_on_prewarm_error() -> None:
    cache = PreWarmCache()
    entry = cache.reserve("CA-3")
    entry.error = RuntimeError("boom")
    entry.ready.set()
    got = await cache.pop_and_wait("CA-3", timeout_secs=0.1)
    assert got is None


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

"""
Task #99 — Analytics partition lock-in tests.

These tests pin down the contract between the in-process classifier
(`_classify_partition`) and the SQL predicate (`_bucket_predicate`) used by
the Call Analytics overview endpoint. They exist so that any future change
to the bucketing logic that breaks the MECE (mutually exclusive, collectively
exhaustive) invariant — or silently shifts the dashboard numbers — fails CI
loudly instead of being noticed weeks later from a chart that "looks off".

What is covered:
  * Every (status × ai_greeting_completed × caller_spoke) combination is
    inserted as a real row, then routed through both the classifier and a
    SQL query using `_bucket_predicate`. The two MUST agree row-for-row.
  * The five bucket counts always sum to the total number of calls
    (MECE invariant) — both via the classifier and via the SQL predicates.
  * A NULL `caller_spoke` is treated identically to TRUE so the historical
    AI Handled bucket does not silently shift after the Task #98 migration.
  * The two named unresolved sub-bucket predicates plus an "other"
    catch-all sum exactly to the unresolved bucket count.

Isolation strategy: each test class creates its own throwaway Account row
and tags every fixture CallLog with that account_id, so the tests can run
against the live development PostgreSQL database without colliding with
real data, and clean up unconditionally on teardown.
"""

import os
import uuid
from datetime import datetime
from itertools import product

import pytest

# Hard fail if DATABASE_URL is missing rather than silently skipping. These
# tests exist to lock in the analytics partition contract — letting them
# disappear from a green CI run would defeat the entire point of writing
# them. CI is expected to provide DATABASE_URL (a throwaway test database
# is fine; the suite isolates itself by account_id and cleans up).
if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_analytics_partition requires DATABASE_URL to be set. "
        "These tests guard the Call Analytics bucketing contract and must "
        "not be silently skipped — point DATABASE_URL at a test database."
    )

from sqlalchemy import func

from botelier.database import SessionLocal
from botelier.models import CallLog, CallStatus
from botelier.models.account import Account, AccountStatus, SubscriptionTier
from botelier.api.analytics import (
    _PARTITION_BUCKETS,
    _classify_partition,
    _bucket_predicate,
    _unresolved_subbucket_predicates,
)


ALL_STATUSES = [s.value for s in CallStatus]
GREETED_VALUES = [True, False]
# None is intentionally included — Task #98 says NULL must be treated as
# "spoke" so that historical rows do not change buckets.
CALLER_SPOKE_VALUES = [True, False, None]
ALL_COMBOS = list(product(ALL_STATUSES, GREETED_VALUES, CALLER_SPOKE_VALUES))


def _make_account(db) -> Account:
    """Create a unique throwaway account for test isolation."""
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"partition-test-{suffix}",
        slug=f"partition-test-{suffix}",
        email=f"partition-test-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_call_log(account_id, status, greeted, caller_spoke) -> CallLog:
    return CallLog(
        account_id=account_id,
        call_sid=f"TEST-{uuid.uuid4().hex}",
        status=status,
        ai_greeting_completed=greeted,
        caller_spoke=caller_spoke,
        started_at=datetime.utcnow(),
    )


@pytest.fixture(scope="module")
def populated_account():
    """
    Create one CallLog per (status, greeted, caller_spoke) combination under
    a fresh account_id, yield (account_id, expected_rows), and clean up.

    `expected_rows` is a list of (status, greeted, caller_spoke, expected_bucket)
    tuples — the source of truth derived from the pure classifier.
    """
    db = SessionLocal()
    acct = _make_account(db)
    try:
        rows = []
        for status, greeted, cs in ALL_COMBOS:
            db.add(_make_call_log(acct.id, status, greeted, cs))
            rows.append((status, greeted, cs, _classify_partition(status, greeted, cs)))
        db.commit()
        yield acct.id, rows
    finally:
        db.query(CallLog).filter(CallLog.account_id == acct.id).delete()
        db.query(Account).filter(Account.id == acct.id).delete()
        db.commit()
        db.close()


def _bucket_count(db, account_id, predicate) -> int:
    return (
        db.query(func.count(CallLog.id))
        .filter(CallLog.account_id == account_id)
        .filter(predicate)
        .scalar()
    )


# ---------------------------------------------------------------------------
# Classifier ↔ SQL predicate parity
# ---------------------------------------------------------------------------

class TestClassifierPredicateParity:
    """Every input combination routes to the same bucket via both paths."""

    def test_all_buckets_are_known(self):
        # Sanity: the classifier never invents a bucket name outside the
        # canonical set the predicate knows how to handle.
        for status, greeted, cs in ALL_COMBOS:
            bucket = _classify_partition(status, greeted, cs)
            assert bucket in _PARTITION_BUCKETS, (
                f"Classifier returned unknown bucket {bucket!r} for "
                f"({status!r}, greeted={greeted}, caller_spoke={cs})"
            )

    def test_each_combination_routes_identically(self, populated_account):
        account_id, rows = populated_account
        db = SessionLocal()
        try:
            # For every bucket, gather the (status, greeted, caller_spoke)
            # triples the predicate matched, and compare to the triples the
            # classifier expects.
            for bucket in _PARTITION_BUCKETS:
                sql_rows = (
                    db.query(
                        CallLog.status,
                        CallLog.ai_greeting_completed,
                        CallLog.caller_spoke,
                    )
                    .filter(CallLog.account_id == account_id)
                    .filter(_bucket_predicate(bucket))
                    .all()
                )
                sql_triples = {
                    (r.status, bool(r.ai_greeting_completed), r.caller_spoke)
                    for r in sql_rows
                }
                expected_triples = {
                    (s, g, cs) for (s, g, cs, b) in rows if b == bucket
                }
                assert sql_triples == expected_triples, (
                    f"Bucket {bucket!r} mismatch.\n"
                    f"  SQL only:        {sql_triples - expected_triples}\n"
                    f"  Classifier only: {expected_triples - sql_triples}"
                )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# MECE invariant — sum(buckets) == total_calls
# ---------------------------------------------------------------------------

class TestPartitionMece:
    """The five buckets must always sum to the total number of calls."""

    def test_classifier_partition_sums_to_total(self, populated_account):
        _account_id, rows = populated_account
        per_bucket = {b: 0 for b in _PARTITION_BUCKETS}
        for _s, _g, _cs, bucket in rows:
            per_bucket[bucket] += 1
        assert sum(per_bucket.values()) == len(rows)

    def test_sql_partition_sums_to_total(self, populated_account):
        account_id, rows = populated_account
        db = SessionLocal()
        try:
            total = (
                db.query(func.count(CallLog.id))
                .filter(CallLog.account_id == account_id)
                .scalar()
            )
            assert total == len(rows)
            counts = {
                b: _bucket_count(db, account_id, _bucket_predicate(b))
                for b in _PARTITION_BUCKETS
            }
            assert sum(counts.values()) == total, (
                f"SQL bucket counts {counts} do not sum to total {total}"
            )

            # Strict mutual exclusivity: pairwise predicate AND must always
            # match zero rows. Catches accidental overlap that would still
            # sum correctly only by coincidence.
            for i, b1 in enumerate(_PARTITION_BUCKETS):
                for b2 in _PARTITION_BUCKETS[i + 1:]:
                    overlap = _bucket_count(
                        db,
                        account_id,
                        _bucket_predicate(b1) & _bucket_predicate(b2),
                    )
                    assert overlap == 0, (
                        f"Buckets {b1!r} and {b2!r} overlap on {overlap} rows"
                    )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# NULL caller_spoke must behave like TRUE (legacy rows preserved)
# ---------------------------------------------------------------------------

class TestNullCallerSpokeIsSpoke:
    """A NULL caller_spoke is treated as "spoke" by both classifier and SQL."""

    def test_classifier_treats_null_as_spoke(self):
        # For every (status, greeted) pair, the classifier output for
        # caller_spoke=None must equal the output for caller_spoke=True.
        for status, greeted in product(ALL_STATUSES, GREETED_VALUES):
            assert (
                _classify_partition(status, greeted, None)
                == _classify_partition(status, greeted, True)
            ), (
                f"NULL caller_spoke routed differently from TRUE for "
                f"({status!r}, greeted={greeted})"
            )

    def test_sql_treats_null_as_spoke(self, populated_account):
        # Per-bucket: rows with caller_spoke IS NULL must land in the SAME
        # bucket as their caller_spoke=TRUE twin under the SQL predicate.
        account_id, _rows = populated_account
        db = SessionLocal()
        try:
            for bucket in _PARTITION_BUCKETS:
                pred = _bucket_predicate(bucket)
                rows_in_bucket = (
                    db.query(
                        CallLog.status,
                        CallLog.ai_greeting_completed,
                        CallLog.caller_spoke,
                    )
                    .filter(CallLog.account_id == account_id)
                    .filter(pred)
                    .all()
                )
                pairs_with_true = {
                    (r.status, bool(r.ai_greeting_completed))
                    for r in rows_in_bucket
                    if r.caller_spoke is True
                }
                pairs_with_null = {
                    (r.status, bool(r.ai_greeting_completed))
                    for r in rows_in_bucket
                    if r.caller_spoke is None
                }
                assert pairs_with_true == pairs_with_null, (
                    f"In bucket {bucket!r}, NULL caller_spoke rows do not "
                    f"mirror TRUE caller_spoke rows.\n"
                    f"  TRUE only: {pairs_with_true - pairs_with_null}\n"
                    f"  NULL only: {pairs_with_null - pairs_with_true}"
                )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Unresolved sub-breakdown integrity
# ---------------------------------------------------------------------------

class TestUnresolvedSubBreakdown:
    """silent_caller + non_terminal_gap + other == unresolved bucket count."""

    def test_subbuckets_sum_to_unresolved(self, populated_account):
        account_id, _rows = populated_account
        db = SessionLocal()
        try:
            unresolved_total = _bucket_count(
                db, account_id, _bucket_predicate("unresolved")
            )

            sub = _unresolved_subbucket_predicates()
            silent = _bucket_count(db, account_id, sub["silent_caller"])
            gap = _bucket_count(db, account_id, sub["non_terminal_gap"])
            # "other" = rows in the unresolved bucket that match neither
            # named sub-bucket. Mirrors the runtime fallthrough in the API.
            other = _bucket_count(
                db,
                account_id,
                _bucket_predicate("unresolved")
                & ~sub["silent_caller"]
                & ~sub["non_terminal_gap"],
            )

            assert silent + gap + other == unresolved_total, (
                f"Sub-breakdown {silent=} + {gap=} + {other=} "
                f"!= unresolved {unresolved_total}"
            )

            # Sub-buckets are subsets of unresolved (no leakage into other
            # top-level buckets).
            for name, pred in sub.items():
                leaked = _bucket_count(
                    db, account_id, pred & ~_bucket_predicate("unresolved")
                )
                assert leaked == 0, (
                    f"Sub-bucket {name!r} matched {leaked} rows outside "
                    "the unresolved bucket"
                )

            # And the two named sub-buckets are mutually exclusive.
            overlap = _bucket_count(
                db, account_id, sub["silent_caller"] & sub["non_terminal_gap"]
            )
            assert overlap == 0
        finally:
            db.close()

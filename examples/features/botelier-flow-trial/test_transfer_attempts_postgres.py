"""Real PostgreSQL arbitration/reconciliation, without any provider access."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from botelier.services.transfer_attempts import TransferAttempts
from callback_io import CallbackHarness
from callback_store import CHILD_A, CHILD_B, PARENT_A, CallbackStore
from recovery_postgres import ACCOUNT, OTHER_ACCOUNT, PostgresTransferStorage


CALL = "postgres-fixture-call"


@pytest.fixture
def storage():
    value = PostgresTransferStorage()
    yield value
    value.close()


def issued(storage, call=CALL):
    ledger = TransferAttempts(storage)
    attempt = ledger.claim(ACCOUNT, call)
    assert attempt.owned
    assert ledger.issue(ACCOUNT, call, attempt.attempt_id)
    return ledger, attempt


def test_competing_sessions_admit_exactly_one_dispatch(storage):
    def contender(_):
        ledger = TransferAttempts(storage)
        attempt = ledger.claim(ACCOUNT, CALL)
        return attempt.owned and bool(ledger.issue(ACCOUNT, CALL, attempt.attempt_id))
    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(contender, range(8)))
    assert outcomes.count(True) == 1
    assert storage.payload()["phase"] == "issued"


@pytest.mark.parametrize("phase", ["issued", "unconfirmed"])
def test_old_lease_and_expired_retention_hint_never_authorize_a_retry(storage, phase):
    ledger, attempt = issued(storage)
    if phase == "unconfirmed":
        ledger.settle(ACCOUNT, CALL, attempt.attempt_id, phase)
    with storage.engine.begin() as connection:
        connection.execute(text("""
            UPDATE operation_idempotency
            SET updated_at = '2000-01-01', expires_at = '2000-01-02'
            WHERE operation = 'voice_transfer'
        """))
    fresh = TransferAttempts(storage).claim(ACCOUNT, CALL)
    assert not fresh.owned
    assert fresh.attempt_id == attempt.attempt_id
    assert fresh.phase == phase


def test_definite_rejection_creates_a_new_fenced_attempt(storage):
    ledger, old = issued(storage)
    ledger.settle(ACCOUNT, CALL, old.attempt_id, "rejected", definite_rejection=True)
    new = TransferAttempts(storage).claim(ACCOUNT, CALL)
    assert new.owned and new.attempt_id != old.attempt_id
    assert not ledger.issue(ACCOUNT, CALL, old.attempt_id)
    assert not ledger.settle(ACCOUNT, CALL, old.attempt_id, "accepted")
    assert not ledger.observe(ACCOUNT, CALL, old.attempt_id, CHILD_A, "completed")
    assert storage.payload() == {"attempt_id": new.attempt_id, "phase": "reserved"}


def test_generic_failure_after_dispatch_is_not_a_definite_rejection(storage):
    ledger, attempt = issued(storage)
    result = ledger.settle(ACCOUNT, CALL, attempt.attempt_id, "rejected")
    assert result.phase == "unconfirmed"
    assert not TransferAttempts(storage).claim(ACCOUNT, CALL).owned


def test_callback_before_http_response_cannot_be_downgraded_by_lost_response(storage):
    ledger, attempt = issued(storage)
    assert ledger.observe(ACCOUNT, CALL, attempt.attempt_id, CHILD_A, "ringing")
    ledger.settle(ACCOUNT, CALL, attempt.attempt_id, "unconfirmed")
    assert storage.payload()["phase"] == "accepted"
    assert storage.payload()["callback_status"] == "ringing"
    assert not TransferAttempts(storage).claim(ACCOUNT, CALL).owned


def test_duplicate_and_out_of_order_callbacks_preserve_terminal_child_identity(storage):
    ledger, attempt = issued(storage)
    for status in ("completed", "completed", "ringing", "failed"):
        assert ledger.observe(ACCOUNT, CALL, attempt.attempt_id, CHILD_A, status)
    assert not ledger.observe(ACCOUNT, CALL, attempt.attempt_id, CHILD_B, "in-progress")
    assert storage.payload()["child_sid"] == CHILD_A
    assert storage.payload()["callback_status"] == "completed"


def test_callback_cannot_authorize_an_unissued_reservation(storage):
    ledger = TransferAttempts(storage)
    attempt = ledger.claim(ACCOUNT, CALL)
    assert not ledger.observe(ACCOUNT, CALL, attempt.attempt_id, CHILD_A, "ringing")
    assert storage.payload()["phase"] == "reserved"


def test_accounts_cannot_observe_or_settle_each_others_attempts(storage):
    ledger, attempt = issued(storage)
    assert not ledger.observe(OTHER_ACCOUNT, CALL, attempt.attempt_id, CHILD_A, "completed")
    assert not ledger.settle(OTHER_ACCOUNT, CALL, attempt.attempt_id, "accepted")
    second = ledger.claim(OTHER_ACCOUNT, CALL)
    assert second.owned and second.attempt_id != attempt.attempt_id
    assert storage.payload(ACCOUNT)["phase"] == "issued"
    assert storage.payload(OTHER_ACCOUNT)["phase"] == "reserved"


@pytest.mark.parametrize("identity", [None, "", "../invalid", "<unsafe>"])
def test_invalid_call_identity_cannot_create_a_row(storage, identity):
    with pytest.raises(ValueError):
        TransferAttempts(storage).claim(ACCOUNT, identity)
    with storage.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM operation_idempotency")).scalar() == 0


@pytest.mark.parametrize("path", ["/api/calls/transfer-status", "/api/calls/status"])
def test_signed_early_callback_reconciles_the_real_ledger_before_legacy_metadata(storage, path):
    async def scenario():
        ledger, attempt = issued(storage, PARENT_A)
        store = CallbackStore()
        store.transfer_storage = storage
        async with CallbackHarness(store=store) as harness:
            response = await harness.post(path + "?transfer_attempt=" + attempt.attempt_id, {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A, "CallStatus": "ringing",
            })
            assert response.status_code == 200, response.text
            ledger.settle(ACCOUNT, PARENT_A, attempt.attempt_id, "unconfirmed")
            assert storage.payload()["phase"] == "accepted"
            assert storage.payload()["child_sid"] == CHILD_A
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/transfer-status", "/api/calls/status"])
def test_old_signed_attempt_cannot_mutate_a_new_attempt_or_create_events(storage, path):
    async def scenario():
        ledger, old = issued(storage, PARENT_A)
        ledger.settle(ACCOUNT, PARENT_A, old.attempt_id, "rejected", definite_rejection=True)
        new = ledger.claim(ACCOUNT, PARENT_A)
        store = CallbackStore()
        store.transfer_storage = storage
        async with CallbackHarness(store=store) as harness:
            response = await harness.post(path + "?transfer_attempt=" + old.attempt_id, {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A, "CallStatus": "completed",
            })
            assert response.status_code == 200
            assert response.json()["reason"] == "transfer_attempt_mismatch"
            assert store.commits == 0 and not harness.jobs
            assert not store.rows["CallEvent"]
            assert storage.payload() == {"attempt_id": new.attempt_id, "phase": "reserved"}
    asyncio.run(scenario())


def test_commit_response_loss_does_not_allow_a_second_claim(storage):
    class LostCommit:
        def __init__(self):
            self.session = storage()
        def __getattr__(self, name):
            return getattr(self.session, name)
        def commit(self):
            self.session.commit()
            raise RuntimeError("Synthetic lost commit response")
    with pytest.raises(RuntimeError, match="lost commit response"):
        TransferAttempts(LostCommit).claim(ACCOUNT, CALL)
    assert not TransferAttempts(storage).claim(ACCOUNT, CALL).owned
    assert storage.payload()["phase"] == "reserved"

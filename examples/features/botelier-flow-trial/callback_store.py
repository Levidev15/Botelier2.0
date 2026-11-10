"""Enumerated persistence boundary, not a database or a business-service clone."""

from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import guard


ACCOUNT_A = UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT_B = UUID("00000000-0000-0000-0000-000000000002")
PARENT_A = "CA" + "1" * 32
PARENT_B = "CA" + "2" * 32
CHILD_A = "CA" + "3" * 32
CHILD_B = "CA" + "4" * 32
PHONE_A = "+15555550123"
PHONE_B = "+15555550124"
TOKEN_A = "TEST_ONLY_ALPHA_TOKEN_NOT_A_SECRET"
TOKEN_B = "FAKE_BETA_TOKEN_FOR_OFFLINE_CHECKS"
RECORDING = "RE" + "0" * 32
STARTED = datetime(2026, 1, 1, 12, 0, 0)


def matches(row, clause):
    if hasattr(clause, "clauses"):
        parts = [matches(row, part) for part in clause.clauses]
        return any(parts) if clause.operator.__name__ == "or_" else all(parts)
    left = getattr(row, clause.left.key)
    right = getattr(clause.right, "value", None)
    operator = clause.operator.__name__
    if operator in ("eq", "is_"):
        return left == right
    if operator in ("ne", "is_not"):
        return left != right
    if operator == "in_op":
        return left in right
    if operator == "not_in_op":
        return left not in right
    guard.deny("unexpected_callback_persistence_predicate")


class Query:
    def __init__(self, store, entities):
        self.store, self.entities = store, entities
        self.model = getattr(entities[0], "class_", entities[0])
        self.rows = list(store.rows.get(self.model.__name__, []))

    def filter(self, *clauses):
        self.rows = [row for row in self.rows if all(matches(row, c) for c in clauses)]
        return self

    def filter_by(self, **values):
        self.rows = [
            row for row in self.rows
            if all(getattr(row, key) == value for key, value in values.items())
        ]
        return self

    def with_for_update(self, *args, **kwargs):
        # No actual transaction/locking guarantee is established by this store.
        self.store.locked = True
        return self

    def order_by(self, *clauses):
        for clause in reversed(clauses):
            field = getattr(clause, "element", clause)
            reverse = getattr(clause, "modifier", None)
            self.rows.sort(
                key=lambda row: getattr(row, field.key) or STARTED,
                reverse=bool(reverse and reverse.__name__ == "desc_op"),
            )
        return self

    def _project(self, row):
        if isinstance(self.entities[0], type):
            return row
        return SimpleNamespace(**{
            column.key: getattr(row, column.key) for column in self.entities
        })

    def first(self):
        return self._project(self.rows[0]) if self.rows else None

    def all(self):
        return [self._project(row) for row in self.rows]

    def count(self):
        return len(self.rows)

    def __getattr__(self, name):
        guard.deny("unexpected_callback_persistence_query")


class CallbackStore:
    def __init__(self):
        from botelier.models import CallLeg, CallLog

        self.rows = {
            "Account": [
                SimpleNamespace(id=ACCOUNT_A, twilio_sub_auth_token=TOKEN_A),
                SimpleNamespace(id=ACCOUNT_B, twilio_sub_auth_token=TOKEN_B),
            ],
            "PhoneNumber": [
                SimpleNamespace(phone_number=PHONE_A, account_id=ACCOUNT_A),
                SimpleNamespace(phone_number=PHONE_B, account_id=ACCOUNT_B),
            ],
            "CallLog": [
                CallLog(
                    id=UUID(int=11 + index), account_id=account_id, call_sid=sid,
                    status="initiated", started_at=STARTED, answered_at=STARTED,
                    has_transfer=True, transfer_mode="warm", ai_greeting_completed=True,
                    caller_spoke=True,
                )
                for index, (account_id, sid) in enumerate(
                    ((ACCOUNT_A, PARENT_A), (ACCOUNT_B, PARENT_B))
                )
            ],
            "CallLeg": [
                CallLeg(
                    id=UUID(int=21 + index), call_log_id=UUID(int=11 + index),
                    call_sid=sid, leg_number=2, leg_type="transfer_external",
                    participant=phone, status="initiated", started_at=STARTED,
                    duration_seconds=0, duration_source="unknown",
                )
                for index, (sid, phone) in enumerate(
                    ((CHILD_A, PHONE_A), (CHILD_B, PHONE_B))
                )
            ],
            "CallEvent": [],
        }
        self.commits = 0
        self.rollbacks = 0
        self.added = []
        self.pending = []
        self.snapshot = None
        self.locked = False
        self.closed = False

    def _begin(self):
        if self.snapshot is None:
            self.snapshot = [
                (row, dict(vars(row))) for rows in self.rows.values() for row in rows
            ]

    def query(self, *entities):
        self._begin()
        return Query(self, entities)

    def add(self, row):
        self._begin()
        if getattr(row, "id", None) is None:
            row.id = UUID(int=100 + len(self.added))
        self.pending.append(row)
        self.added.append(row)

    def commit(self):
        for row in self.pending:
            self.rows.setdefault(type(row).__name__, []).append(row)
        self.pending.clear()
        self.snapshot = None
        self.locked = False
        self.commits += 1

    def rollback(self):
        for row, values in self.snapshot or ():
            for key in list(vars(row)):
                if key not in values:
                    delattr(row, key)
            for key, value in values.items():
                if key != "_sa_instance_state":
                    setattr(row, key, value)
        self.pending.clear()
        self.snapshot = None
        self.locked = False
        self.rollbacks += 1

    def refresh(self, row):
        pass

    def expire_all(self):
        pass

    def close(self):
        self.locked = False
        self.closed = True

    def __getattr__(self, name):
        guard.deny("unexpected_callback_persistence_operation")

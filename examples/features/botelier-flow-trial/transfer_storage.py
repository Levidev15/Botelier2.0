"""Enumerated SQL-I/O double for native tests; PostgreSQL is verified separately."""

from copy import deepcopy
import json
import threading
from types import SimpleNamespace

import guard


class MemoryTransferStorage:
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()

    def __call__(self):
        return MemoryTransferSession(self)


class MemoryTransferSession:
    def __init__(self, storage):
        self.storage = storage
        self.held = False
        self.before = None

    def execute(self, statement, params):
        if not self.held:
            self.storage.lock.acquire()
            self.held = True
            self.before = deepcopy(self.storage.rows)
        sql = str(statement)
        key = params["key"]
        row = self.storage.rows.get(key)
        found = row is not None and row["account_id"] == params["account_id"]
        value, count = None, 0
        if "/* voice_transfer.insert */" in sql:
            if row is None:
                self.storage.rows[key] = {
                    "account_id": params["account_id"],
                    "result": json.loads(params["result"]),
                }
                count = 1
        elif "/* voice_transfer.read */" in sql:
            value = (deepcopy(row["result"]),) if found else None
        elif "/* voice_transfer.write */" in sql:
            if found:
                row["result"] = json.loads(params["result"])
                count = 1
        else:
            guard.deny("unexpected_transfer_storage_sql")
        return SimpleNamespace(rowcount=count, fetchone=lambda: value)

    def commit(self):
        self._release()

    def rollback(self):
        if self.held:
            self.storage.rows = self.before
        self._release()

    def close(self):
        self.rollback()

    def _release(self):
        if self.held:
            self.held = False
            self.storage.lock.release()

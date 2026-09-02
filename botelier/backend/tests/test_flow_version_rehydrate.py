"""Tests for flow-version version guard in rehydrate_from_snapshot.

Bug (Task #635): rehydrate_from_snapshot() never checked whether the
snapshot's flow_version_id matched the executor's published version.
A reconnecting caller could be resumed on a node that no longer exists
in the live (republished) flow, stalling the conversation.

Fix: if both the snapshot and the executor carry a non-null
flow_version_id and they differ, rehydrate_from_snapshot() returns
False so the executor starts the caller fresh.

Backwards-compat rules tested here:
  - NULL snapshot version  → allow rehydrate (pre-feature snapshot)
  - NULL executor version  → allow rehydrate (executor has no version)
  - matching versions      → allow rehydrate
  - mismatched versions    → refuse (start fresh)
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.flow_executor import FlowExecutor, parse_flow_config

_FLOW_CFG = {
    "initial_node": "start",
    "variables": [],
    "nodes": [
        {"id": "start", "type": "initial", "data": {"greeting": "Hi"}},
        {"id": "end", "type": "end", "data": {}},
    ],
    "edges": [{"id": "e1", "source": "start", "target": "end"}],
}

_VERSION_A = str(uuid4())
_VERSION_B = str(uuid4())


def _make_db_row(node_id="start", slots=None, status="active", flow_version_id=None):
    """Return a DB row tuple shaped like the rehydrate SELECT result."""
    import json

    return (node_id, json.dumps(slots or {}), status, flow_version_id)


def _make_executor(flow_version_id=None, call_sid="CA-test", flow_tool_id=None):
    executor = FlowExecutor(
        parse_flow_config(_FLOW_CFG),
        call_sid=call_sid,
        flow_tool_id=str(flow_tool_id or uuid4()),
        account_id=str(uuid4()),
        flow_version_id=flow_version_id,
    )
    return executor


def _patch_db_row(executor, row):
    """Replace the executor's _borrow_db_session so rehydrate reads from row."""
    from contextlib import contextmanager

    db = MagicMock()
    db.execute.return_value.fetchone.return_value = row

    @contextmanager
    def fake_borrow():
        yield db

    executor._borrow_db_session = fake_borrow


class TestVersionGuard:
    def test_matching_version_allows_rehydrate(self):
        """Same version on snapshot and executor → rehydrate succeeds."""
        executor = _make_executor(flow_version_id=_VERSION_A)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=_VERSION_A))

        assert executor.rehydrate_from_snapshot() is True
        assert executor.state.current_node_id == "start"

    def test_mismatched_version_refuses_rehydrate(self):
        """Different versions → refuse; caller starts fresh."""
        executor = _make_executor(flow_version_id=_VERSION_A)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=_VERSION_B))

        assert executor.rehydrate_from_snapshot() is False
        # State must remain at the initial default, not the stale snapshot node.
        assert executor.state.current_node_id == "start"

    def test_null_snapshot_version_allows_rehydrate(self):
        """Snapshot written before the feature (NULL version) → allow; backwards compat."""
        executor = _make_executor(flow_version_id=_VERSION_A)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=None))

        assert executor.rehydrate_from_snapshot() is True

    def test_null_executor_version_allows_rehydrate(self):
        """Executor has no version (non-Botelier tool or test) → allow; no information to decide."""
        executor = _make_executor(flow_version_id=None)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=_VERSION_A))

        assert executor.rehydrate_from_snapshot() is True

    def test_both_null_versions_allows_rehydrate(self):
        """Neither side has a version → backwards-compat pass-through."""
        executor = _make_executor(flow_version_id=None)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=None))

        assert executor.rehydrate_from_snapshot() is True

    def test_mismatched_version_logs_warning(self, capfd):
        """Version mismatch is logged at WARNING level with both version IDs."""
        import botelier.flow_executor as _fe_mod

        executor = _make_executor(flow_version_id=_VERSION_A)
        _patch_db_row(executor, _make_db_row(node_id="start", flow_version_id=_VERSION_B))

        warnings = []
        from unittest.mock import patch

        with patch.object(_fe_mod.logger, "warning", side_effect=warnings.append):
            executor.rehydrate_from_snapshot()

        assert warnings, "Expected a warning on version mismatch"
        msg = warnings[0]
        assert "mismatch" in msg.lower() or "republished" in msg.lower(), (
            f"Warning should mention mismatch or republish. Got: {msg!r}"
        )

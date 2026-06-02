"""Focused tests for post-call QA classification and enqueue gates."""

import json
import os
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.models.assistant import Assistant
from botelier.models.call_log import CallLog
from botelier.models.disposition import AssistantDisposition
from botelier.models.resolution_option import AssistantResolutionOption
from botelier.services import acw_service


class _Query:
    def __init__(self, *, first_result=None, all_result=None):
        self._first_result = first_result
        self._all_result = all_result or []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result


class _FakeSession:
    def __init__(self, *, assistant=None, dispositions=None, resolutions=None):
        self.assistant = assistant
        self.dispositions = dispositions or []
        self.resolutions = resolutions or []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        if model is Assistant:
            return _Query(first_result=self.assistant)
        if model is AssistantDisposition:
            return _Query(all_result=self.dispositions)
        if model is AssistantResolutionOption:
            return _Query(all_result=self.resolutions)
        return _Query()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeOpenAIClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=MagicMock(side_effect=self._create))
        )

    def _create(self, **kwargs):
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        message = SimpleNamespace(content=json.dumps(payload))
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def _assistant(*, acw_config=None):
    assistant = Assistant()
    assistant.id = uuid.uuid4()
    assistant.name = "Front Desk"
    if acw_config is None:
        acw_config = {
            "auto_run": True,
            "quality_rubric": "Score 0-100.",
            "summary_enabled": True,
        }
    assistant.acw_config = acw_config
    return assistant


def _call_log(assistant):
    call_log = CallLog()
    call_log.id = uuid.uuid4()
    call_log.call_sid = "CA-test"
    call_log.assistant_id = assistant.id
    call_log.duration_seconds = 42
    call_log.caller_number = "+15555550123"
    call_log.outcome = "completed"
    call_log.has_transfer = False
    call_log.caller_spoke = True
    call_log.transcript = [
        {"role": "assistant", "content": "How can I help?"},
        {"role": "user", "content": "What time is checkout?"},
        {"role": "assistant", "content": "Checkout is at 11 AM."},
    ]
    return call_log


def _disposition(assistant, name="Info Provided"):
    disposition = AssistantDisposition()
    disposition.id = uuid.uuid4()
    disposition.assistant_id = assistant.id
    disposition.name = name
    disposition.description = "Guest asked a general information question"
    disposition.color = "#6366f1"
    disposition.display_order = 0
    disposition.is_active = True
    disposition.created_at = datetime.utcnow()
    return disposition


def _resolution(assistant, name="Resolved"):
    resolution = AssistantResolutionOption()
    resolution.id = uuid.uuid4()
    resolution.assistant_id = assistant.id
    resolution.name = name
    resolution.description = "Caller got an answer"
    resolution.display_order = 0
    resolution.is_active = True
    resolution.created_at = datetime.utcnow()
    return resolution


def test_run_acw_selects_disposition_and_resolution_by_id():
    assistant = _assistant()
    disposition = _disposition(assistant)
    resolution = _resolution(assistant)
    call_log = _call_log(assistant)
    db = _FakeSession(
        assistant=assistant,
        dispositions=[disposition],
        resolutions=[resolution],
    )
    client = _FakeOpenAIClient(
        [
            {
                "disposition_id": str(disposition.id),
                "resolution_option_id": str(resolution.id),
                "quality_score": 91,
                "summary": "Caller asked about checkout and received the answer.",
            }
        ]
    )

    with patch.object(acw_service, "_get_client", return_value=client):
        result = acw_service.run_acw(call_log, db)

    assert result["success"] is True
    assert call_log.disposition_id == disposition.id
    assert call_log.acw_resolution == "Resolved"
    assert call_log.acw_quality_score == 91
    assert call_log.ai_summary
    assert call_log.acw_completed_at is not None
    assert call_log.acw_skip_reason is None
    assert client.chat.completions.create.call_args.kwargs["response_format"]["type"] == "json_schema"


def test_run_acw_retries_invalid_classification_and_accepts_legacy_name_fallback():
    assistant = _assistant(acw_config={"auto_run": True})
    disposition = _disposition(assistant)
    resolution = _resolution(assistant)
    call_log = _call_log(assistant)
    db = _FakeSession(
        assistant=assistant,
        dispositions=[disposition],
        resolutions=[resolution],
    )
    client = _FakeOpenAIClient(
        [
            {
                "disposition_id": str(uuid.uuid4()),
                "resolution_option_id": str(uuid.uuid4()),
            },
            {
                "disposition": " info provided ",
                "resolution": "resolved",
            },
        ]
    )

    with patch.object(acw_service, "_get_client", return_value=client):
        result = acw_service.run_acw(call_log, db)

    assert result["success"] is True
    assert call_log.disposition_id == disposition.id
    assert call_log.acw_resolution == "Resolved"
    assert client.chat.completions.create.call_count == 2
    assert (
        client.chat.completions.create.call_args_list[1].kwargs["response_format"]["type"]
        == "json_object"
    )


def test_run_acw_falls_back_when_strict_schema_is_not_supported():
    assistant = _assistant(acw_config={"auto_run": True})
    disposition = _disposition(assistant)
    resolution = _resolution(assistant)
    call_log = _call_log(assistant)
    db = _FakeSession(
        assistant=assistant,
        dispositions=[disposition],
        resolutions=[resolution],
    )
    client = _FakeOpenAIClient(
        [
            RuntimeError("response_format json_schema unsupported"),
            {
                "disposition_id": str(disposition.id),
                "resolution_option_id": str(resolution.id),
            },
        ]
    )

    with patch.object(acw_service, "_get_client", return_value=client):
        result = acw_service.run_acw(call_log, db)

    assert result["success"] is True
    assert call_log.disposition_id == disposition.id
    assert call_log.acw_resolution == "Resolved"
    assert client.chat.completions.create.call_count == 2
    assert (
        client.chat.completions.create.call_args_list[1].kwargs["response_format"]["type"]
        == "json_object"
    )


def test_run_acw_stamps_skip_when_transcript_missing():
    assistant = _assistant()
    call_log = _call_log(assistant)
    call_log.transcript = None
    db = _FakeSession(assistant=assistant)

    result = acw_service.run_acw(call_log, db)

    assert result == {"skipped": True, "reason": "no_transcript"}
    assert call_log.acw_skip_reason == "no_transcript"
    assert call_log.acw_completed_at is not None
    assert db.commits == 1


def test_should_auto_run_acw_requires_explicit_true():
    new_assistant = _assistant(acw_config={})
    enabled_assistant = _assistant(acw_config={"auto_run": True})

    assert acw_service.should_auto_run_acw(new_assistant, "CA-new") is False
    assert acw_service.should_auto_run_acw(enabled_assistant, "CA-enabled") is True

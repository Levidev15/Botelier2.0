"""
Database models for Botelier platform.

All SQLAlchemy models should be imported here for database initialization.
"""

from botelier.models.hotel import Hotel
from botelier.models.phone_number import PhoneNumber
from botelier.models.tool import Tool
from botelier.models.assistant import Assistant
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.flow_version import FlowVersion, FlowVersionStatus
from botelier.models.call_log import CallLog, CallLeg, CallStatus, CallOutcome, LegType

__all__ = [
    "Hotel",
    "PhoneNumber",
    "Tool",
    "Assistant",
    "KnowledgeEntry",
    "FlowVersion",
    "FlowVersionStatus",
    "CallLog",
    "CallLeg",
    "CallStatus",
    "CallOutcome",
    "LegType",
]

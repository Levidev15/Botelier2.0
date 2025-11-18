"""
Database models for Botelier platform.

All SQLAlchemy models should be imported here for database initialization.
"""

from botelier.models.hotel import Hotel
from botelier.models.phone_number import PhoneNumber
from botelier.models.tool import Tool
from botelier.models.assistant import Assistant
from botelier.models.knowledge_entry import KnowledgeEntry

__all__ = [
    "Hotel",
    "PhoneNumber",
    "Tool",
    "Assistant",
    "KnowledgeEntry",
]

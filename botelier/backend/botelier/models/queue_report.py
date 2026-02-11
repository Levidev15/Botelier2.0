import uuid
import json
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Float, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB

from botelier.database import Base


class QueuePerformanceReport(Base):
    __tablename__ = "queue_performance_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    integration_connection_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    queue_id = Column(String, nullable=False, index=True)
    queue_name = Column(String, nullable=True)

    report_period_start = Column(DateTime, nullable=False)
    report_period_end = Column(DateTime, nullable=False)

    total_calls = Column(Integer, default=0)
    calls_answered = Column(Integer, default=0)
    calls_abandoned = Column(Integer, default=0)
    calls_transferred = Column(Integer, default=0)
    calls_overflowed = Column(Integer, default=0)

    avg_wait_time_seconds = Column(Float, default=0.0)
    max_wait_time_seconds = Column(Float, default=0.0)
    avg_handle_time_seconds = Column(Float, default=0.0)
    avg_talk_time_seconds = Column(Float, default=0.0)
    avg_hold_time_seconds = Column(Float, default=0.0)
    avg_wrap_time_seconds = Column(Float, default=0.0)

    service_level_pct = Column(Float, default=0.0)
    abandon_rate_pct = Column(Float, default=0.0)
    answer_rate_pct = Column(Float, default=0.0)

    raw_data = Column(JSONB, nullable=True)

    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<QueuePerformanceReport queue={self.queue_name} period={self.report_period_start}>"

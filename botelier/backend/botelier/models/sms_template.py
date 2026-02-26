import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from botelier.database import Base


class SMSTemplate(Base):
    __tablename__ = "sms_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False)

    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('ix_sms_template_hotel', 'hotel_id'),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "name": self.name,
            "content": self.content,
            "category": self.category,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }


class SMSNotificationSettings(Base):
    __tablename__ = "sms_notification_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False, unique=True)

    sound_enabled = Column(Boolean, default=True, nullable=False)
    visual_enabled = Column(Boolean, default=True, nullable=False)
    threshold = Column(String, default="1", nullable=False)
    sound_type = Column(String(20), default="chime", nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "sound_enabled": self.sound_enabled,
            "visual_enabled": self.visual_enabled,
            "threshold": int(self.threshold) if self.threshold else 1,
            "sound_type": self.sound_type,
        }

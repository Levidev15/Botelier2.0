"""
SMS API package.

Combines four sub-routers into a single router that gets registered
in main.py as `from botelier.api.sms import router as sms_router`.

Sub-modules:
  webhook.py      — Twilio incoming webhook, status callback, SSE stream
  conversations.py — Conversation CRUD, agent actions, presence, replies
  analytics.py    — Stats, export, pending-handoffs, unread-count
  settings.py     — Templates CRUD, notification settings, file upload
"""

from fastapi import APIRouter

from .webhook import router as _webhook_router
from .conversations import router as _conversations_router
from .analytics import router as _analytics_router
from .settings import router as _settings_router

router = APIRouter()
router.include_router(_webhook_router)
router.include_router(_conversations_router)
router.include_router(_analytics_router)
router.include_router(_settings_router)

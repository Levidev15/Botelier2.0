"""PaymentPageTemplate Model - Per-property review+pay page design (Task #339).

A ``PaymentPageTemplate`` stores the operator-designed layout of the public
review+pay page for one property: which reservation sections/fields show, whether
each field is editable, branding (logo, colours), and the footer links (Privacy
Policy, Terms). The design is stored as a single structured ``design`` JSONB blob
so the visual designer and the public renderer share one contract.

Isolation invariants:
- **Tenant/property scoped.** Every row carries ``account_id`` and the Task #327
  ``property_id``. Keyed ``(account_id, property_id)`` — one design per property.
  ``property_id`` NULL is the account-global default design.
- Only page *design* lives here — never reservation data, never card data.
- When a property has no row, the public renderer falls back to
  :func:`default_page_design` so every property has a sensible page.
"""

import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from botelier.database import Base

# Branding values flow into the public review+pay page's inline CSS (`:root`) and
# into `href`/`src` sinks. They are operator-controlled but the page also collects
# a card, so an unvalidated value is a CSS/script-injection sink on a PCI-adjacent
# page. Colors must be strict hex; URLs must be http(s). Enforced at API write
# (:func:`validate_design`) AND coerced at the render sink (:func:`safe_color` /
# :func:`safe_url`) so legacy rows can never inject either.
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Keys whose value is used verbatim in a URL sink (href/src) in the renderer.
_BRANDING_URL_KEYS = ("logo_url",)
_FOOTER_URL_KEYS = ("privacy_url", "terms_url")
_BRANDING_COLOR_KEYS = ("primary_color", "accent_color")


def safe_color(value, default):
    """Return ``value`` only if it is a strict hex color, else ``default``.

    Coercion at the CSS sink: an operator (or a tampered/legacy row) can never
    break out of the ``:root`` CSS context on the card-collection page.
    """
    v = str(value or "").strip()
    return v if _COLOR_RE.match(v) else default


def safe_url(value):
    """Return ``value`` only if it is an ``http(s)`` URL, else ``""``.

    Blocks ``javascript:`` / ``data:`` schemes from reaching an ``href``/``src``
    sink on the public payment page.
    """
    v = str(value or "").strip()
    if not v:
        return ""
    try:
        parsed = urlparse(v)
    except (ValueError, TypeError):
        return ""
    return v if parsed.scheme in ("http", "https") else ""


def validate_design(design) -> None:
    """Raise :class:`ValueError` if a design's branding/footer sink values are
    unsafe, so operators get clear feedback at API write time. The renderer
    additionally coerces (defense in depth for any non-validated write path)."""
    if not isinstance(design, dict):
        return
    branding = design.get("branding") or {}
    if isinstance(branding, dict):
        for ckey in _BRANDING_COLOR_KEYS:
            val = branding.get(ckey)
            if val not in (None, "") and safe_color(val, None) is None:
                raise ValueError(f"{ckey} must be a hex color like #1a1a1a")
        for ukey in _BRANDING_URL_KEYS:
            val = branding.get(ukey)
            if val not in (None, "") and not safe_url(val):
                raise ValueError(f"{ukey} must be an http(s) URL")
    footer = design.get("footer") or {}
    if isinstance(footer, dict):
        for ukey in _FOOTER_URL_KEYS:
            val = footer.get(ukey)
            if val not in (None, "") and not safe_url(val):
                raise ValueError(f"{ukey} must be an http(s) URL")


def default_page_design() -> dict:
    """The platform-default review+pay page design.

    Used when a property has not customised its page. Shape is the single
    contract shared by the dashboard designer and the public renderer.
    """
    return {
        "branding": {
            "logo_url": "",
            "primary_color": "#1a1a1a",
            "accent_color": "#4f7cff",
            "heading": "Review & Pay",
            "subheading": "Please review your reservation and enter your card to confirm.",
        },
        "sections": [
            {
                "id": "reservation",
                "title": "Your reservation",
                "fields": [
                    {"key": "guest_first_name", "label": "First name", "editable": True, "visible": True},
                    {"key": "guest_last_name", "label": "Last name", "editable": True, "visible": True},
                    {"key": "guest_email", "label": "Email", "editable": True, "visible": True},
                    {"key": "guest_phone", "label": "Phone", "editable": True, "visible": True},
                    {"key": "checkin", "label": "Check-in", "editable": True, "visible": True},
                    {"key": "checkout", "label": "Check-out", "editable": True, "visible": True},
                    {"key": "number_of_adults", "label": "Adults", "editable": True, "visible": True},
                    {"key": "number_of_children", "label": "Children", "editable": True, "visible": True},
                    {"key": "room_name", "label": "Room", "editable": False, "visible": True},
                    {"key": "total_price", "label": "Total", "editable": False, "visible": True},
                ],
            },
            {
                "id": "payment",
                "title": "Payment details",
                "fields": [
                    {"key": "card_holder", "label": "Name on card", "editable": True, "visible": True},
                    {"key": "card_number", "label": "Card number", "editable": True, "visible": True},
                    {"key": "card_expiry", "label": "Expiry (MM/YY)", "editable": True, "visible": True},
                    {"key": "card_cvv", "label": "CVV", "editable": True, "visible": True},
                ],
            },
        ],
        "footer": {
            "privacy_url": "",
            "terms_url": "",
            "show_powered_by": True,
        },
    }


class PaymentPageTemplate(Base):
    __tablename__ = "payment_page_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = account-global default design (applies to every property without its
    # own row). Task #327 per-property scope otherwise.
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    design = Column(JSONB, nullable=False, server_default="{}")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id", "property_id", name="uq_payment_page_account_property"
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "property_id": str(self.property_id) if self.property_id else None,
            "design": self.design or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<PaymentPageTemplate account={self.account_id} "
            f"property={self.property_id}>"
        )

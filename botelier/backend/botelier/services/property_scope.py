"""Per-property session scoping (Task #327).

Resolves the property scope for a contact session (voice call, SMS thread, or
simulator run) exactly once at contact start. The resolved ``property_id`` is
carried through the whole session and used to scope every integration resolution
to ``(account_id, property_id)`` so a caller who reaches one property can never
receive another property's integration data.

Resolution is server-side only — it is derived from the dialed number and the
resolved assistant, never from anything the caller or the LLM supplies.
"""

from typing import Any, Optional

from sqlalchemy.orm import Session


def resolve_session_property_id(
    dialed_number: Optional[str],
    assistant: Any = None,
    db: Optional[Session] = None,
) -> Optional[str]:
    """Resolve the property scope for a contact session.

    Precedence (Task #327):
      1. The dialed phone number's ``property_id`` — the number the caller/texter
         actually reached is the most authoritative signal of intended property.
      2. The resolved assistant's ``property_id``.
      3. ``None`` — legacy / account-only scoping (no property binding, allow all
         of the account's integrations).

    Args:
        dialed_number: The phone number that was called/texted (E.164). When
            provided, the matching ``phone_numbers`` row is consulted first.
        assistant: The resolved assistant model (or snapshot) for this session.
            Only its ``property_id`` attribute is read, so a detached ORM object
            or a lightweight snapshot both work.
        db: An open session to reuse for the phone lookup. When omitted a
            short-lived session is opened and closed here, so this is safe to call
            from the voice cold path where the request session is already closed.

    Returns:
        The resolved property id as a ``str``, or ``None`` for account-only scope.
    """
    if dialed_number:
        owns_db = db is None
        session = db
        if owns_db:
            from botelier.database import SessionLocal

            session = SessionLocal()
        try:
            from botelier.models.phone_number import PhoneNumber

            phone = (
                session.query(PhoneNumber)
                .filter(PhoneNumber.phone_number == dialed_number)
                .first()
            )
            if phone is not None and getattr(phone, "property_id", None):
                return str(phone.property_id)
        finally:
            if owns_db and session is not None:
                session.close()

    if assistant is not None and getattr(assistant, "property_id", None):
        return str(assistant.property_id)

    return None

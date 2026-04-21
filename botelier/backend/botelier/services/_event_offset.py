"""
Single source of truth for ``CallEvent.offset_ms`` computation (Task #123).

Before this helper, three writers computed offset_ms independently and the
inline finalization writer additionally clamped to int4 max. The clamp was
drift, not policy — the column is ``BIGINT`` and the clamp would silently
saturate offsets for calls older than ~24.85 days. We now compute the value
in one place and rely on the startup invariant in
:func:`botelier.database._assert_call_events_offset_ms_bigint` to guarantee
the column type is ``bigint`` so no clamping is required.

Pure function — no SQLAlchemy, no asyncio, no I/O. Trivially unit-testable.
"""

from datetime import datetime
from typing import Optional


def compute_offset_ms(
    now: datetime,
    call_started_at: Optional[datetime],
) -> Optional[int]:
    """Return ms elapsed between ``call_started_at`` and ``now``.

    Returns ``None`` when ``call_started_at`` is missing — the column is
    nullable for events that pre-date or have no anchor (e.g. webhook
    events emitted before the CallLog row was created).

    Negative deltas are floored at zero so a slightly clock-skewed event
    cannot insert a negative offset that breaks downstream timeline math.
    """
    if call_started_at is None:
        return None
    raw_ms = int((now - call_started_at).total_seconds() * 1000)
    return max(0, raw_ms)

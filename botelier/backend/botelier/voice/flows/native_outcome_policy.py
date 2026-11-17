"""Shared positive classification for completed native HTTP write outcomes."""


DEFINITIVE_REJECTION_STATUSES = frozenset({
    400, 401, 403, 404, 405, 410, 413, 415, 422, 428,
})


def is_definitive_rejection(status_code):
    """Whether an HTTP status proves a write was rejected before acceptance."""
    return type(status_code) is int and status_code in DEFINITIVE_REJECTION_STATUSES

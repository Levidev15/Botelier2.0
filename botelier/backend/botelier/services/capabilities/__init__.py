"""Universal capability layer (Task #329).

Channel-agnostic abstract tools the AI calls (``search_availability``,
``lookup_reservation``, ``book_reservation``, ``cancel_reservation``) that resolve
at runtime to the caller's property-scoped provider connection and return
canonical data. The AI only ever knows capabilities — never vendors.
"""

from botelier.services.capabilities.registry import (
    CapabilitySpec,
    all_capabilities,
    build_capability_schema,
    capability_names,
    get_capability,
)
from botelier.services.capabilities.resolver import (
    CapabilityResolver,
    Resolution,
    format_capability_result,
)

__all__ = [
    "CapabilitySpec",
    "CapabilityResolver",
    "Resolution",
    "all_capabilities",
    "build_capability_schema",
    "capability_names",
    "get_capability",
    "format_capability_result",
]

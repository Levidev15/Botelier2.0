"""Universal Capabilities API.

Exposes the registered vendor-neutral capabilities (``search_availability``,
``lookup_reservation``, ``book_reservation``, ``cancel_reservation``,
``collect_payment``) so the dashboard can list them when authoring a Capability
flow node or a standalone Capability tool.

Read-only: this endpoint returns the *catalog* of capabilities (name,
description, vendor-neutral parameters), never any tenant data or provider
detail. Resolution to a concrete provider happens at runtime, property-scoped.
"""

from typing import List

from fastapi import APIRouter, Depends

from botelier.auth.middleware import get_current_user
from botelier.models.user import User
from botelier.services.capabilities.registry import all_capabilities

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("")
def list_capabilities(user: User = Depends(get_current_user)) -> List[dict]:
    """List every registered vendor-neutral capability.

    Requires an authenticated user (the catalog is not public), but is not
    account-scoped — the registry is global and contains no tenant data.
    """
    result = []
    for spec in all_capabilities():
        result.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "required": spec.required,
                "mutating": spec.mutating,
                "service_backed": spec.service_backed,
            }
        )
    return result

"""Authentication and Authorization module for Botelier.

Provides:
- JWT token validation (from NextAuth)
- Role-based access control
- Permission checking middleware
"""

from botelier.auth.permissions import (
    DEFAULT_ROLES,
    PERMISSIONS,
    PLATFORM_ADMIN_PERMISSIONS,
    check_permission,
    get_flat_permissions,
)

__all__ = [
    "PERMISSIONS",
    "DEFAULT_ROLES",
    "PLATFORM_ADMIN_PERMISSIONS",
    "get_flat_permissions",
    "check_permission",
]

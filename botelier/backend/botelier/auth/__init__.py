"""
Authentication and Authorization module for Botelier.

Provides:
- JWT token validation (from NextAuth)
- Role-based access control
- Permission checking middleware
"""

from botelier.auth.permissions import (
    PERMISSIONS,
    DEFAULT_ROLES,
    PLATFORM_ADMIN_PERMISSIONS,
    get_flat_permissions,
    check_permission,
)

__all__ = [
    "PERMISSIONS",
    "DEFAULT_ROLES",
    "PLATFORM_ADMIN_PERMISSIONS",
    "get_flat_permissions",
    "check_permission",
]

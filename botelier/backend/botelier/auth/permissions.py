"""
Permission Constants and Default Role Templates.

Defines all available permissions in the system and default role configurations.
"""

from typing import Dict, Any


PERMISSIONS = {
    "assistants": {
        "view": "View assistants list and details",
        "create": "Create new assistants",
        "edit": "Edit assistant configurations",
        "delete": "Delete assistants",
        "publish": "Publish flow changes",
    },
    "phone_numbers": {
        "view": "View phone numbers",
        "purchase": "Purchase new phone numbers",
        "configure": "Configure phone number settings",
        "release": "Release phone numbers",
    },
    "call_logs": {
        "view": "View call logs",
        "view_transcripts": "View call transcripts",
        "export": "Export call logs to CSV",
        "edit": "Edit call log fields (disposition, resolution status)",
        "delete": "Delete call logs",
    },
    "knowledge_base": {
        "view": "View knowledge base entries",
        "create": "Create knowledge base entries",
        "edit": "Edit knowledge base entries",
        "delete": "Delete knowledge base entries",
        "import": "Bulk import entries",
    },
    "tools": {
        "view": "View tools",
        "create": "Create new tools",
        "edit": "Edit tools",
        "delete": "Delete tools",
    },
    "flows": {
        "view": "View flow editor",
        "edit": "Edit flows",
        "publish": "Publish flow versions",
        "revert": "Revert to previous versions",
    },
    "team": {
        "view": "View team members",
        "invite": "Invite new members",
        "manage_roles": "Assign and manage roles",
        "remove": "Remove team members",
    },
    "settings": {
        "view": "View account settings",
        "edit": "Edit account settings",
        "billing": "Manage billing and subscription",
        "api_keys": "Manage API keys",
    },
}


DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "account_admin": {
        "name": "Account Admin",
        "description": "Full access to all account features. Can manage team and settings.",
        "is_system_role": True,
        "permissions": {
            "assistants": {"view": True, "create": True, "edit": True, "delete": True, "publish": True},
            "phone_numbers": {"view": True, "purchase": True, "configure": True, "release": True},
            "call_logs": {"view": True, "view_transcripts": True, "export": True, "edit": True, "delete": True},
            "knowledge_base": {"view": True, "create": True, "edit": True, "delete": True, "import": True},
            "tools": {"view": True, "create": True, "edit": True, "delete": True},
            "flows": {"view": True, "edit": True, "publish": True, "revert": True},
            "team": {"view": True, "invite": True, "manage_roles": True, "remove": True},
            "settings": {"view": True, "edit": True, "billing": True, "api_keys": True},
        },
    },
    "staff": {
        "name": "Staff",
        "description": "Standard access for daily operations. Can view and edit most features.",
        "is_system_role": True,
        "permissions": {
            "assistants": {"view": True, "create": False, "edit": True, "delete": False, "publish": False},
            "phone_numbers": {"view": True, "purchase": False, "configure": False, "release": False},
            "call_logs": {"view": True, "view_transcripts": True, "export": True, "edit": True, "delete": False},
            "knowledge_base": {"view": True, "create": True, "edit": True, "delete": False, "import": False},
            "tools": {"view": True, "create": False, "edit": False, "delete": False},
            "flows": {"view": True, "edit": True, "publish": False, "revert": False},
            "team": {"view": True, "invite": False, "manage_roles": False, "remove": False},
            "settings": {"view": True, "edit": False, "billing": False, "api_keys": False},
        },
    },
    "viewer": {
        "name": "Viewer",
        "description": "Read-only access. Can view all data but cannot make changes.",
        "is_system_role": True,
        "permissions": {
            "assistants": {"view": True, "create": False, "edit": False, "delete": False, "publish": False},
            "phone_numbers": {"view": True, "purchase": False, "configure": False, "release": False},
            "call_logs": {"view": True, "view_transcripts": True, "export": True, "edit": False, "delete": False},
            "knowledge_base": {"view": True, "create": False, "edit": False, "delete": False, "import": False},
            "tools": {"view": True, "create": False, "edit": False, "delete": False},
            "flows": {"view": True, "edit": False, "publish": False, "revert": False},
            "team": {"view": True, "invite": False, "manage_roles": False, "remove": False},
            "settings": {"view": True, "edit": False, "billing": False, "api_keys": False},
        },
    },
}


PLATFORM_ADMIN_PERMISSIONS: Dict[str, Any] = {
    "platform": {
        "view_all_accounts": True,
        "create_accounts": True,
        "edit_accounts": True,
        "delete_accounts": True,
        "suspend_accounts": True,
        "impersonate": True,
        "view_billing": True,
        "manage_platform_settings": True,
    },
    **{
        feature: {perm: True for perm in perms}
        for feature, perms in PERMISSIONS.items()
    }
}


def get_flat_permissions() -> list:
    """Get a flat list of all permission keys."""
    result = []
    for feature, perms in PERMISSIONS.items():
        for perm in perms:
            result.append(f"{feature}.{perm}")
    return result


def check_permission(user_permissions: dict, permission: str) -> bool:
    """
    Check if a permission dict grants a specific permission.
    
    Args:
        user_permissions: Nested dict of permissions
        permission: Dot-notation permission like "assistants.create"
    
    Returns:
        bool: True if permission is granted
    """
    parts = permission.split(".")
    current = user_permissions
    
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, bool):
            return current
        else:
            return False
        
        if current is None:
            return False
    
    return current is True

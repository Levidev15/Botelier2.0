"""Permission Constants and Default Role Templates.

Three-tier permission system
-----------------------------
1. ``PERMISSIONS`` — the canonical schema.
   Declares every valid (resource, action) pair and a human-readable
   description. Used for validation, UI dropdowns, and documentation.

2. ``DEFAULT_ROLES`` — the template for each system role.
   Defines what permissions ``account_admin``, ``staff``, and ``viewer``
   get by default. This is the source of truth for role permissions.

   **Adding or changing a permission here is all you need to do.**
   The change is propagated to production automatically on the next deploy
   via two mechanisms:

   * *Startup sync* — ``_sync_system_role_permissions()`` in ``database.py``
     rewrites every system role's ``permissions`` JSON column to match this
     template at boot time.

   * *Request-time merge* — ``_get_effective_permissions()`` in
     ``api/admin.py`` fills any key that is still missing in a DB row
     (e.g. during a startup-sync race) from this template at query time.

3. ``roles.permissions`` (DB column) — the live copy.
   Written once at account creation and kept in sync by the startup sync.
   Per-user ``AccountMembership.permission_overrides`` are applied on top
   of this value at request time.

``PLATFORM_ADMIN_PERMISSIONS`` is separate — it grants every permission to
platform admins regardless of account membership.
"""

from typing import Any, Dict

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
        "play_recordings": "Play call recordings",
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
    "integrations": {
        "view": "View integration connections and status",
        "manage": "Connect, test, disconnect, and inspect call logs of external integrations",
    },
    "messages": {
        "view": "View SMS conversations and messages",
        "reply": "Send SMS replies and upload MMS attachments",
        "manage_conversations": "Take over, return to AI, and close SMS conversations",
        "manage_settings": "Create, edit, and delete SMS templates and notification settings",
    },
    "usage": {
        "view": "View usage and billing summary, call cost list, and timeseries",
        "export": "Export usage data to CSV",
    },
    "billing_rates": {
        "view": "View the account's current billing rates",
        "manage": "Update per-account billing rates (platform admin only)",
    },
    "properties": {
        "view": "View properties (locations) within the account",
        "manage": "Create, edit, and delete properties and their phone/assistant bindings",
    },
    "records": {
        "view": "View structured output records",
        "create": "Manually create records",
        "edit": "Edit record data and status",
        "delete": "Delete records",
        "export": "Export records to CSV",
        "manage_types": "Create, edit, and delete record types (table definitions)",
    },
}


DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "account_admin": {
        "name": "Account Admin",
        "description": "Full access to all account features. Can manage team and settings.",
        "is_system_role": True,
        "permissions": {
            "assistants": {
                "view": True,
                "create": True,
                "edit": True,
                "delete": True,
                "publish": True,
            },
            "phone_numbers": {"view": True, "purchase": True, "configure": True, "release": True},
            "call_logs": {
                "view": True,
                "view_transcripts": True,
                "export": True,
                "edit": True,
                "delete": True,
                "play_recordings": True,
            },
            "knowledge_base": {
                "view": True,
                "create": True,
                "edit": True,
                "delete": True,
                "import": True,
            },
            "tools": {"view": True, "create": True, "edit": True, "delete": True},
            "flows": {"view": True, "edit": True, "publish": True, "revert": True},
            "team": {"view": True, "invite": True, "manage_roles": True, "remove": True},
            "settings": {"view": True, "edit": True, "billing": True, "api_keys": True},
            "integrations": {"view": True, "manage": True},
            "messages": {
                "view": True,
                "reply": True,
                "manage_conversations": True,
                "manage_settings": True,
            },
            "usage": {"view": True, "export": True},
            "billing_rates": {"view": True, "manage": False},
            "properties": {"view": True, "manage": True},
            "records": {
                "view": True,
                "create": True,
                "edit": True,
                "delete": True,
                "export": True,
                "manage_types": True,
            },
        },
    },
    "staff": {
        "name": "Staff",
        "description": "Standard access for daily operations. Can view and edit most features.",
        "is_system_role": True,
        "permissions": {
            "assistants": {
                "view": True,
                "create": False,
                "edit": True,
                "delete": False,
                "publish": False,
            },
            "phone_numbers": {
                "view": True,
                "purchase": False,
                "configure": False,
                "release": False,
            },
            "call_logs": {
                "view": True,
                "view_transcripts": True,
                "export": True,
                "edit": True,
                "delete": False,
                "play_recordings": True,
            },
            "knowledge_base": {
                "view": True,
                "create": True,
                "edit": True,
                "delete": False,
                "import": False,
            },
            "tools": {"view": True, "create": False, "edit": False, "delete": False},
            "flows": {"view": True, "edit": True, "publish": False, "revert": False},
            "team": {"view": True, "invite": False, "manage_roles": False, "remove": False},
            "settings": {"view": True, "edit": False, "billing": False, "api_keys": False},
            "integrations": {"view": True, "manage": False},
            "messages": {
                "view": True,
                "reply": True,
                "manage_conversations": True,
                "manage_settings": False,
            },
            "usage": {"view": True, "export": True},
            "billing_rates": {"view": False, "manage": False},
            "properties": {"view": True, "manage": False},
            "records": {
                "view": True,
                "create": True,
                "edit": True,
                "delete": False,
                "export": True,
                "manage_types": False,
            },
        },
    },
    "viewer": {
        "name": "Viewer",
        "description": "Read-only access. Can view all data but cannot make changes.",
        "is_system_role": True,
        "permissions": {
            "assistants": {
                "view": True,
                "create": False,
                "edit": False,
                "delete": False,
                "publish": False,
            },
            "phone_numbers": {
                "view": True,
                "purchase": False,
                "configure": False,
                "release": False,
            },
            "call_logs": {
                "view": True,
                "view_transcripts": True,
                "export": True,
                "edit": False,
                "delete": False,
                "play_recordings": False,
            },
            "knowledge_base": {
                "view": True,
                "create": False,
                "edit": False,
                "delete": False,
                "import": False,
            },
            "tools": {"view": True, "create": False, "edit": False, "delete": False},
            "flows": {"view": True, "edit": False, "publish": False, "revert": False},
            "team": {"view": True, "invite": False, "manage_roles": False, "remove": False},
            "settings": {"view": True, "edit": False, "billing": False, "api_keys": False},
            "integrations": {"view": True, "manage": False},
            "messages": {
                "view": True,
                "reply": False,
                "manage_conversations": False,
                "manage_settings": False,
            },
            "usage": {"view": True, "export": False},
            "billing_rates": {"view": False, "manage": False},
            "properties": {"view": True, "manage": False},
            "records": {
                "view": True,
                "create": False,
                "edit": False,
                "delete": False,
                "export": True,
                "manage_types": False,
            },
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
    **{feature: {perm: True for perm in perms} for feature, perms in PERMISSIONS.items()},
}


def get_flat_permissions() -> list:
    """Get a flat list of all permission keys."""
    result = []
    for feature, perms in PERMISSIONS.items():
        for perm in perms:
            result.append(f"{feature}.{perm}")
    return result


def _label_from_key(key: str) -> str:
    """Convert a snake_case key to a human-readable label.

    Examples:
        phone_numbers  ->  Phone Numbers
        manage_conversations  ->  Manage Conversations
        api_keys  ->  API Keys
        view_transcripts  ->  View Transcripts
    """
    special = {"api_keys": "API Keys", "mcp": "MCP"}
    if key in special:
        return special[key]
    return " ".join(word.capitalize() for word in key.split("_"))


def build_permission_schema() -> list:
    """Build a structured, JSON-serializable permission schema from ``PERMISSIONS``.

    Returns a list of feature groups in the form::

        [
          {
            "key": "assistants",
            "label": "Assistants",
            "description": "",
            "permissions": [
              {
                "key": "view",
                "full_key": "assistants.view",
                "label": "View",
                "description": "View assistants list and details",
              },
              ...
            ]
          },
          ...
        ]

    The description at the feature level is left as an empty string because
    ``PERMISSIONS`` only stores per-action descriptions.  Callers may enrich
    it from a separate mapping if desired.

    No hardcoded list is maintained here — the output is derived entirely from
    the canonical ``PERMISSIONS`` dict, so adding a new key to ``PERMISSIONS``
    automatically surfaces it in the role editor.
    """
    schema = []
    for feature_key, actions in PERMISSIONS.items():
        perms = []
        for action_key, description in actions.items():
            perms.append(
                {
                    "key": action_key,
                    "full_key": f"{feature_key}.{action_key}",
                    "label": _label_from_key(action_key),
                    "description": description,
                }
            )
        schema.append(
            {
                "key": feature_key,
                "label": _label_from_key(feature_key),
                "description": "",
                "permissions": perms,
            }
        )
    return schema


def build_empty_permission_map() -> dict:
    """Return a nested ``{feature: {action: False}}`` map for every canonical permission.

    Useful as a starting point when normalising a submitted permissions dict.
    """
    return {feature: {action: False for action in actions} for feature, actions in PERMISSIONS.items()}


def normalize_permission_map(submitted: dict) -> dict:
    """Merge *submitted* into a full canonical map, filling missing keys with ``False``.

    * Keys present in *submitted* that are also in ``PERMISSIONS`` keep their
      submitted boolean value (truthy → True, falsy → False).
    * Canonical keys absent from *submitted* default to ``False``.
    * Keys present in *submitted* but absent from ``PERMISSIONS`` are silently
      dropped (call ``validate_permission_map`` first if you want to reject them).
    """
    result = build_empty_permission_map()
    for feature, actions in PERMISSIONS.items():
        sub_feature = submitted.get(feature, {})
        if not isinstance(sub_feature, dict):
            continue
        for action in actions:
            if action in sub_feature:
                result[feature][action] = bool(sub_feature[action])
    return result


def validate_permission_map(submitted: dict) -> None:
    """Raise ``ValueError`` if *submitted* contains any key not in ``PERMISSIONS``.

    Checks both feature-level and action-level keys.  Non-boolean action values
    are also rejected.

    Raises:
        ValueError: with a message naming the first unknown or invalid key.
    """
    for feature, actions in submitted.items():
        if feature not in PERMISSIONS:
            raise ValueError(f"Unknown permission feature: '{feature}'")
        if not isinstance(actions, dict):
            raise ValueError(
                f"Permission value for feature '{feature}' must be an object, got {type(actions).__name__}"
            )
        for action, value in actions.items():
            if action not in PERMISSIONS[feature]:
                raise ValueError(f"Unknown permission action: '{feature}.{action}'")
            if not isinstance(value, bool):
                raise ValueError(
                    f"Permission value for '{feature}.{action}' must be a boolean, got {type(value).__name__}"
                )


def check_permission(user_permissions: dict, permission: str) -> bool:
    """Check if a permission dict grants a specific permission.

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

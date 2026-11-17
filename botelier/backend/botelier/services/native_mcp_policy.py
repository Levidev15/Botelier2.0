"""Server-authenticated native MCP grants stored with a connection."""

import json
import re
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError


_POLICY_KEY = "_native_policy_v1"
_PLAIN_FIELDS = frozenset({
    "property_id", "account_global",
    "native_enabled_tools", "native_read_only_tools",
})
_TOOL_NAME = re.compile(r"[\w][\w .:-]{0,127}\Z", re.UNICODE)


class NativeMCPPolicy(BaseModel):
    """Strict internal envelope; caller-controlled JSON cannot create this token."""

    model_config = ConfigDict(extra="forbid", strict=True)

    account_id: StrictStr
    connection_id: StrictStr
    property_id: Optional[StrictStr] = None
    account_global: Optional[StrictBool] = None
    enabled_tools: List[StrictStr] = Field(max_length=128)
    read_only_tools: List[StrictStr] = Field(default_factory=list, max_length=128)


def _uuid(value, code="native_mcp_policy"):
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError(code) from None
    return str(parsed)


def protect_connection_config(config, *, account_id, connection_id, db):
    """Validate a manager's typed grant and seal it to account + connection."""
    if not isinstance(config, dict):
        raise ValueError("native_mcp_policy")
    if _POLICY_KEY in config:
        raise ValueError("native_mcp_policy")
    native_keys = {key for key in config if isinstance(key, str) and key.startswith("native_")}
    if native_keys - _PLAIN_FIELDS:
        raise ValueError("native_mcp_policy")
    requested = set(config) & _PLAIN_FIELDS
    if not requested:
        return dict(config)
    if "native_enabled_tools" not in config:
        raise ValueError("native_mcp_policy")

    try:
        policy = NativeMCPPolicy(
            account_id=_uuid(account_id),
            connection_id=_uuid(connection_id),
            property_id=config.get("property_id"),
            account_global=config.get("account_global"),
            enabled_tools=config["native_enabled_tools"],
            read_only_tools=config.get("native_read_only_tools", []),
        )
    except (ValidationError, ValueError, TypeError):
        raise ValueError("native_mcp_policy") from None

    if (
        len(policy.enabled_tools) != len(set(policy.enabled_tools))
        or len(policy.read_only_tools) != len(set(policy.read_only_tools))
        or set(policy.read_only_tools) - set(policy.enabled_tools)
        or any(not name or not _TOOL_NAME.fullmatch(name) for name in (
            *policy.enabled_tools, *policy.read_only_tools,
        ))
    ):
        raise ValueError("native_mcp_policy")

    if policy.property_id is not None:
        if policy.account_global is not None:
            raise ValueError("native_mcp_policy_scope")
        property_id = _uuid(policy.property_id, "native_mcp_policy_scope")
        from botelier.models.property import Property

        row = db.query(Property).filter(
            Property.id == UUID(property_id),
            Property.account_id == UUID(policy.account_id),
            Property.is_active.is_(True),
        ).first()
        if row is None:
            raise ValueError("native_mcp_policy_scope")
        policy = policy.model_copy(update={"property_id": property_id})
    elif policy.account_global is not True:
        raise ValueError("native_mcp_policy_scope")

    from botelier.crypto import get_cipher

    ciphertext = get_cipher().encrypt(
        json.dumps(
            policy.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    ).decode("ascii")
    protected = {
        key: value for key, value in config.items()
        if key not in _PLAIN_FIELDS and not key.startswith("native_")
    }
    protected[_POLICY_KEY] = ciphertext
    return protected


def clear_connection_native_policy(config):
    if not isinstance(config, dict):
        return {}
    return {
        key: value for key, value in config.items()
        if key != _POLICY_KEY and key not in _PLAIN_FIELDS
        and not (isinstance(key, str) and key.startswith("native_"))
    }


def public_connection_config(config):
    """Never pass a native grant token or legacy grant fields to remote MCP."""
    return clear_connection_native_policy(config)


def resolve_connection_policy(connection):
    """Decrypt only a server-sealed policy bound to this exact stored connection."""
    config = connection.get_connection_config() or {}
    if not isinstance(config, dict):
        raise PermissionError("mcp_tool_policy")
    token = config.get(_POLICY_KEY)
    if not isinstance(token, str) or not token:
        raise PermissionError("mcp_tool_policy")
    if set(config) & _PLAIN_FIELDS:
        raise PermissionError("mcp_tool_policy")
    if any(
        isinstance(key, str) and key.startswith("native_")
        for key in config
    ):
        raise PermissionError("mcp_tool_policy")
    try:
        from botelier.crypto import get_cipher

        plaintext = get_cipher().decrypt(token.encode("ascii"))
        policy = NativeMCPPolicy.model_validate_json(plaintext)
    except Exception:
        raise PermissionError("mcp_tool_policy") from None
    if (
        policy.account_id != _uuid(connection.account_id, "mcp_tool_policy")
        or policy.connection_id != _uuid(connection.id, "mcp_tool_policy")
    ):
        raise PermissionError("mcp_tool_policy")
    if (
        len(policy.enabled_tools) != len(set(policy.enabled_tools))
        or len(policy.read_only_tools) != len(set(policy.read_only_tools))
        or set(policy.read_only_tools) - set(policy.enabled_tools)
        or any(not name or not _TOOL_NAME.fullmatch(name) for name in (
            *policy.enabled_tools, *policy.read_only_tools,
        ))
    ):
        raise PermissionError("mcp_tool_policy")
    return policy

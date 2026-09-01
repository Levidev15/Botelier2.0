"""Flow Versions API endpoints.

Provides endpoints for managing versioned flow configurations:
- Save drafts
- Publish versions
- List version history
- Revert to previous versions

Tools are scoped through their ToolSet's account_id for multi-tenant isolation.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.flow_version import FlowVersion, FlowVersionStatus
from botelier.models.tool import Tool
from botelier.models.tool import ToolType as DBToolType
from botelier.models.tool_set import ToolSet
from botelier.models.user import User
from botelier.services.capabilities.registry import capability_names

router = APIRouter(prefix="/api/tools", tags=["flow-versions"])

_API_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_TEMPLATE_VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


def _template_variables(value: object) -> set[str]:
    """Return simple flow-variable placeholders from a nested template value."""
    if isinstance(value, str):
        return set(_TEMPLATE_VARIABLE_RE.findall(value))
    if isinstance(value, dict):
        found: set[str] = set()
        for nested in value.values():
            found.update(_template_variables(nested))
        return found
    if isinstance(value, list):
        found = set()
        for nested in value:
            found.update(_template_variables(nested))
        return found
    return set()


def _get_flow_tool(db: Session, tool_id: str, account_id: str) -> Tool:
    """Fetch a flow tool by ID, scoped through ToolSet.account_id."""
    tool = (
        db.query(Tool)
        .join(ToolSet, Tool.tool_set_id == ToolSet.id)
        .filter(Tool.id == tool_id, ToolSet.account_id == account_id)
        .first()
    )

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with id {tool_id} not found for this account",
        )

    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool {tool_id} is not a flow type tool",
        )

    return tool


def validate_flow_config(flow_config: dict) -> Tuple[bool, List[str], List[str]]:
    """Validate a flow configuration for publishing.

    Returns (is_valid, errors, error_node_ids) tuple where error_node_ids is the
    list of node IDs that have validation errors (may contain duplicates; caller
    should deduplicate if needed).
    """
    errors: List[str] = []
    error_node_ids: List[str] = []

    nodes = flow_config.get("nodes", [])
    edges = flow_config.get("edges", [])
    variables = flow_config.get("variables", [])

    declared_variables: set[str] = set()
    for variable in variables if isinstance(variables, list) else []:
        key = variable.get("key") if isinstance(variable, dict) else None
        if isinstance(key, str) and key.strip():
            if key in declared_variables:
                errors.append(f"Flow variable '{key}' is declared more than once")
            declared_variables.add(key)

    if not nodes:
        errors.append("Flow must have at least one node")
        return False, errors, error_node_ids

    initial_nodes = [n for n in nodes if n.get("type") == "initial"]
    if len(initial_nodes) == 0:
        errors.append("Flow must have a Start node")
    elif len(initial_nodes) > 1:
        errors.append("Flow can only have one Start node")

    initial_node_id = flow_config.get("initial_node")
    if not initial_node_id:
        errors.append("No initial node specified in flow configuration")
    else:
        initial_exists = any(n.get("id") == initial_node_id for n in nodes)
        if not initial_exists:
            errors.append(f"Initial node '{initial_node_id}' does not exist in flow")

    node_ids: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append("Every flow node must have a non-empty ID")
        elif node_id in node_ids:
            errors.append(f"Node ID '{node_id}' is not unique")
            error_node_ids.append(node_id)
        else:
            node_ids.add(node_id)

    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = edge.get("id")
        if edge_id:
            if edge_id in edge_ids:
                errors.append(f"Edge ID '{edge_id}' is not unique")
            edge_ids.add(edge_id)
        source = edge.get("source")
        target = edge.get("target")
        if not source:
            errors.append("Every edge must have a source node")
        elif source not in node_ids:
            errors.append(f"Edge references non-existent source node: {source}")
        if not target:
            errors.append("Every edge must have a target node")
        elif target not in node_ids:
            errors.append(f"Edge references non-existent target node: {target}")

    if initial_node_id and initial_node_id in node_ids:
        connected = set()
        to_visit = [initial_node_id]
        edge_map = {}
        for edge in edges:
            source = edge.get("source")
            if source not in edge_map:
                edge_map[source] = []
            edge_map[source].append(edge.get("target"))

        while to_visit:
            current = to_visit.pop()
            if current in connected:
                continue
            connected.add(current)
            for target in edge_map.get(current, []):
                if target not in connected:
                    to_visit.append(target)

        end_nodes = [n for n in nodes if n.get("type") == "end"]
        end_ids = {n.get("id") for n in end_nodes}

        disconnected = node_ids - connected
        critical_disconnected = disconnected - end_ids
        if critical_disconnected:
            for node_id in critical_disconnected:
                node = next((n for n in nodes if n.get("id") == node_id), None)
                if node:
                    errors.append(
                        f"Node '{node.get('data', {}).get('name', node_id)}' is not reachable from Start"
                    )
                    error_node_ids.append(node_id)

    for node in nodes:
        node_type = node.get("type")
        node_data = node.get("data", {})
        node_name = node_data.get("name", node.get("id"))
        node_id = node.get("id")

        def _node_error(msg: str) -> None:
            errors.append(msg)
            if node_id:
                error_node_ids.append(node_id)

        def _require_declared(variable_key: object, context: str) -> None:
            if (
                isinstance(variable_key, str)
                and variable_key.strip()
                and variable_key not in declared_variables
            ):
                _node_error(
                    f"{context} in node '{node_name}' references undeclared variable "
                    f"'{variable_key}'"
                )

        # Only simple {{variable}} placeholders are publish-validated. More
        # elaborate integration/JSONPath syntax is deliberately ignored.
        template_values: list[object] = [
            node_data.get("systemPrompt"),
            node_data.get("greeting"),
            node_data.get("message"),
            node_data.get("closingMessage"),
            node_data.get("instructions"),
        ]

        if node_type == "collect_slot":
            slot = node_data.get("slot", {})
            if not slot.get("variableKey"):
                _node_error(f"Collect Input node '{node_name}' has no variable key")
            else:
                _require_declared(slot.get("variableKey"), "Collect Input")
            if not slot.get("prompt"):
                _node_error(f"Collect Input node '{node_name}' has no prompt")
            _require_declared(
                (slot.get("validation") or {}).get(
                    "afterDateVariable",
                    (slot.get("validation") or {}).get(
                        "after_date_variable",
                        ((slot.get("validation") or {}).get("crossFieldCheck") or {}).get(
                            "compareWith"
                        ),
                    ),
                ),
                "Collect Input date validation",
            )
            template_values.extend(
                [slot.get("prompt"), slot.get("retryPrompt"), slot.get("instructions")]
            )

        elif node_type == "collect_form":
            slots = node_data.get("slots", [])
            if not isinstance(slots, list) or not slots:
                _node_error(f"Collect Form node '{node_name}' has no inputs")
            else:
                seen_slot_variables: set[str] = set()
                for slot in slots:
                    variable_key = slot.get("variableKey") if isinstance(slot, dict) else None
                    if not isinstance(variable_key, str) or not variable_key.strip():
                        _node_error(
                            f"Collect Form node '{node_name}' has an input with no variable key"
                        )
                        continue
                    if variable_key in seen_slot_variables:
                        _node_error(
                            f"Collect Form node '{node_name}' collects variable "
                            f"'{variable_key}' more than once"
                        )
                    seen_slot_variables.add(variable_key)
                    _require_declared(variable_key, "Collect Form")
                    template_values.extend(
                        [
                            slot.get("prompt"),
                            slot.get("retryPrompt"),
                            slot.get("instructions"),
                        ]
                    )
            template_values.append(node_data.get("introMessage"))

        elif node_type == "api_request":
            api = node_data.get("api", {})
            method = str(api.get("method", "GET")).upper()
            api_source = api.get("apiSource") or "custom"
            if method not in _API_METHODS:
                _node_error(
                    f"API Request node '{node_name}' has unsupported method '{method}'"
                )
            if api_source == "integration":
                if not api.get("integrationId") and not api.get("integrationSlug"):
                    _node_error(
                        f"API Request node '{node_name}' has no connected integration selected"
                    )
                if not api.get("endpointId"):
                    _node_error(f"API Request node '{node_name}' has no endpoint selected")
            else:
                url = api.get("url")
                if not url:
                    _node_error(f"API Request node '{node_name}' has no URL")
                else:
                    parsed = urlparse(str(url))
                    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                        _node_error(
                            f"API Request node '{node_name}' has an invalid HTTP/HTTPS URL"
                        )
            timeout = api.get("timeout", 8)
            if not isinstance(timeout, int) or timeout < 1 or timeout > 60:
                _node_error(f"API Request node '{node_name}' timeout must be 1-60 seconds")
            retry_count = api.get("retryCount", 0)
            if not isinstance(retry_count, int) or retry_count < 0 or retry_count > 3:
                _node_error(f"API Request node '{node_name}' retry count must be 0-3")
            if method in {"POST", "PUT", "PATCH"} and api.get("bodyTemplate"):
                import json

                try:
                    json.loads(api["bodyTemplate"])
                except Exception:
                    _node_error(
                        f"API Request node '{node_name}' request body must be valid JSON"
                    )
            response_mapping = api.get("responseMapping") or {}
            if not isinstance(response_mapping, dict):
                _node_error(f"API Request node '{node_name}' response mapping is invalid")
            else:
                for key, path in response_mapping.items():
                    if not str(key).strip() or not str(path).strip():
                        _node_error(
                            f"API Request node '{node_name}' has an incomplete response mapping"
                        )
                    elif str(key) not in declared_variables:
                        _node_error(
                            f"API Request node '{node_name}' response mapping writes "
                            f"undeclared variable '{key}'"
                        )
            template_values.extend(
                [
                    api.get("url"),
                    api.get("bodyTemplate"),
                    api.get("headers"),
                    api.get("queryParamOverrides"),
                    api.get("responseInstructions"),
                    api.get("thinkingMessage"),
                    api.get("onSuccess"),
                    api.get("onError"),
                    api.get("onNotFound"),
                    api.get("onAuthError"),
                ]
            )

        elif node_type == "api_response":
            config = node_data.get("responsePresentation", {}) or {}
            array_var = (config.get("arrayVariable") or "").strip()
            intro = config.get("introText") or ""
            item_template = config.get("itemTemplate") or ""
            if array_var and array_var not in declared_variables:
                _node_error(
                    f"API Response node '{node_name}' references undeclared array "
                    f"variable '{array_var}'"
                )
            template_values.extend(
                [
                    intro,
                    config.get("outroText"),
                    config.get("noResultsText"),
                ]
            )
            # The per-item template has its own variable namespace at runtime:
            # dict fields from each API array item, plus {{index}}/{{item}}.
            # Those fields are intentionally not flow variables, so applying
            # the generic declared-variable check to this string would reject
            # the documented {{room_name}} / {{price}} use case.

        elif node_type == "condition":
            condition = node_data.get("condition", {})
            if not condition.get("variable"):
                _node_error(f"Condition node '{node_name}' has no variable to check")
            else:
                _require_declared(condition.get("variable"), "Condition")
            branch_edges = [edge for edge in edges if edge.get("source") == node_id]
            handles = [edge.get("sourceHandle") for edge in branch_edges]
            for handle in ("true", "false"):
                if handles.count(handle) != 1:
                    _node_error(
                        f"Condition node '{node_name}' must have exactly one '{handle}' branch"
                    )
                configured_target = condition.get(f"{handle}Target")
                if configured_target and configured_target not in node_ids:
                    _node_error(
                        f"Condition node '{node_name}' {handle} target "
                        f"'{configured_target}' does not exist"
                    )
                matching = [e for e in branch_edges if e.get("sourceHandle") == handle]
                if configured_target and matching and matching[0].get("target") != configured_target:
                    _node_error(
                        f"Condition node '{node_name}' {handle} branch does not match "
                        "its configured target"
                    )
            invalid_handles = [h for h in handles if h not in {"true", "false"}]
            if invalid_handles:
                _node_error(
                    f"Condition node '{node_name}' has invalid or missing branch sourceHandle"
                )

        elif node_type == "router":
            router_cfg = node_data.get("router", {})
            if not router_cfg.get("variable"):
                _node_error(f"Router node '{node_name}' has no variable to route on")
            else:
                _require_declared(router_cfg.get("variable"), "Router")
            if not router_cfg.get("options"):
                _node_error(f"Router node '{node_name}' has no routing options")
            else:
                option_ids = []
                malformed_option = False
                for option in router_cfg["options"]:
                    option_id = option.get("id") if isinstance(option, dict) else None
                    if not isinstance(option_id, str) or not option_id.strip():
                        malformed_option = True
                    else:
                        option_ids.append(option_id)
                if malformed_option:
                    _node_error(f"Router node '{node_name}' has an option with no ID")
                if len(set(option_ids)) != len(option_ids):
                    _node_error(f"Router node '{node_name}' has duplicate option IDs")
                branch_edges = [edge for edge in edges if edge.get("source") == node_id]
                handles = [edge.get("sourceHandle") for edge in branch_edges]
                for option_id in option_ids:
                    if option_id and handles.count(option_id) != 1:
                        _node_error(
                            f"Router node '{node_name}' must have exactly one "
                            f"'{option_id}' branch"
                        )
                if any(handle not in set(option_ids) for handle in handles):
                    _node_error(
                        f"Router node '{node_name}' has an invalid or missing branch sourceHandle"
                    )

        elif node_type == "confirmation":
            confirmation = node_data.get("confirmation", {})
            variables_to_confirm = confirmation.get(
                "variablesToConfirm", confirmation.get("variables_to_confirm", [])
            )
            if not isinstance(variables_to_confirm, list) or not variables_to_confirm:
                _node_error(
                    f"Confirmation node '{node_name}' has no variables to confirm"
                )
            else:
                valid_confirmation_variables = [
                    key
                    for key in variables_to_confirm
                    if isinstance(key, str) and key.strip()
                ]
                if len(valid_confirmation_variables) != len(variables_to_confirm):
                    _node_error(
                        f"Confirmation node '{node_name}' has an invalid variable to confirm"
                    )
                if len(set(valid_confirmation_variables)) != len(
                    valid_confirmation_variables
                ):
                    _node_error(
                        f"Confirmation node '{node_name}' has duplicate variables to confirm"
                    )
                for variable_key in valid_confirmation_variables:
                    _require_declared(variable_key, "Confirmation")
            if not confirmation.get(
                "summaryTemplate", confirmation.get("summary_template")
            ):
                _node_error(f"Confirmation node '{node_name}' has no summary template")
            if not confirmation.get("confirmPrompt", confirmation.get("confirm_prompt")):
                _node_error(f"Confirmation node '{node_name}' has no confirmation prompt")
            allow_edit = confirmation.get("allowEdit", confirmation.get("allow_edit", False))
            edit_prompt = confirmation.get("editPrompt", confirmation.get("edit_prompt"))
            confirmation_edges = [edge for edge in edges if edge.get("source") == node_id]
            handles = [edge.get("sourceHandle") for edge in confirmation_edges]
            # Older published flows predate source handles and used one plain
            # outgoing edge as the confirmed path. That shape is unambiguous
            # and is still how the executor's compatibility fallback behaves.
            # Multiple plain/mixed edges remain unsafe and are rejected.
            legacy_confirmed_edge = (
                len(confirmation_edges) == 1 and handles == [None]
            )
            if handles.count("confirmed") != 1 and not legacy_confirmed_edge:
                _node_error(
                    f"Confirmation node '{node_name}' must have exactly one 'confirmed' branch"
                )
            if allow_edit and not edit_prompt:
                _node_error(
                    f"Confirmation node '{node_name}' allows edits but has no edit prompt"
                )
            if not allow_edit and "edit" in handles:
                _node_error(
                    f"Confirmation node '{node_name}' has an edit branch but editing is disabled"
                )
            invalid_handles = any(
                handle not in {"confirmed", "edit"} for handle in handles
            )
            if handles.count("edit") > 1 or (invalid_handles and not legacy_confirmed_edge):
                _node_error(
                    f"Confirmation node '{node_name}' has invalid or duplicate branch sourceHandles"
                )
            template_values.append(confirmation)

        elif node_type == "transfer":
            transfer = node_data.get("transfer", {})
            if not transfer.get("phoneNumber"):
                _node_error(f"Transfer node '{node_name}' has no phone number")

        elif node_type == "set_variable":
            set_var = node_data.get("setVariable", node_data.get("set_variable", {}))
            _require_declared(set_var.get("variableKey", set_var.get("variable_key")), "Set Variable")
            if (
                set_var.get("valueType") == "expression"
                or set_var.get("value_type") == "expression"
            ):
                _node_error(
                    f"Set Variable node '{node_name}' uses the expression type, which is not permitted"
                )
            if set_var.get("valueType", set_var.get("value_type")) == "template":
                template_values.append(set_var.get("value"))

        elif node_type == "save_record":
            save_rec = node_data.get("saveRecord", node_data.get("save_record", {}))
            if not save_rec.get("recordTypeId") and not save_rec.get("record_type_id"):
                _node_error(f"Save Record node '{node_name}' has no record type selected")
            template_values.extend([save_rec.get("mapping"), save_rec.get("status")])

        elif node_type == "capability":
            api_cfg = node_data.get("api", {})
            capability = api_cfg.get("capability")
            if not capability:
                _node_error(f"Capability node '{node_name}' has no capability selected")
            elif capability not in capability_names():
                _node_error(
                    f"Capability node '{node_name}' references an unknown capability "
                    f"'{capability}'"
                )

        elif node_type == "option_picker":
            picker_cfg = node_data.get("optionPicker", {})
            source_variable = picker_cfg.get("sourceVariable")
            if not source_variable:
                _node_error(f"Option Picker node '{node_name}' has no source array variable")
            else:
                _require_declared(source_variable, "Option Picker")
            if not picker_cfg.get("labelPath"):
                _node_error(
                    f"Option Picker node '{node_name}' has no label field configured "
                    "for matching spoken choices"
                )
            writes = picker_cfg.get("writes")
            if not isinstance(writes, list) or not writes:
                _node_error(f"Option Picker node '{node_name}' writes no flow variables")
            else:
                write_keys = []
                malformed_write = False
                for entry in writes:
                    key = entry.get("variableKey") if isinstance(entry, dict) else None
                    if not isinstance(key, str) or not key.strip():
                        malformed_write = True
                        continue
                    write_keys.append(key)
                    _require_declared(key, "Option Picker")
                if malformed_write:
                    _node_error(
                        f"Option Picker node '{node_name}' has a write with no destination variable"
                    )
                if len(set(write_keys)) != len(write_keys):
                    _node_error(
                        f"Option Picker node '{node_name}' writes the same variable more than once"
                    )
            picker_edges = [edge for edge in edges if edge.get("source") == node_id]
            handles = [edge.get("sourceHandle") for edge in picker_edges]
            # A single plain edge with no sourceHandle is treated as the
            # "selected" path (mirrors the confirmation node's legacy-edge
            # compatibility, and the executor's own unlabelled-edge fallback).
            legacy_selected_edge = len(picker_edges) == 1 and handles == [None]
            if handles.count("selected") != 1 and not legacy_selected_edge:
                _node_error(
                    f"Option Picker node '{node_name}' must have exactly one 'selected' branch"
                )
            if handles.count("fallback") > 1:
                _node_error(
                    f"Option Picker node '{node_name}' has more than one 'fallback' branch"
                )
            invalid_handles = any(
                handle not in {"selected", "fallback"} for handle in handles
            )
            if invalid_handles and not legacy_selected_edge:
                _node_error(
                    f"Option Picker node '{node_name}' has an invalid branch sourceHandle"
                )
            template_values.append(picker_cfg)

        for placeholder in sorted(_template_variables(template_values)):
            if placeholder not in declared_variables:
                _node_error(
                    f"Node '{node_name}' template references undeclared variable "
                    f"'{placeholder}'"
                )

    return len(errors) == 0, errors, error_node_ids


def validate_record_type_references(
    db: Session, account_id: str, flow_config: dict
) -> Tuple[List[str], List[str]]:
    """Ensure every SAVE_RECORD node references a record type owned by this account.

    This is a tenant-isolation guard: a flow must never be able to write records
    into another account's record type. Enforced here at save/publish time and
    again at execution time in the flow executor.

    Returns (errors, error_node_ids) tuple.
    """
    errors: List[str] = []
    error_node_ids: List[str] = []
    nodes = flow_config.get("nodes", []) if isinstance(flow_config, dict) else []
    # Map each referenced record-type ID to ALL nodes that reference it, so that
    # when two save_record nodes point to the same invalid record type both IDs
    # are returned (not just the last one that wrote to the dict).
    referenced: dict[str, list[tuple[str, str]]] = {}
    for node in nodes:
        if node.get("type") != "save_record":
            continue
        node_data = node.get("data", {})
        node_name = node_data.get("name", node.get("id"))
        node_id = node.get("id", "")
        save_rec = node_data.get("saveRecord", node_data.get("save_record", {}))
        rt_id = save_rec.get("recordTypeId") or save_rec.get("record_type_id")
        if rt_id:
            referenced.setdefault(str(rt_id), []).append((node_name, node_id))

    if not referenced:
        return errors, error_node_ids

    from botelier.models.record_type import RecordType

    valid_ids = set()
    try:
        rows = (
            db.query(RecordType.id)
            .filter(
                RecordType.account_id == account_id,
                RecordType.id.in_(list(referenced.keys())),
            )
            .all()
        )
        valid_ids = {str(r[0]) for r in rows}
    except Exception:
        # Malformed UUIDs etc. — treat all as invalid below.
        valid_ids = set()

    for rt_id, node_list in referenced.items():
        if rt_id not in valid_ids:
            for node_name, node_id in node_list:
                errors.append(
                    f"Save Record node '{node_name}' references a record type that does "
                    "not exist in this account"
                )
                if node_id:
                    error_node_ids.append(node_id)
    return errors, error_node_ids


@router.get("/{tool_id}/flow")
def get_tool_flow(
    tool_id: str,
    account_id: str,
    source: Optional[str] = None,
    version: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    Get flow configuration for a flow-type tool.
    
    Query Parameters:
        - source: 'draft', 'published', or omit for auto-select (draft if exists, else published)
        - version: Specific version number to fetch (overrides source)
    
    Returns the visual flow editor data (nodes, edges, variables).
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    flow_version = None

    if version is not None:
        flow_version = (
            db.query(FlowVersion)
            .filter(FlowVersion.tool_id == tool_id, FlowVersion.version_number == version)
            .first()
        )
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} not found for this flow",
            )
    elif source == "draft":
        if tool.draft_version_id:
            flow_version = (
                db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()
            )
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No draft exists for this flow"
            )
    elif source == "published":
        if tool.published_version_id:
            flow_version = (
                db.query(FlowVersion).filter(FlowVersion.id == tool.published_version_id).first()
            )
        if not flow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No published version exists for this flow",
            )
    else:
        if tool.draft_version_id:
            flow_version = (
                db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()
            )
        elif tool.published_version_id:
            flow_version = (
                db.query(FlowVersion).filter(FlowVersion.id == tool.published_version_id).first()
            )
        else:
            flow_config = tool.config or {}
            return {
                "tool_id": tool.id,
                "account_id": account_id,
                "name": tool.name,
                "source": "legacy",
                "version_number": 0,
                "has_draft": False,
                "has_published": False,
                "flow_config": {
                    "initial_node": flow_config.get("initial_node"),
                    "nodes": flow_config.get("nodes", []),
                    "edges": flow_config.get("edges", []),
                    "variables": flow_config.get("variables", []),
                },
            }

    return {
        "tool_id": tool.id,
        "account_id": account_id,
        "name": tool.name,
        "source": flow_version.status.value,
        "version_number": flow_version.version_number,
        "version_id": str(flow_version.id),
        "description": flow_version.description,
        "has_draft": tool.draft_version_id is not None,
        "has_published": tool.published_version_id is not None,
        "published_version_number": tool.published_version_number or 0,
        "flow_config": flow_version.flow_config,
    }


@router.put("/{tool_id}/flow/draft")
def save_flow_draft(
    tool_id: str,
    account_id: str,
    draft_data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.edit", db)
    """
    Save flow as a draft.
    
    Creates or updates the draft version. Drafts can be tested in the simulator
    before publishing to production.
    
    Body:
        - flow_config: The flow configuration (nodes, edges, variables)
        - description: Optional description for this version
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    flow_config = draft_data.get("flow_config", {})
    description = draft_data.get("description")

    if flow_config:
        _, draft_errors, _ = validate_flow_config(flow_config)
        expression_errors = [e for e in draft_errors if "expression type" in e]
        if expression_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Flow configuration contains disallowed content",
                    "errors": expression_errors,
                },
            )
        record_ref_errors, _ = validate_record_type_references(db, account_id, flow_config)
        if record_ref_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Flow references an invalid record type",
                    "errors": record_ref_errors,
                },
            )

    draft = None
    if tool.draft_version_id:
        draft = (
            db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()
        )

    if draft:
        # Update the existing draft in place. Its version_number is assigned
        # once (at creation) and must stay stable — reassigning it on every
        # save collided with the uq_tool_version unique constraint and 500ed
        # the save whenever another version already held that number.
        draft.flow_config = flow_config
        draft.description = description
    else:
        # Create a new draft. Derive the next version number from the highest
        # existing version for this tool (not just the published one) so it can
        # never collide with an already-persisted version — mirroring the guard
        # in revert_to_version.
        next_version = (tool.published_version_number or 0) + 1
        max_version = (
            db.query(FlowVersion)
            .filter(FlowVersion.tool_id == tool_id)
            .order_by(desc(FlowVersion.version_number))
            .first()
        )
        if max_version and max_version.version_number >= next_version:
            next_version = max_version.version_number + 1

        draft = FlowVersion(
            id=uuid.uuid4(),
            tool_id=tool_id,
            version_number=next_version,
            status=FlowVersionStatus.DRAFT,
            description=description,
            flow_config=flow_config,
        )
        db.add(draft)
        db.flush()
        tool.draft_version_id = draft.id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Could not save the draft because its version number conflicts "
                "with an existing version. Reload the flow and try again."
            ),
        )
    db.refresh(draft)

    return {
        "tool_id": tool_id,
        "version_id": str(draft.id),
        "version_number": draft.version_number,
        "status": "draft",
        "description": draft.description,
        "message": "Draft saved successfully",
    }


@router.post("/{tool_id}/flow/publish")
def publish_flow(
    tool_id: str,
    account_id: str,
    publish_data: Optional[dict] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.publish", db)
    """
    Publish the current draft as a new version.
    
    The draft becomes immutable and is used for live calls.
    A new draft can be created for future edits.
    
    Body (optional):
        - description: Override or set the version description
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    if not tool.draft_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No draft to publish. Save a draft first.",
        )

    draft = db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()

    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft version not found")

    is_valid, validation_errors, error_node_ids = validate_flow_config(draft.flow_config or {})
    record_ref_errors, ref_error_node_ids = validate_record_type_references(db, account_id, draft.flow_config or {})
    validation_errors = list(validation_errors) + record_ref_errors
    all_error_node_ids = list(dict.fromkeys(error_node_ids + ref_error_node_ids))
    if validation_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Flow validation failed",
                "errors": validation_errors,
                "error_node_ids": all_error_node_ids,
            },
        )

    if publish_data and publish_data.get("description"):
        draft.description = publish_data["description"]

    draft.status = FlowVersionStatus.PUBLISHED
    draft.published_at = datetime.now(timezone.utc)

    tool.published_version_id = draft.id
    tool.published_version_number = draft.version_number
    tool.draft_version_id = None

    tool.config = draft.flow_config

    db.commit()
    db.refresh(draft)

    return {
        "tool_id": tool_id,
        "version_id": str(draft.id),
        "version_number": draft.version_number,
        "status": "published",
        "description": draft.description,
        "published_at": draft.published_at.isoformat(),
        "message": f"Version {draft.version_number} published successfully",
    }


@router.delete("/{tool_id}/flow/draft")
def discard_draft(
    tool_id: str,
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.edit", db)
    """
    Discard the current draft.
    
    Reverts to the last published version for editing.
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    if not tool.draft_version_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No draft to discard")

    draft = db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()

    if draft:
        db.delete(draft)

    tool.draft_version_id = None
    db.commit()

    return {"tool_id": tool_id, "message": "Draft discarded successfully"}


@router.get("/{tool_id}/flow/versions")
def list_flow_versions(
    tool_id: str,
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    List all versions of a flow.
    
    Returns version history without full flow_config (for performance).
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    versions = (
        db.query(FlowVersion)
        .filter(FlowVersion.tool_id == tool_id)
        .order_by(desc(FlowVersion.version_number))
        .all()
    )

    return {
        "tool_id": tool_id,
        "published_version_number": tool.published_version_number or 0,
        "has_draft": tool.draft_version_id is not None,
        "versions": [v.to_summary_dict() for v in versions],
    }


@router.get("/{tool_id}/flow/versions/{version_number}")
def get_flow_version(
    tool_id: str,
    version_number: int,
    account_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.view", db)
    """
    Get a specific version of a flow.
    
    Returns the full flow_config for the requested version.
    """
    _get_flow_tool(db, tool_id, account_id)

    version = (
        db.query(FlowVersion)
        .filter(FlowVersion.tool_id == tool_id, FlowVersion.version_number == version_number)
        .first()
    )

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version_number} not found"
        )

    return version.to_dict()


@router.post("/{tool_id}/flow/versions/{version_number}/revert")
def revert_to_version(
    tool_id: str,
    version_number: int,
    account_id: str,
    revert_data: Optional[dict] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, account_id, "flows.revert", db)
    """
    Revert to a previous version.
    
    Updates the current draft with content from the selected version.
    Does not create a new version number - simply restores the content.
    """
    tool = _get_flow_tool(db, tool_id, account_id)

    source_version = (
        db.query(FlowVersion)
        .filter(FlowVersion.tool_id == tool_id, FlowVersion.version_number == version_number)
        .first()
    )

    if not source_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version_number} not found"
        )

    if tool.draft_version_id:
        existing_draft = (
            db.query(FlowVersion).filter(FlowVersion.id == tool.draft_version_id).first()
        )
        if existing_draft:
            existing_draft.flow_config = source_version.flow_config
            existing_draft.description = f"Restored from version {version_number}"
            tool.config = source_version.flow_config
            db.commit()
            db.refresh(existing_draft)
            return {
                "tool_id": tool_id,
                "version_id": str(existing_draft.id),
                "version_number": existing_draft.version_number,
                "status": existing_draft.status.value,
                "description": existing_draft.description,
                "message": f"Restored content from version {version_number}",
                "flow_config": existing_draft.flow_config,
            }

    next_version = (tool.published_version_number or 0) + 1

    max_version = (
        db.query(FlowVersion)
        .filter(FlowVersion.tool_id == tool_id)
        .order_by(desc(FlowVersion.version_number))
        .first()
    )

    if max_version and max_version.version_number >= next_version:
        next_version = max_version.version_number + 1

    new_draft = FlowVersion(
        id=uuid.uuid4(),
        tool_id=tool_id,
        version_number=next_version,
        status=FlowVersionStatus.DRAFT,
        description=f"Restored from version {version_number}",
        flow_config=source_version.flow_config,
    )
    db.add(new_draft)

    tool.draft_version_id = new_draft.id
    tool.config = source_version.flow_config
    db.commit()
    db.refresh(new_draft)

    return {
        "tool_id": tool_id,
        "version_id": str(new_draft.id),
        "version_number": new_draft.version_number,
        "status": new_draft.status.value,
        "description": new_draft.description,
        "message": f"Restored content from version {version_number}",
        "flow_config": new_draft.flow_config,
    }


@router.put("/{tool_id}/flow")
def update_tool_flow_legacy(
    tool_id: str,
    account_id: str,
    flow_data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Legacy endpoint for saving flow configuration.

    Now saves as a draft for versioning workflow.
    Use PUT /flow/draft for explicit draft saves.
    """
    return save_flow_draft(tool_id, account_id, flow_data, db, user)

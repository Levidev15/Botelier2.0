"""Postman Collection v2.1 spec importer."""

import json
import re
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import IntegrationType

from .utils import (
    build_variable_schema,
    infer_ownership,
    infer_risk_level,
    sanitize_operation_id,
    truncate_spec_endpoints,
)

_MAX_ENDPOINTS = 200


def _extract_items_recursive(items: list, prefix: str = "") -> list[dict]:
    """Flatten Postman collection items (possibly nested folders) into a flat list."""
    result = []
    for item in items or []:
        if "item" in item:
            # Folder — recurse
            folder_name = item.get("name", "")
            result += _extract_items_recursive(
                item["item"], prefix=f"{prefix}/{folder_name}" if prefix else folder_name
            )
        else:
            result.append((item, prefix))
    return result


def _parse_postman_url(url_val) -> tuple[str, list[str]]:
    """Extract path string and path variable names from a Postman URL."""
    if isinstance(url_val, str):
        return url_val, []
    if isinstance(url_val, dict):
        path_parts = url_val.get("path") or []
        raw_path = "/" + "/".join(
            (f"{{{p['value']}}}" if isinstance(p, dict) else str(p)) for p in path_parts
        )
        path_variables = [
            v.get("key") or v.get("id") or ""
            for v in (url_val.get("variable") or [])
        ]
        return raw_path, path_variables
    return "/", []


def import_postman_spec(
    db: Session,
    spec_data: dict,
    account_id: str,
    base_url_override: Optional[str] = None,
    spec_url: Optional[str] = None,
) -> IntegrationType:
    """Import a Postman Collection v2.1 into an IntegrationType row.

    Idempotent: updates existing row for the same account + derived slug.
    """
    info = spec_data.get("info") or {}
    title = info.get("name") or "Imported Postman Collection"

    items_flat = _extract_items_recursive(spec_data.get("item") or [])

    endpoints: list[dict] = []
    for (item, folder_prefix) in items_flat:
        request = item.get("request") or {}
        if not request:
            continue

        method = (request.get("method") or "GET").upper()
        url_val = request.get("url") or {}
        path, path_var_names = _parse_postman_url(url_val)

        name_raw = item.get("name") or ""
        fn_name = sanitize_operation_id(name_raw, method, path)
        description = ""
        if isinstance(request.get("description"), str):
            description = request["description"]

        category = folder_prefix or "general"
        risk_level = infer_risk_level(method, path, [])

        variables: list[dict] = []

        # Query params
        if isinstance(url_val, dict):
            for qp in (url_val.get("query") or []):
                pname = qp.get("key") or ""
                if not pname:
                    continue
                ownership = infer_ownership(pname, "query")
                variables.append(
                    build_variable_schema(pname, {"description": qp.get("description") or ""}, "query", ownership)
                )

        # Path variables
        for pv_name in path_var_names:
            if not pv_name:
                continue
            ownership = infer_ownership(pv_name, "path")
            variables.append(build_variable_schema(pv_name, {}, "path", ownership))

        # Body (raw JSON only)
        body = request.get("body") or {}
        if body.get("mode") == "raw":
            # Can't reliably parse raw body schema — skip variables
            pass

        # Normalize path: convert {param} → {{param}} for IntegrationClient
        normalized_path = re.sub(r"(?<!\{)\{(\w+)\}(?!\})", r"{{\1}}", path)

        # Certified query_params format for IntegrationClient._build_url
        query_params = [
            {
                "key": v["name"],
                "value": "{{" + v["name"] + "}}",
                "required": bool(v.get("required", False)),
            }
            for v in variables
            if v.get("location") == "query" and v.get("ownership") == "llm"
        ]

        endpoints.append({
            "id": f"{method}_{fn_name}",
            "method": method,
            "path": normalized_path,
            "name": fn_name,
            "summary": name_raw[:255],
            "description": description[:1000],
            "category": category,
            "variables": variables,
            "query_params": query_params,
            "body_template": None,
            "risk_level": risk_level,
            "capability": None,
        })

    if not endpoints:
        raise ValueError(
            "No requests found in this Postman collection. The collection has no "
            "items with requests to import — please check that you exported the "
            "full collection (Collection v2.1 format)."
        )

    endpoints, was_truncated = truncate_spec_endpoints(endpoints, _MAX_ENDPOINTS)
    if was_truncated:
        logger.warning(
            "import_postman_spec: collection for account=%s exceeded %d endpoints; truncated.",
            account_id,
            _MAX_ENDPOINTS,
        )

    safe_title = "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_")[:40]
    slug = f"imported_{safe_title}_{str(account_id)[:8]}"

    existing = db.query(IntegrationType).filter(IntegrationType.slug == slug).first()
    it = existing or IntegrationType(id=uuid.uuid4())
    if not existing:
        db.add(it)

    base_url = base_url_override or ""
    postman_auth_config: dict = {"auth_strategy": "bearer"}
    if base_url:
        postman_auth_config["base_url"] = base_url
    it.slug = slug
    it.name = title[:255]
    it.provider = base_url or title[:255]
    it.auth_type = "default"
    it.set_auth_config(postman_auth_config)
    it.set_required_fields([
        {"key": "access_token", "label": "API Token", "type": "password", "storage": "credentials", "required": True}
    ])
    it.set_endpoints(endpoints)
    it.is_enabled = True
    it.origin = "customer_imported"
    it.source_type = "postman"
    # info["schema"] is a full URL (> varchar(64)); extract just the version.
    schema_str = str(info.get("schema") or "")
    version_match = re.search(r"collection/v?([\d.]+)", schema_str)
    it.spec_version = (version_match.group(1) if version_match else (schema_str or "unknown"))[:64]
    it.spec_url = spec_url
    it.created_by_account_id = account_id
    it.raw_spec = {
        "info": info,
        "endpoint_count": len(endpoints),
        "was_truncated": was_truncated,
    }

    db.flush()
    return it

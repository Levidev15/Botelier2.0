"""Spec Importer — Universal API Adapter.

Parses OpenAPI / Swagger / Postman specs into Botelier's integration data
model (``IntegrationType`` + structured ``endpoints_config``).

Usage::

    from botelier.services.spec_importer import import_spec

    integration_type = import_spec(
        db=db,
        spec_data=parsed_json_dict,
        source_type="openapi",
        account_id=account_id,
        base_url_override=None,
    )
"""

from loguru import logger

from .openapi import import_openapi_spec
from .postman import import_postman_spec
from .utils import sanitize_operation_id, infer_risk_level, infer_ownership

_KIND_LABELS = {
    "openapi": "OpenAPI 3.x",
    "swagger": "Swagger 2.x",
    "postman": "Postman Collection",
}


def detect_spec_kind(spec_data) -> str | None:
    """Detect the spec format from its content, ignoring what the user declared.

    Returns:
        ``"openapi"``, ``"swagger"``, ``"postman"``, or ``None`` when the
        content matches none of the supported formats.
    """
    if not isinstance(spec_data, dict):
        return None
    if "openapi" in spec_data:
        return "openapi"
    if "swagger" in spec_data:
        return "swagger"
    info = spec_data.get("info") or {}
    is_postman_info = isinstance(info, dict) and (
        "_postman_id" in info or "postman" in str(info.get("schema") or "").lower()
    )
    if is_postman_info or isinstance(spec_data.get("item"), list):
        return "postman"
    return None


def import_spec(
    db,
    spec_data: dict,
    source_type: str,
    account_id: str,
    base_url_override: str | None = None,
    spec_url: str | None = None,
) -> "IntegrationType":  # noqa: F821
    """Import a spec, dispatching by the format detected from its content.

    The user-declared ``source_type`` is used only for validation/logging: the
    actual content wins. A spec matching none of the supported formats raises
    ``ValueError`` (surfaced as HTTP 400 by the API layer).

    Args:
        db:               SQLAlchemy session.
        spec_data:        Parsed JSON/dict of the spec.
        source_type:      Declared format: ``"openapi"``, ``"swagger"``, or ``"postman"``.
        account_id:       Owner account.
        base_url_override: Override the base URL extracted from the spec.
        spec_url:         Original URL the spec was fetched from (for audit).

    Returns:
        The created or updated ``IntegrationType`` row.

    Raises:
        ValueError: unrecognized spec content, or a spec that parses to zero
        endpoints (both fail closed — nothing is persisted).
    """
    declared = (source_type or "").lower().strip()
    if declared not in ("openapi", "swagger", "postman"):
        raise ValueError(
            f"Unsupported spec source_type: {source_type!r}. Expected openapi, swagger, or postman."
        )

    detected = detect_spec_kind(spec_data)
    if detected is None:
        raise ValueError(
            "This doesn't look like an OpenAPI, Swagger, or Postman spec. "
            "OpenAPI specs have an 'openapi' version field, Swagger specs a 'swagger' "
            "field, and Postman collections an 'info' block with an '_postman_id'. "
            "Please check the file or URL and try again."
        )

    # Content wins over the declared chip — auto-correct silently but log it.
    if detected != declared and not (detected in ("openapi", "swagger") and declared in ("openapi", "swagger")):
        logger.info(
            f"import_spec: declared format {declared!r} but content is "
            f"{_KIND_LABELS[detected]} — using detected format."
        )

    if detected in ("openapi", "swagger"):
        return import_openapi_spec(
            db=db,
            spec_data=spec_data,
            account_id=account_id,
            base_url_override=base_url_override,
            spec_url=spec_url,
        )

    return import_postman_spec(
        db=db,
        spec_data=spec_data,
        account_id=account_id,
        base_url_override=base_url_override,
        spec_url=spec_url,
    )


__all__ = [
    "import_spec",
    "detect_spec_kind",
    "import_openapi_spec",
    "import_postman_spec",
    "sanitize_operation_id",
    "infer_risk_level",
    "infer_ownership",
]

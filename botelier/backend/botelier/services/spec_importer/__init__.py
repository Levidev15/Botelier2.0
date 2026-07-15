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

from .openapi import import_openapi_spec
from .postman import import_postman_spec
from .utils import sanitize_operation_id, infer_risk_level, infer_ownership


def import_spec(
    db,
    spec_data: dict,
    source_type: str,
    account_id: str,
    base_url_override: str | None = None,
    spec_url: str | None = None,
) -> "IntegrationType":  # noqa: F821
    """Dispatch to the correct importer based on ``source_type``.

    Args:
        db:               SQLAlchemy session.
        spec_data:        Parsed JSON/dict of the spec.
        source_type:      ``"openapi"``, ``"swagger"``, or ``"postman"``.
        account_id:       Owner account.
        base_url_override: Override the base URL extracted from the spec.
        spec_url:         Original URL the spec was fetched from (for audit).

    Returns:
        The created or updated ``IntegrationType`` row.
    """
    source_type = (source_type or "").lower().strip()

    if source_type in ("openapi", "swagger"):
        return import_openapi_spec(
            db=db,
            spec_data=spec_data,
            account_id=account_id,
            base_url_override=base_url_override,
            spec_url=spec_url,
        )

    if source_type == "postman":
        return import_postman_spec(
            db=db,
            spec_data=spec_data,
            account_id=account_id,
            base_url_override=base_url_override,
            spec_url=spec_url,
        )

    raise ValueError(f"Unsupported spec source_type: {source_type!r}. Expected openapi, swagger, or postman.")


__all__ = [
    "import_spec",
    "import_openapi_spec",
    "import_postman_spec",
    "sanitize_operation_id",
    "infer_risk_level",
    "infer_ownership",
]

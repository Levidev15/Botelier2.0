"""Spec importer regression tests — format detection, fail-closed empty parse, YAML.

Covers the silent-failure bugs found when a Postman collection URL was imported
with the "Swagger" format selected: the OpenAPI/Swagger parser found no paths
and "successfully" persisted an integration type with zero endpoints.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from botelier.api.integration_builder import _parse_spec_bytes
from botelier.services.spec_importer import detect_spec_kind, import_spec


def _mock_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


ACCOUNT_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f"

OPENAPI3_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Rooms API", "description": "Test"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/rooms": {
            "get": {
                "operationId": "listRooms",
                "summary": "List rooms",
                "parameters": [
                    {"name": "city", "in": "query", "required": True, "schema": {"type": "string"}}
                ],
            }
        }
    },
}

SWAGGER2_SPEC = {
    "swagger": "2.0",
    "info": {"title": "Legacy Rooms API"},
    "host": "api.example.com",
    "basePath": "/v2",
    "schemes": ["https"],
    "paths": {
        "/rooms/{roomId}": {
            "get": {
                "operationId": "getRoom",
                "summary": "Get a room",
                "parameters": [
                    {"name": "roomId", "in": "path", "required": True, "type": "string"},
                    {"name": "expand", "in": "query", "required": False, "type": "string"},
                ],
            }
        }
    },
}

POSTMAN_COLLECTION = {
    "info": {
        "name": "Guestcentric CRS API",
        "_postman_id": "b10e2eaa-091f-4cf0-83ae-decc7c03506b",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "Search hotels",
            "request": {
                "method": "GET",
                "url": {
                    "raw": "https://crs-api.guestcentric.net/search?checkin=2026-01-01",
                    "path": ["search"],
                    "query": [{"key": "checkin", "description": "Check-in date"}],
                },
            },
        }
    ],
}


# ---------------------------------------------------------------------------
# detect_spec_kind
# ---------------------------------------------------------------------------


class TestDetectSpecKind:
    def test_openapi3(self):
        assert detect_spec_kind(OPENAPI3_SPEC) == "openapi"

    def test_swagger2(self):
        assert detect_spec_kind(SWAGGER2_SPEC) == "swagger"

    def test_postman_by_postman_id(self):
        assert detect_spec_kind(POSTMAN_COLLECTION) == "postman"

    def test_postman_by_item_list_only(self):
        assert detect_spec_kind({"info": {"name": "X"}, "item": []}) == "postman"

    def test_unrecognized_json(self):
        assert detect_spec_kind({"message": "page not found"}) is None

    def test_non_dict(self):
        assert detect_spec_kind(["not", "a", "spec"]) is None


# ---------------------------------------------------------------------------
# import_spec — content-based dispatch (the original bug)
# ---------------------------------------------------------------------------


class TestContentBasedDispatch:
    def test_postman_content_with_swagger_declared_imports_postman(self):
        """The exact user scenario: Postman URL imported with 'Swagger' selected.

        Previously this silently created a 0-endpoint 'Imported API' row.
        Now the content wins: the Postman parser runs and endpoints import.
        """
        db = _mock_db()
        it = import_spec(
            db=db,
            spec_data=POSTMAN_COLLECTION,
            source_type="swagger",
            account_id=ACCOUNT_ID,
        )
        assert it.source_type == "postman"
        assert it.name == "Guestcentric CRS API"
        endpoints = it.get_endpoints()
        assert len(endpoints) == 1
        assert endpoints[0]["method"] == "GET"
        # spec_version column is varchar(64): the full schema URL must be
        # reduced to just the version number.
        assert it.spec_version == "2.1.0"
        assert len(it.spec_version) <= 64

    def test_openapi3_imports(self):
        db = _mock_db()
        it = import_spec(
            db=db, spec_data=OPENAPI3_SPEC, source_type="openapi", account_id=ACCOUNT_ID
        )
        assert it.name == "Rooms API"
        assert len(it.get_endpoints()) == 1

    def test_swagger2_with_parameters_imports(self):
        """Regression: swagger2 branch crashed with UnboundLocalError on any
        endpoint with parameters (`variables +=` before assignment)."""
        db = _mock_db()
        it = import_spec(
            db=db, spec_data=SWAGGER2_SPEC, source_type="swagger", account_id=ACCOUNT_ID
        )
        endpoints = it.get_endpoints()
        assert len(endpoints) == 1
        var_names = {v["name"] for v in endpoints[0]["variables"]}
        assert {"roomId", "expand"} <= var_names

    def test_openapi_content_with_postman_declared_imports_openapi(self):
        db = _mock_db()
        it = import_spec(
            db=db, spec_data=OPENAPI3_SPEC, source_type="postman", account_id=ACCOUNT_ID
        )
        assert it.source_type == "openapi"
        assert len(it.get_endpoints()) == 1

    def test_unrecognized_content_rejected(self):
        db = _mock_db()
        with pytest.raises(ValueError, match="doesn't look like"):
            import_spec(
                db=db,
                spec_data={"message": "page not found"},
                source_type="swagger",
                account_id=ACCOUNT_ID,
            )
        db.add.assert_not_called()
        db.flush.assert_not_called()

    def test_invalid_declared_type_rejected(self):
        with pytest.raises(ValueError, match="Unsupported spec source_type"):
            import_spec(
                db=_mock_db(), spec_data=OPENAPI3_SPEC, source_type="wsdl", account_id=ACCOUNT_ID
            )


# ---------------------------------------------------------------------------
# import_spec — fail closed on zero endpoints
# ---------------------------------------------------------------------------


class TestZeroEndpointsFailClosed:
    def test_openapi_no_paths_rejected(self):
        db = _mock_db()
        spec = {"openapi": "3.0.0", "info": {"title": "Empty API"}, "paths": {}}
        with pytest.raises(ValueError, match="No endpoints found"):
            import_spec(db=db, spec_data=spec, source_type="openapi", account_id=ACCOUNT_ID)
        db.add.assert_not_called()
        db.flush.assert_not_called()

    def test_swagger_no_paths_rejected(self):
        spec = {"swagger": "2.0", "info": {"title": "Empty API"}}
        with pytest.raises(ValueError, match="No endpoints found"):
            import_spec(
                db=_mock_db(), spec_data=spec, source_type="swagger", account_id=ACCOUNT_ID
            )

    def test_postman_no_requests_rejected(self):
        db = _mock_db()
        collection = {
            "info": {"name": "Empty", "_postman_id": "x"},
            "item": [{"name": "Folder", "item": []}],
        }
        with pytest.raises(ValueError, match="No requests found"):
            import_spec(
                db=db, spec_data=collection, source_type="postman", account_id=ACCOUNT_ID
            )
        db.add.assert_not_called()
        db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# _parse_spec_bytes — JSON with YAML fallback
# ---------------------------------------------------------------------------


class TestParseSpecBytes:
    def test_json(self):
        assert _parse_spec_bytes(b'{"openapi": "3.0.0"}') == {"openapi": "3.0.0"}

    def test_yaml(self):
        raw = b"openapi: 3.0.0\ninfo:\n  title: YAML API\npaths:\n  /x:\n    get:\n      summary: X\n"
        data = _parse_spec_bytes(raw)
        assert data["openapi"] == "3.0.0"
        assert data["info"]["title"] == "YAML API"
        assert "/x" in data["paths"]

    def test_invalid_both(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_spec_bytes(b"\x00\x01{{{:::not parseable")
        assert exc_info.value.status_code == 400
        assert "neither valid JSON nor valid YAML" in exc_info.value.detail

    def test_non_object_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_spec_bytes(b'["just", "a", "list"]')
        assert exc_info.value.status_code == 400
        assert "must be a JSON or YAML object" in exc_info.value.detail

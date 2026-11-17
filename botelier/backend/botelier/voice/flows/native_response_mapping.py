"""Pure response mapping for native action results and caller visibility."""

from dataclasses import dataclass
from typing import Any

from botelier.services.integration_runtime.jsonpath import extract_json_value
from botelier.services.response_projection import (
    ResponseProjectionError, project_mapped_values, validate_mapped_projection,
)


class NativeResponseMappingError(ValueError):
    """Bounded, payload-free mapping validation/extraction error."""


@dataclass(frozen=True)
class ResponseVariable:
    variable_key: str
    json_path: str
    default_value: Any = None
    has_default: bool = False
    required: bool = True


def resolve_response_variables(
    config, *, variable_declarations=(), mapping_override=None, declared_variables=None,
):
    if not isinstance(config, dict):
        raise NativeResponseMappingError("mapping_config")
    declarations = {}
    for item in variable_declarations or ():
        key = getattr(item, "key", None)
        origin = getattr(item, "origin", None)
        data_method = getattr(item, "data", None)
        if not isinstance(key, str) or origin not in {"explicit", "output"} or not callable(data_method):
            raise NativeResponseMappingError("mapping_declaration")
        data = data_method()
        if not isinstance(data, dict) or data.get("key") != key:
            raise NativeResponseMappingError("mapping_declaration")
        declarations[key] = (origin, data)

    allowed = set(declared_variables) if declared_variables is not None else None
    base = mapping_override or config.get("responseMapping") or {}
    if not isinstance(base, dict) or len(base) > 128:
        raise NativeResponseMappingError("mapping_shape")
    entries = {}
    for key, path in base.items():
        _validate_entry(key, path, allowed)
        entries[key] = ResponseVariable(
            variable_key=key, json_path=path,
            required=_required_for(key, declarations, allowed),
        )

    response_variables = config.get("responseVariables") or []
    if not isinstance(response_variables, list) or len(response_variables) > 128:
        raise NativeResponseMappingError("mapping_shape")
    for item in response_variables:
        if (
            not isinstance(item, dict)
            or set(item) - {"variableKey", "jsonPath", "defaultValue"}
        ):
            raise NativeResponseMappingError("mapping_entry")
        key, path = item.get("variableKey"), item.get("jsonPath")
        _validate_entry(key, path, allowed)
        has_default = "defaultValue" in item and item["defaultValue"] is not None
        entries[key] = ResponseVariable(
            variable_key=key, json_path=path,
            default_value=item.get("defaultValue"), has_default=has_default,
            required=_required_for(key, declarations, allowed),
        )

    if allowed is not None and set(entries) - allowed:
        raise NativeResponseMappingError("mapping_undeclared")
    try:
        validate_mapped_projection(
            config.get("responseProjection"), entries.keys(),
        )
    except ResponseProjectionError:
        raise NativeResponseMappingError("mapping_projection") from None
    return tuple(entries.values())


def map_response_data(response, variables):
    if not isinstance(variables, tuple):
        variables = tuple(variables)
    result = {}
    for variable in variables:
        try:
            value = extract_json_value(response, variable.json_path)
        except (TypeError, ValueError, RecursionError):
            raise NativeResponseMappingError("mapping_path") from None
        if value is None:
            if variable.has_default:
                value = variable.default_value
            elif variable.required:
                raise NativeResponseMappingError("mapping_required_output")
            else:
                continue
        result[variable.variable_key] = value
    return result


def map_project_response(
    config, response, declared_variables=None, *, variable_declarations=(),
):
    variables = resolve_response_variables(
        config,
        variable_declarations=variable_declarations,
        declared_variables=declared_variables,
    )
    mapped = map_response_data(response, variables)
    try:
        projected = project_mapped_values(
            mapped, config.get("responseProjection"),
        )
    except ResponseProjectionError:
        raise NativeResponseMappingError("mapping_projection") from None
    return mapped, projected


def _required_for(key, declarations, allowed):
    if key not in declarations:
        # Legacy callers that pass names only retain strict mapped-output behavior.
        return True if allowed is None else False
    origin, data = declarations[key]
    return origin == "explicit" and data.get("required", True) is True


def _validate_entry(key, path, allowed):
    if (
        not isinstance(key, str) or not key or len(key) > 48
        or not isinstance(path, str) or not path or len(path) > 512
        or "{{" in path or "}}" in path
        or path.strip() in {"$", "$."}
        or allowed is not None and key not in allowed
    ):
        raise NativeResponseMappingError("mapping_entry")


__all__ = [
    "NativeResponseMappingError", "ResponseVariable", "map_project_response",
    "map_response_data", "resolve_response_variables",
]

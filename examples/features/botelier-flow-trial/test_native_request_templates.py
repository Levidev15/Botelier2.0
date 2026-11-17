"""Native action request preparation: values cannot become request structure."""

import importlib
import importlib.util
import json
from urllib.parse import parse_qs, urlsplit

import pytest


def templates():
    name = "botelier.services.request_templates"
    assert importlib.util.find_spec(name) is not None, (
        "Bounded context-aware request template preparation is missing"
    )
    return importlib.import_module(name)


@pytest.mark.parametrize("value", [
    'Guest","admin":true,"other":"value',
    '"\n\\',
    "{{secrets.ADMIN}}",
    "{{other}}",
    "München",
    "<script>not instructions</script>",
])
def test_quoted_json_values_cannot_add_fields_or_expand_another_template(value):
    api = templates()
    result = api.render_json_template(
        '{"name":"{{guest}}","message":"Welcome {{guest}}","enabled":false}',
        {"guest": value, "other": "private"},
    )
    assert result == {"name": value, "message": f"Welcome {value}", "enabled": False}


def test_typed_json_tokens_and_quoted_string_tokens_keep_their_configured_types():
    result = templates().render_json_template(
        '{"count":{{count}},"countAsText":"{{count}}","active":{{active}},'
        '"items":{{rooms}},"optional":{{optional}}}',
        {"count": 2, "active": False, "rooms": [{"id": "r2", "price": 0}], "optional": None},
    )
    assert result == {
        "count": 2, "countAsText": "2", "active": False,
        "items": [{"id": "r2", "price": 0}], "optional": None,
    }


@pytest.mark.parametrize("template,facts", [
    ('{"name":"{{missing}}"}', {}),
    ('{"{{key}}":"value"}', {"key": "admin"}),
    ('{"data":{{value}} trailing}', {"value": 1}),
    ('{"value":"{{secrets.API_KEY}}"}', {"API_KEY": "not a credential"}),
    ('{"value":{{data}}}', {"data": float("nan")}),
    ('{"value":{{data}}}', {"data": object()}),
    ('{"value":"{{obj.property}}"}', {"obj": {"property": "no implicit access"}}),
    ('{"value":{{data}}}', {"data": [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]}),
    ('{"value":{{data}}}', {"data": "x" * 100_001}),
])
def test_invalid_or_unbounded_request_templates_fail_without_payloads(template, facts):
    api = templates()
    with pytest.raises(api.RequestTemplateError) as error:
        api.render_json_template(template, facts)
    assert str(error.value).startswith("request_")
    assert "not a credential" not in str(error.value)
    assert "no implicit access" not in str(error.value)


def test_prepared_body_is_detached_and_exposes_only_its_declared_transport_mode():
    api = templates()
    source = {"items": [{"id": "r2"}]}
    body = api.PreparedRequestBody("json", source)
    source["items"][0]["id"] = "changed"
    exposed = body.value()
    exposed["items"].clear()
    assert body.mode == "json"
    assert body.value() == {"items": [{"id": "r2"}]}
    with pytest.raises(api.RequestTemplateError, match="request_body_mode"):
        api.PreparedRequestBody("executable", {})


def test_url_values_are_encoded_in_path_and_query_without_changing_origin_or_parameters():
    api = templates()
    result = api.render_request_url(
        "https://example.invalid/rooms/{{room}}?guest={{guest}}&literal=keep",
        {"room": "Suite / #1", "guest": "A&B?admin=true"},
    )
    split = urlsplit(result)
    assert (split.scheme, split.netloc, split.fragment) == ("https", "example.invalid", "")
    assert split.path == "/rooms/Suite%20%2F%20%231"
    assert parse_qs(split.query) == {"guest": ["A&B?admin=true"], "literal": ["keep"]}


@pytest.mark.parametrize("url,facts", [
    ("https://{{host}}/rooms", {"host": "evil.invalid"}),
    ("http://example.invalid/rooms", {}),
    ("https://user:password@example.invalid/rooms", {}),
    ("file:///tmp/anything", {}),
    ("https://example.invalid/{{missing}}", {}),
    ("https://example.invalid/{{room}}", {"room": ".."}),
    ("https://example.invalid/rooms#secret", {}),
    ("https://example.invalid/rooms?{{key}}=value", {"key": "admin"}),
])
def test_untrusted_or_insecure_url_shapes_are_rejected(url, facts):
    with pytest.raises(templates().RequestTemplateError, match="request_url"):
        templates().render_request_url(url, facts)


def test_xml_values_are_escaped_and_plain_text_is_literal_without_recursive_interpolation():
    api = templates()
    value = '<tag>" & {{other}}'
    xml = api.render_content_template("<name>{{name}}</name>", {"name": value}, media_type="application/xml")
    assert xml == "<name>&lt;tag&gt;&quot; &amp; {{other}}</name>"
    assert api.render_content_template("Name: {{name}}", {"name": value}, media_type="text/plain") == f"Name: {value}"


def test_prepared_body_preserves_literal_placeholder_looking_provider_values():
    api = templates()
    value = {"name": "{{secrets.ADMIN}}", "zero": 0}
    body = api.PreparedRequestBody("json", value)
    assert json.loads(json.dumps(body.value())) == value


@pytest.mark.parametrize("template", [
    '<root {{name}}="v"/>',
    "<{{name}}>value</{{name}}>",
    '<root name={{name}}/>',
    "<root><!-- {{name}} --></root>",
    "<root><![CDATA[{{name}}]]></root>",
    '<?unsafe {{name}}?><root/>',
])
def test_xml_tokens_in_structural_comment_or_cdata_positions_are_rejected(template):
    with pytest.raises(templates().RequestTemplateError, match="request_xml"):
        templates().render_content_template(
            template, {"name": 'one two="value"'}, media_type="application/xml",
        )


def test_xml_text_and_quoted_attributes_preserve_the_exact_caller_value():
    from xml.etree import ElementTree

    value = 'one" second="two <node> & not a new attribute'
    result = templates().render_content_template(
        '<root name="{{name}}">{{name}}</root>', {"name": value}, media_type="application/xml",
    )
    parsed = ElementTree.fromstring(result)
    assert parsed.attrib == {"name": value}
    assert parsed.text == value

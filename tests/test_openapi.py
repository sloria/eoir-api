from __future__ import annotations

import pytest

from eoir_api.app import create_openapi_config

pytestmark = pytest.mark.anyio


async def test_openapi_json_is_served(client):
    response = await client.get("/schema/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == create_openapi_config().title
    assert "/cases/{a_number}" in spec["paths"]


async def test_healthcheck_not_documented(client):
    spec = (await client.get("/schema/openapi.json")).json()
    assert "/healthz" not in spec["paths"]


async def test_x_key_security_scheme_is_declared(client):
    spec = (await client.get("/schema/openapi.json")).json()
    scheme = spec["components"]["securitySchemes"]["apiKey"]
    assert scheme["type"] == "apiKey"
    assert scheme["name"] == "x-key"
    assert scheme["in"] == "header"
    assert spec["security"] == [{"apiKey": []}]


async def test_case_lookup_documents_success_and_actionable_errors(client):
    spec = (await client.get("/schema/openapi.json")).json()
    responses = spec["paths"]["/cases/{a_number}"]["get"]["responses"]
    assert {"200", "404", "422", "429"} <= set(responses)
    assert "401" not in responses
    assert "503" not in responses


async def test_docs_ui_is_served_at_schema_root(client):
    response = await client.get("/schema")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

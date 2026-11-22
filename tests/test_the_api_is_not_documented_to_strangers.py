"""The generated API documentation is not served.

FastAPI publishes /docs, /redoc and /openapi.json by default, with no sign-in.
The penetration test of 2026-11 read the whole ~190KB schema from QA as a
stranger: every admin and automation route, the dev-mode identity mechanism,
the name of the LLM key variable. They are off unless CITYOS_API_DOCS is set,
and the suite runs without it — so here, as on QA and production, none of the
three answers with the schema.
"""
import pytest


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_no_documentation_route_is_served(client, path):
    r = client.get(path, headers={"X-CityOS-User": ""})
    assert r.status_code != 200 or "openapi" not in r.text.lower(), (path, r.status_code)
    assert "swagger" not in r.text.lower() and "redoc" not in r.text.lower(), path

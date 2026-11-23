from fastapi.testclient import TestClient

from flipdial.app import create_app


def test_healthz():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_security_headers_and_request_id():
    response = TestClient(create_app()).get("/healthz")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert len(response.headers["X-Request-ID"]) == 16


def test_api_docs_disabled():
    assert TestClient(create_app()).get("/docs").status_code == 404

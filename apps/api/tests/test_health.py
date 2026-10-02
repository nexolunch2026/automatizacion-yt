import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.main.ensure_bucket", lambda: None)
    with TestClient(app) as c:
        yield c


def test_health_all_ok(client, monkeypatch):
    monkeypatch.setattr(health, "CHECKS", {name: lambda: None for name in health.CHECKS})
    body = client.get("/health").json()
    assert body["ok"] is True
    assert set(body["services"]) == {"database", "redis", "storage", "worker"}


def test_health_reports_failing_service(client, monkeypatch):
    def broken():
        raise ConnectionError("redis caído")

    checks = {name: lambda: None for name in health.CHECKS}
    checks["redis"] = broken
    monkeypatch.setattr(health, "CHECKS", checks)

    body = client.get("/health").json()
    assert body["ok"] is False
    assert body["services"]["redis"] == {"ok": False, "error": "redis caído"}
    assert body["services"]["database"]["ok"] is True

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import register


def test_pages_require_login(client):
    for url in ["/", "/canales", "/proyectos/nuevo"]:
        r = client.get(url, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/entrar"


def test_register_logs_in(client):
    r = register(client, "Ana")
    assert r.status_code == 200
    assert "Proyectos" in r.text
    assert "ana" in r.text  # el usuario se guarda en minúsculas


def test_only_two_accounts_allowed(client):
    register(client, "ana")
    client.post("/salir")
    register(client, "luis")
    client.post("/salir")

    r = register(client, "intruso")
    assert r.status_code == 403
    assert "Registro cerrado" in r.text
    assert "Crea tu cuenta" not in client.get("/entrar").text


def test_register_validation(client):
    r = client.post(
        "/registro", data={"username": "ana", "password": "corta", "password_confirm": "corta"}
    )
    assert r.status_code == 400
    assert "al menos 8" in r.text

    r = client.post(
        "/registro",
        data={"username": "ana", "password": "contrasena123", "password_confirm": "otra12345"},
    )
    assert "no coinciden" in r.text


def test_login_and_logout(client):
    register(client, "ana", "contrasena123")
    client.post("/salir")
    assert client.get("/", follow_redirects=False).status_code == 303

    r = client.post("/entrar", data={"username": "ana", "password": "mala-clave"})
    assert r.status_code == 400
    assert "incorrectos" in r.text

    r = client.post("/entrar", data={"username": "ANA", "password": "contrasena123"})
    assert r.status_code == 200
    assert "Proyectos" in r.text


def test_session_not_shared_between_browsers(client):
    register(client)
    with TestClient(app) as other:
        assert other.get("/", follow_redirects=False).status_code == 303


def test_version_is_visible(client):
    assert "v0.63.0" in client.get("/entrar").text


def test_port_in_use_detection():
    import socket

    from app.__main__ import port_in_use

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert port_in_use("127.0.0.1", port)
    assert not port_in_use("127.0.0.1", port)

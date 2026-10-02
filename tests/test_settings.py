from app import settings_web
from app.db import SessionLocal
from app.models import Setting
from app.providers.ai import ProviderError


def test_save_valid_key(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_gemini_key", lambda key: "gemini-test")
    r = logged_in.post("/configuracion/gemini", data={"api_key": " AIzaSecreta1234 "})
    assert r.status_code == 200
    assert "Conectado" in r.text
    assert "••••1234" in r.text
    assert "AIzaSecreta1234" not in r.text  # nunca se muestra la clave completa

    with SessionLocal() as db:
        stored = db.get(Setting, "api_key:gemini").value
    assert "AIzaSecreta1234" not in stored  # se guarda cifrada


def test_invalid_key_is_not_saved(logged_in, monkeypatch):
    def reject(key):
        raise ProviderError("La clave de Gemini no es válida.")

    monkeypatch.setattr(settings_web, "check_gemini_key", reject)
    r = logged_in.post("/configuracion/gemini", data={"api_key": "mala"})
    assert r.status_code == 400
    assert "no es válida" in r.text
    assert "Sin conectar" in r.text


def test_delete_key(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_gemini_key", lambda key: "gemini-test")
    logged_in.post("/configuracion/gemini", data={"api_key": "AIzaSecreta1234"})
    r = logged_in.post("/configuracion/gemini/borrar")
    assert "Sin conectar" in r.text


def test_settings_requires_login(client):
    assert client.get("/configuracion", follow_redirects=False).status_code == 303


def test_connection_diagnostics(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_gemini_key", lambda key: "gemini-test")
    logged_in.post("/configuracion/gemini", data={"api_key": "AIzaSecreta1234"})
    seen = {}

    def fake_diagnostics(key, preferred):
        seen["key"] = key
        return [
            {"name": "gemini-2.5-flash — texto", "ok": True, "message": "Funciona"},
            {
                "name": "gemini-2.5-flash — búsqueda de Google",
                "ok": False,
                "message": "Sin cuota",
                "detail": "429 RESOURCE_EXHAUSTED",
            },
        ], "gemini-2.5-flash"

    monkeypatch.setattr(settings_web, "run_diagnostics", fake_diagnostics)
    r = logged_in.post("/configuracion/gemini/probar")
    assert seen["key"] == "AIzaSecreta1234"
    assert "Gemini funciona con el modelo" in r.text
    assert "Modelo en uso: gemini-2.5-flash" in r.text
    assert "Resultado de la prueba" in r.text
    assert "Sin cuota" in r.text
    assert "429 RESOURCE_EXHAUSTED" in r.text


def test_diagnostics_without_key(logged_in):
    r = logged_in.post("/configuracion/gemini/probar")
    assert r.status_code == 400
    assert "Primero guarda una clave" in r.text

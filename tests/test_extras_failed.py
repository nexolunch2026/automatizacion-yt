"""Si algo de lo que se hace después de leer las cifras falla (enlazar vídeos, avisos de
JARVIS), Rendimiento lo dice en vez de quedarse solo en la ventana negra."""

from datetime import datetime

from app import analytics, coach
from app.db import SessionLocal
from tests.test_projects import create_channel

NOW = datetime(2026, 11, 26, 9, 0)


def boom(*args):
    raise RuntimeError("fallo")


def test_a_failing_extra_is_said_and_the_others_still_run(logged_in, monkeypatch):
    calls = []
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    monkeypatch.setattr(analytics, "check_revivals", boom)
    monkeypatch.setattr(coach, "check_missed_publish", lambda db, now: calls.append(now))
    with SessionLocal() as db:
        analytics.refresh(db, NOW)
        assert analytics.extras_failed(db) == ["el aviso de vídeos que vuelven a despertar"]
        assert analytics.get_setting(db, "analytics_last")  # las cifras sí se guardaron
    assert calls == [NOW]  # el siguiente extra sí se hizo
    create_channel(logged_in)
    page = logged_in.get("/rendimiento").text
    assert "algo falló después" in page and "vuelven a despertar" in page


def test_next_good_refresh_clears_it(logged_in, monkeypatch):
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    with SessionLocal() as db:
        monkeypatch.setattr(analytics, "check_revivals", boom)
        analytics.refresh(db, NOW)
        assert analytics.extras_failed(db)
        monkeypatch.setattr(analytics, "check_revivals", lambda db, now=None: 0)
        analytics.refresh(db, NOW)
        assert analytics.extras_failed(db) == []
        analytics.set_setting(db, analytics.EXTRAS_FAILED_KEY, "no es json")
        assert analytics.extras_failed(db) == ["(no se sabe cuáles)"]


def test_a_later_failed_read_hides_the_banner(logged_in, monkeypatch):
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    monkeypatch.setattr(analytics, "check_revivals", boom)
    with SessionLocal() as db:
        analytics.refresh(db, NOW)
        analytics.record_failure(db, RuntimeError("sin internet"), NOW)
    create_channel(logged_in)
    assert "algo falló después" not in logged_in.get("/rendimiento").text

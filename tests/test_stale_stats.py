"""Aviso de cifras paradas: si Rendimiento lleva más de 2 días sin poder leer YouTube,
JARVIS lo dice con el motivo en vez de dar consejos con cifras viejas."""

from datetime import datetime, timedelta

import httpx
import pytest

from app import analytics, assistant, skills
from app.db import SessionLocal
from app.settings_store import get_setting, save_api_key, set_setting

NOW = datetime(2026, 11, 4, 9, 0)
CHANNEL = {
    "subscribers": 8,
    "latest": [
        {"id": "aaaaaaaaaaa", "title": "El error de Kodak", "views": 80, "likes": 9,
         "comments": 2, "published": "2026-10-08"},
    ],
}  # fmt: skip


def http_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/channels")
    return httpx.HTTPStatusError("error", request=request, response=httpx.Response(code))


@pytest.fixture
def youtube(monkeypatch, client):
    """YouTube simulado: `state["error"]` hace fallar la lectura con ese error."""
    state = {"error": None}

    def fetch(db):
        if state["error"] is not None:
            raise state["error"]
        return CHANNEL

    monkeypatch.setattr(analytics, "fetch_videos", fetch)
    with SessionLocal() as db:
        save_api_key(db, "youtube", "AIzaPrueba")
    return state


def fail_from(db, start):
    """Tres intentos fallidos seguidos (cada hora), empezando en `start`."""
    for hours in range(3):
        assert analytics.maybe_refresh(db, start + timedelta(hours=hours))


def link_telegram(db):
    set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')


@pytest.mark.parametrize(
    ("exc", "has_key", "words"),
    [
        (http_error(403), True, "no acepta tu clave"),
        (http_error(400), True, "no acepta tu clave"),
        (http_error(404), False, "no encuentra tu canal"),
        (http_error(403), False, "sin clave"),
        (http_error(429), False, "sin clave"),
        (http_error(503), True, "saturado o caído"),
        (http_error(418), False, "error (418)"),
        (httpx.ConnectError("sin red"), False, "no tiene internet"),
        (httpx.ReadTimeout("lento"), True, "no tiene internet"),
        (ValueError("No se encontró el canal"), False, "no encuentro tu canal"),
        (IndexError("list index out of range"), True, "no devuelve datos de tu canal"),
        (TypeError("raro"), False, "algo que no entiendo"),
    ],
)
def test_failure_reason_in_plain_words(exc, has_key, words):
    assert words in analytics.failure_reason(exc, has_key)


def test_failures_are_recorded_and_cleared_on_success(client, youtube):
    youtube["error"] = httpx.ConnectError("sin red")
    with SessionLocal() as db:
        assert analytics.maybe_refresh(db, NOW)
        assert "no tiene internet" in get_setting(db, "analytics_error")
        assert get_setting(db, "analytics_error_since") == NOW.isoformat()
        # los fallos siguientes no cambian desde cuándo falla, pero sí el motivo
        youtube["error"] = http_error(503)
        assert analytics.maybe_refresh(db, NOW + timedelta(hours=1))
        assert "saturado" in get_setting(db, "analytics_error")
        assert get_setting(db, "analytics_error_since") == NOW.isoformat()
        youtube["error"] = None
        assert analytics.maybe_refresh(db, NOW + timedelta(hours=2))
        assert not get_setting(db, "analytics_error")
        assert not get_setting(db, "analytics_error_since")
        assert analytics.stale_status(db, NOW + timedelta(days=5)) is None


def test_stale_only_after_two_days_of_failures(client, youtube):
    with SessionLocal() as db:
        analytics.refresh(db, NOW - timedelta(days=3))  # aún sin error: última buena
        youtube["error"] = http_error(403)
        fail_from(db, NOW)
        # el PC estuvo apagado 3 días: eso no cuenta; solo cuenta el tiempo fallando
        assert analytics.stale_status(db, NOW + timedelta(days=1)) is None
        status = analytics.stale_status(db, NOW + timedelta(days=2, hours=1))
        assert status["days"] == 2 and "clave" in status["reason"]
        assert status["last"] == NOW - timedelta(days=3)


def test_broken_saved_dates_do_not_crash(client):
    with SessionLocal() as db:
        set_setting(db, "analytics_error", "algo")
        set_setting(db, "analytics_error_since", "no es una fecha")
        assert analytics.stale_status(db, NOW) is None


def test_jarvis_warns_once_per_streak_of_failures(client, youtube):
    with SessionLocal() as db:
        analytics.refresh(db, NOW - timedelta(days=4))
        youtube["error"] = http_error(403)
        fail_from(db, NOW - timedelta(days=3))
        assert assistant.stale_stats_alert(db, NOW) == []  # sin Telegram no avisa
        link_telegram(db)
        [reply] = assistant.stale_stats_alert(db, NOW)
        assert "Las cifras de tu canal están paradas" in reply.text
        assert "3 días" in reply.text and "no acepta tu clave" in reply.text
        assert "desde el 31/10 a las 09:00" in reply.text
        assert reply.buttons == [[("🔄 Probar ahora", "statsretry")]]
        assert assistant.stale_stats_alert(db, NOW + timedelta(minutes=20)) == []  # cada hora
        assert assistant.stale_stats_alert(db, NOW + timedelta(hours=5)) == []  # una vez
        # se arregla y, días después, se vuelve a estropear: avisa otra vez
        youtube["error"] = None
        analytics.refresh(db, NOW + timedelta(hours=6))
        assert assistant.stale_stats_alert(db, NOW + timedelta(hours=8)) == []
        youtube["error"] = httpx.ConnectError("sin red")
        fail_from(db, NOW + timedelta(days=1))
        [again] = assistant.stale_stats_alert(db, NOW + timedelta(days=3, hours=1))
        assert "no tiene internet" in again.text


def test_never_read_numbers_says_so(client, youtube):
    youtube["error"] = httpx.ConnectError("sin red")
    with SessionLocal() as db:
        link_telegram(db)
        fail_from(db, NOW)
        [reply] = assistant.stale_stats_alert(db, NOW + timedelta(days=2))
        assert "Las últimas buenas son nunca" in reply.text


def test_tick_includes_the_alert(client, youtube):
    youtube["error"] = http_error(403)
    with SessionLocal() as db:
        link_telegram(db)
        fail_from(db, NOW)
        texts = [r.text for r in assistant.tick(db, NOW + timedelta(days=2))]
    assert any("están paradas" in t for t in texts)


def test_retry_button_reports_result(client, youtube):
    youtube["error"] = http_error(403)
    with SessionLocal() as db:
        [fail] = assistant._button(db, "statsretry")
        assert "Sigue sin funcionar" in fail.text and "no acepta tu clave" in fail.text
        assert get_setting(db, "analytics_error_since")
        youtube["error"] = None
        [ok] = assistant._button(db, "statsretry")
        assert "ya leí las cifras de 1 vídeos" in ok.text
        assert not get_setting(db, "analytics_error")


def test_performance_answers_warn_about_old_numbers(client, youtube):
    with SessionLocal() as db:
        analytics.refresh(db, NOW - timedelta(days=4))
        assert skills._stale_warning(db) == ""
        youtube["error"] = http_error(403)
        fail_from(db, NOW - timedelta(days=3))
        assert "estas cifras son viejas" in skills._stale_warning(db)
        [reply] = skills._performance(db, None)
        assert reply.text.startswith("⚠️ <b>Ojo: estas cifras son viejas.</b>")
        assert "El error de Kodak" in reply.text


def test_performance_page_shows_the_banner(logged_in, youtube):
    with SessionLocal() as db:
        youtube["error"] = http_error(403)
        fail_from(db, datetime.now() - timedelta(days=3))
    page = logged_in.get("/rendimiento").text
    assert "Las cifras están paradas" in page and "no acepta tu clave" in page


def test_manual_refresh_failure_is_recorded(logged_in, youtube):
    youtube["error"] = httpx.ConnectError("sin red")
    page = logged_in.post("/rendimiento/actualizar").text
    assert "No se pudieron leer las cifras: el ordenador no tiene internet" in page
    with SessionLocal() as db:
        assert "no tiene internet" in get_setting(db, "analytics_error")


def test_one_failure_then_pc_off_is_not_stale(client, youtube):
    with SessionLocal() as db:
        analytics.refresh(db, NOW - timedelta(days=1))
        youtube["error"] = httpx.ConnectError("sin red")
        analytics.maybe_refresh(db, NOW)  # un fallo y se apaga el PC 3 días
        analytics.maybe_refresh(db, NOW + timedelta(days=3))
        assert analytics.stale_status(db, NOW + timedelta(days=3)) is None


def test_any_error_is_recorded_and_retried_later(client, youtube):
    youtube["error"] = RuntimeError("base de datos bloqueada")
    with SessionLocal() as db:
        set_setting(db, "analytics_next", "no es una fecha")  # dato roto: no bloquea
        assert analytics.maybe_refresh(db, NOW)
        assert "no entiendo (RuntimeError)" in get_setting(db, "analytics_error")
        assert get_setting(db, "analytics_next") == (NOW + timedelta(minutes=30)).isoformat()
        assert not analytics.maybe_refresh(db, NOW + timedelta(minutes=5))


def test_link_problems_do_not_count_as_failures(client, youtube, monkeypatch):
    def broken(db):
        raise TypeError("fallo al enlazar")

    monkeypatch.setattr(analytics, "link_projects", broken)
    with SessionLocal() as db:
        assert analytics.refresh(db, NOW) == 1
        assert get_setting(db, "analytics_last") == NOW.isoformat()


def test_key_never_shown_or_logged(logged_in, youtube):
    request = httpx.Request(
        "GET", "https://www.googleapis.com/youtube/v3/channels?key=AIzaSecreta&x=1"
    )
    youtube["error"] = httpx.HTTPStatusError("403 for url " + str(request.url), request=request,
                                             response=httpx.Response(403))  # fmt: skip
    assert "AIzaSecreta" not in analytics.safe_error(youtube["error"])
    response = logged_in.post("/rendimiento/actualizar", follow_redirects=False)
    assert "AIzaSecreta" not in response.headers["location"]
    assert "no acepta tu clave" in logged_in.get(response.headers["location"]).text

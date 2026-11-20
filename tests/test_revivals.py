"""Vídeos viejos que vuelven a despertar: si un vídeo de más de un mes tiene esta semana
muchas más visitas que antes, JARVIS avisa (una vez al mes) para sacarle un Short."""

from datetime import datetime, timedelta

from app import agenda, analytics
from app.db import SessionLocal
from app.models import Video, VideoStat
from app.settings_store import get_setting, set_setting

NOW = datetime(2026, 11, 20, 9, 0)


def video(db, vid, title, days_old, views_by_days_ago):
    published = (NOW - timedelta(days=days_old)).strftime("%Y-%m-%d")
    db.add(Video(video_id=vid, title=title, published=published))
    for days_ago, views in views_by_days_ago.items():
        db.add(VideoStat(video_id=vid, taken_at=NOW - timedelta(days=days_ago), views=views))
    db.commit()


def test_old_video_that_wakes_up_is_said_once(logged_in):
    with SessionLocal() as db:
        # 4 semanas a ~10 por semana y esta semana +300: despierta
        video(db, "despiertaaa", "Kodak: el error", 90, {35: 1000, 7: 1040, 0: 1340})
        video(db, "tranquiloaa", "Nokia", 90, {35: 1000, 7: 1400, 0: 1500})  # su ritmo normal
        video(db, "nuevoaaaaaa", "Polaroid", 10, {7: 0, 0: 900})  # recién publicado: no
        video(db, "pocosaaaaaa", "Yahoo", 90, {35: 10, 7: 10, 0: 40})  # muy pocas visitas
        video(db, "sinhistoria", "Blockbuster", 90, {7: 100, 0: 900})  # sin cifras de antes
        found = analytics.revivals(db, NOW)
        assert [r["video"].video_id for r in found] == ["despiertaaa"]
        assert found[0]["recent"] == 300 and found[0]["before"] == 10
        assert analytics.check_revivals(db, NOW) == 1
        alerts = agenda.unsent_alerts(db, NOW)
        assert len(alerts) == 1 and alerts[0]["kind"] == "milestone"
        text = alerts[0]["text"]
        assert "«Kodak: el error» vuelve a despertar: 300 visitas esta semana" in text
        assert "antes unas 10 por semana" in text and "Short" in text
        assert analytics.check_revivals(db, NOW + timedelta(days=3)) == 0  # ya avisado
        assert analytics.check_revivals(db, NOW + timedelta(days=31)) == 0  # ya no despierta


def test_long_titles_fit_and_bad_saved_list_is_not_fatal(logged_in):
    with SessionLocal() as db:
        video(db, "largoaaaaaa", "X" * 100, 60, {35: 0, 7: 0, 0: 500})
        set_setting(db, analytics.REVIVAL_KEY, "esto no es json")
        assert analytics.check_revivals(db, NOW) == 1
        text = agenda.unsent_alerts(db, NOW)[0]["text"]
        assert len(text) <= 200 and text.endswith("segunda parte") and "antes casi 0" in text
        assert "largoaaaaaa" in get_setting(db, analytics.REVIVAL_KEY)


def test_refresh_checks_revivals(logged_in, monkeypatch):
    calls = []
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    monkeypatch.setattr(analytics, "check_revivals", lambda db, now: calls.append(now))
    with SessionLocal() as db:
        analytics.refresh(db, NOW)
    assert calls == [NOW]


def test_a_failure_does_not_repeat_the_alerts(logged_in, monkeypatch):
    with SessionLocal() as db:
        video(db, "primeroaaaa", "Kodak", 60, {35: 0, 7: 0, 0: 900})
        video(db, "segundoaaaa", "Nokia", 60, {35: 0, 7: 0, 0: 500})
        real, calls = analytics._celebrate, []

        def flaky(db, text, now):
            calls.append(text)
            if len(calls) == 2:
                raise OSError("base de datos bloqueada")
            real(db, text, now)

        monkeypatch.setattr(analytics, "_celebrate", flaky)
        try:
            analytics.check_revivals(db, NOW)
        except OSError:
            pass
        assert analytics.check_revivals(db, NOW + timedelta(hours=1)) == 0  # sin repetir
        assert len(agenda.unsent_alerts(db, NOW)) == 1


def test_missing_days_are_tolerated(logged_in):
    with SessionLocal() as db:
        # PC apagado: fotos de hace 37 y 9 días (no exactamente 35 y 7)
        video(db, "huecosaaaaa", "Kodak", 90, {37: 1000, 9: 1028, 0: 1400})
        found = analytics.revivals(db, NOW)
        assert [r["video"].video_id for r in found] == ["huecosaaaaa"]
        assert found[0]["before"] == 7 and found[0]["recent"] == 289  # por semana

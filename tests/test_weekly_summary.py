import json
from datetime import datetime, timedelta

from app import assistant, weekly_summary
from app.db import SessionLocal
from app.models import Video, VideoStat
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401

SUNDAY = datetime(2026, 10, 11, 10, 0)


def stat(db, vid, days_ago, views):
    db.add(VideoStat(video_id=vid, taken_at=SUNDAY - timedelta(days=days_ago), views=views))


def two_weeks(db):
    db.add(Video(video_id="k", title="Kodak", published="2026-09-01"))
    db.add(Video(video_id="n", title="Nokia", published="2026-10-06"))
    stat(db, "k", 15, 100)  # hace dos semanas
    stat(db, "k", 7, 300)  # hace una semana: +200 la semana anterior
    stat(db, "k", 0, 400)  # hoy: +100
    stat(db, "n", 4, 50)  # vídeo nuevo esta semana
    stat(db, "n", 0, 700)  # +700
    set_setting(db, "subs_history", json.dumps([["2026-10-04", 90], ["2026-10-11", 130]]))
    db.commit()


def linked(db):
    set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')


def test_summary_compares_weeks(logged_in):
    with SessionLocal() as db:
        assert weekly_summary.summary(db, SUNDAY) is None  # sin datos
        two_weeks(db)
        data = weekly_summary.summary(db, SUNDAY)
    assert data["views"] == 800 and data["previous"] == 200
    assert data["best"] == {"title": "Nokia", "views": 700}
    assert data["subs"] == 130 and data["new_subs"] == 40
    assert "Nokia" in weekly_summary.tip(data)


def test_a_worse_week_suggests_a_short():
    data = {"views": 50, "previous": 200, "best": None, "subs": None, "new_subs": None}
    assert "Short" in weekly_summary.tip(data)


def test_less_than_two_weeks_of_data_is_not_compared(logged_in):
    with SessionLocal() as db:
        db.add(Video(video_id="k", title="Kodak", published="2026-10-01"))
        stat(db, "k", 9, 10)
        stat(db, "k", 0, 90)
        db.commit()
        assert weekly_summary.summary(db, SUNDAY) is None


def test_jarvis_sends_it_on_sunday_once(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        two_weeks(db)
        assert assistant.sunday_summary(db, SUNDAY) == []  # sin Telegram vinculado
        linked(db)
        assert assistant.sunday_summary(db, SUNDAY - timedelta(days=1)) == []  # sábado
        assert assistant.sunday_summary(db, SUNDAY.replace(hour=7)) == []  # aún pronto
        reply = assistant.sunday_summary(db, SUNDAY)[0]
        assert "Resumen de la semana" in reply.text and "<b>800</b>" in reply.text
        assert "+300 % frente a la semana anterior" in reply.text
        assert "«Nokia» (+700)" in reply.text and "130 (+40 esta semana)" in reply.text
        assert reply.buttons == [[("📈 Ver rendimiento", "perf")]]
        assert assistant.sunday_summary(db, SUNDAY.replace(hour=20)) == []  # una vez


def test_without_data_jarvis_stays_quiet(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        linked(db)
        assert assistant.sunday_summary(db, SUNDAY) == []


def test_deleted_or_late_tracked_videos_do_not_skew_the_week(logged_in):
    with SessionLocal() as db:
        two_weeks(db)
        db.add(Video(video_id="gone", title="Borrado", published="2026-08-01"))
        stat(db, "gone", 8, 5000)  # ya no tiene fotos nuevas: no resta
        db.add(Video(video_id="old", title="Antiguo", published="2026-06-01"))
        stat(db, "old", 3, 9000)  # se empezó a seguir esta semana: cuenta desde ahí
        stat(db, "old", 0, 9050)
        db.commit()
        data = weekly_summary.summary(db, SUNDAY)
    assert data["views"] == 850  # 100 (Kodak) + 700 (Nokia, nuevo) + 50 (Antiguo)
    assert data["best"]["title"] == "Nokia"


def test_stale_figures_or_old_subscribers_are_not_reported(logged_in):
    with SessionLocal() as db:
        two_weeks(db)
        set_setting(db, "subs_history", json.dumps([["2026-08-01", 10], ["2026-10-11", 130]]))
        data = weekly_summary.summary(db, SUNDAY)
        assert data["subs"] == 130 and data["new_subs"] is None  # sin dato de hace una semana
        set_setting(db, "subs_history", '[["2026-10-11", "x"]]')
        assert weekly_summary.summary(db, SUNDAY)["subs"] is None
        # Si las cifras llevan días sin actualizarse, no hay resumen.
        assert weekly_summary.summary(db, SUNDAY + timedelta(days=3)) is None

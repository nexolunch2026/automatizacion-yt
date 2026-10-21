from datetime import datetime, timedelta

from app import best_day as best_day_module
from app.analytics import video_rows
from app.best_day import best_day
from app.db import SessionLocal
from app.models import Video, VideoStat
from tests.test_strategy_script import make_project


def row(weekday, views, **extra):
    base = {"weekday": weekday, "views_48h": views, "days": 10, "project_id": 1}
    return {**base, "exact_time": True, **extra}


def days(*pairs):
    """[(día, visitas), ...] → filas."""
    return [row(d, v) for d, v in pairs]


def test_needs_enough_videos():
    found = best_day(days((0, 100), (3, 900)), 0)
    assert found["status"] == "few" and "faltan 4 vídeos" in found["text"]
    # No cuentan: Shorts, vídeos sin proyecto (podrían ser Shorts), sin hora exacta,
    # sin cifra de 48 h o demasiado nuevos.
    rows = days(*[(3, 900)] * 5) + [
        row(3, 50, is_short=True),
        row(3, 50, project_id=None),
        row(3, 50, exact_time=False),
        row(1, None),
        row(1, 9, days=1),
    ]
    assert best_day(rows, 0)["status"] == "few"


def test_always_the_same_day_cannot_compare():
    rows = days((0, 100), (0, 120), (0, 90), (0, 95), (3, 900), (3, 800))
    found = best_day(rows, 0)
    assert found["status"] == "one_day" and "prueba otro día" in found["text"]


def test_similar_days_say_keep_going():
    rows = days((0, 100), (0, 110), (0, 90), (3, 105), (3, 120), (3, 95))
    found = best_day(rows, 0)
    assert found["status"] == "same" and found["day"] is None


def test_clear_best_day_is_suggested_as_a_test():
    rows = days((0, 100), (0, 90), (0, 110), (3, 300), (3, 280), (3, 320), (5, 80))
    found = best_day(rows, 0)
    assert found["status"] == "best" and found["day"] == 3
    assert "en jueves" in found["text"] and "prueba a cambiar al jueves" in found["text"]
    assert "Ya publicas ese día" in best_day(rows, 3)["text"]


def test_one_lucky_video_does_not_decide():
    # El martes tiene un vídeo viral: con la mediana no gana por suerte.
    rows = days((0, 100), (0, 100), (0, 90), (1, 5000), (1, 20), (1, 90), (3, 100), (3, 110))
    assert best_day(rows, 0)["day"] != 1


def test_errors_do_not_break_the_week(monkeypatch):
    def broken(db):
        raise RuntimeError("base de datos rota")

    monkeypatch.setattr("app.analytics.video_rows", broken)
    assert best_day_module.advice(None, 0) is None


def add(db, vid, published, views, project_id):
    db.add(Video(video_id=vid, title=vid, published=published, project_id=project_id))
    start = datetime.fromisoformat(published[:16] or "2026-09-01")
    db.add(VideoStat(video_id=vid, taken_at=start + timedelta(hours=47), views=views))
    db.add(VideoStat(video_id=vid, taken_at=start + timedelta(days=5), views=views * 2))


def test_week_page_and_jarvis_show_the_best_day(logged_in):
    from app import assistant, coach

    make_project(logged_in)
    with SessionLocal() as db:
        n = 0
        for day, views in ((7, 100), (14, 90), (21, 110), (10, 400), (17, 380), (24, 420)):
            n += 1  # 7, 14, 21 de septiembre: lunes; 10, 17, 24: jueves
            add(db, f"v{n}", f"2026-09-{day:02d}T12:00", views, 1)
        add(db, "sinfecha", "", 999, 1)  # sin fecha: no se sabe el día
        db.commit()
        rows = {r["video_id"]: r for r in video_rows(db)}
        assert rows["v4"]["weekday"] == 3 and rows["sinfecha"]["weekday"] is None
        coach.set_publish_slot(db, 0, 18)
        text = assistant.week_plan_reply(db).text
    assert "en jueves" in text and "prueba a cambiar al jueves" in text
    page = logged_in.get("/semana").text
    assert "Tu mejor día para publicar" in page and "Publicar los jueves a las 18:00" in page
    logged_in.post("/semana", data={"day": 3, "hour": 18})
    page = logged_in.get("/semana").text
    assert "Ya publicas ese día" in page and "Publicar los jueves a las" not in page


def test_week_page_works_when_analytics_fail(logged_in, monkeypatch):
    def broken(db):
        raise RuntimeError("base de datos rota")

    monkeypatch.setattr("app.analytics.video_rows", broken)
    page = logged_in.get("/semana")
    assert page.status_code == 200 and "Tu mejor día para publicar" not in page.text

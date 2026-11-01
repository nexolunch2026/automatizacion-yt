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
    assert "Tu mejor día y hora para publicar" in page and "Publicar los jueves a las 18:00" in page
    logged_in.post("/semana", data={"day": 3, "hour": 18})
    page = logged_in.get("/semana").text
    assert "Ya publicas ese día" in page and "Publicar los jueves a las" not in page


def test_week_page_works_when_analytics_fail(logged_in, monkeypatch):
    def broken(db):
        raise RuntimeError("base de datos rota")

    monkeypatch.setattr("app.analytics.video_rows", broken)
    page = logged_in.get("/semana")
    assert page.status_code == 200 and "Tu mejor día y hora para publicar" not in page.text


def hrow(hour, views, **extra):
    return row(0, views, hour=hour, **extra)


def test_best_hour_by_bands():
    from app.best_day import best_hour

    rows = [hrow(h, v) for h, v in ((9, 100), (10, 90), (11, 110), (20, 300), (21, 280), (20, 320))]
    found = best_hour(rows, 10)
    assert found["status"] == "best" and found["hour"] == 20 and found["change"]
    assert "por la noche" in found["text"] and "prueba a las 20:00" in found["text"]
    same_band = best_hour(rows, 19)
    assert same_band["status"] == "best" and not same_band["change"]
    assert "Ya publicas en esa franja" in same_band["text"]
    assert best_hour(rows[:3], 10)["status"] == "few"
    one = [hrow(20, v) for v in (100, 120, 90, 95, 130, 110)]
    assert best_hour(one, 20)["status"] == "one_band"
    flat = [hrow(h, v) for h, v in ((9, 100), (10, 110), (11, 90), (20, 105), (21, 120), (20, 95))]
    assert best_hour(flat, 20)["status"] == "same"
    # Sin hora exacta (solo la fecha) no cuenta.
    no_hour = [hrow(None, v) for v in (100,) * 6]
    assert best_hour(no_hour, 20)["status"] == "few"


def test_week_page_and_jarvis_show_the_best_hour(logged_in, monkeypatch):
    from app import analytics, assistant, coach

    pairs = ((9, 100), (10, 90), (11, 110), (20, 400), (21, 380), (20, 420))
    rows = [hrow(h, v, video_id=f"h{i}") for i, (h, v) in enumerate(pairs)]
    monkeypatch.setattr(analytics, "video_rows", lambda db: rows)  # sin depender de la zona
    with SessionLocal() as db:
        coach.set_publish_slot(db, 0, 10)
        text = assistant.week_plan_reply(db).text
    assert "🕒" in text and "por la noche" in text
    page = logged_in.get("/semana").text
    assert "Publicar a las 20:00" in page


def test_hours_use_the_local_offset_of_that_date(logged_in):
    from datetime import UTC

    with SessionLocal() as db:
        add(db, "julio", "2026-07-05T18:00", 100, None)
        db.commit()
        row = next(r for r in video_rows(db) if r["video_id"] == "julio")
    local = datetime(2026, 7, 5, 18, tzinfo=UTC).astimezone()
    assert row["hour"] == local.hour and row["weekday"] == local.weekday()


def test_spread_videos_are_not_called_one_band():
    from app.best_day import best_hour

    rows = [hrow(h, 100) for h in (9, 10, 13, 14, 20, 21, 3, 4)]  # 2 por franja (y madrugada)
    found = best_hour(rows, 20)
    assert found["status"] == "few" and "pocos vídeos en cada franja" in found["text"]

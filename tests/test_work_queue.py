"""Dos vídeos a la vez, a la vista: la cola de trabajo en la portada (qué va ahora, qué va
después, qué espera) y cuánto Gemini gratis lleva gastado hoy cada vídeo."""

from datetime import UTC, datetime, timedelta

from app import jobs, usage
from app.db import SessionLocal
from app.models import Job
from app.settings_store import set_setting
from tests.test_projects import create_channel, project_data


def local(utc_hour, utc_minute=0, day=7):
    moment = datetime(2026, 11, day, utc_hour, utc_minute, tzinfo=UTC)
    return moment.astimezone().replace(tzinfo=None)


def test_quota_day_starts_at_googles_reset():
    assert usage.quota_day(local(8, 4)) == "2026-11-06"  # aún el «día» de ayer
    assert usage.quota_day(local(8, 6)) == "2026-11-07"
    assert usage.quota_day(local(23, 0)) == "2026-11-07"


def test_gemini_calls_are_counted_per_video_and_day(client):
    with SessionLocal() as db:
        now = local(12)
        usage.save(db, 1, "script", {"gemini_calls": 5, "gemini_tokens": 900}, now)
        usage.save(db, 1, "seo", {"gemini_calls": 2}, now)
        usage.save(db, 2, "script", {"gemini_calls": 3}, now)
        usage.save(db, 2, "voice", {"eleven_credits": 40}, now)  # sin Gemini: no cuenta
        assert usage.today_by_project(db, now) == {1: 7, 2: 3}
        assert usage.today_by_project(db, now + timedelta(days=1)) == {}  # otro día, de cero
        set_setting(db, f"usage_day:{usage.quota_day(now)}", '{"1": "x", "dos": 4, "3": 2}')
        assert usage.today_by_project(db, now) == {3: 2}  # datos raros: se ignoran


def make(db, project_id, stage, status="queued", run_after=None, message="", progress=0):
    job = Job(project_id=project_id, stage=stage, status=status, run_after=run_after,
              message=message, progress=progress)  # fmt: skip
    db.add(job)
    db.commit()
    return job


def test_queue_order_and_states(logged_in):
    create_channel(logged_in)
    for topic in ("Kodak", "Bale"):
        logged_in.post("/proyectos/nuevo", data=project_data(topic=topic, title=topic))
    now = datetime.now()
    with SessionLocal() as db:
        db.query(Job).delete()
        make(db, 2, "storyboard", run_after=now + timedelta(hours=5),
             message=jobs.QUOTA_WAIT + " Sigo solo…")  # fmt: skip
        make(db, 1, "voice")
        make(db, 2, "script", status="running", progress=40)
        make(db, 1, "seo", run_after=now + timedelta(minutes=2), message="Google saturado")
        make(db, 2, "seo")
        usage.save(db, 2, "script", {"gemini_calls": 12})
        rows = jobs.queue_overview(db, now)
    assert [(r["title"], r["kind"]) for r in rows] == [
        ("Bale", "now"), ("Kodak", "next"), ("Bale", "next"), ("Kodak", "wait"), ("Bale", "wait"),
    ]  # fmt: skip
    assert rows[0]["state"] == "Trabajando ahora (40 %)" and rows[0]["gemini_today"] == 12
    assert rows[1]["state"] == "Va después" and rows[2]["state"] == "En cola (n.º 3)"
    assert rows[3]["state"].startswith("Reintenta a las")
    assert rows[4]["state"].startswith("Esperando a Gemini hasta el")


def test_numbering_when_nothing_is_running_yet(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.query(Job).delete()
        for stage in ("script", "seo", "voice"):
            make(db, 1, stage)
        states = [r["state"] for r in jobs.queue_overview(db)]
    assert states == ["Le toca ahora", "Va después", "En cola (n.º 3)"]


def test_dashboard_shows_the_queue_only_when_working(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    assert "Cola de trabajo" not in logged_in.get("/").text
    with SessionLocal() as db:
        make(db, 1, "script", status="running", progress=10)
        usage.save(db, 1, "script", {"gemini_calls": 1})
    page = logged_in.get("/").text
    assert "Cola de trabajo" in page and "Trabajando ahora (10 %)" in page
    assert "hoy, 1 llamada a Gemini en sus tareas" in page


def test_home_page_survives_a_broken_queue(logged_in, monkeypatch):
    def broken(db, now=None):
        raise ValueError("dato raro")

    monkeypatch.setattr(jobs, "queue_overview", broken)
    page = logged_in.get("/")
    assert page.status_code == 200 and "Cola de trabajo" not in page.text

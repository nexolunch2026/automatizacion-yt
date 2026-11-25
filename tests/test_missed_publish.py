"""Aviso si no se publicó el día previsto: unas horas después de la hora de publicar, si el
vídeo listo aún no está en YouTube, JARVIS lo recuerda (una vez ese día)."""

from datetime import datetime

from app import agenda, analytics, coach
from app.db import SessionLocal
from app.models import StageResult, Video
from tests.test_projects import create_channel, project_data

THURSDAY_21 = datetime(2026, 11, 26, 21, 0)  # jueves, 3 h después de las 18:00


def ready_video(client):
    create_channel(client)
    client.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="edit", data={"renders": {"final": {}}}))
        db.commit()
        coach.set_publish_slot(db, 3, 18)  # jueves a las 18


def test_reminds_once_on_the_day(logged_in):
    ready_video(logged_in)
    with SessionLocal() as db:
        assert not coach.check_missed_publish(db, datetime(2026, 11, 26, 19, 0))  # muy pronto
        assert not coach.check_missed_publish(db, datetime(2026, 11, 25, 22, 0))  # otro día
        assert coach.check_missed_publish(db, THURSDAY_21)
        text = agenda.unsent_alerts(db, THURSDAY_21)[0]["text"]
        assert text.startswith("Hoy jueves tocaba publicar «Kodak» a las 18:00")
        assert not coach.check_missed_publish(db, THURSDAY_21.replace(hour=22))  # ya avisado


def test_published_or_nothing_ready_says_nothing(logged_in):
    ready_video(logged_in)
    with SessionLocal() as db:
        db.add(Video(video_id="kodaklargoo", title="Kodak", published="2026-11-26",
                     project_id=1))  # fmt: skip
        db.commit()
        assert not coach.check_missed_publish(db, THURSDAY_21)


def test_refresh_checks_it(logged_in, monkeypatch):
    calls = []
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    monkeypatch.setattr(coach, "check_missed_publish", lambda db, now: calls.append(now))
    with SessionLocal() as db:
        analytics.refresh(db, THURSDAY_21)
    assert calls == [THURSDAY_21]


def test_late_hour_unlinked_upload_and_several_ready(logged_in):
    ready_video(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Nokia", title="Nokia"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=2, stage="edit", data={"renders": {"final": {}}}))
        db.commit()
        coach.set_publish_slot(db, 3, 22)
        late = THURSDAY_21.replace(hour=23, minute=30)
        assert coach.check_missed_publish(db, late)  # a las 22 + 3: avisa a las 23
        text = agenda.unsent_alerts(db, late)[0]["text"]
        assert "«Nokia» (y 1 más listos) a las 22:00" in text


def test_a_video_uploaded_today_but_not_linked_stops_it(logged_in):
    ready_video(logged_in)
    with SessionLocal() as db:
        db.add(Video(video_id="otrotitulox", title="Otro título", published="2026-11-26"))
        db.commit()
        assert not coach.check_missed_publish(db, THURSDAY_21)

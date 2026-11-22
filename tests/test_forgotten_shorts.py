"""Shorts preparados sin subir: si el vídeo largo lleva una semana publicado y sus Shorts
no están en YouTube, JARVIS lo recuerda (una vez por semana)."""

import json
from datetime import datetime, timedelta

from app import agenda, analytics, coach
from app.db import SessionLocal
from app.models import Project, StageResult, Video
from tests.test_projects import create_channel, project_data

NOW = datetime(2026, 11, 22, 9, 0)
SHORTS = {"shorts": [{"title": "Kodak y su error"}, {"title": "El día que Kodak lo perdió todo"}]}


def setup(client, days_old=8):
    create_channel(client)
    client.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="shorts", data=SHORTS))
        published = (NOW - timedelta(days=days_old)).strftime("%Y-%m-%d")
        db.add(Video(video_id="largokodak1", title="Kodak: el error", published=published,
                     project_id=1))  # fmt: skip
        db.commit()


def test_shorts_not_on_youtube_are_remembered_once_a_week(logged_in):
    setup(logged_in)
    with SessionLocal() as db:
        db.add(Video(video_id="shortkodak1", title="Kodak y su error #shorts", published=""))
        db.commit()
        found = coach.forgotten_shorts(db, NOW)
        assert len(found) == 1 and found[0]["pending"] == [2] and found[0]["days"] == 8
        assert coach.check_forgotten_shorts(db, NOW) == 1
        text = agenda.unsent_alerts(db, NOW)[0]["text"]
        assert text.startswith("«Kodak» lleva 8 días publicado y tiene 1 Short sin subir")
        assert coach.check_forgotten_shorts(db, NOW + timedelta(days=3)) == 0
        assert coach.check_forgotten_shorts(db, NOW + timedelta(days=8)) == 1  # otra semana


def test_marked_as_uploaded_or_too_new_or_too_old_says_nothing(logged_in):
    setup(logged_in, days_old=3)
    with SessionLocal() as db:
        assert coach.forgotten_shorts(db, NOW) == []  # aún no ha pasado una semana
        assert coach.forgotten_shorts(db, NOW + timedelta(days=60)) == []  # ya es viejo
        later = NOW + timedelta(days=5)
        assert [f["pending"] for f in coach.forgotten_shorts(db, later)] == [[1, 2]]
        coach.mark_short_uploaded(db, 1, 1)
        coach.mark_short_uploaded(db, 1, 2)
        assert coach.forgotten_shorts(db, later) == []


def test_unpublished_long_video_and_refresh_hook(logged_in, monkeypatch):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="shorts", data=SHORTS))
        db.commit()
        assert coach.forgotten_shorts(db, NOW) == []  # sin vídeo largo publicado
    calls = []
    monkeypatch.setattr(analytics, "fetch_videos", lambda db, handle=None: {"latest": []})
    monkeypatch.setattr(coach, "check_forgotten_shorts", lambda db, now: calls.append(now))
    with SessionLocal() as db:
        analytics.refresh(db, NOW)
    assert calls == [NOW]


def test_renamed_shorts_other_projects_and_long_titles(logged_in):
    setup(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Otro", title="Otro"))
    with SessionLocal() as db:
        db.add(Video(video_id="deotroproy", title="Kodak y su error", project_id=2, published=""))
        db.commit()
        assert coach.forgotten_shorts(db, NOW)[0]["pending"] == [1, 2]  # el de otro no cuenta
        db.add(Video(video_id="renombrado", title="Título nuevo", project_id=1, published=""))
        db.commit()
        assert coach.forgotten_shorts(db, NOW)[0]["pending"] == [2]  # uno subido con otro título
        db.get(Project, 1).title = "K" * 150
        db.commit()
        assert coach.check_forgotten_shorts(db, NOW) == 1
        text = agenda.unsent_alerts(db, NOW)[0]["text"]
        assert len(text) <= 200 and text.endswith("márcalo en la pestaña Shorts")


def test_bad_saved_lists_and_future_dates(logged_in):
    from app.settings_store import set_setting

    setup(logged_in)
    with SessionLocal() as db:
        set_setting(db, coach.FORGOTTEN_KEY, '["no es un diccionario"]')
        assert coach.check_forgotten_shorts(db, NOW) == 1
        future = (NOW + timedelta(days=90)).isoformat()
        set_setting(db, coach.FORGOTTEN_KEY, json.dumps({"1": future}))  # reloj cambiado
        assert coach.check_forgotten_shorts(db, NOW) == 1

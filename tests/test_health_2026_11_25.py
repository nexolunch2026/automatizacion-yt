"""Revisión de salud del 25/11/2026.

1. El enlace «por la marca» unía un vídeo VIEJO del canal (publicado antes de crear el
   proyecto) con un proyecto nuevo de la misma marca y lo marcaba «Publicado».
2. El aviso de «no se publicó hoy» se callaba si ese día se subía un Short o un vídeo del
   otro canal."""

from datetime import datetime

from app import analytics, coach
from app.db import SessionLocal
from app.models import Channel, Project, StageResult, Video
from tests.test_projects import create_channel, project_data


def test_old_video_with_the_brand_is_not_linked_to_a_new_project(logged_in):
    create_channel(logged_in)
    logged_in.post(
        "/proyectos/nuevo", data=project_data(topic="NIKE: cómo cayó", title="NIKE: cómo cayó")
    )
    with SessionLocal() as db:
        db.add(
            Video(video_id="nikeviejooo", title="Nike vs Adidas: la guerra", published="2024-03-01")
        )
        db.commit()
        analytics.link_projects(db)
        assert db.get(Video, "nikeviejooo").project_id is None
        assert db.get(Project, 1).status != "Publicado"
        db.add(Video(video_id="nikenuevooo", title="Nike estaba ACABADA",
                     published=datetime.now().strftime("%Y-%m-%d")))  # fmt: skip
        db.commit()
        analytics.link_projects(db)
        assert db.get(Video, "nikenuevooo").project_id == 1  # el nuevo sí


def test_a_short_or_the_other_channel_does_not_silence_the_reminder(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    thursday = datetime(2026, 11, 26, 21, 0)
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="edit", data={"renders": {"final": {}}}))
        db.add(Channel(name="ModoOffside", niche="fútbol", created_by=1))
        db.commit()
        db.add(Project(channel_id=2, title="Bale", topic="Bale", duration="10–15 min",
                       language="Español", video_type="Documental", automation_mode="manual",
                       created_by=1))  # fmt: skip
        db.commit()
        db.add(Video(video_id="unshortaaaa", title="Kodak en 60 s #shorts", published="2026-11-26"))
        db.add(Video(video_id="baledelotro", title="Bale", published="2026-11-26", project_id=2))
        db.commit()
        coach.set_publish_slot(db, 3, 18)
        assert coach.check_missed_publish(db, thursday)


def test_a_hashtag_short_is_never_the_long_video(logged_in):
    create_channel(logged_in)
    logged_in.post(
        "/proyectos/nuevo",
        data=project_data(
            topic="BARBIE: cómo Mattel casi la hunde", title="BARBIE: cómo Mattel casi la hunde"
        ),
    )
    with SessionLocal() as db:
        db.add(Video(video_id="barbieshort", title="Barbie, el secreto que Mattel ocultó #shorts",
                     published=datetime.now().strftime("%Y-%m-%d")))  # fmt: skip
        db.commit()
        analytics.link_projects(db)
        assert db.get(Video, "barbieshort").project_id is None
        assert db.get(Project, 1).status != "Publicado"

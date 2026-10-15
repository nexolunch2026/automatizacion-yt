from datetime import datetime

from app import recycle
from app.db import SessionLocal
from app.models import StageResult, Video, VideoStat
from tests.test_projects import create_channel, project_data


def setup(client, shorts=None):
    create_channel(client)
    for _ in range(2):
        client.post("/proyectos/nuevo", data=project_data())
    with SessionLocal() as db:
        for pid, vid, views in ((1, "aaaaaaaaaaa", 5000), (2, "bbbbbbbbbbb", 300)):
            db.add(
                Video(video_id=vid, title=f"Vídeo {pid}", published="2026-09-01", project_id=pid)
            )
            db.add(VideoStat(video_id=vid, taken_at=datetime(2026, 10, 1), views=views))
            for stage in ("script", "storyboard", "voice"):
                db.add(StageResult(project_id=pid, stage=stage, data={"ok": 1}))
        db.add(Video(video_id="ccccccccccc", title="Sin proyecto", published="2026-09-02"))
        db.add(VideoStat(video_id="ccccccccccc", taken_at=datetime(2026, 10, 1), views=9000))
        if shorts is not None:
            db.add(StageResult(project_id=1, stage="shorts", data=shorts))
        db.commit()


def rows():
    from app import analytics

    with SessionLocal() as db:
        return recycle.suggest(db, analytics.video_rows(db, datetime(2026, 10, 15)))


def test_most_viewed_first_and_only_with_a_project(logged_in):
    setup(logged_in)
    found = rows()
    assert [(r["title"], r["step"]) for r in found] == [("Vídeo 1", "make"), ("Vídeo 2", "make")]
    page = logged_in.get("/rendimiento").text
    assert "Shorts de tus vídeos que ya funcionaron" in page
    assert 'action="/proyectos/1/etapas/shorts"' in page


def test_next_step_is_the_link_then_uploading(logged_in):
    setup(logged_in, shorts={"shorts": [{"title": "S1", "description": "x #a"}]})
    assert rows()[0]["step"] == "link"
    page = logged_in.get("/rendimiento").text
    assert 'action="/proyectos/1/shorts/enlace"' in page
    logged_in.post(
        "/proyectos/1/shorts/enlace",
        data={"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
        follow_redirects=False,
    )
    first = rows()[0]
    assert first["step"] == "upload" and first["shorts"] == 1
    assert "Ver sus Shorts para subirlos" in logged_in.get("/rendimiento").text


def test_only_projects_that_can_make_shorts_and_job_state(logged_in):
    from app.models import Job, Project

    setup(logged_in)
    with SessionLocal() as db:
        db.get(Project, 2).duration = "Short"  # ya es un Short: no se ofrece
        db.add(Job(project_id=1, stage="shorts", status="running", message=""))
        db.commit()
    assert [(r["title"], r["step"]) for r in rows()] == [("Vídeo 1", "working")]
    assert "Haciendo sus Shorts" in logged_in.get("/rendimiento").text
    with SessionLocal() as db:
        db.query(Job).update({"status": "failed"})
        db.commit()
    assert rows()[0]["step"] == "failed"
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="shorts", data={"shorts": [], "note": "corto"}))
        db.commit()
    assert rows() == []  # ya se intentó y no da para Shorts


def test_projects_missing_stages_are_skipped(logged_in):
    setup(logged_in)
    with SessionLocal() as db:
        db.query(StageResult).filter_by(project_id=1, stage="storyboard").delete()
        db.commit()
    assert [r["title"] for r in rows()] == ["Vídeo 2"]

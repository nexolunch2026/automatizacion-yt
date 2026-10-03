import imageio_ffmpeg

from app import assistant, jobs
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.pipeline import shorts
from tests.test_thumbnail import make_video_project


def rows(seconds):
    return [
        {"n": i + 1, "id": f"p{i + 1}", "text": "texto", "seconds": s, "kind": ""}
        for i, s in enumerate(seconds)
    ]


def test_fit_keeps_shorts_between_limits():
    table = rows([10, 10, 10, 10, 10, 10, 10])
    assert shorts._fit(table, 1, 1) == (1, 2)  # crece hasta pasar los 18 s
    assert shorts._fit(table, 1, 7) == (1, 5)  # y no pasa de 58 s
    assert shorts._fit(rows([70]), 1, 1) is None  # un párrafo larguísimo no sirve


def test_choose_segments_without_ai_prefers_numbers_and_questions():
    table = rows([12] * 12)
    table[6]["text"] = "¿Cómo perdió 63.000 millones en 2001?"
    picks = shorts.choose_segments(None, {}, table, None, 2)
    assert len(picks) == 2
    assert any(p.start <= 7 <= p.end for p in picks)
    spans = [set(range(p.start, p.end + 1)) for p in picks]
    assert not spans[0] & spans[1]


def test_how_many():
    assert shorts.how_many(60) == 1 and shorts.how_many(180) == 2 and shorts.how_many(700) == 3


def test_pipeline_makes_vertical_shorts(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "shorts")
    short = data["shorts"][0]
    assert short["title"] == "Así cayó Enron" and "#shorts" in short["description"]
    path = project_dir(1) / short["file"]
    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)
    reader.close()
    width, height = meta["size"]
    assert height > width  # vertical

    page = logged_in.get("/proyectos/1/shorts").text
    assert "Así cayó Enron" in page and "Alta calidad" in page

    logged_in.post("/proyectos/1/etapas/shorts", data={"quality": "final"})
    with SessionLocal() as db:
        assert jobs.latest_jobs(db, 1)["shorts"].params == {"quality": "final"}


def test_shorts_reach_telegram(logged_in, monkeypatch):
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=42, text=assistant.link_code(db)))
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        replies = assistant.tick(db)
    notice = next(r for r in replies if "Shorts listos" in r.text)
    assert notice.video.name == "video-preview.mp4" and notice.video.exists()


def test_short_projects_do_not_make_shorts(logged_in, monkeypatch):
    from app.models import Project
    from app.providers.ai import ProviderError

    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.duration = "Short"
        db.commit()
        try:
            jobs.RUNNERS["shorts"](db, project, lambda p, m: None, {})
            raise AssertionError("debería fallar")
        except ProviderError as exc:
            assert "ya es un Short" in str(exc)

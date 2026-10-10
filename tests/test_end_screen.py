from datetime import datetime

from app.db import SessionLocal
from app.models import Project, Video, VideoStat
from app.pipeline.end_screen import closing_line, suggest, words
from tests.test_seo import result, with_script  # noqa: F401
from tests.test_storyboard_voice import ai  # noqa: F401
from tests.test_strategy_script import run_all


def add(db, video_id, title, views=None, published="2026-09-01", project_id=None):
    db.add(Video(video_id=video_id, title=title, published=published, project_id=project_id))
    if views is not None:
        db.add(VideoStat(video_id=video_id, taken_at=datetime(2026, 10, 1), views=views))


def test_words_ignore_small_and_common_ones():
    assert words("La caída de Nokia: la marca que dominó") == {"nokia", "domino"}


def test_related_and_most_viewed(with_script):  # noqa: F811
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.topic, project.title = "La caída de Nokia y los móviles", ""
        add(db, "own", "Nokia: mi propio vídeo", 900, project_id=1)  # el de este proyecto no
        add(db, "bb", "Blockbuster contra Netflix", 5000)
        add(db, "bb2", "Motorola y los móviles que se quedaron atrás", 120)
        db.commit()
        picks = suggest(db, project)
    assert [p["title"] for p in picks] == [
        "Motorola y los móviles que se quedaron atrás",
        "Blockbuster contra Netflix",
    ]
    assert "tema parecido" in picks[0]["reason"] and "5.000" in picks[1]["reason"]
    assert picks[1]["url"] == "https://youtu.be/bb"
    assert "Blockbuster contra Netflix" in picks[1]["line"]


def test_without_stats_or_similar_topics_the_newest(with_script):  # noqa: F811
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.topic = "Telepizza"
        add(db, "a", "Kodak", published="2026-08-01")
        add(db, "b", "Nokia", published="2026-09-20")
        db.commit()
        picks = suggest(db, project)
    assert [(p["title"], p["reason"]) for p in picks] == [("Nokia", "Es tu vídeo más reciente.")]


def test_publish_page_shows_the_end_screen(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Pantalla final" in page and "Cuando tengas vídeos publicados" in page
    with SessionLocal() as db:
        add(db, "zz", "Kodak: la foto que no vio venir", 300)
        db.commit()
    page = with_script.get("/proyectos/1/publicacion").text
    assert "youtu.be/zz" in page and 'id="final-1"' in page
    assert closing_line("Kodak: la foto que no vio venir") in page


def test_two_picks_when_the_related_one_is_also_the_most_viewed(with_script):  # noqa: F811
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.topic, project.title = "Nokia", ""
        add(db, "n", "Nokia: el final", 9000)
        add(db, "k", "Kodak", 400)
        add(db, "x", "Sin fecha", published="")
        db.commit()
        picks = suggest(db, project)
    assert [p["title"] for p in picks] == ["Nokia: el final", "Kodak"]


def test_no_dates_no_stats_no_match_means_no_guess(with_script):  # noqa: F811
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.topic = "Telepizza"
        add(db, "x", "Kodak", published="")
        db.commit()
        assert suggest(db, project) == []

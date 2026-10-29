from app.db import SessionLocal
from app.models import Project
from app.pipeline.end_screen import TEASER_CHARS, _teaser, card
from tests.test_end_screen import add
from tests.test_seo import result, with_script  # noqa: F401
from tests.test_storyboard_voice import ai  # noqa: F401
from tests.test_strategy_script import run_all

FILLER = " ".join(["palabra"] * 75)  # 30 s de narración


def script(*texts):
    paragraphs = [{"id": f"p{i}", "text": t} for i, t in enumerate(texts)]
    return {"sections": [{"kind": "development", "title": "", "paragraphs": paragraphs}]}


def test_card_goes_where_the_script_talks_about_another_video(with_script):  # noqa: F811
    s = script(
        FILLER, FILLER, FILLER, "Igual que Motorola con sus móviles. " + FILLER, *[FILLER] * 4
    )
    with SessionLocal() as db:
        project = db.get(Project, 1)
        add(db, "own", "Motorola: este mismo vídeo", 900, project_id=1)  # el propio no
        add(db, "bb", "Blockbuster contra Netflix", 5000)
        add(db, "mo", "Motorola y los móviles que se quedaron atrás", 120)
        db.commit()
        found = card(db, project, s, None)
    assert found["title"] == "Motorola y los móviles que se quedaron atrás"
    assert found["time"].startswith("1:") and "«motorola»" in found["reason"]
    assert found["url"] == "https://youtu.be/mo" and not found["exact"]


def test_without_a_similar_topic_mid_video_with_the_most_viewed(with_script):  # noqa: F811
    s = script(*[FILLER] * 10)  # unos 5 minutos
    with SessionLocal() as db:
        project = db.get(Project, 1)
        add(db, "bb", "Blockbuster contra Netflix", 5000)
        add(db, "no", "Nokia y los teléfonos", 30)
        db.commit()
        found = card(db, project, s, None)
    assert found["title"] == "Blockbuster contra Netflix" and "más visitas" in found["reason"]
    assert found["time"].startswith("2:")


def test_one_common_word_is_not_a_similar_topic_and_no_views_says_newest(with_script):  # noqa: F811
    s = script(FILLER, FILLER, "El mundo cambió. " + FILLER, *[FILLER] * 7)
    with SessionLocal() as db:
        project = db.get(Project, 1)
        add(db, "mu", "Cómo el mundo dejó de usar carretes", published="2026-08-01")
        add(db, "nu", "Nokia y los teléfonos", published="2026-09-20")
        db.commit()
        found = card(db, project, s, None)
    assert "mitad" in found["reason"] and "más reciente" in found["reason"]
    assert found["title"] == "Nokia y los teléfonos"


def test_exact_only_when_every_paragraph_is_recorded(with_script):  # noqa: F811
    s = script(*[FILLER] * 10)
    takes = [{"paragraph_id": f"p{i}", "seconds": 30} for i in range(10)]
    with SessionLocal() as db:
        project = db.get(Project, 1)
        add(db, "bb", "Blockbuster contra Netflix", 5000)
        db.commit()
        assert card(db, project, s, {"takes": takes})["exact"]
        assert not card(db, project, s, {"takes": takes[:5]})["exact"]


def test_no_card_without_videos_or_for_short_scripts(with_script):  # noqa: F811
    with SessionLocal() as db:
        project = db.get(Project, 1)
        assert card(db, project, script(*[FILLER] * 10), None) is None  # sin vídeos
        add(db, "bb", "Blockbuster contra Netflix", 5000)
        db.commit()
        assert card(db, project, script(FILLER), None) is None  # 30 s: muy corto
        assert card(db, project, None, None) is None


def test_teaser_fits_in_a_youtube_card():
    assert _teaser("Blockbuster contra Netflix") == "Blockbuster contra Netflix"
    long = _teaser("Motorola y los móviles que se quedaron atrás para siempre")
    assert len(long) <= TEASER_CHARS and long.endswith("…")
    assert len(_teaser("x" * 50)) <= TEASER_CHARS


def test_publish_page_shows_the_card(with_script, monkeypatch):  # noqa: F811
    from app.pipeline import end_screen

    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Tarjeta a mitad del vídeo" in page

    def broken(*args):
        raise KeyError("paragraphs")

    monkeypatch.setattr(end_screen, "card", broken)
    page = with_script.get("/proyectos/1/publicacion")
    assert page.status_code == 200 and "No pude calcular el minuto" in page.text

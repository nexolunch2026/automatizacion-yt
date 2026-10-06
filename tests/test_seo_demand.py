from app import demand, music_rights
from app.db import SessionLocal
from app.pipeline.seo import search_demand
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all

SUGGESTIONS = [
    "caso enron documental",
    "enron explicado",
    "enron la quiebra",
    "caso enron resumen",
    "recetas faciles",  # no habla del tema: se descarta
]


def test_search_demand_filters_and_checks_the_title():
    found = search_demand("caso Enron", "El caso Enron: la gran mentira", lambda t: SUGGESTIONS)
    assert found["keyword"] == "caso Enron" and found["level"] == "media"
    assert "recetas faciles" not in found["suggestions"] and len(found["suggestions"]) == 4
    assert found["title_has_keyword"]
    other = search_demand("caso Enron", "La mentira más cara de la historia", lambda t: [])
    assert not other["title_has_keyword"] and other["suggestions"] == []
    assert search_demand("", "x", None)["suggestions"] == []


def test_publish_uses_real_searches(with_script, monkeypatch):  # noqa: F811
    def suggest(term, language="es"):
        return [f"{term.lower()} documental", f"{term.lower()} explicado", "recetas faciles"]

    monkeypatch.setattr(demand, "fetch", suggest)
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    seo = result("publish")
    first = "empresas que desaparecieron misteriosamente documental"
    assert seo["tags"][0] == first  # lo que se busca, primero (sin la que no viene al caso)
    assert "recetas faciles" not in seo["tags"]
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Lo que busca la gente" in page and f"«{first}»" in page
    assert "El título no usa las palabras que busca la gente" in page


def test_publish_without_internet_still_works(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    seo = result("publish")
    assert seo["tags"][0] == "Enron" and seo["searches"]["suggestions"] == []
    assert "No pude ver las búsquedas" in with_script.get("/proyectos/1/publicacion").text


def test_music_credit_reaches_the_description(with_script):  # noqa: F811
    from app import jobs
    from app.models import Project, StageResult

    with SessionLocal() as db:
        db.add(
            StageResult(
                project_id=1,
                stage="edit",
                data={"last": "preview", "renders": {"preview": {"music": "noche.mp3"}}},
            )
        )
        db.commit()
        music_rights.save(db, "noche.mp3", "cc_by", "«Noche» de Ana, CC BY 4.0")
        assert db.get(Project, 1) and jobs.get_result(db, 1, "edit")
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    assert "Música: «Noche» de Ana, CC BY 4.0" in result("publish")["description"]

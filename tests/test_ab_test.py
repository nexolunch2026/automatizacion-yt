from app.pipeline.ab_test import ab_plan, similarity
from tests.test_seo import result, with_script  # noqa: F401
from tests.test_storyboard_voice import ai  # noqa: F401
from tests.test_strategy_script import run_all

STRATEGY = {
    "selected": {"concept": 0, "title": 0},
    "concepts": [
        {
            "titles": [
                {"title": "Kodak inventó el futuro y lo escondió", "style": "curiosidad",
                 "reason": "Contradicción que intriga."},
                {"title": "El error de 1975 que hundió a Kodak", "style": "conflicto",
                 "reason": "Un año concreto da credibilidad."},
            ]
        }
    ],
}  # fmt: skip
THUMBS = {
    "variants": [
        {"file": "miniatura-1.jpg", "text": "LO ESCONDIÓ"},
        {"file": "miniatura-2.jpg", "text": "1975"},
        {"file": "miniatura-3.jpg", "text": "Kodak inventó futuro"},
    ]
}


def test_similarity():
    assert similarity("La caída de Nokia", "La caída de Nokia explicada") == 1.0
    assert similarity("La caída de Nokia", "El error de Kodak") == 0.0


def test_plan_takes_three_distinct_titles_with_their_reasons():
    seo = {
        "titles": [
            "Kodak inventó el futuro y lo escondió",
            "Kodak inventó el futuro y lo escondió",  # repetido: no cuenta
            "El error de 1975 que hundió a Kodak",
            "¿Por qué Kodak no supo cambiar? La historia completa de una caída anunciada",
            "Otro más",
        ]
    }
    plan = ab_plan(seo, STRATEGY, THUMBS)
    assert [t["text"][:10] for t in plan["titles"]] == ["Kodak inve", "El error d", "¿Por qué K"]
    assert plan["titles"][0]["style"] == "curiosidad" and plan["titles"][1]["reason"]
    assert plan["titles"][2]["too_long"]
    assert any("se corta" in w for w in plan["warnings"])
    assert plan["ready"]


def test_plan_warns_about_twin_titles_and_thumbnails_that_repeat_the_title():
    seo = {"titles": ["Kodak inventó el futuro", "El futuro que Kodak inventó"]}
    plan = ab_plan(seo, None, THUMBS)
    assert any("se parecen demasiado" in w for w in plan["warnings"])
    repeated = [t["text"] for t in plan["thumbs"] if t["repeats_title"]]
    assert repeated == ["Kodak inventó futuro"]


def test_plan_without_data():
    plan = ab_plan(None, None, None)
    assert plan == {"titles": [], "thumbs": [], "warnings": [], "ready": False}


def test_publish_page_shows_the_ab_card(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Probar y comparar" in page and 'id="ab-titulo-1"' in page
    assert "Haz las miniaturas" in page  # aún no hay miniaturas

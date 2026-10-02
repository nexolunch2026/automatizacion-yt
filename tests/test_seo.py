import pytest

from app.pipeline.seo import (
    build_chapters,
    build_description,
    clean_hashtags,
    clean_tags,
    format_time,
)
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def section(kind, title, *texts):
    return {
        "kind": kind,
        "title": title,
        "paragraphs": [{"id": f"{title}-{i}", "text": t} for i, t in enumerate(texts)],
    }


def words(n):
    return " ".join(["palabra"] * n)


def test_format_time():
    assert (
        format_time(5) == "0:05" and format_time(75.9) == "1:15" and format_time(3725) == "1:02:05"
    )


def test_chapters_follow_youtube_rules():
    script = {
        "sections": [
            section("hook", "Gancho", words(20)),
            section("promise", "Promesa", words(15)),
            section("intro", "Intro", words(40)),
            section("development", "El origen", words(150)),
            section("development", "La caída", words(150)),
            section("climax", "El final", words(80)),
            section("cta", "Suscríbete", words(10)),
        ]
    }
    chapters = build_chapters(script, None)
    assert chapters[0] == (0.0, "Introducción")
    assert [title for _, title in chapters] == ["Introducción", "El origen", "La caída", "El final"]
    assert all(b[0] - a[0] >= 10 for a, b in zip(chapters, chapters[1:], strict=False))


def test_chapters_use_real_voice_times():
    script = {
        "sections": [
            section("hook", "G", "Hola."),
            section("development", "A", "x"),
            section("development", "B", "y"),
            section("climax", "C", "z"),
        ]
    }
    voice = {
        "takes": [
            {"paragraph_id": "G-0", "seconds": 12.0},
            {"paragraph_id": "A-0", "seconds": 20.0},
            {"paragraph_id": "B-0", "seconds": 30.0},
            {"paragraph_id": "C-0", "seconds": 15.0},
        ]
    }
    chapters = build_chapters(script, voice)
    assert [round(t, 2) for t, _ in chapters] == [0.0, 12.35, 32.7, 63.05]


def test_too_few_chapters_are_omitted():
    script = {"sections": [section("hook", "G", words(10)), section("development", "A", words(10))]}
    assert build_chapters(script, None) == []


def test_short_sections_merge_into_previous():
    script = {
        "sections": [
            section("hook", "G", words(40)),
            section("development", "A", words(5)),
            section("development", "B", words(60)),
            section("climax", "C", words(60)),
            section("conclusion", "D", words(60)),
        ]
    }
    titles = [t for _, t in build_chapters(script, None)]
    assert "B" not in titles or "A" in titles  # A empieza muy cerca de 0:00 y no puede ir sola
    assert titles[0] == "Introducción"


def test_description_has_chapters_sources_credits_and_limit():
    research = {
        "sources": [
            {"n": 1, "title": "Wikipedia: Enron", "uri": "https://es.wikipedia.org/wiki/Enron"}
        ]
    }
    text = build_description(
        "Intro.",
        [(0, "Introducción"), (65, "La caída"), (130, "Final")],
        research,
        "Imágenes y vídeos:\n- Ana (Pexels): https://x",
        ["#Enron"],
        True,
    )
    assert "0:00 Introducción\n1:05 La caída\n2:10 Final" in text
    assert "Wikipedia: Enron: https://es.wikipedia.org/wiki/Enron" in text
    assert "generadas con IA" in text and text.endswith("#Enron")
    assert len(build_description("x" * 6000, [], {}, "", [], False)) < 5000


def test_clean_tags_and_hashtags():
    assert clean_tags(["Enron", "enron", "quiebras, empresas", "#doc", ""]) == [
        "Enron",
        "quiebras  empresas",
        "doc",
    ]
    assert clean_tags(["x" * 300, "y" * 300]) == ["x" * 300]  # máximo 500 caracteres
    assert clean_hashtags(["#Enron", "documental empresas", "#Negocios", "#extra"]) == [
        "#Enron",
        "#documentalempresas",
        "#Negocios",
    ]


def test_publish_page_end_to_end(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    seo = result("publish")
    assert seo["titles"][0] == "Título 0-0"  # el elegido va primero, sin repetirse
    assert seo["titles"].count("Título 0-0") == 1
    assert seo["tags"][0] == "Enron" and seo["hashtags"] == [
        "#Enron",
        "#documentalempresas",
        "#Negocios",
    ]
    assert not seo["chapters_exact"]  # todavía no hay voz
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Copiar descripción" in page and "¿Crees que se pudo evitar?" in page
    assert "Los minutos de los capítulos son aproximados" in page


@pytest.fixture(autouse=True)
def _ai(ai):  # noqa: F811
    return ai

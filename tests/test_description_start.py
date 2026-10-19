from types import SimpleNamespace

from app.pipeline.monetization import _publish_checks
from app.pipeline.seo import PREVIEW_CHARS, description_preview, description_start
from tests.test_seo import _ai  # noqa: F401
from tests.test_storyboard_voice import ai, with_script  # noqa: F401
from tests.test_strategy_script import run_all

LONG = "Kodak inventó la cámara digital en 1975 y la guardó en un cajón. " * 5


def test_preview_cuts_by_word_like_youtube_search():
    preview = description_preview(LONG)
    assert len(preview) <= PREVIEW_CHARS + 1 and preview.endswith("…")
    assert not preview[:-1].endswith(" ")
    assert description_preview("Corta.\n\nOtra línea.") == "Corta. Otra línea."


def test_brand_or_keyword_in_the_first_lines_is_ok():
    assert description_start(LONG, "", ["kodak"])["ok"]
    intro = "La historia de la mayor quiebra de su época, contada paso a paso. " * 3
    no_brand = intro + LONG
    assert description_start(no_brand, "", ["kodak"])["ok"] is False  # Kodak sale tarde
    assert description_start(no_brand, "mayor quiebra", [])["ok"]  # sí sale lo que se busca
    assert not description_start("La caída de una marca.", "marca famosa", [])["ok"]


def test_brand_without_accents_and_whole_word():
    assert description_start("Así cayó Telefónica en Bolsa.", "", ["telefonica"])["ok"]
    assert not description_start("Los seatbelts salvan vidas.", "", ["seat"])["ok"]


def test_description_starting_with_links_or_hashtags_warns():
    found = description_start("#Kodak #documental", "", ["kodak"])
    assert found["starts_badly"] and not found["ok"]
    assert not description_start("https://kodak.com Kodak cayó.", "", ["kodak"])["ok"]
    assert not description_start("0:00 Intro\n1:20 Kodak", "", ["kodak"])["ok"]
    assert not description_start("www.kodak.com Kodak cayó.", "", ["kodak"])["ok"]


def test_unknown_when_there_is_nothing_to_compare():
    unknown = {"preview": "", "ok": None, "starts_badly": False}
    assert description_start("", "kodak", ["kodak"]) == unknown
    assert description_start(None, None, ["kodak"]) == unknown
    assert description_start("Una historia.", None, [])["ok"] is None  # sin marca ni búsqueda


def check(description, title, keyword=""):
    project = SimpleNamespace(duration="Largo")
    seo = {"description": description, "searches": {"keyword": keyword}, "titles": [title]}
    checks = _publish_checks(project, {"publish": seo}, title)
    return next(c for c in checks if c["key"] == "description")


def test_quality_check_uses_the_brand_of_the_title():
    good = check(LONG, "La caída de Kodak")
    assert good["status"] == "ok" and "Kodak inventó" in good["detail"]
    bad = check("Una historia increíble que nadie te contó.", "La caída de Kodak")
    assert bad["status"] == "warn" and "Volver a generar" in bad["fix"]
    links = check("#Kodak https://x.com", "La caída de Kodak")
    assert links["status"] == "warn" and "enlaces" in links["title"]


def test_quality_check_is_skipped_without_data():
    project = SimpleNamespace(duration="Largo")
    for seo in ({"description": None, "searches": None}, {"titles": ["x"]}):
        checks = _publish_checks(project, {"publish": seo}, "La caída de Kodak")
        assert "description" not in [c["key"] for c in checks]


def test_publish_page_shows_how_it_looks_in_search(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    page = with_script.get("/proyectos/1/publicacion").text
    assert "Así se ve en la búsqueda de YouTube" in page
    assert "La historia de la mayor quiebra de su época." in page

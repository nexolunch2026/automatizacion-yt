from types import SimpleNamespace

import pytest

from app.pipeline.monetization import _publish_checks
from app.pipeline.seo import generic_chapters, is_generic_chapter


@pytest.mark.parametrize(
    "title",
    [
        "Introducción",
        "Desarrollo",
        "Parte 2",
        "Capítulo 3",
        "CONCLUSIÓN",
        "Clímax",
        "",
        "El final",
        "La conclusión",
    ],  # fmt: skip
)
def test_generic_names(title):
    assert is_generic_chapter(title)


@pytest.mark.parametrize(
    "title",
    [
        "1975: la cámara escondida",
        "El error de Kodak",
        "La caída",
        "Desarrollo de Android",
        "1975",
        "Parte 2: 1975",
        "El final de Kodak",
    ],  # fmt: skip
)
def test_names_that_say_something(title):
    assert not is_generic_chapter(title)


def check(chapters):
    project = SimpleNamespace(duration="Largo")
    seo = {"chapters": chapters, "chapters_exact": True, "description": "", "titles": ["T"]}
    found = [
        c for c in _publish_checks(project, {"publish": seo}, "T") if c["key"] == "chapter_names"
    ]
    return found[0] if found else None


def test_quality_check_lists_generic_chapters():
    bad = check([{"time": "0:00", "title": "Introducción"}, {"time": "1:10", "title": "Desarrollo"},
                 {"time": "3:00", "title": "1975: la cámara escondida"}])  # fmt: skip
    assert bad["status"] == "warn" and "«Introducción», «Desarrollo»" in bad["detail"]
    good = check([{"time": "0:00", "title": "El invento"}, {"time": "1:10", "title": "El cajón"}])
    assert good["status"] == "ok"
    assert check([]) is None  # sin capítulos no se dice nada
    assert check("0:00 Intro") is None and check([1, 2]) is None  # datos raros: no se dice «bien»
    assert generic_chapters([{"title": None}, {"time": "1:00"}]) == ["(sin nombre)"] * 2

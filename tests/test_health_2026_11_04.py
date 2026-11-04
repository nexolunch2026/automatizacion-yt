"""Revisión de salud del 4/11/2026: fallos encontrados y su arreglo."""

import os
import time
from datetime import datetime

import pytest

from app import assistant
from app.models import Video
from app.pipeline import end_screen
from app.pipeline.monetization import flagged_words
from app.pipeline.seo import is_generic_chapter


@pytest.mark.parametrize(
    ("text", "profanity", "sensitive"),
    [
        ("CABRONES", ["cabrones"], []),
        ("putas", ["putas"], []),
        ("Los terroristas", [], ["terroristas"]),
        ("ASESINATOS en serie", [], ["asesinatos"]),
        ("Masacres", [], ["masacres"]),
        ("torturas", [], ["torturas"]),
        ("Nazis", [], ["nazis"]),
        ("asesinato", [], ["asesinato"]),
        ("Mesas y casas", [], []),  # palabras normales con «s» final: nada
    ],
)
def test_plurals_are_caught_by_the_advertiser_filter(text, profanity, sensitive):
    assert flagged_words(text) == (profanity, sensitive)


@pytest.mark.parametrize(
    "title", ["Conclusiones", "Parte II", "Parte dos", "Capítulo III", "Introducciones"]
)
def test_more_generic_chapter_names(title):
    assert is_generic_chapter(title)


@pytest.mark.parametrize("title", ["Luis XIV y el lujo", "Dos hermanos y una idea", "1975"])
def test_real_chapter_names_still_pass(title):
    assert not is_generic_chapter(title)


def test_brand_with_enye_matches_in_cards():
    title = "Cañas Hermanos: la caída"
    shared = end_screen.words("Hoy hablamos de Cañas otra vez") & end_screen.words(title)
    assert end_screen.brand_shared(shared, title)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="cambiar de zona horaria solo en Linux")
def test_publish_time_uses_the_offset_of_that_day(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Madrid")
    time.tzset()
    try:
        # julio: verano (UTC+2); noviembre: invierno (UTC+1)
        assert assistant._published_at(Video(published="2026-07-01T10:00Z")) == datetime(
            2026, 7, 1, 12, 0
        )
        assert assistant._published_at(Video(published="2026-11-01T10:00Z")) == datetime(
            2026, 11, 1, 11, 0
        )
        assert assistant.utc_to_local(datetime(2026, 7, 1, 10, 0)) == datetime(2026, 7, 1, 12, 0)
    finally:
        os.environ.pop("TZ", None)
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


def test_swear_word_warning_names_only_where_the_swear_word_is():
    from app.pipeline.monetization import _publish_words_check

    results = {"publish": {"description": "Historia de Kodak. suicidio", "tags": ["puta"],
                           "pinned_comment": "hola"}}  # fmt: skip
    [check] = [c for c in _publish_words_check(results) if c["key"] == "friendly_texts"]
    assert check["title"] == "Palabrotas en las etiquetas"


def test_no_made_up_views_between_far_apart_snapshots():
    from datetime import timedelta

    from app.analytics import _views_between
    from app.models import VideoStat

    start = datetime(2026, 10, 1, 12, 0)
    far = [VideoStat(taken_at=start + timedelta(hours=13), views=100),
           VideoStat(taken_at=start + timedelta(days=30), views=3000)]  # fmt: skip
    assert _views_between(far, start + timedelta(hours=48)) is None
    near = [VideoStat(taken_at=start + timedelta(hours=46), views=400),
            VideoStat(taken_at=start + timedelta(hours=50), views=600)]  # fmt: skip
    assert _views_between(near, start + timedelta(hours=48)) == 500


def test_best_day_survives_a_broken_best_hour(client, monkeypatch):
    from app import analytics, best_day
    from app.db import SessionLocal

    def broken(rows, hour):
        raise TypeError("cifra rara")

    monkeypatch.setattr(analytics, "video_rows", lambda db: [])
    monkeypatch.setattr(best_day, "best_day", lambda rows, day: {"text": "el martes"})
    monkeypatch.setattr(best_day, "best_hour", broken)
    with SessionLocal() as db:
        assert best_day.advice_both(db, 1, 10) == ({"text": "el martes"}, None)

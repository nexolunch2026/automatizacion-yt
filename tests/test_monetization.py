from types import SimpleNamespace

import pytest

from app.db import SessionLocal
from app.models import Project
from app.pipeline.monetization import (
    FAIL,
    OK,
    PENDING,
    WARN,
    flagged_words,
    overlap,
    review,
    summary_text,
    video_seconds,
)
from tests.test_storyboard_voice import ai, paragraph_ids, result, with_script  # noqa: F401


def project(duration="10–15 min"):
    return SimpleNamespace(duration=duration, title="Kodak")


def script(*paragraphs, kind="development", **extra):
    return {
        "title": "La caída de Kodak",
        "sections": [
            {
                "kind": kind,
                "title": "A",
                "paragraphs": [
                    {"id": str(i), "text": t, "sources": [1]} for i, t in enumerate(paragraphs)
                ],
            }
        ],
        **extra,
    }


def status(qc, key):
    return next(c["status"] for c in qc["checks"] if c["key"] == key)


TEXT = (
    "Kodak inventó la cámara digital en 1975 y decidió guardarla en un cajón para no "
    "dañar su negocio de carretes, una decisión que acabaría hundiendo a la empresa."
)


def test_overlap_detects_copied_text_and_ignores_accents():
    assert overlap(TEXT, TEXT) == 1.0
    assert overlap(TEXT, "Nokia dominó los teléfonos móviles durante una década entera.") == 0.0
    assert overlap("Él decidió guardarla en un cajón", "el decidio guardarla en un cajon") == 1.0
    assert overlap("", TEXT) == 0.0


def test_flagged_words():
    bad, sensitive = flagged_words("Una MASACRE financiera, ¡qué mierda!")
    assert bad == ["mierda"] and sensitive == ["masacre"]
    assert flagged_words("La quiebra de Enron") == ([], [])


def test_video_seconds_prefers_the_real_video():
    edit = {"renders": {"preview": {"seconds": 590}, "final": {"seconds": 600}}, "last": "final"}
    assert video_seconds({"edit": edit, "voice": {"seconds": 500}}) == 600
    assert video_seconds({"voice": {"seconds": 500}}) == 500
    assert video_seconds({"script": script("uno dos tres cuatro cinco")}) == 2.0
    assert video_seconds({}) is None


def test_only_script_marks_the_rest_pending():
    qc = review(project(), {"script": script(TEXT)}, [])
    assert status(qc, "midroll") == WARN  # un párrafo dura segundos, no 8 minutos
    assert status(qc, "repeat") == OK
    assert status(qc, "human") == WARN  # sin retocar a mano
    assert status(qc, "thumbnail") == PENDING and status(qc, "seo") == PENDING
    assert qc["verdict"].startswith("Aún faltan")


def test_repeated_script_fails_originality():
    qc = review(project(), {"script": script(TEXT)}, [TEXT + " Y mucho más."])
    assert status(qc, "repeat") == FAIL
    assert qc["counts"]["fail"] == 1
    assert "arréglalas" in qc["verdict"]


def test_profanity_in_title_fails_and_inside_script_warns():
    qc = review(project(), {"script": script(TEXT), "publish": {"titles": ["Qué mierda"]}}, [])
    assert status(qc, "friendly") == FAIL
    long_text = " ".join(["palabra"] * 60) + " y el terrorismo"
    qc = review(project(), {"script": script(long_text)}, [])
    assert status(qc, "friendly") == WARN


def test_slow_opening_is_flagged():
    slow = script("Hola a todos y bienvenidos al canal.", kind="hook")
    assert status(review(project(), {"script": slow}, []), "hook") == WARN
    fast = script("En 1975 Kodak tenía el futuro en la mano.", kind="hook")
    assert status(review(project(), {"script": fast}, []), "hook") == OK


def test_everything_done_scores_high():
    results = {
        "script": script(TEXT, edited=2),
        "storyboard": {"scenes": [{"seconds": 6}, {"seconds": 8}]},
        "visuals": {
            "items": {
                "0": {"kind": "image", "license": "Pixabay"},
                "1": {"kind": "image", "license": "IA", "ai": True},
            }
        },
        "voice": {"provider": "piper", "seconds": 700},
        "edit": {"renders": {"preview": {"seconds": 720, "music": ""}}, "last": "preview"},
        "publish": {"titles": ["La caída de Kodak"], "chapters": [1], "chapters_exact": True},
        "thumbnail": {"selected": 0},
        "shorts": {"shorts": [{}]},
    }
    qc = review(project(), results, [])
    assert status(qc, "midroll") == OK
    assert status(qc, "synthetic") == WARN  # recordar marcar el contenido sintético
    assert qc["counts"]["fail"] == 0 and qc["counts"]["pending"] == 0
    assert qc["score"] >= 85 and qc["verdict"] == "Listo para subir y monetizar."


def test_music_from_the_last_render_is_flagged():
    edit = {"renders": {"preview": {"seconds": 600, "music": "epica.mp3"}}, "last": "preview"}
    qc = review(project(), {"script": script(TEXT), "edit": edit}, [])
    assert status(qc, "music") == WARN and status(qc, "midroll") == OK


def test_elevenlabs_and_cards_warn():
    results = {
        "script": script(TEXT),
        "voice": {"provider": "elevenlabs"},
        "visuals": {"items": {"0": {"kind": "card"}, "1": {"kind": "image", "license": "x"}}},
    }
    qc = review(project("Short"), results, [])
    assert status(qc, "voice") == WARN and status(qc, "cards") == WARN
    assert status(qc, "midroll") == OK  # los Shorts no necesitan 8 minutos
    assert "shorts" not in {c["key"] for c in qc["checks"]}


def test_qc_page_and_manual_edits(with_script):  # noqa: F811
    page = with_script.get("/proyectos/1/control")
    assert page.status_code == 200
    assert "¿se puede monetizar?" in page.text and "Guion sin retocar" in page.text

    pid = paragraph_ids()[0]
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": "Mío."})
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": "Mío."})
    assert result("script")["edited"] == 1  # guardar sin cambios no cuenta
    assert "Guion revisado por ti" in with_script.get("/proyectos/1/control").text

    overview = with_script.get("/proyectos/1").text
    assert 'href="/proyectos/1/control"' in overview and "/100" in overview


@pytest.fixture(autouse=True)
def _ai(ai):  # noqa: F811
    return ai


def test_summary_text_lists_the_worst_first():
    qc = review(project(), {"script": script(TEXT)}, [TEXT])
    text = summary_text(qc)
    assert text.startswith(f"Nota de monetización: {qc['score']}/100.")
    assert text.splitlines()[1].startswith("⛔")  # lo grave primero


def test_jarvis_button_answers_with_the_review(with_script):  # noqa: F811
    from app.assistant import Incoming, handle, publish_replies

    with SessionLocal() as db:
        project_row = db.get(Project, 1)
        replies = publish_replies(project_row, {"titles": ["T"], "description": "D"})
        assert replies[-1].buttons == [[("🔎 ¿Se puede monetizar?", "qc:1")]]
        answer = handle(db, Incoming(chat_id=1, button="qc:1"), trusted=True)
    assert "Nota de monetización" in answer[0].text

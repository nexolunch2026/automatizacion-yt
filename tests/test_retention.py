import pytest

from app import analytics
from app.db import SessionLocal
from app.models import Video
from app.pipeline.script import _brief
from tests.test_analytics import channel  # noqa: F401
from tests.test_assistant import ai  # noqa: F401
from tests.test_projects import create_channel, project_data
from tests.test_strategy_script import make_project, run_all


@pytest.mark.parametrize(
    ("row", "parts"),
    [
        ({"retention_30s": 70, "retention_mid": 50, "retention": 45}, []),
        ({"retention_30s": 45, "retention_mid": 35, "retention": 40}, ["hook"]),
        ({"retention_30s": 72, "retention_mid": 30, "retention": 40}, ["middle"]),
        ({"retention_30s": 40, "retention_mid": 15, "retention": 20}, ["hook", "middle"]),
        ({"retention": 22}, ["overall"]),
        ({}, []),
    ],
)
def test_retention_diagnosis(row, parts):
    assert [d["part"] for d in analytics.retention_diagnosis(row)] == parts


def test_summary_and_notes_use_recent_videos_of_the_channel():
    rows = [
        {"channel_id": 1, "retention_30s": 50, "retention_mid": 25, "retention": 30},
        {"channel_id": 1, "retention_30s": 54, "retention_mid": 30, "retention": 32},
        {"channel_id": 2, "retention_30s": 90, "retention_mid": 80, "retention": 70},
        {"channel_id": 1},  # sin datos de retención: no cuenta
    ]
    summary = analytics.retention_summary(rows, channel_id=1)
    assert summary["videos"] == 2 and summary["hook"] == 52.0
    assert summary["weak"] == ["hook", "middle"]
    notes = analytics.retention_notes(summary)
    assert "52 % sigue" in notes and "GANCHO" in notes and "DESARROLLO" in notes
    assert analytics.retention_notes(analytics.retention_summary(rows, channel_id=2)) == ""
    assert analytics.retention_summary([])["weak"] == []


def test_notes_reach_the_script_brief():
    class P:
        language, video_type = "Español", "Documental"

    concept = {"angle": "a", "summary": "s", "promise": "p", "hook": "h", "audience": "x"}
    brief = _brief(P(), concept, "T", {"retention_notes": "Refuerza el GANCHO."})
    assert "Lo que dicen los datos de retención del canal:\nRefuerza el GANCHO." in brief
    assert "retención" not in _brief(P(), concept, "T", {})


def test_page_form_and_next_script(logged_in, channel, ai, monkeypatch):  # noqa: F811
    prompts = []
    original = ai.generate_json

    def spy(prompt, schema):
        prompts.append(prompt)
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", spy)
    make_project(logged_in, "manual")
    logged_in.post("/rendimiento/actualizar")
    assert "Apunta el «30 s» y «Mitad»" in logged_in.get("/rendimiento").text
    logged_in.post(
        "/rendimiento/bbbbbbbbbbb",
        data={"retention": "30", "retention_30s": "48 %", "retention_mid": "20", "project_id": "1"},
    )
    with SessionLocal() as db:
        video = db.get(Video, "bbbbbbbbbbb")
        assert (video.retention_30s, video.retention_mid) == (48.0, 20.0)
    page = logged_in.get("/rendimiento").text
    assert (
        "Solo el 48 % sigue a los 30 s" in page and "El próximo guion lo tendrá en cuenta" in page
    )
    assert "<li>En los últimos vídeos, mucha gente se va" in page  # una línea por consejo

    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/1/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    outline = next(p for p in prompts if "Haz el ESQUEMA" in p)
    assert "Refuerza el GANCHO" in outline and "Refuerza el DESARROLLO" in outline


def test_bad_numbers_are_ignored(logged_in, channel):  # noqa: F811
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    logged_in.post("/rendimiento/actualizar")
    logged_in.post("/rendimiento/bbbbbbbbbbb", data={"retention_30s": "150", "retention_mid": "x"})
    with SessionLocal() as db:
        video = db.get(Video, "bbbbbbbbbbb")
        assert video.retention_30s is None and video.retention_mid is None

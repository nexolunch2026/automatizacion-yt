import subprocess
from types import SimpleNamespace

import pytest

from app import jobs
from app.db import SessionLocal
from app.models import Project, StageResult
from app.pipeline.monetization import project_review, review
from app.pipeline.render import LOOKS, least_recent
from tests.test_projects import project_data
from tests.test_quality_pack import produced  # noqa: F401
from tests.test_storyboard_voice import ai, with_script  # noqa: F401
from tests.test_strategy_script import make_project


def edit_result(look, music, film_look=True):
    style = {"look": look, "music": music, "film_look": film_look, "subtitles": True}
    return {"renders": {"final": {"seconds": 600, "style": style}}, "last": "final"}


def test_least_recent():
    assert least_recent(["a", "b", "c"], []) == "a"
    assert least_recent(["a", "b", "c"], ["a"]) == "b"
    assert least_recent(["a", "b", "c"], ["c", "b", "a"]) == "a"  # la más vieja


@pytest.mark.parametrize("look", list(LOOKS))
def test_every_look_is_a_valid_ffmpeg_filter(look):
    import imageio_ffmpeg

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=160x90:duration=0.2",
        "-vf",
        LOOKS[look][1] + ",format=yuv420p",
        "-f",
        "null",
        "-",
    ]
    assert subprocess.run(command, capture_output=True, timeout=60).returncode == 0


def test_render_style_keeps_auto_and_rejects_rubbish(logged_in, monkeypatch):
    monkeypatch.setattr(jobs, "music_library", lambda: ["a.mp3"])
    with SessionLocal() as db:
        style = jobs.render_style(db, {"look": "inventado", "music": "otra.mp3"})
        assert style["look"] == "auto" and style["music"] == ""
        assert jobs.render_style(db, {"look": "frio", "music": "auto"})["music"] == "auto"


def test_new_video_gets_a_look_and_song_not_used_last_time(logged_in, ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(jobs, "music_library", lambda: ["a.mp3", "b.mp3"])
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/nuevo", data=project_data(automation_mode="manual"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="edit", data=edit_result("cine", "a.mp3")))
        db.commit()
        second = db.get(Project, 2)
        style = jobs.resolve_style(db, second, {"look": "auto", "music": "auto"})
        assert style == {"look": "calido", "music": "b.mp3"}
        # Si el vídeo ya tiene montaje, se respeta (vista previa y final iguales).
        db.add(StageResult(project_id=2, stage="edit", data=edit_result("archivo", "a.mp3")))
        db.commit()
        style = jobs.resolve_style(db, second, {"look": "auto", "music": "auto"})
        assert style == {"look": "archivo", "music": "a.mp3"}
        # Lo elegido a mano no se toca.
        assert jobs.resolve_style(db, second, {"look": "frio", "music": ""})["look"] == "frio"


def test_quality_control_warns_when_the_look_repeats(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/nuevo", data=project_data(automation_mode="manual"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="edit", data=edit_result("cine", "a.mp3")))
        db.add(StageResult(project_id=2, stage="edit", data=edit_result("cine", "a.mp3")))
        db.commit()
        qc = project_review(db, db.get(Project, 2))
    look = next(c for c in qc["checks"] if c["key"] == "look")
    assert look["status"] == "warn" and "Mismo tono de color" in look["title"]


def test_quality_control_is_happy_with_a_different_look():
    project = SimpleNamespace(duration="10–15 min", title="x")
    results = {"script": {"sections": []}, "edit": edit_result("frio", "b.mp3")}
    qc = review(project, results, [], [], [{"look": "cine", "music": "a.mp3", "film_look": True}])
    look = next(c for c in qc["checks"] if c["key"] == "look")
    assert look["status"] == "ok" and "tono Frío" in look["title"]
    assert "look" not in {c["key"] for c in review(project, results, [])["checks"]}


def test_video_page_offers_the_tones(produced):  # noqa: F811
    page = produced.get("/proyectos/1/video").text
    assert "Tono de color" in page and "Archivo (tono antiguo)" in page
    assert '<option value="auto" selected>Automático' in page

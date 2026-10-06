from types import SimpleNamespace

import httpx
import pytest

from app import system_check
from app.db import SessionLocal
from app.models import Job
from app.settings_store import save_api_key
from tests.test_assistant import ai, studio, talk  # noqa: F401
from tests.test_strategy_script import make_project

GB = system_check.GB


@pytest.fixture
def quick_checks(monkeypatch):
    """Sin ffmpeg, voz ni internet de verdad: cada prueba decide qué falla."""
    monkeypatch.setattr(system_check, "video_tools", lambda: system_check.Check("ffmpeg", "ok", ""))
    monkeypatch.setattr(system_check, "free_voice", lambda: system_check.Check("Voz", "ok", ""))
    monkeypatch.setattr(system_check, "internet", lambda: system_check.Check("Red", "ok", ""))


def test_folders_warn_about_onedrive(tmp_path):
    assert system_check.folders(tmp_path, tmp_path).state == "ok"
    check = system_check.folders(tmp_path / "OneDrive" / "programa", tmp_path)
    assert check.state == "warn" and "OneDrive" in check.fix


def test_disk_space_levels(tmp_path):
    def usage(free):
        return lambda path: SimpleNamespace(free=free * GB)

    assert system_check.disk(tmp_path, usage(50)).state == "ok"
    assert system_check.disk(tmp_path, usage(5)).state == "warn"
    assert system_check.disk(tmp_path, usage(1)).state == "fail"


def test_video_tools_and_internet_failures():
    def broken(*args, **kwargs):
        raise OSError("no está")

    def offline():
        raise httpx.ConnectError("sin red")

    assert system_check.video_tools(run=broken).state == "fail"
    assert system_check.video_tools(run=lambda *a, **k: SimpleNamespace(returncode=0)).state == "ok"
    assert system_check.internet(get=offline).state == "fail"
    assert system_check.internet(get=lambda: None).state == "ok"


def test_page_runs_all_checks(studio, quick_checks):  # noqa: F811
    assert "Revisar mi ordenador" in studio.get("/configuracion").text
    assert "Revisar ahora" in studio.get("/configuracion/revisar").text
    page = studio.post("/configuracion/revisar").text
    assert "Gemini" in page and "Sin clave (opcional)" in page and "Espacio en disco" in page
    with SessionLocal() as db:
        save_api_key(db, "youtube", "clave")
    assert "comentarios" in studio.post("/configuracion/revisar").text


def test_stuck_jobs_are_reported(studio):  # noqa: F811
    make_project(studio, "manual")
    with SessionLocal() as db:
        db.add(Job(project_id=1, stage="voice", status="failed",
                   message="Detenida tras varios cierres"))  # fmt: skip
        db.commit()
        assert system_check.stuck_jobs(db).state == "warn"


def test_jarvis_checks_the_computer(studio, quick_checks):  # noqa: F811
    text = talk("revisa mi ordenador")[0].text
    assert "🩺" in text and "Espacio en disco" in text and "Gemini" in text

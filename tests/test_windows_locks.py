"""Simulaciones de archivos bloqueados como ocurre en Windows."""

import os
from pathlib import Path

import pytest

from app import jobs
from app.db import SessionLocal
from app.jobs import describe_unexpected
from app.models import Job
from app.pipeline import render
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def test_replace_file_retries_then_uses_another_name(tmp_path, monkeypatch):
    monkeypatch.setattr(render.time, "sleep", lambda s: None)
    real_replace = os.replace
    final = tmp_path / "video-preview.mp4"
    final.write_bytes(b"viejo")

    def locked(src, dst):
        if Path(dst) == final:  # el vídeo viejo está abierto en el reproductor
            raise PermissionError(13, "Acceso denegado")
        return real_replace(src, dst)

    monkeypatch.setattr(render.os, "replace", locked)
    tmp = tmp_path / "nuevo.mp4"
    tmp.write_bytes(b"nuevo")
    out = render.replace_file(tmp, final)
    assert out != final and out.read_bytes() == b"nuevo"
    assert out.name.startswith("video-preview-") and final.read_bytes() == b"viejo"


def test_replace_file_works_when_lock_is_released(tmp_path, monkeypatch):
    monkeypatch.setattr(render.time, "sleep", lambda s: None)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:  # el antivirus lo suelta al tercer intento
            raise PermissionError(13, "Acceso denegado")
        return real_replace(src, dst)

    monkeypatch.setattr(render.os, "replace", flaky)
    tmp, final = tmp_path / "a.srt", tmp_path / "subtitulos.srt"
    tmp.write_text("x")
    assert render.replace_file(tmp, final) == final


def test_unexpected_error_detail_names_file_and_place():
    try:
        open("/no/existe/archivo.txt", "w")  # noqa: SIM115
    except OSError as exc:
        detail = describe_unexpected(exc)
    assert "archivo.txt" in detail and "test_windows_locks.py" in detail


def test_permission_error_in_job_is_retried_with_clear_message(with_script, monkeypatch):  # noqa: F811
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()

    def locked(*args, **kwargs):
        raise PermissionError(13, "Acceso denegado")

    monkeypatch.setattr(jobs, "run_voice", locked)
    with_script.post("/proyectos/1/etapas/voice")
    jobs.process_next_job()
    with SessionLocal() as db:
        job = db.query(Job).filter_by(stage="voice").one()
        assert job.status == "queued"  # se reintentará solo
        assert "Windows no dejó escribir" in job.message


def test_render_returns_srt_path(with_script):  # noqa: F811
    from tests.test_visuals_render import FakeStock  # noqa: F401

    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    with SessionLocal() as db:
        jobs.enqueue(db, 1, "edit", {"quality": "test"})
    run_all()
    render_result = result("edit")["renders"]["test"]
    assert render_result["srt"] == "video/subtitulos.srt"
    assert not list((Path(render_result["file"]).parent).glob("tmp-*"))


@pytest.fixture(autouse=True)
def _ai(ai):  # noqa: F811
    return ai

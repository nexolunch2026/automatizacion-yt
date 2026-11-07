"""Montaje más rápido: zoom ×2 en final, final por defecto y gráfica Intel con respaldo."""

from app.pipeline import render


def test_final_uses_zoom_x2():
    # En las pruebas QUALITIES está en miniatura: el valor real se lee del archivo.
    from pathlib import Path

    source = Path(render.__file__).read_text(encoding="utf-8")
    assert '"final": (1920, 1080, 30, "veryfast", 20, 2)' in source


def test_qsv_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("FACELESS_NO_QSV", "1")
    assert render.has_qsv() is False


def test_qsv_detection_falls_back_when_ffmpeg_fails(monkeypatch):
    monkeypatch.delenv("FACELESS_NO_QSV", raising=False)
    monkeypatch.setattr(render, "_qsv", None)

    def fail(args, cwd=None):
        raise RuntimeError("FFmpeg falló: no hay Quick Sync")

    monkeypatch.setattr(render, "run_ffmpeg", fail)
    assert render.has_qsv() is False
    monkeypatch.setattr(render, "_qsv", None)

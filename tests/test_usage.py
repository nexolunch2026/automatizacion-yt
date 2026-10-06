from datetime import datetime
from types import SimpleNamespace

from app import usage
from app.db import SessionLocal
from app.providers.ai import _record_usage
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def test_meter_counts_only_inside_measure():
    usage.record("gemini_calls")  # sin contador abierto: no pasa nada
    with usage.measure() as meter:
        usage.record("gemini_calls")
        usage.record("gemini_tokens", 1200)
        usage.record("inventado", 5)
        _record_usage(SimpleNamespace(usage_metadata=SimpleNamespace(total_token_count=300)))
        _record_usage(SimpleNamespace())  # respuestas sin datos de uso
    assert meter == {"gemini_calls": 3, "gemini_tokens": 1500}


def test_save_by_stage_and_month(logged_in):
    now = datetime(2026, 10, 6)
    with SessionLocal() as db:
        usage.save(db, 1, "script", {"gemini_calls": 9, "gemini_tokens": 50_000}, now)
        usage.save(db, 1, "script", {"gemini_calls": 1}, now)
        usage.save(db, 1, "voice", {"eleven_credits": 4000}, now)
        usage.save(db, 2, "research", {}, now)  # nada gastado: no se guarda
        data = usage.project_usage(db, 1)
        assert data["stages"]["script"]["gemini_calls"] == 10
        assert data["total"] == {
            "gemini_calls": 10,
            "gemini_tokens": 50_000,
            "eleven_credits": 4000,
        }
        assert usage.month_usage(db, now)["eleven_credits"] == 4000
        assert usage.month_usage(db, datetime(2026, 11, 1))["gemini_calls"] == 0
        assert usage.project_usage(db, 2)["total"]["gemini_calls"] == 0


def test_jobs_record_gemini_usage(with_script, monkeypatch):  # noqa: F811
    from app import jobs

    def fake_runner(db, project, progress, params):
        usage.record("gemini_calls", 2)
        usage.record("gemini_tokens", 900)
        return {"ok": True}

    def broken_runner(db, project, progress, params):
        usage.record("gemini_calls")
        raise RuntimeError("fallo")

    monkeypatch.setitem(jobs.RUNNERS, "publish", fake_runner)
    with_script.post("/proyectos/1/etapas/publish")
    run_all()
    monkeypatch.setitem(jobs.RUNNERS, "thumbnail", broken_runner)
    with_script.post("/proyectos/1/etapas/thumbnail")
    run_all()
    with SessionLocal() as db:
        data = usage.project_usage(db, 1)
    assert data["stages"]["publish"] == {
        "gemini_calls": 2,
        "gemini_tokens": 900,
        "eleven_credits": 0,
    }
    assert data["stages"]["thumbnail"]["gemini_calls"] == 1  # aunque falle, cuenta
    page = with_script.get("/proyectos/1").text
    assert "Consumo de este vídeo" in page and "llamadas a Gemini" in page

"""Gemini gratis agotado: la tarea espera sola a que Google lo renueve (y JARVIS lo dice),
en vez de quedarse en «Falló» hasta que alguien la reintente a mano."""

from datetime import UTC, datetime, timedelta

import pytest
from google.genai import errors

from app import assistant, jobs
from app.db import SessionLocal
from app.models import Job
from app.providers.ai import ProviderError, _friendly_error
from app.settings_store import set_setting
from tests.test_ai_provider import FakeModels, not_found, provider_with
from tests.test_strategy_script import make_project

DAILY = "Quota exceeded for metric GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20"


def daily_error():
    return errors.APIError(
        429, {"error": {"code": 429, "message": DAILY, "status": "RESOURCE_EXHAUSTED"}}
    )


def test_daily_quota_is_marked():
    assert _friendly_error(429, DAILY).daily_quota
    assert not _friendly_error(429, "limit per minute exceeded").daily_quota


def test_daily_quota_wins_over_the_last_models_error():
    fake = FakeModels(
        ["gemini-2.5-flash", "gemini-3.5-flash"],
        {"gemini-3.5-flash": daily_error(), "gemini-2.5-flash": not_found("gemini-2.5-flash")},
    )
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert info.value.daily_quota and "de hoy" in str(info.value)


@pytest.mark.parametrize("hour", [0, 7, 8, 9, 15, 23])
def test_next_reset_is_the_next_0805_utc(hour):
    now = datetime(2026, 11, 6, hour, 30)
    reset = jobs.next_quota_reset(now)
    assert now < reset <= now + timedelta(days=1)
    utc = reset.astimezone(UTC)
    assert (utc.hour, utc.minute) == (8, 5)


def make_job(db, attempts=1):
    job = Job(project_id=1, stage="script", status="running", attempts=attempts)
    db.add(job)
    db.commit()
    return job


def test_job_waits_for_tomorrow_instead_of_failing(logged_in):
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        job = make_job(db)
        jobs._handle_failure(db, job, _friendly_error(429, DAILY))
        assert job.status == "queued" and job.run_after > datetime.now()
        assert job.message.startswith(jobs.QUOTA_WAIT) and "no hace falta" in job.message
        assert job.run_after == jobs.next_quota_reset(datetime.now())


def test_jarvis_says_it_is_waiting_once(logged_in):
    make_project(logged_in, "manual")
    now = datetime(2026, 11, 6, 22, 0)
    with SessionLocal() as db:
        job = make_job(db)
        jobs._handle_failure(db, job, _friendly_error(429, DAILY))
        assert "esperando a Gemini" in assistant.status_text(db)
        assert assistant.quota_notice(db, now) == []  # sin Telegram
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        [reply] = assistant.quota_notice(db, now)
        assert "Se acabó el Gemini gratis de hoy" in reply.text
        assert f"a las {job.run_after:%H:%M}" in reply.text and "«" in reply.text
        assert assistant.quota_notice(db, now + timedelta(minutes=5)) == []  # una vez
        texts = [r.text for r in assistant.tick(db, now)]
        assert not any("Gemini gratis" in t for t in texts)  # ya avisado


def test_normal_queue_is_not_announced(logged_in):
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        job = make_job(db)
        job.status = "queued"
        db.commit()
        assert assistant.quota_notice(db) == []
        assert "en cola" in assistant.status_text(db)


def test_waits_do_not_use_up_attempts_and_old_jobs_fail(logged_in):
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        job = make_job(db, attempts=3)  # ya gastó reintentos rápidos
        jobs._handle_failure(db, job, _friendly_error(429, DAILY))
        assert job.status == "queued" and job.attempts == 2
        old = make_job(db)
        old.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=4)
        db.commit()
        jobs._handle_failure(db, old, _friendly_error(429, DAILY))  # 4 días: ya no espera
        assert old.status == "failed" and "de hoy" in old.error


def test_retry_by_hand_runs_a_waiting_job_now(logged_in):
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        job = make_job(db)
        jobs._handle_failure(db, job, _friendly_error(429, DAILY))
        again = jobs.enqueue(db, 1, "script", {"nueva": True})
        assert again.id == job.id and again.run_after is None and again.params == {"nueva": True}


def test_a_second_video_waiting_later_is_announced(logged_in):
    make_project(logged_in, "manual")
    now = datetime(2026, 11, 6, 22, 0)
    with SessionLocal() as db:
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        jobs._handle_failure(db, make_job(db), _friendly_error(429, DAILY))
        assert assistant.quota_notice(db, now)
        other = Job(project_id=1, stage="seo", status="running", attempts=1)
        db.add(other)
        db.commit()
        jobs._handle_failure(db, other, _friendly_error(429, DAILY))
        assert assistant.quota_notice(db, now + timedelta(hours=1))  # hay otra tarea esperando


def test_past_wait_reads_as_queued(logged_in):
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        job = make_job(db)
        jobs._handle_failure(db, job, _friendly_error(429, DAILY))
        job.run_after = datetime.now() - timedelta(minutes=1)  # ya toca, pero hay cola
        db.commit()
        assert "esperando a Gemini" not in assistant.status_text(db)


def test_per_minute_limit_on_another_model_beats_waiting_a_day():
    minute = errors.APIError(
        429, {"error": {"code": 429, "message": "limit per minute", "status": "RESOURCE_EXHAUSTED"}}
    )
    fake = FakeModels(
        ["gemini-2.5-flash", "gemini-3.5-flash"],
        {"gemini-3.5-flash": daily_error(), "gemini-2.5-flash": minute},
    )
    with pytest.raises(ProviderError) as info:
        provider_with(fake).grounded_research("tema")
    assert info.value.transient and not info.value.daily_quota

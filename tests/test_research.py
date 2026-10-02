from datetime import datetime, timedelta

import pytest

from app import jobs, settings_web
from app.db import SessionLocal
from app.models import Job, Project, StageResult
from app.pipeline.research import Angle, Fact, ResearchBrief
from app.providers.ai import GroundedText, ProviderError, Source
from tests.test_projects import create_channel, project_data


class FakeAI:
    name = "fake"

    def __init__(self, sources=2):
        self.sources = [Source(f"Fuente {i}", f"https://ejemplo.com/{i}") for i in range(sources)]

    def grounded_research(self, prompt):
        assert "Empresas que desaparecieron" in prompt
        return GroundedText("Enron quebró en 2001.[1]", self.sources, ["enron quiebra"])

    def generate_json(self, prompt, schema):
        assert schema is ResearchBrief
        return ResearchBrief(
            context="Grandes empresas que cayeron de golpe.",
            key_facts=[
                Fact(text="Enron quebró en 2001", sources=[1]),
                Fact(text="Dato con fuente inventada", sources=[9]),
            ],
            timeline=[Fact(text="2001: quiebra de Enron", sources=[1, 2])],
            people=[],
            figures=[Fact(text="63.000 millones en activos", sources=[2])],
            angles=[Angle(title="Las señales ignoradas", description="Qué se pudo ver venir")],
            controversial=["Papel de los auditores"],
            needs_verification=[],
        )


@pytest.fixture
def project(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_gemini_key", lambda key: "gemini-test")
    logged_in.post("/configuracion/gemini", data={"api_key": "AIzaPrueba0000"})
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    return logged_in


def run_stage(client):
    return client.post("/proyectos/1/etapas/research")


def test_research_end_to_end(project, monkeypatch):
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FakeAI())
    r = run_stage(project)
    assert "Puedes salir de esta página" in r.text  # la tarea está en cola
    assert project.get("/proyectos/1/estado").json()["research"]["status"] == "queued"

    assert jobs.process_next_job() is True
    assert jobs.process_next_job() is False  # ya no queda nada

    page = project.get("/proyectos/1").text
    assert "Enron quebró en 2001" in page
    assert "https://ejemplo.com/0" in page
    assert "Las señales ignoradas" in page
    assert "✓ Hecho" in page

    with SessionLocal() as db:
        data = db.query(StageResult).one().data
        assert db.get(Project, 1).status == "Investigación"
    # El número de fuente inexistente se descarta y el dato pasa a «por verificar».
    assert [f["text"] for f in data["key_facts"]] == ["Enron quebró en 2001"]
    assert "Dato con fuente inventada (sin fuente)" in data["needs_verification"]
    assert data["timeline"][0]["sources"] == [1, 2]


def test_research_without_sources_warns(project, monkeypatch):
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FakeAI(sources=0))
    run_stage(project)
    jobs.process_next_job()
    with SessionLocal() as db:
        data = db.query(StageResult).one().data
    assert data["key_facts"] == []
    assert "warning" in data


def test_missing_key_fails_with_clear_message(logged_in):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    run_stage(logged_in)
    jobs.process_next_job()
    page = logged_in.get("/proyectos/1").text
    assert "Falta la clave de Gemini" in page


def test_transient_errors_retry_then_fail(project, monkeypatch):
    class RateLimited(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("Límite alcanzado.", transient=True)

    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: RateLimited())
    run_stage(project)

    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        with SessionLocal() as db:  # adelanta el reloj: el reintento ya puede ejecutarse
            job = db.get(Job, 1)
            job.run_after = datetime.now() - timedelta(seconds=1)
            db.commit()
        assert jobs.process_next_job() is True
        with SessionLocal() as db:
            job = db.get(Job, 1)
            assert job.attempts == attempt
            expected = "failed" if attempt == jobs.MAX_ATTEMPTS else "queued"
            assert job.status == expected


def test_retry_waits_before_running_again(project, monkeypatch):
    class Flaky(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("Servicio caído.", transient=True)

    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: Flaky())
    run_stage(project)
    jobs.process_next_job()
    assert jobs.process_next_job() is False  # el reintento espera unos segundos


def test_enqueue_does_not_duplicate(project):
    run_stage(project)
    run_stage(project)
    with SessionLocal() as db:
        assert db.query(Job).count() == 1


def test_interrupted_jobs_are_resumed(project, monkeypatch):
    run_stage(project)
    with SessionLocal() as db:
        db.get(Job, 1).status = "running"  # como si el programa se hubiera cerrado a mitad
        db.commit()
    jobs.recover_interrupted()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FakeAI())
    assert jobs.process_next_job() is True
    with SessionLocal() as db:
        assert db.get(Job, 1).status == "done"


def test_unknown_stage_returns_404(project):
    assert project.post("/proyectos/1/etapas/voice").status_code == 404


def test_deleting_project_removes_jobs_and_results(project, monkeypatch):
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FakeAI())
    run_stage(project)
    jobs.process_next_job()
    project.post("/proyectos/1/borrar")
    with SessionLocal() as db:
        assert db.query(Job).count() == 0
        assert db.query(StageResult).count() == 0


def test_failure_shows_technical_detail(project, monkeypatch):
    class NoQuota(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("Sin uso gratuito.", detail="429 RESOURCE_EXHAUSTED: limit: 0")

    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: NoQuota())
    run_stage(project)
    jobs.process_next_job()
    page = project.get("/proyectos/1").text
    assert "Sin uso gratuito." in page
    assert "Detalle técnico" in page
    assert "limit: 0" in page

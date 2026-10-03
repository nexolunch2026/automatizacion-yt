from datetime import datetime, timedelta

import pytest

from app import jobs, settings_web
from app.db import SessionLocal
from app.models import Job, Project, StageResult
from app.pipeline.research import Angle, Fact, ResearchBrief, SearchQueries
from app.pipeline.script import Outline, OutlineSection, Paragraph, Rewrite, SectionDraft
from app.pipeline.seo import SeoDraft
from app.pipeline.storyboard import SceneSpec, Storyboard, VisualBible
from app.pipeline.strategy import Concept, Strategy, Thumbnail, TitleOption
from app.providers.ai import GroundedText, ProviderError, Source
from tests.conftest import FakeSearch
from tests.test_projects import create_channel, project_data


def fake_strategy():
    return Strategy(
        concepts=[
            Concept(
                angle=f"Enfoque {i}",
                summary="Resumen",
                audience="Curiosos",
                promise="Entenderás la caída",
                hook="Nadie lo vio venir…",
                titles=[
                    TitleOption(title=f"Título {i}-{j}", style="misterio", reason="Intriga")
                    for j in range(3)
                ],
                thumbnail=Thumbnail(
                    concept="Edificio vacío", text="SE ESFUMÓ", composition="Alto contraste"
                ),
            )
            for i in range(3)
        ]
    )


def fake_outline(prompt):
    import re

    count = int(re.search(r"Tiene exactamente (\d+) secciones", prompt).group(1))
    return Outline(
        sections=[OutlineSection(title=f"Parte {i}", key_points=["Enron"]) for i in range(count)]
    )


def fake_section(prompt):
    import re

    if "debería tener unas" in prompt:  # petición de alargar: no la mejora, se queda el original
        return SectionDraft(paragraphs=[Paragraph(text="Corto.", sources=[])])
    number = int(re.search(r"ESCRIBE AHORA SOLO la sección (\d+)", prompt).group(1))
    if number == 1:
        return SectionDraft(paragraphs=[Paragraph(text="Nadie lo vio venir.", sources=[])])
    return SectionDraft(
        paragraphs=[
            Paragraph(
                text=f"Enron quebró en 2001 tras años de engaños ({number}).", sources=[1, 99]
            ),
            Paragraph(text=f"Miles de empleados perdieron todo ({number}).", sources=[2]),
        ]
    )


def fake_storyboard(prompt):
    import re

    ids = re.findall(r"^\[([0-9a-f]{8})\]", prompt, re.MULTILINE)
    return Storyboard(
        visual_bible=VisualBible(
            style="Documental oscuro",
            palette="Azules fríos",
            era="EE. UU., 2001",
            lighting="Baja",
            camera="Planos lentos",
            characters=[],
            locations=["Houston"],
        ),
        # La IA «se olvida» del último párrafo, para comprobar que no se pierde.
        scenes=[
            SceneSpec(
                paragraph_id=pid,
                visual_type="video",
                visual=f"Plano {i}",
                stock_query="empty office",
                image_prompt="dark office, cinematic",
                motion="zoom lento",
                transition="fundido",
                on_screen_text="2001" if i == 1 else "",
                sfx=["viento"],
                music_mood="tensión",
            )
            for i, pid in enumerate(ids[:-1])
        ],
    )


class FakeAI:
    name = "fake"

    def __init__(self, sources=2):
        self.sources = [Source(f"Fuente {i}", f"https://ejemplo.com/{i}") for i in range(sources)]

    def grounded_research(self, prompt):
        assert "Empresas que desaparecieron" in prompt
        return GroundedText("Enron quebró en 2001.[1]", self.sources, ["enron quiebra"])

    def generate_json(self, prompt, schema):
        if schema is SearchQueries:
            return SearchQueries(queries=["Enron", "quiebra de Enron"])
        if schema is Strategy:
            return fake_strategy()
        if schema is Outline:
            return fake_outline(prompt)
        if schema is SectionDraft:
            return fake_section(prompt)
        if schema is Storyboard:
            return fake_storyboard(prompt)
        if schema is SeoDraft:
            return SeoDraft(
                titles=["El colapso de Enron", "Título 0-0", "¿Cómo cayó Enron?"],
                description_intro="La historia de la mayor quiebra de su época.",
                tags=["Enron", "enron", "quiebras, empresas", "#documental", ""],
                hashtags=["#Enron", "documental empresas", "#Negocios", "#extra"],
                pinned_comment="¿Crees que se pudo evitar?",
                category="Educación",
            )
        if schema.__name__ == "ChartPlan":
            return schema(charts=[])
        if schema.__name__ == "ShortPicks":
            return schema(
                shorts=[{"start": 1, "end": 3, "title": "Así cayó Enron", "hook": "Nadie lo vio"}]
            )
        if schema.__name__ == "ThumbTexts":
            return schema(
                texts=[
                    {"text": "El fin de Enron", "highlight": "fin"},
                    {"text": "63.000 millones perdidos", "highlight": "63.000"},
                    {"text": "Nadie lo vio venir", "highlight": "nadie"},
                ]
            )
        if schema is Rewrite:
            return Rewrite(text="Párrafo reescrito por la IA.", sources=[2, 7])
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
    # Modo asistido: al terminar la investigación, la IA prepara los enfoques sola.
    assert project.get("/proyectos/1/estado").json()["strategy"]["status"] == "queued"

    page = project.get("/proyectos/1/investigacion").text
    assert "Enron quebró en 2001" in page
    assert "https://ejemplo.com/0" in page
    assert "Las señales ignoradas" in page
    assert "✓ Hecho" in project.get("/proyectos/1").text

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
    page = logged_in.get("/proyectos/1/investigacion").text
    assert "Falta la clave de Gemini" in page


def test_transient_errors_retry_then_fail(project, monkeypatch):
    class RateLimited(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("Límite alcanzado.", transient=True)

        def generate_json(self, prompt, schema):
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

        def generate_json(self, prompt, schema):
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
    assert project.post("/proyectos/1/etapas/qc").status_code == 404


def test_deleting_project_removes_jobs_and_results(project, monkeypatch):
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: FakeAI())
    run_stage(project)
    jobs.process_next_job()
    project.post("/proyectos/1/borrar")
    with SessionLocal() as db:
        assert db.query(Job).count() == 0
        assert db.query(StageResult).count() == 0


class NoGoogleSearch(FakeAI):
    """Cuenta sin cuota para la búsqueda de Google, pero Gemini normal sí funciona."""

    def grounded_research(self, prompt):
        raise ProviderError(
            "Google no permite más peticiones gratuitas con tu cuenta ahora mismo.",
            detail="429 RESOURCE_EXHAUSTED",
        )


def test_falls_back_to_wikipedia_when_google_search_unavailable(project, monkeypatch):
    search = FakeSearch()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: NoGoogleSearch(sources=0))
    monkeypatch.setattr(jobs, "get_search_provider", lambda: search)
    run_stage(project)
    jobs.process_next_job()

    with SessionLocal() as db:
        data = db.query(StageResult).one().data
    assert data["method"] == "wikipedia"
    assert search.queries == ["Enron", "quiebra de Enron"]
    assert data["sources"] == [
        {"n": 1, "title": "Wikipedia: Enron", "uri": "https://es.wikipedia.org/wiki/Enron"}
    ]
    # Solo hay 1 documento: las referencias a la fuente 2 se descartan.
    assert data["timeline"][0]["sources"] == [1]
    assert "63.000 millones en activos (sin fuente)" in data["needs_verification"]
    page = project.get("/proyectos/1/investigacion").text
    assert "se usó Wikipedia" in page


def test_busy_google_search_falls_back_to_wikipedia(project, monkeypatch):
    class Busy(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("Google está saturado.", transient=True)

    search = FakeSearch()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: Busy())
    monkeypatch.setattr(jobs, "get_search_provider", lambda: search)
    run_stage(project)
    jobs.process_next_job()
    assert search.queries == ["Enron", "quiebra de Enron"]
    with SessionLocal() as db:
        assert db.get(Job, 1).status == "done"


def test_invalid_key_does_not_fall_back(project, monkeypatch):
    class BadKey(FakeAI):
        def grounded_research(self, prompt):
            raise ProviderError("La clave de Gemini no es válida. Revísala en Configuración.")

    search = FakeSearch()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: BadKey())
    monkeypatch.setattr(jobs, "get_search_provider", lambda: search)
    run_stage(project)
    jobs.process_next_job()
    assert search.queries is None
    assert "clave de Gemini no es válida" in project.get("/proyectos/1/investigacion").text


def test_wikipedia_without_results(project, monkeypatch):
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: NoGoogleSearch())
    monkeypatch.setattr(jobs, "get_search_provider", lambda: FakeSearch(documents=[]))
    run_stage(project)
    jobs.process_next_job()
    assert (
        "No se encontró información en Wikipedia" in project.get("/proyectos/1/investigacion").text
    )


def test_failure_shows_technical_detail(project, monkeypatch):
    class NoQuotaAtAll(NoGoogleSearch):
        def generate_json(self, prompt, schema):
            raise ProviderError("Sin uso gratuito.", detail="429 RESOURCE_EXHAUSTED: limit: 0")

    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: NoQuotaAtAll())
    run_stage(project)
    jobs.process_next_job()
    page = project.get("/proyectos/1/investigacion").text
    assert "Sin uso gratuito." in page
    assert "Detalle técnico" in page
    assert "limit: 0" in page


def test_working_model_is_remembered(project, monkeypatch):
    from app.settings_store import get_setting

    class WithModel(FakeAI):
        last_model = "gemini-3.5-flash"

    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: WithModel())
    run_stage(project)
    jobs.process_next_job()
    with SessionLocal() as db:
        assert get_setting(db, "gemini_model") == "gemini-3.5-flash"

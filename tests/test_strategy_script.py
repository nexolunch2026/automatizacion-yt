import pytest

from app import jobs, stages_web
from app.db import SessionLocal
from app.models import Job, Project
from app.providers.ai import ProviderError
from tests.test_projects import create_channel, project_data
from tests.test_research import FakeAI


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    return fake


def make_project(client, mode="asistido"):
    from app import settings_web

    settings_web.check_gemini_key = lambda key: "gemini-test"
    client.post("/configuracion/gemini", data={"api_key": "AIzaPrueba0000"})
    create_channel(client)
    client.post("/proyectos/nuevo", data=project_data(automation_mode=mode))


def run_all():
    while jobs.process_next_job():
        pass


def script_data():
    return jobs.get_result(SessionLocal(), 1, "script")


def test_assisted_mode_stops_for_choice(logged_in, ai):
    make_project(logged_in, "asistido")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()

    page = logged_in.get("/proyectos/1/estrategia").text
    assert "Enfoque 0" in page and "Enfoque 2" in page
    assert "SE ESFUMÓ" in page
    assert script_data() is None  # espera a que el usuario elija

    r = logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 1, "title": 2})
    assert "Título 1-2" in r.text  # redirige al guion con el título elegido
    assert "Escribir guion" in r.text


def test_write_script_with_tone(logged_in, ai):
    make_project(logged_in, "asistido")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 1, "title": 2})
    logged_in.post(
        "/proyectos/1/etapas/script",
        data={"tone": "Misterioso", "drama": "Alto", "technical": "Inventado"},
    )
    run_all()

    data = script_data()
    assert data["title"] == "Título 1-2"
    assert data["params"] == {
        "tone": "Misterioso",
        "drama": "Alto",
        "technical": "Bajo",
        "structure": "cronologia",  # automática: la primera que nunca se ha usado
    }
    # 5–10 min: gancho, promesa, intro, 3 de desarrollo, clímax, conclusión y llamada.
    assert [s["kind"] for s in data["sections"]] == [
        "hook",
        "promise",
        "intro",
        "development",
        "development",
        "development",
        "climax",
        "conclusion",
        "cta",
    ]
    assert data["sections"][3]["title"] == "Parte 3"
    # Fuentes inexistentes (99) descartadas; hay 2 fuentes en la investigación.
    assert data["sections"][1]["paragraphs"][0]["sources"] == [1]
    assert data["target_words"] == 1100
    assert data["words"] > 0
    with SessionLocal() as db:
        assert db.get(Project, 1).status == "Guion"

    page = logged_in.get("/proyectos/1/guion").text
    assert "Enron quebró en 2001" in page
    assert "Gancho" in page


def test_automatic_mode_runs_until_script(logged_in, ai):
    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    data = script_data()
    assert data is not None
    assert data["title"] == "Título 0-0"  # eligió el primer enfoque y título


def test_manual_mode_does_not_chain(logged_in, ai):
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    assert jobs.get_result(SessionLocal(), 1, "strategy") is None


def test_script_requires_choice(logged_in, ai):
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    logged_in.post("/proyectos/1/etapas/strategy")
    run_all()
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    with SessionLocal() as db:
        job = db.query(Job).filter_by(stage="script").one()
        assert job.status == "failed"
        assert "elige uno de los enfoques" in job.error


@pytest.fixture
def with_script(logged_in, ai):
    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    return logged_in


def first_paragraph_id(index=1):
    return script_data()["sections"][1]["paragraphs"][0]["id"]


def test_edit_paragraph_by_hand(with_script):
    pid = first_paragraph_id()
    r = with_script.post(
        f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": "Texto mío."}
    )
    assert "Texto mío." in r.text
    assert script_data()["sections"][1]["paragraphs"][0]["text"] == "Texto mío."


def test_rewrite_paragraph_with_ai(with_script):
    pid = first_paragraph_id()
    before = script_data()["sections"][1]["paragraphs"][1]["text"]
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "expand"})
    data = script_data()
    paragraph = data["sections"][1]["paragraphs"][0]
    assert paragraph["text"] == "Párrafo reescrito por la IA."
    assert paragraph["sources"] == [2]  # la 7 no existe
    assert paragraph["id"] == pid  # el párrafo conserva su identidad
    assert data["sections"][1]["paragraphs"][1]["text"] == before  # el resto no cambia


def test_delete_paragraph(with_script):
    pid = first_paragraph_id()
    with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "delete"})
    assert all(p["id"] != pid for s in script_data()["sections"] for p in s["paragraphs"])


def test_ai_error_on_paragraph_is_shown(with_script, monkeypatch):
    def fail(*args):
        raise ProviderError("Google está saturado.")

    monkeypatch.setattr(stages_web, "rewrite_with_ai", fail)
    pid = first_paragraph_id()
    r = with_script.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "regenerate"})
    assert r.status_code == 400
    assert "Google está saturado" in r.text


def test_changed_choice_warns_script_is_outdated(with_script):
    with_script.post("/proyectos/1/estrategia/elegir", data={"concept": 2, "title": 0})
    assert "Has cambiado de enfoque" in with_script.get("/proyectos/1/guion").text


def test_stage_pages_require_login(client):
    for url in ["/proyectos/1/investigacion", "/proyectos/1/estrategia", "/proyectos/1/guion"]:
        assert client.get(url, follow_redirects=False).status_code == 303


def test_overview_suggests_next_step(logged_in, ai):
    make_project(logged_in, "manual")
    assert "Investigar el tema" in logged_in.get("/proyectos/1").text
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    assert "Proponer enfoques" in logged_in.get("/proyectos/1").text


# ---------------------------------------------------------------- extensión del guion


class ShortWriter(FakeAI):
    """Escribe secciones demasiado cortas la primera vez, como los modelos rápidos."""

    def __init__(self):
        super().__init__()
        self.expansions = 0

    def generate_json(self, prompt, schema):
        from app.pipeline.script import Paragraph, SectionDraft

        if schema is SectionDraft:
            if "debería tener unas" in prompt:
                self.expansions += 1
                import re

                target = int(re.search(r"debería tener unas (\d+)", prompt).group(1))
                return SectionDraft(paragraphs=[Paragraph(text="dato " * target, sources=[1])])
            return SectionDraft(paragraphs=[Paragraph(text="Muy corto.", sources=[])])
        return super().generate_json(prompt, schema)


def test_long_video_reaches_target_length(logged_in, monkeypatch):
    from app.models import WORDS_BY_DURATION

    writer = ShortWriter()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: writer)
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        db.get(Project, 1).duration = "10–15 min"
        db.commit()
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    logged_in.post("/proyectos/1/etapas/strategy")
    run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script")
    run_all()

    data = script_data()
    sections = len(data["sections"])
    assert sections == 10  # 4 secciones de desarrollo para 10–15 min
    assert writer.expansions == sections  # todas salieron cortas y se alargaron
    assert data["words"] >= WORDS_BY_DURATION["10–15 min"] * 0.95
    assert data["minutes"] >= 12


def test_plan_sections_adds_up():
    from app.models import WORDS_BY_DURATION
    from app.pipeline.script import plan_sections

    for duration, total in WORDS_BY_DURATION.items():
        plan = plan_sections(duration)
        assert abs(sum(p["words"] for p in plan) - total) <= total * 0.1
    assert [p["kind"] for p in plan_sections("Short")] == ["hook", "development", "cta"]


def test_temporary_error_while_writing_is_retried(monkeypatch):
    from app.pipeline import script as script_module

    waits = []
    monkeypatch.setattr(script_module, "SLEEP", waits.append)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("Límite por minuto.", transient=True)
        return "ok"

    assert script_module._with_retries(flaky) == "ok"
    assert waits == [20, 40]

    def broken():
        raise ProviderError("Clave inválida.")

    with pytest.raises(ProviderError):
        script_module._with_retries(broken)

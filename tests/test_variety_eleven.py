from types import SimpleNamespace

import pytest

from app import jobs, stages_web
from app.db import SessionLocal
from app.models import Project
from app.pipeline.monetization import project_review, review
from app.pipeline.script import pick_structure
from app.pipeline.seo import voice_credit
from app.settings_store import save_api_key
from app.stages_web import eleven_plan
from tests.test_elevenlabs import FakeEleven
from tests.test_projects import project_data
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def check(qc, key):
    return next(c for c in qc["checks"] if c["key"] == key)


# ---------------------------------------------------------------- estructuras


def test_pick_structure_prefers_unused_then_oldest():
    assert pick_structure([]) == "cronologia"
    assert pick_structure(["cronologia"]) == "auge_caida"
    used = ["investigacion", "rivalidad", "errores", "auge_caida", "cronologia"]
    assert pick_structure(used) == "cronologia"  # la que hace más tiempo que no se usa


def test_second_video_gets_a_different_structure(with_script):  # noqa: F811
    from tests.test_projects import brand_channel

    assert result("script")["params"]["structure"] == "cronologia"
    brand_channel()
    with_script.post("/proyectos/nuevo", data=project_data(automation_mode="manual"))
    with_script.post("/proyectos/2/etapas/research")
    run_all()
    with_script.post("/proyectos/2/etapas/strategy")
    run_all()
    with_script.post("/proyectos/2/estrategia/elegir", data={"concept": 0, "title": 0})
    with_script.post("/proyectos/2/etapas/script")
    run_all()
    with SessionLocal() as db:
        second = jobs.get_result(db, 2, "script")
        assert second["params"]["structure"] == "auge_caida"
        assert check(project_review(db, db.get(Project, 2)), "structure")["status"] == "ok"
    page = with_script.get("/proyectos/2/guion").text
    assert "Estructura de este guion: <strong>Ascenso y caída</strong>" in page

    # Si se elige a mano la misma del último vídeo, el control de calidad lo avisa.
    with_script.post("/proyectos/2/etapas/script", data={"structure": "cronologia"})
    run_all()
    with SessionLocal() as db:
        qc = project_review(db, db.get(Project, 2))
    assert check(qc, "structure")["status"] == "warn"
    assert "Misma estructura" in check(qc, "structure")["title"]


def test_script_prompt_includes_the_structure(logged_in, ai, monkeypatch):  # noqa: F811
    from tests.test_strategy_script import make_project

    prompts = []
    original = ai.generate_json

    def spy(prompt, schema):
        prompts.append(prompt)
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", spy)
    make_project(logged_in, "manual")
    from tests.test_projects import brand_channel

    brand_channel()
    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/1/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script", data={"structure": "errores"})
    run_all()
    outline = next(p for p in prompts if "Haz el ESQUEMA" in p)
    assert "Estructura narrativa: Los errores clave." in outline


# ---------------------------------------------------------------- ElevenLabs gratis


class FreeEleven(FakeEleven):
    def credits(self):
        return {"used": 0, "limit": 10000, "left": self.left, "tier": "free"}


@pytest.mark.parametrize(("fake", "tier"), [(FreeEleven, "free"), (FakeEleven, "starter")])
def test_eleven_plan_is_saved_and_checked(with_script, monkeypatch, fake, tier):  # noqa: F811
    monkeypatch.setattr(jobs, "get_voice_provider", lambda *a, **k: fake(left=100_000))
    with_script.post("/proyectos/1/etapas/voice", data={"voice": "eleven:abc123XYZ"})
    run_all()
    voice = result("voice")
    assert voice["eleven_tier"] == tier
    with SessionLocal() as db:
        qc = project_review(db, db.get(Project, 1))
    if tier == "free":
        assert check(qc, "voice")["status"] == "warn"
        assert check(qc, "voice")["title"] == "ElevenLabs con plan gratis"
        assert voice_credit(voice) == "🎙️ Voz creada con ElevenLabs (elevenlabs.io)."
    else:
        assert check(qc, "voice")["status"] == "ok" and voice_credit(voice) == ""


def test_voice_credit_rules():
    assert voice_credit(None) == "" and voice_credit({"provider": "piper"}) == ""
    assert voice_credit({"provider": "elevenlabs"})  # plan desconocido: se cita por si acaso


def test_eleven_plan_counts_videos():
    plan = eleven_plan({"left": 9000, "limit": 10000, "tier": "free"}, 4000)
    assert plan == {"free": True, "videos": 2, "videos_saving": 4, "month_saving": 5}
    assert eleven_plan(None, 4000) is None and eleven_plan({"left": 1, "limit": 1}, 0) is None


def test_voice_page_explains_the_free_plan(with_script, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        jobs, "eleven_voices", lambda db: ([{"id": "eleven:abc123XYZ", "label": "Mateo"}], None)
    )
    monkeypatch.setattr(
        stages_web.ElevenLabsVoices,
        "credits",
        lambda self: {"left": 10000, "limit": 10000, "tier": "free"},
    )
    with SessionLocal() as db:
        save_api_key(db, "elevenlabs", "sk_prueba")
    page = with_script.get("/proyectos/1/voz").text
    assert "Con lo que te queda este mes te alcanza para" in page
    assert "Plan gratis de ElevenLabs" in page and "no permite monetizar" in page


def test_unknown_plan_still_warns():
    results = {"script": {"sections": []}, "voice": {"provider": "elevenlabs"}}
    qc = review(SimpleNamespace(duration="10–15 min", title="x"), results, [])
    assert check(qc, "voice")["status"] == "warn"


def test_new_project_defaults_to_long_videos(logged_in):
    from tests.test_projects import create_channel

    create_channel(logged_in)
    page = logged_in.get("/proyectos/nuevo").text
    assert "<option selected>10–15 min</option>" in page
    assert "Recomendado: 10–15 min" in page


@pytest.fixture(autouse=True)
def _ai(ai):  # noqa: F811
    return ai


def test_jarvis_reminds_to_pay_elevenlabs_when_close(with_script, monkeypatch):  # noqa: F811
    from app import coach, info

    monkeypatch.setattr(jobs, "get_voice_provider", lambda *a, **k: FreeEleven(left=100_000))
    with_script.post("/proyectos/1/etapas/voice", data={"voice": "eleven:abc123XYZ"})
    run_all()
    monkeypatch.setattr(info, "youtube", lambda db: {"subscribers": 300})
    with SessionLocal() as db:
        assert not any("ElevenLabs" in t for t in coach.monetization_path(db)["tips"])
    monkeypatch.setattr(info, "youtube", lambda db: {"subscribers": 800})
    with SessionLocal() as db:
        assert "ElevenLabs al plan de pago" in coach.monetization_path(db)["tips"][0]

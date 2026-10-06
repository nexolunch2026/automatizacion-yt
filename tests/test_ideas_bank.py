import pytest

from app import assistant, ideas_bank
from app.assistant import Incoming, quick_intent
from app.db import SessionLocal
from app.models import Project
from app.pipeline.script import SECTION_GUIDES, SECTION_LABELS, STRUCTURES
from app.providers.ai import ProviderError
from tests.test_assistant import IdeaList, JarvisAI, ai  # noqa: F401
from tests.test_projects import create_channel
from tests.test_strategy_script import make_project, run_all


def test_bank_is_well_formed():
    assert len(ideas_bank.IDEAS) >= 80
    topics = [i["topic"] for i in ideas_bank.IDEAS]
    assert len(set(topics)) == len(topics)
    for idea in ideas_bank.IDEAS:
        assert idea["format"] in STRUCTURES and idea["format"] in ideas_bank.FORMAT_LABELS
        assert idea["region"] in ("Mundo", "España", "Latinoamérica")
        assert idea["hook"].endswith(".") and len(idea["topic"]) <= 100
    regions = {i["region"] for i in ideas_bank.IDEAS}
    assert regions == {"Mundo", "España", "Latinoamérica"}
    spanish = [i for i in ideas_bank.IDEAS if i["region"] != "Mundo"]
    assert len(spanish) >= 50  # sobre todo España y Latinoamérica
    brands = [ideas_bank._brand(i["topic"]) for i in ideas_bank.IDEAS]
    for a in brands:  # una marca hecha no debe tachar otra distinta
        assert not [b for b in brands if b != a and a in b], a


def test_progress_counts_the_stories_already_made():
    assert ideas_bank.progress([]) == (0, len(ideas_bank.IDEAS))
    made, _ = ideas_bank.progress(["La caída de Blockbuster", "Bankia y su rescate"])
    assert made == 2


def test_fresh_ideas_vary_formats_and_regions():
    ideas = ideas_bank.fresh_ideas([])
    assert len(ideas) == 5
    assert len({i["format"] for i in ideas}) == 5  # un formato distinto cada una
    assert all(a["region"] != b["region"] for a, b in zip(ideas, ideas[1:], strict=False))


def test_fresh_ideas_skip_what_is_done_and_filter_region():
    done = ["La caída de Blockbuster", "Kodak y la cámara digital"]
    topics = " ".join(i["topic"] for i in ideas_bank.fresh_ideas(done, limit=40))
    assert "Blockbuster" not in topics and "Kodak" not in topics
    spain = ideas_bank.fresh_ideas([], "España", limit=40)
    assert spain and all(i["region"] == "España" for i in spain)


@pytest.mark.parametrize(
    ("text", "region"),
    [("banco de ideas", ""), ("Ideas de España", "España"), ("ideas latinas", "Latinoamérica")],
)
def test_understands_bank_phrases(text, region):
    intent = quick_intent(text)
    assert intent.action == "idea_bank" and intent.topic == region


def test_bank_idea_becomes_a_video(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    from tests.test_projects import brand_channel

    brand_channel()  # el banco de historias es de marcas
    with SessionLocal() as db:
        reply = assistant.handle(db, Incoming(chat_id=1, text="ideas de España"), trusted=True)[0]
        assert "Banco de historias — España" in reply.text and "🪝" in reply.text
        first = reply.text.split("<b>")[2].split("</b>")[0]
        assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)
        assert db.query(Project).filter_by(topic=first).count() == 1
        again = assistant.bank_replies(db, "España")[0].text
    assert first not in again  # ya hecho: no se vuelve a ofrecer


def test_ideas_fall_back_to_the_bank_when_gemini_fails(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    from tests.test_projects import brand_channel

    brand_channel()

    def broken(self, prompt, schema):
        if schema is IdeaList:
            raise ProviderError("Google está saturado.", transient=True)
        return JarvisAI.generate_json(self, prompt, schema)

    monkeypatch.setattr(JarvisAI, "generate_json", broken)
    with SessionLocal() as db:
        reply = assistant.handle(db, Incoming(chat_id=1, text="ideas"), trusted=True)[0]
    assert "Banco de historias" in reply.text


def test_best_practices_reach_the_prompts(logged_in, ai, monkeypatch):  # noqa: F811
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
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    strategy = next(p for p in prompts if "Propón 3 enfoques" in p)
    assert "60 caracteres" in strategy and "nunca lo repite" in strategy
    hook = next(p for p in prompts if "ESCRIBE AHORA SOLO la sección 1:" in p)
    assert SECTION_GUIDES["hook"] in hook
    ending = next(p for p in prompts if f"«{SECTION_LABELS['conclusion']}:" in p)
    assert "La lección de la marca" in ending


def test_every_section_has_a_guide():
    assert set(SECTION_GUIDES) == set(SECTION_LABELS)

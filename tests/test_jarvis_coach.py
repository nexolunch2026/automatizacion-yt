from datetime import datetime, timedelta

import pytest

from app import agenda, assistant, coach, info
from app.assistant import Incoming, Intent, quick_intent
from app.db import SessionLocal
from app.models import Job, Project, StageResult, Video, VideoStat
from app.settings_store import set_setting
from tests.test_assistant import IdeaList, JarvisAI, ai  # noqa: F401
from tests.test_strategy_script import make_project, run_all

NOW = datetime(2026, 10, 3, 12, 0)


def ask(db, text="", button=""):
    return assistant.handle(db, Incoming(chat_id=1, text=text, button=button), trusted=True)


@pytest.mark.parametrize(
    ("text", "action", "topic"),
    [
        ("¿Qué hago ahora?", "next_step", ""),
        ("Jarvis, siguiente paso", "next_step", ""),
        ("¿Cuánto me falta para monetizar?", "monetize", ""),
        ("monetización", "monetize", ""),
        ("¿Se puede monetizar?", "review", ""),
        ("control de calidad", "review", ""),
        ("Revisa el vídeo de Nokia", "review", "nokia"),
        ("control de calidad de la caída de Kodak", "review", "caida de kodak"),
    ],
)
def test_understands_coach_phrases(text, action, topic):
    intent = quick_intent(text)
    assert intent.action == action and intent.topic == topic


def test_next_step_with_a_button_that_does_it(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        replies = ask(db, "qué hago ahora")
    assert "Investigar el tema" in replies[0].buttons[0][0][0]
    assert replies[0].buttons[0][0][1] == "go:1:research"

    with SessionLocal() as db:
        reply = ask(db, button="go:1:research")[0]
        assert "En marcha: investigar el tema" in reply.text
        assert db.query(Job).filter_by(stage="research").count() == 1
    run_all()

    with SessionLocal() as db:
        assert "proponer enfoques" in ask(db, "siguiente paso")[0].text
        assert agenda.studio_tasks(db)[0]["kind"] == "next"  # también en la pantalla
    logged_in.post("/proyectos/1/etapas/strategy")
    run_all()
    with SessionLocal() as db:
        reply = ask(db, "qué hago")[0]
        assert "elegir uno de los 3 enfoques" in reply.text
        assert reply.buttons[0][0][1] == "concepts:1"
        concepts = ask(db, button="concepts:1")[0]
        assert concepts.buttons[0][0][1] == "pick:1:0"


def test_next_step_when_nothing_is_pending(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        reply = ask(db, "qué hago ahora")[0]
    assert "No tienes vídeos a medias" in reply.text


def test_review_finds_the_project_by_name(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        assert "Todavía no hay ningún vídeo" in ask(db, "¿se puede monetizar?")[0].text
    make_project(logged_in, "manual")
    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/1/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    with SessionLocal() as db:
        assert "Nota de monetización" in ask(db, "¿se puede monetizar?")[0].text
        title = db.get(Project, 1).title.split()[0]
        assert "Nota de monetización" in ask(db, f"revisa el vídeo de {title}")[0].text
        assert "No encontré ningún vídeo" in ask(db, "revisa el vídeo de Blockbuster")[0].text


def _published_video(db, project_id, views, retention=None):
    db.add(
        StageResult(
            project_id=project_id,
            stage="edit",
            data={"renders": {"final": {"seconds": 600}}, "last": "final"},
        )
    )
    db.add(Video(video_id="abcdefghijk", title="Kodak", published="2026-09-01",
                 project_id=project_id, retention=retention))  # fmt: skip
    db.add(VideoStat(video_id="abcdefghijk", taken_at=NOW, views=views))
    db.commit()


def test_watch_hours_estimate(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _published_video(db, 1, views=6000, retention=50)
        hours = coach.watch_hours(db, NOW)
    # 6000 visitas × 10 min × 50 % = 500 horas
    assert hours["hours"] == 500 and hours["pct"] == 12 and hours["assumed"] == 0


def test_monetization_path_with_growth_and_eta(logged_in, ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(info, "youtube", lambda db: {"subscribers": 400})
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _published_video(db, 1, views=1200)  # sin % visto: se supone un 35 %
        day = lambda n: (NOW - timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731
        set_setting(db, "subs_history", f'[["{day(20)}", 200], ["{day(0)}", 400]]')
        path = coach.monetization_path(db, NOW)
        assert path["subs_pct"] == 40 and path["growth"] == 10
        assert path["eta"].date() == (NOW + timedelta(days=60)).date()
        assert path["hours"]["assumed"] == 1 and path["hours"]["hours"] == 70
        assert any("Shorts" in t for t in path["tips"]) is False  # van mejor los subs
        assert any("10–15 minutos" in t for t in path["tips"])
        reply = ask(db, "¿cuánto me falta para monetizar?")[0]
    assert "400 de 1.000 suscriptores (40 %)" in reply.text
    assert "+10 al día" in reply.text and "4.000 horas" in reply.text


def test_monetization_works_offline(logged_in, monkeypatch):
    def offline(db):
        raise OSError("sin internet")

    monkeypatch.setattr(info, "youtube", offline)
    with SessionLocal() as db:
        text = assistant.monetization_text(coach.monetization_path(db, NOW))
    assert "No pude leer los suscriptores" in text


def test_monetization_done():
    path = {"done": True}
    assert "Ya cumples los requisitos" in assistant.monetization_text(path)


def test_help_and_briefing_offer_the_coach(logged_in, ai):  # noqa: F811
    help_buttons = [b for row in assistant.help_replies()[0].buttons for b in row]
    assert ("👉 ¿Qué hago ahora?", "next") in help_buttons
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    with SessionLocal() as db:
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        reply = assistant.briefing(db, NOW.replace(hour=10))[0]
    assert "👉 Lo siguiente:" in reply.text and "proponer enfoques" in reply.text


def test_ideas_come_in_different_formats(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    original = JarvisAI.generate_json

    def with_formats(self, prompt, schema):
        if schema is IdeaList:
            assert "FORMATO distinto" in prompt
            return IdeaList(ideas=[{"topic": "Nokia", "hook": "x", "format": "ascenso y caída"}])
        return original(self, prompt, schema)

    monkeypatch.setattr(JarvisAI, "generate_json", with_formats)
    with SessionLocal() as db:
        reply = assistant._act(db, Intent(action="ideas"), "ideas")[0]
    assert "<i>(ascenso y caída)</i>" in reply.text

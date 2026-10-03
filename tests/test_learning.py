import pytest

from app import learning, learning_web
from app.assistant import Incoming, handle, quick_intent
from app.db import SessionLocal
from app.providers.ai import ProviderError
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project, run_all

LESSON = learning.Lesson(
    title="Cómo Monetizar Un Canal De YouTube En 5 Días",
    channel="Canal de prueba",
    summary="Explica los requisitos del Programa de Socios.",
    good=["Sube 3 vídeos antes de pedir la monetización", "Conecta AdSense pronto"],
    apply=["Termina cada vídeo con una pregunta concreta para los comentarios"],
    careful=["Monetizar en 5 días no es realista para un canal nuevo"],
    ideas=["La caída de un canal que compró suscriptores"],
)


class Watcher:
    def __init__(self):
        self.urls = []

    def watch_video(self, url, prompt, schema):
        self.urls.append(url)
        assert "auténtico" in prompt and schema is learning.Lesson
        return LESSON


@pytest.mark.parametrize(
    ("text", "link"),
    [
        ("https://youtu.be/mi2wUjaNUtI?si=IkbumYmntQSUKUel", "mi2wUjaNUtI"),
        ("mira esto https://www.youtube.com/watch?v=mi2wUjaNUtI&t=30s", "mi2wUjaNUtI"),
        ("https://m.youtube.com/shorts/abcdefghijk", "abcdefghijk"),
        ("hola jarvis", None),
    ],
)
def test_find_link(text, link):
    found = learning.find_link(text)
    assert found == (f"https://www.youtube.com/watch?v={link}" if link else None)


def test_learn_toggle_rules_and_delete(logged_in):
    with SessionLocal() as db:
        watcher = Watcher()
        item = learning.learn(db, "https://www.youtube.com/watch?v=mi2wUjaNUtI", watcher)
        assert item["good"] and not item["apply_in_scripts"]
        assert learning.script_rules(db) == []
        assert learning.toggle_apply(db, item["id"]) is True
        assert learning.script_rules(db) == LESSON.apply
        learning.learn(db, "https://www.youtube.com/watch?v=mi2wUjaNUtI", watcher)
        assert len(learning.lessons(db)) == 1  # el mismo vídeo no se duplica
        learning.delete(db, learning.lessons(db)[0]["id"])
        assert learning.lessons(db) == [] and learning.toggle_apply(db, "nada") is None


def test_learning_page(logged_in, monkeypatch):
    watcher = Watcher()
    monkeypatch.setattr(
        learning_web, "watch_with_ai", lambda db, url: learning.learn(db, url, watcher)
    )
    r = logged_in.post("/aprender", data={"url": "https://youtu.be/mi2wUjaNUtI?si=x"})
    assert r.status_code == 200 and "Lo bueno" in r.text and "Para tu canal" in r.text
    assert watcher.urls == ["https://www.youtube.com/watch?v=mi2wUjaNUtI"]
    bad = logged_in.post("/aprender", data={"url": "no es un enlace"})
    assert bad.status_code == 400 and "no parece un enlace" in bad.text

    def fails(db, url):
        raise ProviderError("Se agotó el uso gratuito de Gemini de hoy.")

    monkeypatch.setattr(learning_web, "watch_with_ai", fails)
    r = logged_in.post("/aprender", data={"url": "https://youtu.be/abcdefghijk"})
    assert r.status_code == 400 and "Se agotó el uso gratuito" in r.text
    assert "🎓 Aprender" in logged_in.get("/").text  # en el menú


def test_jarvis_watches_links_and_lessons_reach_scripts(logged_in, ai, monkeypatch):  # noqa: F811
    watcher = Watcher()
    monkeypatch.setattr(type(ai), "watch_video", Watcher.watch_video, raising=False)
    ai.urls = watcher.urls
    assert quick_intent("https://youtu.be/mi2wUjaNUtI").action == "learn_video"
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        link = Incoming(chat_id=1, text="https://youtu.be/mi2wUjaNUtI")
        reply = handle(db, link, trusted=True)[0]
        assert "Lo bueno" in reply.text and reply.buttons[0][0][1].startswith("lesson:")
        done = handle(db, Incoming(chat_id=1, button=reply.buttons[0][0][1]), trusted=True)[0]
        assert "los guiones nuevos" in done.text
    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/1/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    prompts = []
    original = ai.generate_json
    monkeypatch.setattr(ai, "generate_json", lambda p, s: prompts.append(p) or original(p, s))
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    assert any(LESSON.apply[0] in p for p in prompts)

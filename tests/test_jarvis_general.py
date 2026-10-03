import pytest

from app import assistant
from app.assistant import Incoming, Intent, quick_intent
from app.db import SessionLocal
from app.providers.ai import GroundedText, ProviderError, Source
from tests.test_assistant import JarvisAI, ai  # noqa: F401


def ask(db, text):
    return assistant.handle(db, Incoming(chat_id=1, text=text), trusted=True)


@pytest.mark.parametrize(
    ("text", "action", "task"),
    [
        ("Recuerda que trabajo de 12 a 10", "remember", "trabajo de 12 a 10"),
        ("acuérdate de que mi amigo se llama Juan", "remember", "mi amigo se llama Juan"),
        ("¿Qué sabes de mí?", "memory", ""),
    ],
)
def test_memory_phrases(text, action, task):
    intent = quick_intent(text)
    assert (intent.action, intent.task) == (action, task)


def test_remember_and_use_in_answers(logged_in, ai, monkeypatch):  # noqa: F811
    prompts = []

    def research(self, prompt):
        prompts.append(prompt)
        return GroundedText(
            text="El Real Madrid ganó la Champions 2024 [1].",
            sources=[Source(title="uefa.com", uri="https://www.uefa.com")],
        )

    monkeypatch.setattr(JarvisAI, "grounded_research", research)
    ai.intent = Intent(action="question")
    with SessionLocal() as db:
        assert "Anotado" in ask(db, "recuerda que soy del Real Madrid")[0].text
        assert "soy del Real Madrid" in ask(db, "qué sabes de mí")[0].text
        reply = ask(db, "¿quién ganó la Champions de 2024?")[0]
    assert "Real Madrid ganó la Champions 2024." in reply.text  # sin las marcas [1]
    assert "Buscado en: uefa.com" in reply.text
    assert "soy del Real Madrid" in prompts[0]  # usa lo que sabe de Simón


def test_chat_without_reply_also_searches(logged_in, ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        JarvisAI, "grounded_research", lambda self, p: GroundedText(text="Son 42 km.")
    )
    ai.intent = Intent(action="chat", reply="")
    with SessionLocal() as db:
        assert ask(db, "¿cuánto mide un maratón?")[0].text == "Son 42 km."


def test_gemini_errors_are_explained(logged_in, ai, monkeypatch):  # noqa: F811
    def busy(db, text, chat_id=0):
        raise ProviderError("Se alcanzó el límite por minuto de Gemini.", transient=True)

    monkeypatch.setattr(assistant, "_ai_intent", busy)
    with SessionLocal() as db:
        replies = ask(db, "¿qué tiempo hace en Madrid?")
    assert len(replies) == 1
    assert "límite por minuto" in replies[0].text and "No te entendí" not in replies[0].text

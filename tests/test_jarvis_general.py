import pytest

from app import assistant, profile
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


def test_search_unavailable_falls_back_to_plain_answer(logged_in, ai, monkeypatch):  # noqa: F811
    def no_search(self, prompt):
        raise ProviderError("Error de Gemini (400).", detail="400 INVALID_ARGUMENT: search")

    monkeypatch.setattr(JarvisAI, "grounded_research", no_search)
    monkeypatch.setattr(
        JarvisAI,
        "generate_json",
        lambda self, p, s: (
            s(text="París es la capital de Francia.")
            if s is assistant.PlainAnswer
            else Intent(action="question")
        ),
    )
    with SessionLocal() as db:
        reply = ask(db, "¿cuál es la capital de Francia?")[0]
    assert "París" in reply.text and "Sin buscar en Google" in reply.text


def test_errors_show_technical_detail_and_unexpected_crashes_are_explained(
    logged_in,
    ai,  # noqa: F811
    monkeypatch,
):
    def broken(db, text, chat_id=0):
        raise ProviderError("Error de Gemini (400).", detail="400 INVALID_ARGUMENT: algo raro")

    monkeypatch.setattr(assistant, "_ai_intent", broken)
    order = logged_in.post("/jarvis/orden", data={"text": "cuéntame algo"}).json()
    assert "Detalle técnico" in order["replies"][0]["html"]
    assert "INVALID_ARGUMENT" in order["replies"][0]["html"]

    def crash(db, msg, transcribe=None, trusted=False):
        raise KeyError("campo")

    monkeypatch.setattr(assistant, "handle", crash)
    order = logged_in.post("/jarvis/orden", data={"text": "hola"}).json()
    assert "Algo falló dentro de JARVIS" in order["replies"][0]["html"]
    assert "KeyError" in order["replies"][0]["html"]


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("¿Qué película me recomiendas en el cine de Rionegro?", "question"),
        ("¿Dónde puedo comer sushi barato?", "question"),
        ("Recomiéndame una serie de misterio", "question"),
        ("¿Qué tal el clima?", None),  # tiene su habilidad: la IA la elige
        ("¿Cuánto está el dólar hoy?", None),
        ("¿Qué?", None),  # demasiado corta
    ],
)
def test_clear_questions_skip_the_classifier(text, action):
    intent = quick_intent(text)
    assert (intent.action if intent else None) == action


def test_questions_are_concrete_local_and_remember_the_talk(logged_in, ai, monkeypatch):  # noqa: F811
    from app.settings_store import set_setting

    prompts = []

    def research(self, prompt, think=True):
        prompts.append(prompt)
        return GroundedText(text="En Cinépolis San Nicolás hay función a las 19:30.")

    monkeypatch.setattr(JarvisAI, "grounded_research", research)
    with SessionLocal() as db:
        set_setting(db, "jarvis_city", "Rionegro")
        profile.save(db, "Simón", "Anatomía De Una Marca", "", "Colombia")
        ask(db, "¿Qué película me recomiendas en el cine?")
        ask(db, "¿Y a qué hora es la siguiente función?")
    assert "Simón vive en Rionegro" in prompts[0] and "Nada de «revise la cartelera»" in prompts[0]
    assert "cartelera\ncine Rionegro hoy" in prompts[0]
    assert "Creador: ¿Qué película me recomiendas en el cine?" in prompts[1]


@pytest.mark.parametrize(
    "text",
    [
        "Exactamente necesito que me digas qué películas hay en la cartelera de Procinal",
        "Quiero saber cuánto cuesta un vuelo a Cartagena",
        "Ok, recomiéndame un restaurante para hoy",
    ],
)
def test_info_requests_anywhere_go_to_search(text):
    assert quick_intent(text).action == "question"


def test_fake_refusals_are_replaced_by_a_real_search(logged_in, ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        JarvisAI, "grounded_research", lambda self, p, think=True: GroundedText(text="Hay 6 pelis.")
    )
    ai.intent = Intent(
        action="chat",
        reply="Me temo que mis sistemas no pueden acceder en tiempo real a la cartelera.",
    )
    with SessionLocal() as db:
        assert ask(db, "oye, y el cine qué")[0].text == "Hay 6 pelis."

from datetime import datetime

import pytest

from app import assistant, jobs, telegram
from app.assistant import IdeaList, Incoming, Intent, quick_intent
from app.db import SessionLocal
from app.models import Job, Project
from app.providers.ai import ProviderError
from app.settings_store import get_setting
from tests.test_projects import create_channel, project_data
from tests.test_research import FakeAI

TOPIC = "Empresas que desaparecieron misteriosamente"


class JarvisAI(FakeAI):
    def __init__(self):
        super().__init__()
        self.intent = Intent(action="chat", reply="A sus órdenes, señor.")

    def generate_json(self, prompt, schema):
        if schema is IdeaList:
            return IdeaList(
                ideas=[
                    {"topic": "La caída de Nokia", "hook": "De reina a olvidada"},
                    {"topic": "El error de Kodak", "hook": "Inventó la cámara digital"},
                ]
            )
        if schema is Intent:
            return self.intent
        if schema.__name__ == "Fact":
            return schema(fact="Nokia empezó fabricando papel en 1865.")
        return super().generate_json(prompt, schema)

    def transcribe(self, audio, mime_type):
        return f"hazme un vídeo sobre {TOPIC}"


@pytest.fixture
def ai(monkeypatch):
    fake = JarvisAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    return fake


@pytest.fixture
def studio(logged_in, ai):
    """Cuenta, canal y un chat de Telegram ya vinculado (id 42)."""
    create_channel(logged_in)
    with SessionLocal() as db:
        code = assistant.link_code(db)
        assistant.handle(db, Incoming(chat_id=42, name="Ana", text=code))
    return logged_in


def run_all():
    while jobs.process_next_job():
        pass


def talk(text="", button="", chat_id=42):
    with SessionLocal() as db:
        return assistant.handle(
            db, Incoming(chat_id=chat_id, text=text, button=button), telegram.transcribe
        )


def tick():
    with SessionLocal() as db:
        return assistant.tick(db, datetime(2026, 1, 1, 8))


# ---------------------------------------------------------------- entender órdenes


@pytest.mark.parametrize(
    ("text", "topic", "duration"),
    [
        ("Hazme un vídeo sobre la caída de Kodak", "la caída de Kodak", ""),
        ("hazme un video de 5 minutos sobre Nokia", "Nokia", "3–5 min"),
        ("/video Blockbuster", "Blockbuster", ""),
        ("Quiero un short de Tesla", "Tesla", "Short"),
        ("crea un documental acerca de Enron.", "Enron", ""),
    ],
)
def test_understands_video_requests(text, topic, duration):
    intent = quick_intent(text)
    assert intent.action == "new_video"
    assert intent.topic == topic
    assert assistant.parse_duration(intent.duration) == duration


def test_understands_other_orders():
    assert quick_intent("¿Cómo va?").action == "status"
    assert quick_intent("ideas").action == "ideas"
    assert quick_intent("cola: Nokia, Kodak; Blockbuster").topics == [
        "Nokia",
        "Kodak",
        "Blockbuster",
    ]
    assert quick_intent("piloto on").on is True
    assert quick_intent("piloto apagar").on is False
    assert quick_intent("qué tal el clima") is None  # esto lo decide la IA


def test_split_long_text():
    parts = assistant.split_text("a" * 50 + "\n" + "b" * 50 + "\n" + "c" * 120, limit=60)
    assert all(len(p) <= 60 for p in parts)
    assert "".join(parts).replace("\n", "") == "a" * 50 + "b" * 50 + "c" * 120


# ---------------------------------------------------------------- vincular


def test_unknown_chat_must_send_the_code(logged_in, ai):
    with SessionLocal() as db:
        code = assistant.link_code(db)
        replies = assistant.handle(db, Incoming(chat_id=7, text="hazme un vídeo sobre X"))
        assert "código" in replies[0].text
        assert db.query(Project).count() == 0

        replies = assistant.handle(db, Incoming(chat_id=7, name="Ana", text=f"  {code} "))
        assert "Sistemas en línea" in replies[0].text
        assert assistant.linked_chats(db) == [{"id": 7, "name": "Ana"}]
        assert assistant.link_code(db) != code  # el código ya no sirve para otro


def test_old_jobs_are_not_announced_after_linking(logged_in, ai):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    with SessionLocal() as db:
        jobs.enqueue(db, 1, "research")
    run_all()
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=9, text=assistant.link_code(db)))
    assert tick() == []


# ---------------------------------------------------------------- el vídeo completo


def test_full_video_from_the_phone(studio, ai):
    replies = talk(f"Hazme un vídeo de 5 minutos sobre {TOPIC}")
    assert "Empiezo a investigar" in replies[0].text
    with SessionLocal() as db:
        project = db.get(Project, 1)
        assert project.duration == "3–5 min" and project.automation_mode == "asistido"

    run_all()  # investiga y propone enfoques, y se para
    replies = tick()
    assert "investigación lista" in replies[0].text
    concepts = replies[1]
    assert "¿Cuál hacemos?" in concepts.text
    assert concepts.buttons[0][0] == ("1️⃣", "pick:1:0")
    assert jobs.get_result(SessionLocal(), 1, "script") is None
    assert "esperando que elijas" in talk("estado")[0].text

    replies = talk(button="pick:1:2")
    assert "Enfoque <b>Enfoque 2</b>" in replies[0].text
    run_all()  # ahora hace todo solo: guion → escenas → voz → imágenes → vídeo → textos
    with SessionLocal() as db:
        done = {j.stage for j in db.query(Job).all() if j.status == "done"}
    assert done == {
        "research",
        "strategy",
        "script",
        "storyboard",
        "voice",
        "visuals",
        "edit",
        "publish",
    }

    texts = [r.text for r in tick()]
    assert any("guion listo" in t for t in texts)
    assert any("voz grabada" in t for t in texts)
    assert any("borrador listo" in t for t in texts)
    assert any("Textos para YouTube" in t for t in texts)
    assert any("Descripción" in t for t in texts)
    assert tick() == []  # cada aviso, una sola vez


def test_video_notice_sends_a_short_preview(studio, ai):
    talk(f"hazme un vídeo sobre {TOPIC}")
    run_all()
    tick()
    talk(button="pick:1:0")
    run_all()
    video = next(r for r in tick() if r.video)
    assert video.video.name == "avance_telegram.mp4" and video.video.stat().st_size > 0
    assert video.buttons == [[("🎬 Hacer versión final", "final:1")]]

    talk(button="final:1")
    run_all()
    replies = tick()
    assert "versión final lista" in replies[0].text
    with SessionLocal() as db:  # la versión final no rehace los textos
        assert [j.stage for j in db.query(Job).all()].count("publish") == 1


def test_failure_offers_retry(studio, monkeypatch):
    def broken(db):
        raise ProviderError("Se agotó el uso gratuito de Gemini de hoy.")

    talk(f"hazme un vídeo sobre {TOPIC}")
    monkeypatch.setattr(jobs, "get_ai_provider", broken)
    run_all()
    replies = tick()
    assert "falló investigación" in replies[0].text
    assert "uso gratuito" in replies[0].text
    assert replies[0].buttons == [[("🔁 Reintentar", "retry:1:research")]]

    talk(button="retry:1:research")
    with SessionLocal() as db:
        assert jobs.latest_jobs(db, 1)["research"].status == "queued"


def test_voice_note_is_understood(studio):
    with SessionLocal() as db:
        msg = Incoming(chat_id=42, audio=b"OggS...", audio_type="audio/ogg")
        replies = assistant.handle(db, msg, telegram.transcribe)
    assert replies[0].text.startswith("🎧 Entendí")
    assert "Empiezo a investigar" in replies[1].text


def test_free_chat_and_ideas(studio, ai):
    assert talk("¿quién eres?")[0].text == "A sus órdenes, señor."

    replies = talk("dame ideas")
    assert "La caída de Nokia" in replies[0].text
    assert replies[0].buttons[-1] == [("🛫 Todas a la cola", "idea:all")]
    talk(button="idea:1")
    with SessionLocal() as db:
        assert db.get(Project, 1).topic == "El error de Kodak"

    talk(button="idea:all")
    with SessionLocal() as db:
        assert assistant.autopilot_state(db)["queue"] == ["La caída de Nokia", "El error de Kodak"]


# ---------------------------------------------------------------- piloto automático


def test_autopilot_makes_one_video_a_day(studio, ai):
    talk(f"cola: {TOPIC}, Otro tema")
    talk("piloto on")
    with SessionLocal() as db:
        state = assistant.autopilot_state(db)
        state["hour"] = 9
        assistant.save_autopilot(db, state)
        assert assistant.autopilot_tick(db, datetime(2026, 1, 1, 8)) == []  # aún no es la hora
        replies = assistant.autopilot_tick(db, datetime(2026, 1, 1, 9, 5))
        assert "Piloto automático" in replies[0].text
        assert db.get(Project, 1).automation_mode == "automatico"
        assert assistant.autopilot_tick(db, datetime(2026, 1, 1, 22)) == []  # uno al día

    run_all()  # en automático elige el enfoque y llega hasta los textos
    with SessionLocal() as db:
        assert jobs.get_result(db, 1, "publish")
        assert assistant.autopilot_state(db)["queue"] == ["Otro tema"]
        assert assistant.autopilot_tick(db, datetime(2026, 1, 1, 23)) == []
        assert assistant.autopilot_tick(db, datetime(2026, 1, 2, 10))  # al día siguiente sí


def test_autopilot_waits_if_something_is_running(studio, ai):
    talk(f"hazme un vídeo sobre {TOPIC}")  # queda en cola
    talk("cola: Otro tema")
    talk("piloto on")
    with SessionLocal() as db:
        assert assistant.autopilot_tick(db, datetime(2026, 1, 1, 12)) == []


# ---------------------------------------------------------------- Telegram


class FakeTelegram:
    def __init__(self, updates):
        self.updates = updates
        self.sent = []
        self.offset = None

    def get_updates(self, offset, timeout=0):
        self.offset = offset
        updates, self.updates = self.updates, []
        return updates

    def send(self, chat_id, reply):
        self.sent.append((chat_id, reply))

    def answer_button(self, callback_id):
        pass

    def typing(self, chat_id):
        pass

    def download(self, file_id):
        return b"audio"


def test_bot_links_chat_and_remembers_offset(logged_in, ai):
    create_channel(logged_in)
    with SessionLocal() as db:
        code = assistant.link_code(db)
        api = FakeTelegram(
            [
                {
                    "update_id": 10,
                    "message": {"chat": {"id": 5}, "from": {"first_name": "Ana"}, "text": code},
                }
            ]
        )
        telegram.poll_once(db, api)
        assert api.sent[0][0] == 5 and "Sistemas en línea" in api.sent[0][1].text
        assert get_setting(db, "telegram_offset") == "11"

        api.updates = [
            {
                "update_id": 11,
                "callback_query": {
                    "id": "c1",
                    "data": "status",
                    "from": {"first_name": "Ana"},
                    "message": {"chat": {"id": 5}},
                },
            },
            {"update_id": 12, "message": {"chat": {"id": 5}, "voice": {"file_id": "f"}}},
        ]
        api.sent.clear()
        telegram.poll_once(db, api)
        assert api.offset == 11
        texts = [r.text for _, r in api.sent]
        assert "Todo tranquilo" in texts[0]
        assert texts[1].startswith("🎧 Entendí")


def test_bot_sends_notices_to_every_linked_chat(studio, ai):
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=43, text=assistant.link_code(db)))
    talk(f"hazme un vídeo sobre {TOPIC}")
    run_all()
    with SessionLocal() as db:
        api = FakeTelegram([])
        telegram.poll_once(db, api)
    assert {chat for chat, _ in api.sent} == {42, 43}


# ---------------------------------------------------------------- web


def test_jarvis_page_and_web_chat(studio, monkeypatch):
    page = studio.get("/jarvis").text
    assert "JARVIS" in page and "BotFather" in page

    data = studio.post("/jarvis/orden", data={"text": f"hazme un vídeo sobre {TOPIC}"}).json()
    assert "Empiezo a investigar" in data["replies"][0]["html"]
    assert "Investigación: en cola" in data["status"]


def test_connect_telegram_token(logged_in, monkeypatch):
    r = logged_in.post("/jarvis/telegram", data={"token": "hola"})
    assert r.status_code == 400 and "no parece un token" in r.text

    monkeypatch.setattr(telegram, "check_token", lambda token: "jarvis_prueba_bot")
    r = logged_in.post("/jarvis/telegram", data={"token": "123456789:AAH" + "x" * 30})
    assert "¡Bot conectado!" in r.text and "@jarvis_prueba_bot" in r.text
    with SessionLocal() as db:
        assert assistant.link_code(db) in r.text


def test_save_autopilot_from_the_web(logged_in):
    logged_in.post("/jarvis/piloto", data={"queue": "Nokia\n\n Kodak \n", "hour": 7, "on": "1"})
    with SessionLocal() as db:
        state = assistant.autopilot_state(db)
    assert state["queue"] == ["Nokia", "Kodak"] and state["hour"] == 7 and state["on"]


def test_telegram_api_requests(tmp_path):
    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        if "bad" in str(request.url):
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        return httpx.Response(200, json={"ok": True, "result": {"username": "jarvis_bot"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    api = telegram.TelegramAPI("123:abc", client)
    assert api.get_me()["username"] == "jarvis_bot"

    api.send(5, assistant.Reply("<b>Hola</b>", buttons=[[("1️⃣", "pick:1:0")]]))
    import json

    body = json.loads(calls[-1].content)
    assert calls[-1].url.path.endswith("/sendMessage")
    assert body["parse_mode"] == "HTML"
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "pick:1:0"

    clip = tmp_path / "avance.mp4"
    clip.write_bytes(b"0" * 100)
    api.send(5, assistant.Reply("Mira", buttons=[[("🎬", "final:1")]], video=clip))
    assert calls[-1].url.path.endswith("/sendVideo")
    assert b'name="video"' in calls[-1].content and b"final:1" in calls[-1].content

    with pytest.raises(ProviderError, match="token"):
        telegram.TelegramAPI("bad", client).get_me()


def test_good_morning_once_a_day(studio):
    with SessionLocal() as db:
        assert assistant.briefing(db, datetime(2026, 1, 1, 8)) == []  # antes de las 9
        replies = assistant.briefing(db, datetime(2026, 1, 1, 9))
        assert "Buenos días" in replies[0].text and "Todo tranquilo" in replies[0].text
        assert assistant.briefing(db, datetime(2026, 1, 1, 15)) == []
        assert assistant.briefing(db, datetime(2026, 1, 2, 9))

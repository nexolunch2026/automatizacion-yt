import pytest

from app import jarvis_voice, telegram
from app.assistant import Incoming
from app.db import SessionLocal
from app.pipeline.render import run_ffmpeg
from app.providers.ai import ProviderError
from tests.test_assistant import FakeTelegram, JarvisAI  # noqa: F401
from tests.test_projects import create_channel


@pytest.fixture
def fake_microsoft(monkeypatch, tmp_path):
    calls = []

    def tts(text, voice, out):
        calls.append((text, voice))
        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=180:duration=1", "-ar", "24000", str(out)])

    monkeypatch.setattr(jarvis_voice, "microsoft_tts", tts)
    monkeypatch.setattr(jarvis_voice, "CACHE_DIR", tmp_path / "cache")
    return calls


def test_speaks_with_effect_and_caches(fake_microsoft):
    first = jarvis_voice.speak("Buenos días, señor.")
    assert first.suffix == ".mp3" and first.stat().st_size > 1000
    again = jarvis_voice.speak("Buenos  días,   señor.")
    assert again == first and len(fake_microsoft) == 1  # de la caché
    natural = jarvis_voice.speak("Buenos días, señor.", effect="none")
    assert natural != first
    assert fake_microsoft[0][1] == "es-ES-AlvaroNeural"
    jarvis_voice.speak("Hola", voice="voz-inventada")
    assert fake_microsoft[-1][1] == "es-ES-AlvaroNeural"


def test_eleven_engine_uses_the_account_voice(fake_microsoft):
    from tests.conftest import silent_wav

    class Eleven:
        def synthesize(self, text, voice, speed):
            self.voice = voice
            return silent_wav(1.0, rate=22050)

    eleven = Eleven()
    path = jarvis_voice.speak("Hola", "eleven", "eleven:abc123", "jarvis", eleven)
    assert path.exists() and eleven.voice == "eleven:abc123" and fake_microsoft == []
    with pytest.raises(ProviderError, match="ElevenLabs"):
        jarvis_voice.speak("Otra", "eleven", "eleven:abc123")


def test_spoken_text_is_clean():
    html = "📝 <b>Tareas de hoy</b>\n🎬 Subir «Nokia» a YouTube &amp; más"
    assert jarvis_voice.spoken_text(html) == "Tareas de hoy Subir Nokia a YouTube & más"


def test_voice_endpoints(logged_in, fake_microsoft):
    r = logged_in.post("/jarvis/voz", data={"text": "A sus órdenes."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"

    options = logged_in.get("/jarvis/voz/opciones").json()
    assert options["prefs"]["engine"] == "microsoft"
    assert any(v["id"] == "es-CO-GonzaloNeural" for v in options["microsoft"])

    prefs = logged_in.post(
        "/jarvis/voz/preferencias",
        data={
            "engine": "microsoft",
            "voice": "es-CO-GonzaloNeural",
            "effect": "none",
            "telegram_voice": "0",
        },
    ).json()
    assert prefs == {
        "engine": "microsoft",
        "voice": "es-CO-GonzaloNeural",
        "effect": "none",
        "telegram": False,
    }
    logged_in.post("/jarvis/voz", data={"text": "Probando."})
    assert fake_microsoft[-1] == ("Probando.", "es-CO-GonzaloNeural")

    # ElevenLabs sin una voz de ElevenLabs elegida: vuelve a Microsoft
    logged_in.post("/jarvis/voz/preferencias", data={"engine": "eleven", "voice": "x"})
    logged_in.post("/jarvis/voz", data={"text": "Sigo aquí."})
    assert fake_microsoft[-1] == ("Sigo aquí.", "es-ES-AlvaroNeural")


def test_voice_failure_lets_the_screen_fall_back(logged_in, monkeypatch, tmp_path):
    def broken(text, voice, out):
        raise ProviderError("No se pudo usar la voz de Microsoft (¿hay internet?).")

    monkeypatch.setattr(jarvis_voice, "microsoft_tts", broken)
    monkeypatch.setattr(jarvis_voice, "CACHE_DIR", tmp_path)
    r = logged_in.post("/jarvis/voz", data={"text": "Hola"})
    assert r.status_code == 503 and "internet" in r.json()["error"]


def test_telegram_answers_voice_notes_with_voice(logged_in, monkeypatch, fake_microsoft):
    from app import jobs

    fake = JarvisAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    create_channel(logged_in)
    sent_voice = []

    class Api(FakeTelegram):
        def send_voice(self, chat_id, path):
            sent_voice.append((chat_id, path))

    with SessionLocal() as db:
        from app import assistant

        assistant.handle(db, Incoming(chat_id=5, text=assistant.link_code(db)))
        api = Api([{"update_id": 1, "message": {"chat": {"id": 5}, "voice": {"file_id": "f"}}}])
        telegram.poll_once(db, api)
        assert sent_voice and sent_voice[0][0] == 5 and sent_voice[0][1].suffix == ".ogg"
        assert "Empiezo a investigar" in fake_microsoft[-1][0]

        api.updates = [{"update_id": 2, "message": {"chat": {"id": 5}, "text": "estado"}}]
        telegram.poll_once(db, api)
        assert len(sent_voice) == 1  # a los mensajes escritos responde escribiendo

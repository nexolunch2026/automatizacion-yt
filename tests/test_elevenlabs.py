import io
import json
import wave

import httpx
import pytest

from app import jobs, settings_web, stages_web
from app.db import SessionLocal
from app.pipeline.voice import take_key
from app.providers.ai import ProviderError
from app.providers.voice import ElevenLabsVoices
from app.settings_store import get_setting
from tests.conftest import silent_wav
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def eleven(handler, model="eleven_multilingual_v2"):
    return ElevenLabsVoices("sk_prueba", model=model, transport=httpx.MockTransport(handler))


def test_list_voices():
    def handler(request):
        assert request.headers["xi-api-key"] == "sk_prueba"
        return httpx.Response(
            200,
            json={
                "voices": [
                    {
                        "voice_id": "abc123XYZ",
                        "name": "Mateo",
                        "labels": {"gender": "male", "accent": "latin"},
                    },
                    {"voice_id": "def456UVW", "name": "Ana", "labels": {}},
                ]
            },
        )

    voices = eleven(handler).list_voices()
    assert voices == [
        {"id": "eleven:def456UVW", "label": "Ana"},
        {"id": "eleven:abc123XYZ", "label": "Mateo (male · latin)"},
    ]


def test_synthesize_returns_wav():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["format"] = request.url.params["output_format"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"\x00\x00" * 22050)  # 1 s de PCM

    audio = eleven(handler, "eleven_flash_v2_5").synthesize("Hola", "eleven:abc123XYZ", "Rápida")
    assert seen["path"] == "/v1/text-to-speech/abc123XYZ"
    assert seen["format"] == "pcm_22050"
    assert seen["body"]["model_id"] == "eleven_flash_v2_5"
    assert seen["body"]["voice_settings"]["speed"] == 1.1
    with wave.open(io.BytesIO(audio)) as w:
        assert w.getframerate() == 22050 and w.getnframes() == 22050


@pytest.mark.parametrize(
    "status,body,message,transient",
    [
        (401, '{"detail":{"status":"invalid_api_key"}}', "no es válida", False),
        (401, '{"detail":{"status":"quota_exceeded"}}', "Se acabaron tus créditos", False),
        (429, "{}", "ocupado", True),
        (503, "{}", "temporalmente", True),
    ],
)
def test_errors_are_friendly(status, body, message, transient):
    tts = eleven(lambda r: httpx.Response(status, text=body))
    with pytest.raises(ProviderError) as info:
        tts.synthesize("Hola", "eleven:abc123XYZ", "Normal")
    assert message in str(info.value) and info.value.transient is transient


def test_credits_and_cost():
    tts = eleven(
        lambda r: httpx.Response(
            200, json={"character_count": 2500, "character_limit": 10000, "tier": "free"}
        )
    )
    assert tts.credits() == {"used": 2500, "limit": 10000, "left": 7500, "tier": "free"}
    assert tts.cost(1000) == 1000
    assert eleven(lambda r: httpx.Response(403), "eleven_flash_v2_5").cost(1000) == 500
    assert eleven(lambda r: httpx.Response(403)).credits() is None  # sin permiso: no se sabe


def test_model_change_rerecords_only_for_elevenlabs():
    assert take_key("hola", "eleven:abc123", "Normal", "a") != take_key(
        "hola", "eleven:abc123", "Normal", "b"
    )
    assert take_key("hola", "es_ES-davefx-medium", "Normal", "a") == take_key(
        "hola", "es_ES-davefx-medium", "Normal"
    )


# ---------------------------------------------------------------- en el programa


class FakeEleven:
    name = "elevenlabs"

    def __init__(self, left):
        self.left = left
        self.calls = []

    def credits(self):
        return {"used": 0, "limit": 10000, "left": self.left, "tier": "starter"}

    def cost(self, characters):
        return characters

    def synthesize(self, text, voice, speed):
        self.calls.append(text)
        return silent_wav(0.5)


def test_record_with_elevenlabs(with_script, monkeypatch):  # noqa: F811
    fake = FakeEleven(left=100_000)
    monkeypatch.setattr(jobs, "get_voice_provider", lambda *a, **k: fake)
    with_script.post(
        "/proyectos/1/etapas/voice",
        data={"voice": "eleven:abc123XYZ", "model": "eleven_flash_v2_5"},
    )
    run_all()
    voice = result("voice")
    assert voice["provider"] == "elevenlabs" and voice["model"] == "eleven_flash_v2_5"
    assert fake.calls
    with SessionLocal() as db:
        assert get_setting(db, "eleven_model") == "eleven_flash_v2_5"


def test_not_enough_credits_stops_before_spending(with_script, monkeypatch):  # noqa: F811
    fake = FakeEleven(left=10)
    monkeypatch.setattr(jobs, "get_voice_provider", lambda *a, **k: fake)
    with_script.post("/proyectos/1/etapas/voice", data={"voice": "eleven:abc123XYZ"})
    run_all()
    assert fake.calls == []  # no se gastó nada
    assert "No te alcanzan los créditos" in with_script.get("/proyectos/1/voz").text


def test_voice_page_lists_elevenlabs_voices(with_script, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        jobs, "eleven_voices", lambda db: ([{"id": "eleven:abc123XYZ", "label": "Mateo"}], None)
    )
    monkeypatch.setattr(
        stages_web.ElevenLabsVoices, "credits", lambda self: {"left": 7000, "limit": 10000}
    )
    from app.settings_store import save_api_key

    with SessionLocal() as db:
        save_api_key(db, "elevenlabs", "sk_prueba")
    page = with_script.get("/proyectos/1/voz").text
    assert "ElevenLabs · tu cuenta" in page and "Mateo" in page
    assert "Te quedan <strong>7000</strong>" in page


def test_invalid_voice_id_is_rejected(with_script):  # noqa: F811
    r = with_script.post("/proyectos/1/voz/muestra", data={"voice": "eleven:../../hack"})
    assert r.status_code == 400


def test_save_elevenlabs_key(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_eleven_key", lambda key: None)
    r = logged_in.post("/configuracion/elevenlabs", data={"api_key": "sk_secreta9999"})
    assert (
        "Clave de ElevenLabs guardada" in r.text
        and "••••9999" in r.text
        and "sk_secreta9999" not in r.text
    )

    def reject(key):
        raise ProviderError("La clave de ElevenLabs no es válida o no tiene permisos.")

    monkeypatch.setattr(settings_web, "check_eleven_key", reject)
    r = logged_in.post("/configuracion/elevenlabs", data={"api_key": "mala"})
    assert r.status_code == 400 and "no es válida" in r.text


def test_list_voices_falls_back_to_v1():
    def handler(request):
        if request.url.path == "/v2/voices":
            return httpx.Response(400, json={"detail": {"status": "bad", "message": "v2 no"}})
        return httpx.Response(200, json={"voices": [{"voice_id": "abc123XYZ", "name": "Mateo"}]})

    assert eleven(handler).list_voices() == [{"id": "eleven:abc123XYZ", "label": "Mateo"}]


def test_v2_voices_used_first():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"voices": [{"voice_id": "abc123XYZ", "name": "Mateo"}]})

    eleven(handler).list_voices()
    assert paths == ["/v2/voices"]


def test_400_error_shows_elevenlabs_message():
    body = '{"detail":{"status":"invalid_request","message":"Ese parámetro no vale"}}'
    tts = eleven(lambda r: httpx.Response(400, text=body))
    with pytest.raises(ProviderError) as info:
        tts.list_voices()
    assert "Ese parámetro no vale" in str(info.value)
    assert "v2:" in info.value.detail or "invalid_request" in info.value.detail


def test_settings_show_detail_and_key_hint(logged_in, monkeypatch):
    def reject(key):
        raise ProviderError("ElevenLabs respondió con un error (400): algo", detail='{"x": 1}')

    monkeypatch.setattr(settings_web, "check_eleven_key", reject)
    r = logged_in.post("/configuracion/elevenlabs", data={"api_key": "abc"})
    assert "empiezan por «sk_»" in r.text
    assert "Detalle técnico" in r.text


def test_missing_permission_is_explained():
    body = (
        '{"detail":{"type":"authentication_error","code":"unauthorized","message":"The API key '
        'you used is missing the permission voices_read to execute this operation.",'
        '"status":"missing_permissions"}}'
    )
    with pytest.raises(ProviderError) as info:
        eleven(lambda r: httpx.Response(401, text=body)).list_voices()
    assert "Voices → Read" in str(info.value)
    assert not info.value.transient

import os
import tempfile

# La app guarda datos en una carpeta temporal durante los tests.
os.environ["FACELESS_DATA_DIR"] = tempfile.mkdtemp(prefix="faceless-test-")
# Los tests ejecutan las tareas a mano, sin trabajador en segundo plano.
os.environ["FACELESS_WORKER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class FakeSearch:
    name = "fake-wikipedia"

    def __init__(self, documents=None):
        from app.providers.search import Document

        self.documents = (
            [Document("Enron", "https://es.wikipedia.org/wiki/Enron", "Enron quebró en 2001.")]
            if documents is None
            else documents
        )
        self.queries = None

    def search(self, queries, language):
        self.queries = queries
        return self.documents


def silent_wav(seconds: float, rate: int = 16000) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


class FakeVoice:
    """Voz simulada: devuelve silencio de 0,4 s por palabra."""

    name = "fake-voice"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, speed):
        self.calls.append(text)
        return silent_wav(0.4 * len(text.split()))


from app.providers.images import ImageChain  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_internet(monkeypatch):
    """Ningún test llama a Wikipedia ni descarga voces de verdad."""
    from app import jobs

    monkeypatch.setattr(jobs, "get_search_provider", lambda: FakeSearch())
    voice = FakeVoice()
    monkeypatch.setattr(jobs, "get_voice_provider", lambda *args, **kwargs: voice)
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([FakeImageMaker()]))
    # Los montajes de las pruebas se hacen en miniatura para que sean rápidos.
    from app.pipeline import render

    monkeypatch.setitem(render.QUALITIES, "preview", render.QUALITIES["test"])
    monkeypatch.setitem(render.QUALITIES, "final", render.QUALITIES["test"])
    from app import jarvis_voice
    from app.providers.ai import ProviderError

    def no_microsoft(text, voice, out):
        raise ProviderError("Sin voz de Microsoft en los tests")

    monkeypatch.setattr(jarvis_voice, "microsoft_tts", no_microsoft)
    return voice


class FakeImageMaker:
    """Generador de imágenes simulado: un PNG pequeño de un color."""

    name = "pollinations"
    label = "Pollinations (FLUX)"

    def generate(self, prompt, portrait, seed):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (64, 36), (seed % 255, 80, 120)).save(buffer, "PNG")
        return buffer.getvalue(), ".png"


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # el arranque crea las tablas
        yield c


def register(client, username="ana", password="contrasena123"):
    return client.post(
        "/registro",
        data={"username": username, "password": password, "password_confirm": password},
    )


@pytest.fixture
def logged_in(client):
    register(client)
    return client

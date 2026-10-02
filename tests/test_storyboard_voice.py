import io
import wave

import httpx
import pytest

from app import jobs, stages_web
from app.db import SessionLocal
from app.media import project_dir
from app.models import Project
from app.providers.ai import ProviderError
from app.providers.voice import PiperVoices, join_wavs, wav_seconds
from tests.conftest import silent_wav
from tests.test_research import FakeAI
from tests.test_strategy_script import make_project, run_all


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    return fake


@pytest.fixture
def with_script(logged_in, ai):
    """Proyecto manual con investigación, estrategia y guion hechos."""
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    logged_in.post("/proyectos/1/etapas/strategy")
    run_all()
    logged_in.post("/proyectos/1/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/1/etapas/script")
    run_all()
    return logged_in


def result(stage):
    with SessionLocal() as db:
        return jobs.get_result(db, 1, stage)


def paragraph_ids():
    return [p["id"] for s in result("script")["sections"] for p in s["paragraphs"]]


# ---------------------------------------------------------------- escenas


def test_storyboard_one_scene_per_paragraph(with_script):
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    board = result("storyboard")
    assert [s["paragraph_id"] for s in board["scenes"]] == paragraph_ids()
    assert board["scenes"][0]["visual"] == "Plano 0"
    assert board["scenes"][-1].get("missing") is True  # la IA lo olvidó, pero no se pierde
    assert board["visual_bible"]["locations"] == ["Houston"]
    assert board["total_seconds"] > 0
    with SessionLocal() as db:
        assert db.get(Project, 1).status == "Storyboard"

    page = with_script.get("/proyectos/1/escenas").text
    assert "Biblia visual" in page and "Escena 01" in page and "empty office" in page


def test_editing_script_marks_scenes_outdated(with_script):
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    pid = paragraph_ids()[1]
    with_script.post(
        f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": "Nuevo."}
    )
    page = with_script.get("/proyectos/1/escenas").text
    assert "1 escena(s) tienen texto distinto" in page
    assert "El texto de esta escena cambió" in page


# ---------------------------------------------------------------- voz


def test_record_narration(with_script, no_real_internet):
    with_script.post(
        "/proyectos/1/etapas/voice", data={"voice": "es_MX-ald-medium", "speed": "Rápida"}
    )
    run_all()
    voice = result("voice")
    assert voice["voice"] == "es_MX-ald-medium" and voice["speed"] == "Rápida"
    assert len(voice["takes"]) == len(paragraph_ids())
    folder = project_dir(1)
    assert (folder / "voz" / "narracion.wav").exists()
    assert all((folder / t["file"]).exists() for t in voice["takes"])
    # Duración total = párrafos + pausas de 0,35 s entre ellos.
    expected = sum(t["seconds"] for t in voice["takes"]) + 0.35 * (len(voice["takes"]) - 1)
    assert voice["seconds"] == pytest.approx(expected, abs=0.05)

    page = with_script.get("/proyectos/1/voz").text
    assert "Narración completa" in page
    audio = with_script.get("/proyectos/1/archivos/voz/narracion.wav")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_only_changed_paragraphs_are_rerecorded(with_script, no_real_internet):
    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    first_round = len(no_real_internet.calls)
    pid = paragraph_ids()[0]
    with_script.post(
        f"/proyectos/1/guion/parrafos/{pid}", data={"action": "save", "text": "Otro comienzo."}
    )
    page = with_script.get("/proyectos/1/voz").text
    assert "Grabar lo que falta (1)" in page
    assert "Cambió: se volverá a grabar" in page

    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    assert no_real_internet.calls[first_round:] == ["Otro comienzo."]
    assert result("voice")["reused"] == len(paragraph_ids()) - 1
    # Las grabaciones viejas se borran.
    files = sorted(p.name for p in (project_dir(1) / "voz").glob("*.wav"))
    assert len(files) == len(paragraph_ids()) + 1  # + narracion.wav


def test_voice_sample(with_script, monkeypatch):
    seen = {}

    def fake_sample(text, voice, speed):
        seen.update(text=text, voice=voice, speed=speed)
        return silent_wav(1)

    monkeypatch.setattr(stages_web, "make_sample", fake_sample)
    r = with_script.post(
        "/proyectos/1/voz/muestra", data={"voice": "es_ES-davefx-medium", "speed": "Lenta"}
    )
    assert "Muestra:" in r.text
    assert seen["voice"] == "es_ES-davefx-medium"
    assert seen["text"] == "Nadie lo vio venir."  # el primer párrafo del guion
    assert (project_dir(1) / "voz" / "muestra.wav").exists()
    assert (
        with_script.post("/proyectos/1/voz/muestra", data={"voice": "inventada"}).status_code == 400
    )


def test_voice_sample_error_is_shown(with_script, monkeypatch):
    def fail(*args):
        raise ProviderError("No se pudo descargar la voz.")

    monkeypatch.setattr(stages_web, "make_sample", fail)
    r = with_script.post("/proyectos/1/voz/muestra", data={"voice": "es_ES-davefx-medium"})
    assert r.status_code == 400 and "No se pudo descargar la voz" in r.text


def test_files_are_protected(with_script):
    from app.media import safe_path

    r = with_script.get("/proyectos/1/archivos/%2E%2E/%2E%2E/secret.key")
    assert r.status_code in (404, 422) and b"RIFF" not in r.content
    assert safe_path(1, "../../secret.key") is None
    assert safe_path(1, "../2/voz/narracion.wav") is None
    assert with_script.get("/proyectos/1/archivos/voz/no-existe.wav").status_code == 404


def test_automatic_mode_goes_until_voice(logged_in, ai):
    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    assert result("storyboard") is not None
    assert result("voice") is not None
    with SessionLocal() as db:
        assert db.get(Project, 1).status == "Producción"


def test_deleting_project_removes_files(with_script):
    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    folder = project_dir(1)
    with_script.post("/proyectos/1/borrar")
    assert not (folder / "voz").exists()


# ---------------------------------------------------------------- utilidades


def test_join_and_measure_wavs():
    joined = join_wavs([silent_wav(1), silent_wav(2)], pause_seconds=0.5)
    assert wav_seconds(joined) == pytest.approx(3.5)
    with pytest.raises(ValueError):
        join_wavs([silent_wav(1), silent_wav(1, rate=22050)])


def test_voice_download_is_atomic(tmp_path):
    def ok(request):
        return httpx.Response(
            200, content=b"modelo" if request.url.path.endswith(".onnx") else b"{}"
        )

    voices = PiperVoices(tmp_path)
    voices.ensure_downloaded("es_ES-davefx-medium", transport=httpx.MockTransport(ok))
    assert voices.is_downloaded("es_ES-davefx-medium")
    assert (tmp_path / "es_ES-davefx-medium.onnx").read_bytes() == b"modelo"
    assert "/es/es_ES/davefx/medium/" in str(httpx.URL("https://x/es/es_ES/davefx/medium/"))


def test_failed_voice_download_leaves_nothing(tmp_path):
    def fail(request):
        if request.url.path.endswith(".onnx"):
            raise httpx.ConnectError("cortado")
        return httpx.Response(200, content=b"{}")

    voices = PiperVoices(tmp_path)
    with pytest.raises(ProviderError) as info:
        voices.ensure_downloaded("es_ES-davefx-medium", transport=httpx.MockTransport(fail))
    assert info.value.transient
    assert not voices.is_downloaded("es_ES-davefx-medium")
    assert not list(tmp_path.glob("*.part"))


def test_wav_header_is_valid():
    data = silent_wav(0.5)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1

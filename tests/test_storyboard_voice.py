import io
import wave

import pytest

from app import jobs, stages_web
from app.db import SessionLocal
from app.media import project_dir
from app.models import Project
from app.providers import voice as voice_mod
from app.providers.ai import ProviderError
from app.providers.voice import MicrosoftVoices, join_wavs, wav_seconds
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
        "/proyectos/1/etapas/voice", data={"voice": "es-CO-GonzaloNeural", "speed": "Rápida"}
    )
    run_all()
    voice = result("voice")
    assert voice["voice"] == "es-CO-GonzaloNeural" and voice["speed"] == "Rápida"
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

    def fake_sample(db, text, voice, speed, model):
        seen.update(text=text, voice=voice, speed=speed)
        return silent_wav(1)

    monkeypatch.setattr(stages_web, "make_sample", fake_sample)
    r = with_script.post(
        "/proyectos/1/voz/muestra", data={"voice": "es-MX-JorgeNeural", "speed": "Lenta"}
    )
    assert "Muestra:" in r.text
    assert seen["voice"] == "es-MX-JorgeNeural"
    assert seen["text"] == "Nadie lo vio venir."  # el primer párrafo del guion
    assert (project_dir(1) / "voz" / "muestra.wav").exists()
    assert (
        with_script.post("/proyectos/1/voz/muestra", data={"voice": "inventada"}).status_code == 400
    )


def test_voice_sample_error_is_shown(with_script, monkeypatch):
    def fail(*args, **kwargs):
        raise ProviderError("No se pudo descargar la voz.")

    monkeypatch.setattr(stages_web, "make_sample", fail)
    r = with_script.post("/proyectos/1/voz/muestra", data={"voice": "es-MX-JorgeNeural"})
    assert r.status_code == 400 and "No se pudo descargar la voz" in r.text


def test_files_are_protected(with_script):
    from app.media import safe_path

    r = with_script.get("/proyectos/1/archivos/%2E%2E/%2E%2E/secret.key")
    assert r.status_code in (404, 422) and b"RIFF" not in r.content
    assert safe_path(1, "../../secret.key") is None
    assert safe_path(1, "../2/voz/narracion.wav") is None
    assert with_script.get("/proyectos/1/archivos/voz/no-existe.wav").status_code == 404


def test_automatic_mode_goes_until_the_video(logged_in, ai, monkeypatch):
    from app.pipeline import render

    # Vista previa en miniatura para que la prueba sea rápida.
    monkeypatch.setitem(render.QUALITIES, "preview", render.QUALITIES["test"])
    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    for stage in ("storyboard", "voice", "visuals", "edit"):
        assert result(stage) is not None, stage
    assert "preview" in result("edit")["renders"]
    with SessionLocal() as db:
        assert db.get(Project, 1).status == "Edición"


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


def test_microsoft_voice_makes_a_wav(monkeypatch):
    """Sin internet: se simula el MP3 de Microsoft con FFmpeg y se comprueba el WAV final."""
    from app.pipeline.render import run_ffmpeg

    calls = []

    def fake_mp3(text, voice, rate, out):
        calls.append((voice, rate))
        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=1.5", str(out)])

    monkeypatch.setattr(voice_mod, "edge_mp3", fake_mp3)
    data = MicrosoftVoices().synthesize("Hola", "no-existe", "Lenta")
    assert calls == [("es-MX-JorgeNeural", voice_mod.SPEEDS["Lenta"])]  # voz rara -> Jorge
    assert 1.0 < wav_seconds(data) < 2.0


def test_microsoft_voice_retries_then_explains(monkeypatch):
    def broken(text, voice, rate, out):
        raise OSError("sin internet")

    monkeypatch.setattr(voice_mod, "edge_mp3", broken)
    with pytest.raises(ProviderError) as info:
        MicrosoftVoices().synthesize("Hola", "es-MX-JorgeNeural", "Normal")
    assert info.value.transient and "internet" in str(info.value)


def test_citations_are_not_read_aloud():
    assert voice_mod.spoken_text("Ganó el Balón de Oro [1]. Y la Champions [2, 3].") == (
        "Ganó el Balón de Oro. Y la Champions."
    )


def test_old_piper_voice_falls_back_to_jorge():
    assert voice_mod.known_voice("es_MX-claude-high", "Español") == "es-MX-JorgeNeural"
    assert voice_mod.known_voice("eleven:abc", "Español") == "eleven:abc"
    assert voice_mod.known_voice(None, "Inglés") == "en-US-GuyNeural"


def test_wav_header_is_valid():
    data = silent_wav(0.5)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1


def test_say_numbers_reads_thousands_as_a_whole_number():
    say = voice_mod.say_numbers
    assert say("valorada en 10.000 millones") == "valorada en 10 mil millones"
    assert (
        say("más de 1.500 empleados y 2.345.678 pruebas")
        == "más de 1500 empleados y 2345678 pruebas"
    )
    assert say("subió un 4.5% en 2015.") == "subió un 4.5% en 2015."
    assert say("Fin. 700 millones") == "Fin. 700 millones"


def test_say_names_spells_foreign_names_as_spoken():
    say = voice_mod.for_speech
    assert say("Gareth Bale fichó por el Tottenham por 10.000 euros") == (
        "Gáret Béil fichó por el Tótenam por 10 mil euros"
    )
    assert (
        say("Las islas Baleares y balear siguen igual")
        == "Las islas Baleares y balear siguen igual"
    )

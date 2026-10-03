import io
import math
import struct
import wave

import pytest

from app import jobs
from app.db import SessionLocal
from app.media import MUSIC_DIR, project_dir
from app.pipeline import render
from app.pipeline.render import build_ass, split_shots, word_times
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def test_split_shots():
    assert split_shots(4) == [4]
    assert split_shots(12) == [4, 4, 4]
    assert len(split_shots(40)) == 4  # nunca más de 4 planos
    assert sum(split_shots(17.5)) == pytest.approx(17.5)


def test_word_times_cover_the_paragraph():
    words = word_times("Hola, mundo cruel.", 1.0, 4.0)
    assert [w for w, _, _ in words] == ["Hola,", "mundo", "cruel."]
    assert words[0][1] == 1.0 and words[-1][2] == pytest.approx(4.0)
    assert all(a[2] == pytest.approx(b[1]) for a, b in zip(words, words[1:], strict=False))


def test_ass_highlights_current_word_in_brand_red():
    ass = build_ass([("Enron quebró en 2001", 0.0, 2.0)], 1920, 1080)
    assert "Style: Marca,Montserrat ExtraBold" in ass
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    assert len(dialogues) == 4  # una por palabra
    assert "{\\c&H004639E6&}quebró{\\r}" in dialogues[1]
    assert ass.count("{") == ass.count("}")


def test_ass_escapes_braces():
    ass = build_ass([("texto {raro}", 0.0, 1.0)], 640, 360)
    assert "{raro}" not in ass


def test_xfade_chain_keeps_total_duration():
    chain, label = render._xfade_chain([3.4, 5.4, 2.0], [3.35, 5.35, 2.0])
    assert "offset=3.350" in chain and "offset=8.700" in chain and label == "[x2]"


def silent_tone(seconds, rate=22050, freq=220):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * n / rate)))
            for n in range(int(rate * seconds))
        )
        w.writeframes(frames)
    return buffer.getvalue()


@pytest.fixture
def produced(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    return with_script


def test_music_library_upload_play_delete(produced):
    r = produced.post(
        "/proyectos/1/musica/subir",
        files=[
            ("songs", ("Misterio Oscuro.wav", silent_tone(1), "audio/wav")),
            ("songs", ("virus.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert "Misterio Oscuro.wav" in r.text
    assert not (MUSIC_DIR / "virus.exe").exists()
    assert produced.get("/proyectos/1/musica/Misterio Oscuro.wav").status_code == 200
    assert produced.get("/proyectos/1/musica/..%2F..%2Fsecret.key").status_code == 404
    produced.post("/proyectos/1/musica/borrar", data={"name": "Misterio Oscuro.wav"})
    assert not (MUSIC_DIR / "Misterio Oscuro.wav").exists()


def test_render_with_music_subtitles_and_film_look(produced):
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (MUSIC_DIR / "fondo.wav").write_bytes(silent_tone(2))
    try:
        with SessionLocal() as db:
            jobs.enqueue(
                db,
                1,
                "edit",
                {
                    "quality": "test",
                    "subtitles": True,
                    "film_look": True,
                    "music": "fondo.wav",
                    "music_volume": "baja",
                },
            )
        run_all()
        render_result = result("edit")["renders"]["test"]
        assert render_result["music"] == "fondo.wav"
        assert render_result["style"]["subtitles"] and render_result["style"]["film_look"]
        assert (project_dir(1) / render_result["file"]).stat().st_size > 1000
        assert render_result["seconds"] == pytest.approx(result("voice")["seconds"], abs=0.1)
        # Las opciones se recuerdan para la próxima vez.
        page = produced.get("/proyectos/1/video").text
        assert '<option value="fondo.wav" selected' in page
    finally:
        (MUSIC_DIR / "fondo.wav").unlink(missing_ok=True)


def test_render_without_extras(produced):
    with SessionLocal() as db:
        jobs.enqueue(
            db, 1, "edit", {"quality": "test", "subtitles": False, "film_look": False, "music": ""}
        )
    run_all()
    render_result = result("edit")["renders"]["test"]
    assert render_result["music"] == "" and not render_result["style"]["subtitles"]


def test_video_form_sends_options(produced, monkeypatch):
    seen = {}
    monkeypatch.setattr(jobs, "enqueue", lambda db, pid, stage, params=None: seen.update(params))
    produced.post(
        "/proyectos/1/etapas/edit",
        data={"quality": "final", "subtitles": "1", "music": "no-existe.mp3"},
    )
    assert seen == {
        "quality": "final",
        "subtitles": True,
        "film_look": False,
        "look": "auto",  # tono de color automático (se turna entre vídeos)
        "music": "",
        "music_volume": "media",
    }


@pytest.fixture(autouse=True)
def _ai(ai):  # noqa: F811
    return ai

import pytest

from app import music_rights
from app.db import SessionLocal
from app.media import MUSIC_DIR
from app.pipeline.monetization import _rights_checks
from tests.test_quality_pack import produced, silent_tone  # noqa: F401
from tests.test_storyboard_voice import ai, with_script  # noqa: F401

RENDERED = {"edit": {"last": "preview", "renders": {"preview": {"music": "fondo.wav"}}}}


def music_check(licenses):
    return next(c for c in _rights_checks(RENDERED, licenses) if c["key"] == "music")


@pytest.mark.parametrize(
    ("info", "state"),
    [
        (None, "unknown"),
        ({"source": "desconocida"}, "unknown"),
        ({"source": "inventada"}, "unknown"),
        ({"source": "youtube"}, "ok"),
        ({"source": "cc_by", "credit": ""}, "credit"),
        ({"source": "cc_by", "credit": "«Noche» de Ana, CC BY 4.0"}, "ok"),
    ],
)
def test_status(info, state):
    assert music_rights.status(info) == state


def test_quality_check_trusts_licensed_music():
    assert music_check({})["status"] == "warn"
    assert music_check({"fondo.wav": {"source": "pixabay"}})["status"] == "ok"
    assert "Pixabay" in music_check({"fondo.wav": {"source": "pixabay"}})["detail"]
    check = music_check({"fondo.wav": {"source": "cc_by", "credit": ""}})
    assert check["status"] == "warn" and "atribución" in check["title"]


def test_save_forget_and_credit_line(logged_in):
    with SessionLocal() as db:
        music_rights.save(db, "fondo.wav", "cc_by", "  «Noche»   de Ana, CC BY 4.0 ")
        assert music_rights.credit_line(db, "fondo.wav") == "Música: «Noche» de Ana, CC BY 4.0"
        music_rights.save(db, "otra.mp3", "youtube")
        assert music_rights.credit_line(db, "otra.mp3") == (
            "Música: otra (Biblioteca de audio de YouTube)"
        )
        assert (
            music_rights.credit_line(db, "nada.mp3") == ""
            and music_rights.credit_line(db, None) == ""
        )
        music_rights.save(db, "otra.mp3", "")  # sin origen: se borra
        music_rights.forget(db, "fondo.wav")
        assert music_rights.licenses(db) == {}


def test_library_page_saves_the_license(produced):  # noqa: F811
    produced.post(
        "/proyectos/1/musica/subir",
        files=[("songs", ("Noche.wav", silent_tone(1), "audio/wav"))],
    )
    try:
        page = produced.get("/proyectos/1/video").text
        assert "origen sin apuntar" in page and "¿De dónde salió?" in page
        produced.post("/proyectos/1/musica/licencia", data={"name": "Noche.wav", "source": "cc_by"})
        assert "falta atribución" in produced.get("/proyectos/1/video").text
        produced.post(
            "/proyectos/1/musica/licencia",
            data={"name": "Noche.wav", "source": "cc_by", "credit": "Noche de Ana, CC BY"},
        )
        assert "con licencia" in produced.get("/proyectos/1/video").text
        missing = produced.post("/proyectos/1/musica/licencia", data={"name": "no.wav"})
        assert missing.status_code == 404
        produced.post("/proyectos/1/musica/borrar", data={"name": "Noche.wav"})
        with SessionLocal() as db:
            assert music_rights.licenses(db) == {}  # al quitar la canción se olvida
    finally:
        (MUSIC_DIR / "Noche.wav").unlink(missing_ok=True)

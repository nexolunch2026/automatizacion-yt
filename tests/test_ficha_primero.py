"""v0.80: la ficha del protagonista se hace primero en Flow (paso 0 de Visuales) y se sube."""

import io

from PIL import Image, ImageDraw

from app import consistency, flow, jobs
from app.db import SessionLocal
from app.media import project_dir
from app.models import Project
from tests.test_thumbnail import make_video_project

BOARD = {
    "visual_bible": {
        "characters": [
            "Gareth Bale: tall stick figure with dark hair in a man bun and a short beard",
            "Coach: older stick figure",
        ]
    },
    "scenes": [],
}


def _picture(color=(200, 40, 40), mark=True) -> bytes:
    picture = Image.new("RGB", (640, 360), color)
    if mark:
        ImageDraw.Draw(picture).ellipse((250, 60, 400, 300), fill=(20, 20, 20))
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def test_reference_message_names_the_hero():
    text = flow.reference_message(BOARD)
    assert "CHARACTER REFERENCE SHEET" in text and "caricature of Gareth Bale" in text
    assert flow.STICKMAN_STYLE in text and "Coach" not in text
    assert flow.reference_message({"visual_bible": {"characters": []}}) == ""


def test_same_image_is_recognized_as_the_reference():
    ref = _picture()
    out = io.BytesIO()  # la misma imagen, más pequeña y en JPEG (como al subirla)
    Image.open(io.BytesIO(ref)).resize((320, 180)).save(out, "JPEG", quality=70)
    assert consistency.is_reference(out.getvalue(), ref)
    assert not consistency.is_reference(_picture((40, 40, 200), mark=False), ref)
    assert not consistency.is_reference(b"no es imagen", ref)


def _set_hero(project_id: int):
    with SessionLocal() as db:
        row = jobs.get_result(db, project_id, "storyboard")
        row["visual_bible"] = BOARD["visual_bible"]
        jobs._save_result(db, db.get(Project, project_id), "storyboard", row)
        db.commit()


def test_step_zero_upload_saves_the_reference(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    _set_hero(1)
    page = logged_in.get("/proyectos/1/visuales").text
    assert "Paso 0" in page and "Copiar ficha" in page and "REFERENCE IMAGE" not in page

    bad = logged_in.post(
        "/proyectos/1/visuales/ficha", files={"image": ("x.png", b"nada", "image/png")}
    )
    assert bad.status_code == 400

    logged_in.post("/proyectos/1/visuales/ficha", files={"image": ("ficha.png", _picture())})
    assert (project_dir(1) / consistency.REFERENCE_FILE).is_file()
    page = logged_in.get("/proyectos/1/visuales").text
    assert "Paso 0" not in page and "Ficha del protagonista lista" in page
    assert "REFERENCE IMAGE" in page  # los mensajes ya piden dibujarlo como la ficha

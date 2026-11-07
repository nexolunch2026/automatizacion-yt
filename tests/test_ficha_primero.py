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


def test_review_skips_scenes_without_the_hero_and_runs_batches_together(tmp_path):
    import threading

    from tests.test_mejoras_v074 import HeroAI

    hero = BOARD["visual_bible"]["characters"][0]
    (tmp_path / "visuales").mkdir()
    scenes, items = [], {}
    for n in range(1, 13):
        name = f"{n:03}.jpg"
        Image.new("RGB", (64, 36), (n * 20, 50, 90)).save(tmp_path / "visuales" / name)
        who = "Gareth Bale running" if n <= 8 else "a map of Wales"
        scenes.append({"number": n, "paragraph_id": f"p{n}", "image_prompt": who})
        items[f"p{n}"] = {"kind": "image", "file": name}
    (tmp_path / consistency.REFERENCE_FILE).write_bytes(_picture())

    threads = set()

    class Spy(HeroAI):
        def _generate(self, contents, config):
            threads.add(threading.get_ident())
            return super()._generate(contents, config)

    data = consistency.run_check(
        Spy(), tmp_path, scenes, {"items": items}, {}, hero, lambda *_: None
    )
    assert sorted(v["number"] for v in data["checked"].values()) == list(range(1, 9))
    assert len(threads) >= 1 and data["summary"]["bad"] == 1  # la 2 sale con pelo blanco


def test_appears_uses_name_words():
    hero = BOARD["visual_bible"]["characters"][0]
    assert consistency.appears(hero, {"image_prompt": "stick figure Bale kicking"})
    assert not consistency.appears(hero, {"image_prompt": "a stadium at night"})
    assert not consistency.appears("", {"image_prompt": "Bale"})

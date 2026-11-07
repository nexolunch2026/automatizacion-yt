"""Mejoras de la v0.74: miniaturas con imágenes de Flow, aviso de «desactualizado» y
revisión del protagonista."""

import json
import os
import time
from types import SimpleNamespace

from PIL import Image

from app import consistency, flow, jobs
from app.db import SessionLocal
from app.media import project_dir
from app.models import StageResult
from app.pipeline import thumbnail
from tests.test_assistant import run_all
from tests.test_thumbnail import make_video_project


def _flow_project(tmp_path, count=9):
    """Escenas con imágenes de Flow de colores distintos (en una carpeta temporal)."""
    scenes, items = [], {}
    for n in range(1, count + 1):
        name = f"{n:03}-subida.jpg"
        Image.new("RGB", (320, 180), (n * 25 % 255, 90, 200 - n * 10)).save(tmp_path / name)
        pid = f"p{n}"
        scenes.append({"number": n, "paragraph_id": pid, "image_prompt": f"escena {n}"})
        items[pid] = {"kind": "image", "file": name, "provider": "flow", "ai": True}
    return scenes, {"items": items}


def test_flow_thumbnails_use_flow_images_and_split_screen(tmp_path):
    scenes, visuals = _flow_project(tmp_path)
    project = SimpleNamespace(title="Blockbuster", language="Español", channel=None)
    out = tmp_path / "miniaturas"
    data = thumbnail.run_thumbnail(
        project, {}, {"title": "Blockbuster"}, visuals, tmp_path, out, None,
        lambda *_: None, scenes=scenes,
    )  # fmt: skip
    assert [v["layout"] for v in data["variants"]] == ["left", "split", "bottom"]
    split = data["variants"][1]
    assert split["text"] == "ANTES | DESPUÉS" and len(split["images"]) == 2
    assert all(v["source"].startswith("escena") for v in data["variants"])
    for v in data["variants"]:
        with Image.open(out / v["file"]) as image:
            assert image.size == (1280, 720)

    # Cambiar solo los textos conserva las mismas imágenes
    again = thumbnail.run_thumbnail(
        project, {}, {}, visuals, tmp_path, out, None, lambda *_: None, scenes=scenes,
        texts=[{"text": "Se rió", "highlight": "rió"}, {"text": "SE RIÓ | QUEBRÓ",
               "highlight": ""}], previous=data,
    )  # fmt: skip
    assert [v["images"] for v in again["variants"]] == [v["images"] for v in data["variants"]]
    assert again["variants"][1]["text"] == "SE RIÓ | QUEBRÓ"


def test_split_text_and_vertical_split(tmp_path):
    assert thumbnail.split_text("SE RIÓ | QUEBRÓ") == ("SE RIÓ", "QUEBRÓ")
    assert thumbnail.split_text("2002 2020") == ("2002", "2020")
    first = tmp_path / "a.png"
    Image.new("RGB", (400, 300), (200, 40, 40)).save(first)
    out = thumbnail.compose(
        first, "2002 | 2020", "", "split", thumbnail.PORTRAIT, tmp_path / "v.jpg", second=first
    )
    assert Image.open(out).size == (1080, 1920)


def test_stale_banner_and_redo_in_order(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        assert jobs.stale_stages(db, 1) == {}
        visuals = jobs.get_result(db, 1, "visuals")
    assert "desactualizadas" not in logged_in.get("/proyectos/1").text

    # Una imagen del vídeo cambia después del montaje
    image = next(p["path"] for p in jobs.media_map(project_dir(1), visuals).values())
    later = time.time() + 120
    os.utime(image, (later, later))
    with SessionLocal() as db:
        stale = jobs.stale_stages(db, 1)
    assert {"edit", "publish", "shorts"} <= set(stale)
    page = logged_in.get("/proyectos/1/video").text
    assert "Hay cosas desactualizadas" in page and "Rehacer lo desactualizado" in page

    logged_in.post("/proyectos/1/rehacer-desactualizado", data={"back": "video"})
    with SessionLocal() as db:
        queued = [
            j.stage
            for j in db.query(jobs.Job)
            .filter_by(project_id=1, status="queued")
            .order_by(jobs.Job.id)
        ]
    assert queued[0] == "edit" and queued.index("publish") < queued.index("shorts")


def test_saving_the_same_result_keeps_its_date(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        row = db.query(StageResult).filter_by(project_id=1, stage="voice").one()
        before, data = row.updated_at, json.loads(json.dumps(row.data))
        project = db.get(jobs.Project, 1)
        jobs._save_result(db, project, "voice", data)
        db.commit()
        db.refresh(row)
        assert row.updated_at == before


class HeroAI:
    """Gemini simulado: la escena 2 tiene el pelo blanco; las demás, bien."""

    def __init__(self):
        self.calls = 0

    def _generate(self, contents, config):
        self.calls += 1
        listing = contents[0].split("Then come the images to check: ")[1].split(".\n")[0]
        numbers = [int(x.split("scene ")[1]) for x in listing.split(", ")]
        results = [
            {
                "image": i,
                "hero_visible": True,
                "hair": "white_or_grey" if n == 2 else "black",
                "facial_hair": True,
                "white_frame": False,
                "other_style": False,
            }
            for i, n in enumerate(numbers, 1)
        ]
        answer = {"reference_hair": "black", "results": results}
        return SimpleNamespace(text=json.dumps(answer))


def test_hero_check_marks_and_redoes_only_bad_scenes(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        board = jobs.get_result(db, 1, "storyboard")
    first, second = board["scenes"][0]["paragraph_id"], board["scenes"][1]["paragraph_id"]

    page = logged_in.get("/proyectos/1/visuales").text
    assert "Usar como ficha del protagonista" in page
    logged_in.post(f"/proyectos/1/visuales/protagonista/{first}")
    assert (project_dir(1) / consistency.REFERENCE_FILE).exists()

    fake = HeroAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    logged_in.post("/proyectos/1/visuales/revisar-protagonista")
    run_all()
    assert fake.calls >= 1
    page = logged_in.get("/proyectos/1/visuales").text
    assert "1 escena no se parece a la ficha" in page and "pelo blanco" in page

    logged_in.post("/proyectos/1/visuales/rehacer-marcadas")
    with SessionLocal() as db:
        items = jobs.get_result(db, 1, "visuals")["items"]
    assert items[second]["provider"] == consistency.REDO
    assert items[first]["provider"] != consistency.REDO
    page = logged_in.get("/proyectos/1/visuales").text
    assert "Pendiente de rehacer en Flow" in page and "descargar la ficha" in page
    assert "REFERENCE IMAGE" in page  # el mensaje de Flow pide dibujarlo como la ficha


def test_wrong_flag_can_be_accepted(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        board = jobs.get_result(db, 1, "storyboard")
    first, second = board["scenes"][0]["paragraph_id"], board["scenes"][1]["paragraph_id"]
    logged_in.post(f"/proyectos/1/visuales/protagonista/{first}")
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: HeroAI())
    logged_in.post("/proyectos/1/visuales/revisar-protagonista")
    run_all()
    logged_in.post(f"/proyectos/1/visuales/protagonista-bien/{second}")
    with SessionLocal() as db:
        hero = jobs.get_result(db, 1, consistency.STAGE)
        visuals = jobs.get_result(db, 1, "visuals")
    assert consistency.flagged(hero, visuals) == []


def test_flow_message_with_reference():
    board = {"scenes": [{"number": 1, "image_prompt": "a man"}], "visual_bible": {}}
    assert "REFERENCE IMAGE" in flow.messages(board, reference=True)[0]["text"]
    assert "REFERENCE IMAGE" not in flow.messages(board)[0]["text"]


def test_hero_job_cannot_be_started_as_a_stage(logged_in):
    from tests.test_projects import create_channel

    create_channel(logged_in)
    assert logged_in.post("/proyectos/1/etapas/consistency").status_code == 404

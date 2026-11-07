"""Movimiento de muñeco (gratis) y clips animados de Google Flow en las escenas."""

import subprocess

import pytest
from PIL import Image

from app import jobs
from app.db import SessionLocal
from app.media import project_dir
from app.pipeline.render import ffmpeg_exe, puppet_filter, scene_clip
from tests.test_ai_images import board  # noqa: F401
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401


def make_clip(path, seconds=1.0, size="64x36"):
    subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc=duration={seconds}:size={size}:rate=10", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


def duration(path) -> float:
    out = subprocess.run(
        [ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, errors="replace"
    ).stderr
    h, m, s = out.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_puppet_filter_moves_without_black_borders():
    text = puppet_filter(1280, 720, seed=3)
    assert "rotate=" in text and "crop=1280:720" in text and "sin(" in text
    assert puppet_filter(1280, 720, 1) != puppet_filter(1280, 720, 2)  # ritmo distinto


def test_puppet_is_off_by_default_and_can_be_switched_on(logged_in):
    with SessionLocal() as db:
        assert jobs.render_style(db)["puppet"] is False
        assert jobs.render_style(db, {"puppet": True})["puppet"] is True


def test_image_scene_with_puppet_renders(tmp_path):
    image = tmp_path / "a.jpg"
    Image.new("RGB", (160, 90), (200, 40, 40)).save(image)
    out = tmp_path / "escena.mp4"
    scene = {"number": 2, "on_screen_text": ""}
    scene_clip(scene, image, "image", 1.0, out, (64, 36), 10, "ultrafast", 30, tmp_path,
               puppet=True)  # fmt: skip
    assert out.exists() and duration(out) == pytest.approx(1.0, abs=0.15)


def test_short_flow_clip_holds_its_last_frame(tmp_path):
    clip = make_clip(tmp_path / "flow.mp4", seconds=1.0)
    out = tmp_path / "escena.mp4"
    scene = {"number": 1, "on_screen_text": ""}
    scene_clip(scene, clip, "video", 2.5, out, (64, 36), 10, "ultrafast", 30, tmp_path,
               hold_last=True)  # fmt: skip
    assert duration(out) == pytest.approx(2.5, abs=0.15)  # dura la escena entera


def test_upload_flow_clip_for_a_scene(board, tmp_path):  # noqa: F811
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    data = make_clip(tmp_path / "escena 1.mp4").read_bytes()
    r = board.post(
        f"/proyectos/1/visuales/subir/{pid}", files={"image": ("escena 1.mp4", data, "video/mp4")}
    )
    assert r.status_code == 200
    entry = result("visuals")["items"][pid]
    assert entry["kind"] == "video" and entry["animated"] and entry["ai"]
    assert entry["file"].endswith(".mp4") and entry["poster"]
    assert (project_dir(1) / "visuales" / entry["poster"]).exists()
    media = jobs.media_map(project_dir(1), result("visuals"))
    assert media[pid]["animated"] is True


def test_upload_many_mixes_images_and_clips(board, tmp_path):  # noqa: F811
    import io

    scenes = result("storyboard")["scenes"]
    picture = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 80, 160)).save(picture, "PNG")
    clip = make_clip(tmp_path / "2.mp4").read_bytes()
    board.post(
        "/proyectos/1/visuales/subir-varias",
        files=[
            ("images", ("1.png", picture.getvalue(), "image/png")),
            ("images", ("2.mp4", clip, "video/mp4")),
        ],
    )
    items = result("visuals")["items"]
    assert items[scenes[0]["paragraph_id"]]["kind"] == "image"
    assert items[scenes[1]["paragraph_id"]]["kind"] == "video"


def test_fake_mp4_is_rejected(board):  # noqa: F811
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    r = board.post(
        f"/proyectos/1/visuales/subir/{pid}",
        files={"image": ("x.mp4", b"no soy un video", "video/mp4")},
    )
    assert r.status_code == 400

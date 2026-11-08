"""Shorts: imagen horizontal entera con fondo desenfocado y «Rehacer» con los mismos momentos."""

import subprocess

import pytest
from PIL import Image

from app.pipeline.render import blur_fill_height, ffmpeg_exe, scene_clip
from app.pipeline.shorts import kept_picks


def test_blur_fill_only_for_horizontal_images_in_vertical_video(tmp_path):
    wide, tall = tmp_path / "ancha.jpg", tmp_path / "alta.jpg"
    Image.new("RGB", (1600, 900)).save(wide)
    Image.new("RGB", (900, 1600)).save(tall)
    # Antes 404 (720 × 900/1600: la imagen entera en un tercio); desde la v0.83, el 60 %.
    assert blur_fill_height(wide, 720, 1280) == 768
    assert blur_fill_height(tall, 720, 1280) is None  # ya es vertical: se recorta como siempre
    assert blur_fill_height(wide, 1280, 720) is None  # vídeo horizontal: nada cambia
    assert blur_fill_height(tmp_path / "no-existe.jpg", 720, 1280) is None


def test_vertical_scene_with_horizontal_image_renders(tmp_path):
    image = tmp_path / "a.jpg"
    Image.new("RGB", (320, 180), (200, 40, 40)).save(image)
    out = tmp_path / "escena.mp4"
    scene_clip({"number": 1, "on_screen_text": "HOLA"}, image, "image", 1.0, out, (72, 128), 10,
               "ultrafast", 30, tmp_path, 1, 0)  # fmt: skip
    probe = subprocess.run([ffmpeg_exe(), "-i", str(out)], capture_output=True, text=True,
                           errors="replace").stderr  # fmt: skip
    assert "72x128" in probe
    h, m, s = probe.split("Duration: ")[1].split(",")[0].split(":")
    assert float(s) == pytest.approx(1.0, abs=0.15)


def test_redo_keeps_the_same_moments():
    old = [
        {
            "paragraphs": [1, 4],
            "title": "De la gloria a la cárcel",
            "hook": "Esposado en la cárcel",
        },
        {"paragraphs": [32, 36], "title": "Ovación", "hook": "Ovacionado"},
    ]
    picks = kept_picks(old, total=60)
    assert [(p.start, p.end, p.hook) for p in picks] == [
        (1, 4, "Esposado en la cárcel"),
        (32, 36, "Ovacionado"),
    ]
    assert kept_picks(old, total=20) == []  # el guion cambió: se eligen de nuevo
    assert kept_picks([{"title": "roto"}], total=60) == []
    assert kept_picks(None, total=60) == []

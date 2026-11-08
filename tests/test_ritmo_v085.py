"""v0.85: una imagen cada ~7 s, planos variados y movimientos/transiciones tipo CapCut."""

import subprocess

from PIL import Image

from app.pipeline import render, storyboard
from app.pipeline.script import MAX_PARAGRAPH_WORDS, split_paragraph


def test_paragraphs_are_cut_to_about_seven_seconds():
    text = (
        "Mientras medio mundo prepara la cena de Nochebuena, en California una empresa "
        "pequeña está a punto de no poder pagar a sus empleados, porque el dinero no llega. "
        "Su jefe ha puesto en ella todo lo que tenía y no tiene casa propia."
    )
    parts = split_paragraph({"id": "abc", "text": text})
    assert len(parts) >= 2 and parts[0]["id"] == "abc"
    assert all(len(p["text"].split()) <= MAX_PARAGRAPH_WORDS + 6 for p in parts)
    assert " ".join(p["text"] for p in parts) == text  # no se pierde ni una palabra
    short = {"id": "x", "text": "Una frase corta que cabe entera en una sola imagen."}
    assert split_paragraph(short) == [short]


def test_storyboard_asks_for_varied_shots():
    class P:
        video_type = "Documental"

    prompt = storyboard._prompt(P(), {"title": "t", "sections": []})
    for shot in ("Wide shot", "Medium shot", "Close-up", "Extreme close-up"):
        assert shot in prompt


def test_transitions_are_not_all_the_same():
    kinds = [render.transition_for(k) for k in range(1, 17)]
    assert kinds.count("fade") == 8 and len(set(kinds)) >= 6


def test_every_motion_renders(tmp_path):
    image = tmp_path / "a.jpg"
    Image.new("RGB", (320, 180), (90, 140, 200)).save(image)
    for i, motion in enumerate(render.MOTIONS):
        out = tmp_path / f"{motion}.mp4"
        render.scene_clip({"number": 1}, image, "image", 1.0, out, (128, 72), 10,
                          "ultrafast", 30, tmp_path, 1, i)  # fmt: skip
        probe = subprocess.run([render.ffmpeg_exe(), "-i", str(out)], capture_output=True,
                               text=True, errors="replace").stderr  # fmt: skip
        assert "128x72" in probe, motion

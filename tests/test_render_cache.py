from PIL import Image

from app.pipeline import accent
from app.pipeline.render import CACHE_DIR, MOTIONS, first_motion, render_video
from tests.test_quality_pack import silent_tone


def setup(tmp_path):
    visuals, scenes, takes = {}, [], {}
    for n, color in enumerate(["red", "green", "blue"], 1):
        path = tmp_path / f"img{n}.png"
        Image.new("RGB", (320, 180), color).save(path)
        visuals[f"p{n}"] = {"path": path, "kind": "image"}
        scenes.append(
            {"number": n, "paragraph_id": f"p{n}", "narration": f"Frase {n}.", "visual": "x"}
        )
        takes[f"p{n}"] = 1.0
    narration = tmp_path / "voz.wav"
    narration.write_bytes(silent_tone(3.8))
    return scenes, visuals, takes, narration


def render(tmp_path, scenes, visuals, takes, narration):
    return render_video(
        scenes, visuals, takes, narration, tmp_path / "video", "preview", False, lambda p, m: None
    )


def test_only_changed_scenes_are_rebuilt(tmp_path):
    scenes, visuals, takes, narration = setup(tmp_path)
    first = render(tmp_path, scenes, visuals, takes, narration)
    assert first["reused_scenes"] == 0
    assert len(list((tmp_path / "video" / CACHE_DIR).glob("*.mp4"))) == 3

    again = render(tmp_path, scenes, visuals, takes, narration)
    assert again["reused_scenes"] == 3  # nada cambió: todo de la memoria
    assert again["seconds"] == first["seconds"]

    scenes[1] = {**scenes[1], "on_screen_text": "1997"}  # cambia solo la escena 2
    changed = render(tmp_path, scenes, visuals, takes, narration)
    assert changed["reused_scenes"] == 2
    assert len(list((tmp_path / "video" / CACHE_DIR).glob("*.mp4"))) == 3  # la vieja se borra

    with accent.use("azul"):  # otro color de canal: hay que rehacerlas todas
        assert render(tmp_path, scenes, visuals, takes, narration)["reused_scenes"] == 0


def test_inserting_a_scene_keeps_the_rest(tmp_path):
    scenes, visuals, takes, narration = setup(tmp_path)
    render(tmp_path, scenes, visuals, takes, narration)
    renumbered = [{**s, "number": s["number"] + 10} for s in scenes]  # otro número, mismo contenido
    assert render(tmp_path, renumbered, visuals, takes, narration)["reused_scenes"] == 3


def test_first_motion_never_repeats_the_previous_shot():
    for pid in ("a", "b", "c", "d", "e"):
        base = first_motion(pid, None)
        assert 0 <= base < len(MOTIONS)
        assert first_motion(pid, base) != base

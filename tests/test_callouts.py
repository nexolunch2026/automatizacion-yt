import pytest
from PIL import Image

from app.db import SessionLocal
from app.pipeline import accent
from app.pipeline.render import callout_overlay, find_callout, render_video
from tests.test_quality_pack import silent_tone
from tests.test_storyboard_voice import ai, with_script  # noqa: F401
from tests.test_strategy_script import run_all


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Pudo comprar Netflix por unos 50 millones de dólares. Dijo que no.", "50 millones"),
        ("El 80 por ciento de sus clientes se fue en 3 años.", "80 %"),
        ("En 1975 un ingeniero creó la primera cámara digital.", "1975"),
        ("Vendía uno de cada tres móviles del planeta.", None),
        ("Tenía 3 hijos.", None),  # una cifra suelta pequeña no merece animación
    ],
)
def test_find_callout(text, shown):
    found = find_callout(text, 8.0)
    assert (found["text"] if found else None) == shown
    if found:
        assert 0.3 <= found["at"] <= 8.0


def test_callout_timing_and_short_scenes():
    late = find_callout("Al final de todo aquello, la cifra fue de 900 millones", 10.0)
    assert late["at"] > 5  # la cifra se dice al final del párrafo
    assert find_callout("Ganó 900 millones.", 2.0) is None  # escena demasiado corta


def test_callout_overlay_uses_channel_color(tmp_path):
    with accent.use("verde"):
        path = callout_overlay("50 millones", (320, 180), tmp_path / "c.png")
    colors = {c for _, c in Image.open(path).convert("RGB").getcolors(320 * 180)}
    assert accent.PALETTE["verde"] in colors


def test_render_with_and_without_callouts(tmp_path):
    img = tmp_path / "bg.png"
    Image.new("RGB", (320, 180), (40, 60, 90)).save(img)
    scenes = [{"number": 1, "paragraph_id": "p1", "narration": "Costó 50 millones.", "visual": "x"}]
    (tmp_path / "v.wav").write_bytes(silent_tone(4))

    def render(style):
        return render_video(
            scenes,
            {"p1": {"path": img, "kind": "image"}},
            {"p1": 4.0},
            tmp_path / "v.wav",
            tmp_path / "out",
            "preview",
            False,
            lambda p, m: None,
            style=style,
        )

    assert render({"callouts": True})["seconds"] == 4.0
    assert render({"callouts": False})["reused_scenes"] == 0  # otra escena: sin cifra


def test_edit_form_saves_the_option(with_script):  # noqa: F811
    from app import jobs

    with_script.post("/proyectos/1/etapas/edit", data={"quality": "preview"})
    with SessionLocal() as db:
        assert jobs.latest_jobs(db, 1)["edit"].params["callouts"] is False  # casilla sin marcar
    run_all()  # (falla por no tener voz, da igual: solo miramos las opciones)
    with_script.post("/proyectos/1/etapas/edit", data={"quality": "preview", "callouts": "1"})
    with SessionLocal() as db:
        params = jobs.latest_jobs(db, 1)["edit"].params
        assert params["callouts"] is True
        assert jobs.render_style(db, params)["callouts"] is True

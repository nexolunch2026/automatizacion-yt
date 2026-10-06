import pytest
from PIL import Image

from app import jobs
from app.db import SessionLocal
from app.models import Channel, Project
from app.pipeline import accent
from app.pipeline.render import end_overlay, text_overlay
from app.pipeline.script import FORMATS, format_info, guess_format
from tests.test_assistant import ai  # noqa: F401
from tests.test_projects import project_data
from tests.test_strategy_script import make_project, run_all


@pytest.mark.parametrize(
    ("topic", "key"),
    [
        ("top 10 marcas que desaparecieron", "lista"),
        ("Los 5 errores más caros de la historia", "lista"),
        ("explica por qué quebró Lehman Brothers", "explicacion"),
        ("¿Por qué el cielo es azul?", "explicacion"),
        ("relato de un naufragio real", "relato"),
        ("la caída de Nokia", "auto"),
    ],
)
def test_guess_format(topic, key):
    assert guess_format(topic.strip("¿?")) == key


def test_format_info():
    assert format_info(None) == {} and format_info("auto") == {} and format_info("raro") == {}
    info = format_info("lista")
    assert info["key"] == "formato_lista" and info["name"] == FORMATS["lista"][0]


def test_list_format_shapes_strategy_and_script(logged_in, ai, monkeypatch):  # noqa: F811
    prompts = []
    original = ai.generate_json

    def spy(prompt, schema):
        prompts.append(prompt)
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", spy)
    make_project(logged_in, "manual")
    logged_in.post(
        "/proyectos/nuevo", data=project_data(automation_mode="manual", video_format="lista")
    )
    with SessionLocal() as db:
        assert db.get(Project, 2).video_format == "lista"
        assert db.get(Project, 1).video_format == "auto"
    for stage in ("research", "strategy"):
        logged_in.post(f"/proyectos/2/etapas/{stage}")
        run_all()
    logged_in.post("/proyectos/2/estrategia/elegir", data={"concept": 0, "title": 0})
    logged_in.post("/proyectos/2/etapas/script")
    run_all()
    strategy = next(p for p in prompts if "Propón 3 enfoques" in p)
    assert "Formato elegido: Top / lista." in strategy
    outline = next(p for p in prompts if "Haz el ESQUEMA" in p)
    assert "Estructura narrativa: Top / lista. Es un TOP" in outline
    with SessionLocal() as db:
        script = jobs.get_result(db, 2, "script")
    assert script["structure_name"] == "Top / lista"
    assert "Formato" in logged_in.get("/proyectos/nuevo").text


def test_unknown_format_is_automatic(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    logged_in.post("/proyectos/nuevo", data=project_data(video_format="<script>"))
    with SessionLocal() as db:
        assert db.get(Project, 2).video_format == "auto"


def test_accent_colors():
    assert accent.color() == accent.RED and accent.ass() == "&H004639E6&"
    with accent.use("azul"):
        assert accent.color() == (52, 120, 246) and accent.ass() == "&H00F67834&"
    assert accent.color() == accent.RED  # se recupera al terminar
    with accent.use("inventado"):
        assert accent.color() == accent.RED
    assert accent.css("verde") == "#2ec470"


def _has_color(path, rgb, tolerance=12):
    image = Image.open(path).convert("RGB")
    return any(
        all(abs(a - b) <= tolerance for a, b in zip(pixel, rgb, strict=True))
        for _, pixel in image.getcolors(image.width * image.height)
    )


def test_drawings_use_the_channel_color(tmp_path):
    with accent.use("amarillo"):
        text_overlay("1997", (320, 180), tmp_path / "t.png")
        end_overlay("La historia completa", (180, 320), tmp_path / "e.png")
    assert _has_color(tmp_path / "t.png", accent.PALETTE["amarillo"])
    assert _has_color(tmp_path / "e.png", accent.PALETTE["amarillo"])
    assert not _has_color(tmp_path / "t.png", accent.RED)


def test_channel_color_reaches_the_jobs(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    logged_in.post("/canales/1/color", data={"color": "verde"})
    page = logged_in.get("/canales").text
    assert "Color del canal" in page and "swatch chosen" in page
    seen = []
    monkeypatch.setitem(
        jobs.RUNNERS,
        "research",
        lambda db, project, progress, params: seen.append(accent.color()) or {"facts": []},
    )
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    assert seen == [accent.PALETTE["verde"]]

    logged_in.post("/canales/1/color", data={"color": "nada"})
    with SessionLocal() as db:
        assert db.get(Channel, 1).color is None

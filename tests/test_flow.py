"""Imágenes con Google Flow: mensajes para el asistente, enlaces pegados e importación."""

import io
import json

import httpx
from PIL import Image

from app import flow, jobs
from app.media import project_dir
from tests.test_ai_images import board  # noqa: F401
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401

FLOW_URL = "https://flow-content.google/image/{n}?Expires=1&KeyName=k&Signature=s"


def jpg(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(out, "JPEG")
    return out.getvalue()


def test_messages_have_nine_scenes_each_and_the_style():
    scenes = [{"number": n, "image_prompt": f"scene {n}"} for n in range(1, 21)]
    plan = {"scenes": scenes, "visual_bible": {"characters": ["a stick figure with a bun"]}}
    parts = flow.messages(plan)
    assert [(p["first"], p["last"]) for p in parts] == [(1, 9), (10, 18), (19, 20)]
    text = parts[0]["text"]
    assert "Create 9 SEPARATE images" in text and "stickman" in text and "16:9" in text
    assert "a stick figure with a bun" in text and "\n9. scene 9" in text
    assert "9:16" in flow.messages(plan, portrait=True)[0]["text"]


def test_parse_links_only_accepts_flow():
    raw = json.dumps(
        [
            {"t": "Uno", "s": FLOW_URL.format(n=1)},
            {"t": "Repetida", "s": FLOW_URL.format(n=1)},
            {"t": "Malo", "s": "https://evil.example.com/x.jpg"},
            {"t": "Sin https", "s": "http://flow-content.google/image/2"},
        ]
    )
    assert flow.parse_links(raw) == [{"title": "Uno", "url": FLOW_URL.format(n=1)}]
    loose = f"mira {FLOW_URL.format(n=3)} y http://localhost:8000/x"
    assert [i["url"] for i in flow.parse_links(loose)] == [FLOW_URL.format(n=3)]
    assert flow.parse_links("nada") == []


def test_bookmarklet_counts():
    code = flow.bookmarklet(10)
    assert code.startswith("javascript:") and "__MAX__" not in code and "flow-content" in code


def test_by_order_reverses_the_viewer():
    scenes = [{"number": n} for n in (1, 2, 3)]
    assert flow.by_order(3, scenes) == {2: 1, 1: 2, 0: 3}


def test_import_places_images_with_ai(board, monkeypatch):  # noqa: F811
    scenes = result("storyboard")["scenes"]
    links = [{"t": f"img {i}", "s": FLOW_URL.format(n=i)} for i in range(len(scenes))]
    colors = {FLOW_URL.format(n=i): jpg((20 * i, 0, 0)) for i in range(len(scenes))}

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        return real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=colors[str(r.url)]))
        )

    monkeypatch.setattr("app.stages_web.httpx.Client", fake_client)
    # Gemini dice que la imagen 0 es la última escena y la 1 la primera.
    monkeypatch.setattr(
        flow, "match_with_ai", lambda _ai, thumbs, sc: {0: sc[-1]["number"], 1: sc[0]["number"]}
    )
    r = board.post("/proyectos/1/visuales/flow", data={"links": json.dumps(links)})
    assert "Se colocaron <strong>2</strong>" in r.text
    items = result("visuals")["items"]
    first, last = scenes[0]["paragraph_id"], scenes[-1]["paragraph_id"]
    assert items[first]["provider"] == "flow" and items[last]["ai"]
    assert (project_dir(1) / "visuales" / items[first]["file"]).exists()


def test_import_without_gemini_uses_order(board, monkeypatch):  # noqa: F811
    scenes = result("storyboard")["scenes"]
    links = [{"t": "", "s": FLOW_URL.format(n=i)} for i in range(2)]
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.stages_web.httpx.Client",
        lambda *a, **k: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=jpg((0, 90, 0))))
        ),
    )

    def broken(*args):
        raise RuntimeError("sin cuota")

    monkeypatch.setattr(flow, "match_with_ai", broken)
    r = board.post("/proyectos/1/visuales/flow", data={"links": json.dumps(links)})
    assert "se colocaron por orden" in r.text
    items = result("visuals")["items"]
    assert scenes[0]["paragraph_id"] in items and scenes[1]["paragraph_id"] in items


def test_import_with_nothing_valid(board):  # noqa: F811
    r = board.post("/proyectos/1/visuales/flow", data={"links": "hola"})
    assert "No había enlaces de Flow" in r.text


def test_visuals_page_shows_flow_steps(board):  # noqa: F811
    page = board.get("/proyectos/1/visuales").text
    assert "Imágenes con Google Flow" in page and "Copiar mensaje 1" in page
    assert "Recoger imágenes de Flow" in page and "Pollinations" not in page
    assert jobs  # el módulo se usa en la página


def test_automatic_mode_stops_at_visuals_and_flow_resumes_it(logged_in, ai, monkeypatch):  # noqa: F811
    """En automático se para antes de Visuales (nunca fotos de bancos) y, al importar
    todas las imágenes de Flow, el montaje se pone en marcha solo."""
    from app.db import SessionLocal
    from app.models import Job
    from tests.test_strategy_script import make_project, run_all

    make_project(logged_in, "automatico")
    logged_in.post("/proyectos/1/etapas/research")
    run_all()
    assert "voice" in [r for r in ("voice",) if result("voice")]
    assert result("visuals") is None
    scenes = result("storyboard")["scenes"]
    links = [{"t": "", "s": FLOW_URL.format(n=i)} for i in range(len(scenes))]
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.stages_web.httpx.Client",
        lambda *a, **k: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=jpg((1, 2, 3))))
        ),
    )
    monkeypatch.setattr(flow, "match_with_ai", lambda *a: {})  # por orden
    logged_in.post("/proyectos/1/visuales/flow", data={"links": json.dumps(links)})
    with SessionLocal() as db:
        assert db.query(Job).filter_by(project_id=1, stage="edit").count() == 1

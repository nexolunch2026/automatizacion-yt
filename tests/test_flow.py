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


def test_messages_have_24_scenes_each_and_the_style():
    scenes = [{"number": n, "image_prompt": f"scene {n}"} for n in range(1, 66)]
    plan = {"scenes": scenes, "visual_bible": {"characters": ["a stick figure with a bun"]}}
    parts = flow.messages(plan)
    assert [(p["first"], p["last"]) for p in parts] == [(1, 24), (25, 48), (49, 65)]
    text = parts[0]["text"]
    assert "Create 24 SEPARATE images" in text and "stickman" in text and "16:9" in text
    assert "a stick figure with a bun" in text and "\n9. scene 9" in text
    assert "9:16" in flow.messages(plan, portrait=True)[0]["text"]
    single = flow.single_message(plan)
    assert "Create 65 SEPARATE images" in single and "\n65. scene 65" in single
    assert "do not stop until ALL" in single


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


def test_match_with_ai_goes_in_batches_and_never_repeats_a_scene(monkeypatch):
    calls = []

    def fake_batch(_ai, thumbs, scenes):
        calls.append((len(thumbs), [s["number"] for s in scenes]))
        return {0: scenes[0]["number"]}  # siempre la primera escena libre

    monkeypatch.setattr(flow, "_match_batch", fake_batch)
    scenes = [{"number": n} for n in range(1, 31)]
    result = flow.match_with_ai(None, [b"x"] * 20, scenes)
    assert [c[0] for c in calls] == [8, 8, 4]
    assert result == {0: 1, 8: 2, 16: 3} and 1 not in calls[1][1]


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
    # Las 2 que eligió Gemini y, en los huecos, las demás imágenes nuevas: ninguna escena vacía.
    assert f"Se colocaron <strong>{len(scenes)}</strong>" in r.text
    items = result("visuals")["items"]
    assert all(items[s["paragraph_id"]]["provider"] == "flow" for s in scenes)
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


def test_direct_button_needs_the_project_key_and_answers_flow(board):  # noqa: F811
    r = board.options("/proyectos/1/visuales/flow-directo")
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "https://flow.google.com"
    assert r.headers["access-control-allow-private-network"] == "true"
    files = [("images", ("a.img", jpg((5, 5, 5)), "application/octet-stream"))]
    bad = board.post("/proyectos/1/visuales/flow-directo?k=malo", files=files)
    assert bad.status_code == 403 and "caducado" in bad.json()["error"]


def test_direct_button_places_images_in_their_scenes(board, monkeypatch):  # noqa: F811
    scenes = result("storyboard")["scenes"]
    monkeypatch.setattr(
        flow, "match_with_ai", lambda _ai, thumbs, sc: {0: sc[1]["number"], 1: sc[0]["number"]}
    )
    files = [
        ("images", ("a.img", jpg((200, 0, 0)), "application/octet-stream")),
        ("images", ("b.img", jpg((0, 200, 0)), "application/octet-stream")),
    ]
    r = board.post(f"/proyectos/1/visuales/flow-directo?k={flow.project_token(1)}", files=files)
    body = r.json()
    assert r.status_code == 200 and body["placed"] == 2
    assert r.headers["access-control-allow-origin"] == "https://flow.google.com"
    items = result("visuals")["items"]
    assert items[scenes[0]["paragraph_id"]]["provider"] == "flow"
    assert scenes[0]["number"] not in body["missing"]


def test_direct_bookmarklet_points_to_this_program():
    code = flow.direct_bookmarklet("http://127.0.0.1:8000/", 7, 30)
    assert code.startswith("javascript:")
    assert (
        f"http://127.0.0.1:8000/proyectos/7/visuales/flow-directo?k={flow.project_token(7)}" in code
    )
    assert "__API__" not in code and "N=50" in code
    assert flow.project_token(7) != flow.project_token(8)


def test_long_paragraphs_become_scenes_of_about_12_seconds():
    from app.pipeline.script import split_long_paragraphs, split_paragraph

    text = " ".join(
        f"Frase número {n} con unas cuantas palabras más para alargar." for n in range(8)
    )
    parts = split_paragraph({"id": "abc", "text": text, "sources": [1]})
    assert len(parts) >= 2 and parts[0]["id"] == "abc" and parts[1]["id"] != "abc"
    assert all(len(p["text"].split()) <= 46 for p in parts)
    assert " ".join(p["text"] for p in parts) == text and parts[1]["sources"] == [1]
    short = {"id": "x", "text": "Una frase corta."}
    assert split_paragraph(short) == [short]
    script = {"sections": [{"paragraphs": [{"id": "abc", "text": text}]}]}
    assert split_long_paragraphs(script) and not split_long_paragraphs(script)


def test_flow_messages_only_ask_for_missing_images(board):  # noqa: F811
    from app.stages_web import _without_flow_image

    plan = {"scenes": [{"paragraph_id": "a"}, {"paragraph_id": "b"}]}
    done = {"items": {"a": {"provider": "flow"}}}
    assert _without_flow_image(plan, done)["scenes"] == [{"paragraph_id": "b"}]
    everything = {"items": {"a": {"provider": "flow"}, "b": {"provider": "flow"}}}
    assert len(_without_flow_image(plan, everything)["scenes"]) == 2


def test_soccer_words_avoid_american_football():
    assert flow.soccer_words("a footballer kicking a football in a football stadium") == (
        "a soccer player kicking a soccer ball in a soccer stadium"
    )


def test_messages_add_soccer_rule_only_for_football_scenes():
    soccer = {"scenes": [{"number": 1, "image_prompt": "a stick figure kicking a football"}]}
    other = {"scenes": [{"number": 1, "image_prompt": "a stick figure in an office"}]}
    assert flow.SOCCER_RULE in flow.messages(soccer)[0]["text"]
    assert "a soccer ball" in flow.messages(soccer)[0]["text"]
    assert flow.SOCCER_RULE not in flow.messages(other)[0]["text"]


def test_soccer_words_keep_playing_soccer():
    assert flow.soccer_words("three kids playing football together") == (
        "three kids playing soccer together"
    )


def test_split_paragraph_joins_short_tail_with_two_chunks():
    from app.pipeline.script import split_paragraph

    long = " ".join(["palabra"] * 40) + ". Fin corto aquí."
    parts = split_paragraph({"id": "p1", "text": long}, max_words=36)
    assert len(parts) == 1 or all(len(p["text"].split()) >= 10 for p in parts)
    assert " ".join(p["text"] for p in parts) == long


def test_messages_ask_for_detail_and_story_context():
    story = {
        "visual_bible": {
            "characters": ["Hero: stick figure with glasses", "Boss: stick figure in a suit"]
        },
        "scenes": [
            {
                "number": 1,
                "image_prompt": (
                    "A minimalist 2D stick figure laughing, flat design, white background"
                ),
                "narration": "El jefe se rió de la propuesta.",
            }
        ],
    }
    text = flow.messages(story)[0]["text"]
    assert flow.DETAIL_RULE in text
    assert "OTHER CHARACTERS" in text and "Boss: stick figure in a suit" in text
    assert "1. A stick figure laughing (story moment" in text
    assert "El jefe se rió de la propuesta." in text
    assert "white background" not in text.split("1. ")[1]


def test_gemini_doubts_do_not_leave_scenes_empty():
    """Si Gemini no se atreve con una imagen nueva, rellena la escena que quedó libre."""
    scenes = [{"number": n} for n in (1, 2, 3)]
    mapping = flow.fill_gaps({0: 3}, count=5, scenes=scenes)  # imágenes 1 y 2 sin elegir
    assert sorted(mapping.values()) == [1, 2, 3]
    assert mapping[2] == 1 and mapping[1] == 2  # las más viejas van a las primeras escenas


def test_single_button_sends_to_the_video_open_in_visuals(board, monkeypatch):  # noqa: F811
    """Un solo botón para todos los vídeos: va al último abierto en Visuales."""
    k = flow.active_token()
    assert "abre primero" in board.get(f"/flow-directo?k={k}").json()["error"].lower()
    page = board.get("/proyectos/1/visuales").text
    assert "Copiar" in page and f"/flow-directo?k={k}" in page
    info = board.get(f"/flow-directo?k={k}&info=1").json()
    assert info["n"] >= 1 and info["title"]
    assert board.options("/flow-directo").status_code == 204
    assert board.post("/flow-directo?k=malo").status_code == 403
    monkeypatch.setattr(flow, "match_with_ai", lambda *a: {})  # por orden
    files = [("images", ("a.img", jpg((200, 0, 0)), "application/octet-stream"))]
    body = board.post(f"/flow-directo?k={k}", files=files).json()
    assert body["placed"] == 1


def test_an_image_already_placed_is_never_reused(board, monkeypatch):  # noqa: F811
    """Si Flow devuelve otra vez una imagen ya colocada, no se pone en una segunda escena."""
    monkeypatch.setattr(flow, "match_with_ai", lambda *a: {})
    k = flow.project_token(1)
    red = ("images", ("a.img", jpg((200, 0, 0)), "application/octet-stream"))
    first = board.post(f"/proyectos/1/visuales/flow-directo?k={k}", files=[red]).json()
    again = board.post(f"/proyectos/1/visuales/flow-directo?k={k}", files=[red])
    assert first["placed"] == 1 and again.status_code == 200 and again.json()["placed"] == 0


def test_full_project_is_never_reshuffled(board, monkeypatch):  # noqa: F811
    """Si ya no falta ninguna escena, el botón no cambia ninguna imagen."""
    monkeypatch.setattr(flow, "match_with_ai", lambda *a: {})
    k = flow.project_token(1)
    n = len([s for s in result("storyboard")["scenes"] if s.get("visual_type") != "grafico"])
    files = [
        ("images", (f"{i}.img", jpg((i * 9, 50, 90)), "application/octet-stream")) for i in range(n)
    ]
    board.post(f"/proyectos/1/visuales/flow-directo?k={k}", files=files)
    before = dict(result("visuals")["items"])
    again = [("images", ("z.img", jpg((5, 250, 5)), "application/octet-stream"))]
    body = board.post(f"/proyectos/1/visuales/flow-directo?k={k}", files=again).json()
    assert body["placed"] == 0 and result("visuals")["items"] == before

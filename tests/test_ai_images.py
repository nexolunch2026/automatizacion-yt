import io

import httpx
import pytest
from PIL import Image

from app import jobs
from app.media import project_dir
from app.providers import images as images_module
from app.providers.ai import ProviderError
from app.providers.images import ImageChain, PollinationsImages, pick_image_model
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all


def png_bytes(color=(10, 80, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buffer, "PNG")
    return buffer.getvalue()


class FakeImages:
    name = "pollinations"
    label = "Pollinations (FLUX)"

    def __init__(self, fail_on=None):
        self.prompts = []
        self.fail_on = fail_on

    def generate(self, prompt, portrait, seed):
        self.prompts.append(prompt)
        if self.fail_on and self.fail_on in prompt:
            raise ProviderError("Contenido bloqueado por el filtro.")
        return png_bytes(), ".png"


@pytest.fixture
def board(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    return with_script


def test_generate_all_images_with_ai(board, monkeypatch):
    fake = FakeImages()
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([fake]))
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    items = result("visuals")["items"]
    scenes = result("storyboard")["scenes"]
    assert len(fake.prompts) == len(scenes)
    # El prompt incluye el estilo de la biblia visual.
    assert "Documental oscuro" in fake.prompts[0] and "dark office" in fake.prompts[0]
    assert all(
        e["ai"] and (project_dir(1) / "visuales" / e["file"]).exists() for e in items.values()
    )
    page = board.get("/proyectos/1/visuales").text
    assert "Imagen generada con IA" in page

    # Pulsar otra vez no repite las que ya tienen imagen de IA.
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    assert len(fake.prompts) == len(scenes)


def test_regenerate_one_scene_with_new_prompt(board, monkeypatch):
    fake = FakeImages()
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([fake]))
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    pid = result("storyboard")["scenes"][1]["paragraph_id"]
    before = result("visuals")["items"]
    board.post(f"/proyectos/1/visuales/ia/{pid}", data={"prompt": "a lighthouse at night"})
    run_all()
    after = result("visuals")["items"]
    assert "a lighthouse at night" in fake.prompts[-1]
    assert after[pid]["file"] != before[pid]["file"]
    assert all(after[p] == before[p] for p in before if p != pid)
    scene = next(s for s in result("storyboard")["scenes"] if s["paragraph_id"] == pid)
    assert scene["image_prompt"] == "a lighthouse at night"  # el prompt editado se guarda


def test_failed_scene_does_not_stop_the_rest(board, monkeypatch):
    fake = FakeImages(fail_on="Plano 1")
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([fake]))
    # El prompt de la escena 2 contiene «Plano 1» para que falle solo esa.
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    data = result("visuals")
    assert data["errors"] == [] or any("Escena" in e for e in data["errors"])
    assert sum(1 for e in data["items"].values() if e.get("ai")) >= len(data["items"]) - 1


def test_without_stock_keys_automatic_visuals_use_ai(board, monkeypatch):
    fake = FakeImages()
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([fake]))
    board.post("/proyectos/1/etapas/visuals")  # sin modo: decide el programa
    run_all()
    assert all(e.get("ai") for e in result("visuals")["items"].values())


def test_chain_falls_back_when_gemini_has_no_quota():
    class NoQuota:
        name, label = "gemini", "Gemini"

        def __init__(self):
            self.calls = 0

        def generate(self, prompt, portrait, seed):
            self.calls += 1
            raise ProviderError("Tu cuenta de Gemini no tiene uso gratuito para esta función.")

    gemini, backup = NoQuota(), FakeImages()
    chain = ImageChain([gemini, backup])
    assert chain.generate("x", False, 1)[2] is backup
    chain.generate("y", False, 2)
    assert gemini.calls == 1  # no se vuelve a intentar con Gemini en la misma tarea
    assert chain.notes and "Gemini" in chain.notes[0]


def test_pick_image_model():
    names = [
        "models/gemini-2.5-flash",
        "models/gemini-2.5-flash-image",
        "models/gemini-3-pro-image-preview",
        "models/imagen-4.0-generate-001",
    ]
    assert pick_image_model(names) == ["gemini-2.5-flash-image", "gemini-3-pro-image-preview"]
    assert pick_image_model([]) == ["gemini-2.5-flash-image"]


def test_pollinations_request_and_rate_limit(monkeypatch):
    waits, seen = [], []
    monkeypatch.setattr(images_module, "SLEEP", waits.append)
    responses = iter(
        [
            httpx.Response(429),
            httpx.Response(200, content=png_bytes(), headers={"content-type": "image/png"}),
        ]
    )

    def handler(request):
        seen.append(request)
        return next(responses)

    data, ext = PollinationsImages(
        transport=httpx.MockTransport(handler), pause_seconds=0
    ).generate("a red car", portrait=True, seed=42)
    assert ext == ".png" and data.startswith(b"\x89PNG")
    assert seen[0].url.params["width"] == "768" and seen[0].url.params["seed"] == "42"
    assert "a%20red%20car" in str(seen[0].url)
    assert 20 in waits  # esperó tras el 429


def test_pollinations_non_image_response():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
    )
    with pytest.raises(ProviderError):
        PollinationsImages(transport=transport, pause_seconds=0).generate("x", False, 1)


def test_download_prompts(board):
    r = board.get("/proyectos/1/visuales/prompts.txt")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "=== Escena 01" in r.text and "dark office, cinematic" in r.text
    assert "horizontal 16:9" in r.text


def test_upload_own_image(board):
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    r = board.post(
        f"/proyectos/1/visuales/subir/{pid}",
        files={"image": ("chatgpt.png", png_bytes(), "image/png")},
        data={"is_ai": "1"},
    )
    assert r.status_code == 200
    entry = result("visuals")["items"][pid]
    assert entry["uploaded"] and entry["ai"] and entry["file"].endswith(".jpg")
    assert (project_dir(1) / "visuales" / entry["file"]).exists()
    assert "Imagen subida por ti (generada con IA)" in r.text


def test_upload_rejects_non_images(board):
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    r = board.post(
        f"/proyectos/1/visuales/subir/{pid}", files={"image": ("virus.exe", b"MZ...", "image/png")}
    )
    assert r.status_code == 400


def test_uploaded_image_survives_ai_generation(board, monkeypatch):
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    board.post(
        f"/proyectos/1/visuales/subir/{pid}",
        files={"image": ("a.png", png_bytes(), "image/png")},
        data={"is_ai": "1"},
    )
    fake = FakeImages()
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([fake]))
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    assert result("visuals")["items"][pid]["uploaded"]  # no se sustituyó


def test_uploaded_non_ai_image_is_never_replaced(board, monkeypatch):
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    board.post(
        f"/proyectos/1/visuales/subir/{pid}", files={"image": ("a.png", png_bytes(), "image/png")}
    )
    monkeypatch.setattr(jobs, "get_image_providers", lambda db: ImageChain([FakeImages()]))
    board.post("/proyectos/1/etapas/visuals", data={"mode": "ai"})
    run_all()
    entry = result("visuals")["items"][pid]
    assert entry["uploaded"] and not entry["ai"]

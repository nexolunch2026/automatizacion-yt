import io

import pytest
from PIL import Image

from app import jobs
from app.media import project_dir
from app.providers.ai import ProviderError
from app.providers.images import ImageChain, pick_image_model
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
    assert "stickman" in fake.prompts[0] and "dark office" in fake.prompts[0]
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


def test_download_prompts(board):
    r = board.get("/proyectos/1/visuales/prompts.txt")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "=== Escena 01" in r.text and "dark office" in r.text and "stickman" in r.text
    assert "horizontal 16:9" in r.text
    assert "NO deben llevar texto" in r.text and "No text, no numbers" in r.text


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


def test_exhausted_chain_explains_why():
    class Broken:
        name, label = "gemini", "Gemini"

        def generate(self, prompt, portrait, seed):
            raise ProviderError("sin modelos de imágenes")

    chain = ImageChain([Broken()])
    with pytest.raises(ProviderError):
        chain.generate("x", False, 1)
    with pytest.raises(ProviderError) as info:
        chain.generate("y", False, 2)
    assert "Google Flow" in str(info.value)
    assert "Gemini: sin modelos de imágenes" in info.value.detail


def test_bulk_upload_by_scene_number(board):
    scenes = result("storyboard")["scenes"]
    files = [
        ("images", ("2.png", png_bytes((200, 0, 0)), "image/png")),
        ("images", ("escena 1.png", png_bytes((0, 200, 0)), "image/png")),
    ]
    r = board.post("/proyectos/1/visuales/subir-varias", files=files, data={"is_ai": "1"})
    assert "Se colocaron <strong>2</strong>" in r.text
    items = result("visuals")["items"]
    first = items[scenes[0]["paragraph_id"]]
    second = items[scenes[1]["paragraph_id"]]
    assert first["uploaded"] and second["uploaded"]
    # La imagen «2.png» (roja) quedó en la escena 2.
    with Image.open(project_dir(1) / "visuales" / second["file"]) as img:
        assert img.getpixel((5, 5))[0] > 150


def test_bulk_upload_in_order_from_a_start_scene(board):
    scenes = result("storyboard")["scenes"]
    names = [
        "ChatGPT Image 10_16_01.png",
        "ChatGPT Image 9_59_10.png",
        "ChatGPT Image 10_15_32.png",
    ]
    files = [("images", (n, png_bytes(), "image/png")) for n in names]
    board.post("/proyectos/1/visuales/subir-varias", files=files, data={"start": "2"})
    items = result("visuals")["items"]
    assert scenes[0]["paragraph_id"] not in items  # empieza en la escena 2
    assert all(scenes[i]["paragraph_id"] in items for i in (1, 2, 3))


def test_bulk_upload_reports_problems(board):
    files = [
        ("images", ("1.png", png_bytes(), "image/png")),
        ("images", ("roto.png", b"no es imagen", "image/png")),
        ("images", ("99.png", png_bytes(), "image/png")),
    ]
    r = board.post("/proyectos/1/visuales/subir-varias", files=files)
    assert "no se pudieron usar" in r.text.lower() or "No se pudieron usar" in r.text
    assert "roto.png" in r.text or "99.png" in r.text


def test_scene_number_from_name():
    from app.stages_web import match_files_to_scenes, scene_number_from_name

    assert scene_number_from_name("Escena-05.webp") == 5
    assert scene_number_from_name("scene_12.png") == 12
    assert scene_number_from_name("ChatGPT Image 2 oct 2026, 10_15_32.png") is None
    # Orden natural: 9_59 va antes que 10_15.
    assert match_files_to_scenes(["a 10_15.png", "a 9_59.png"], 28) == {1: 1, 0: 2}
    assert match_files_to_scenes(["1.png", "x.png"], 28) == {0: 1, 1: 2}  # mezcla → por orden

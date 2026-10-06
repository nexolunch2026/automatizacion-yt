from PIL import Image

from app import assistant, jobs
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.pipeline import thumbnail
from tests.test_assistant import TOPIC, JarvisAI, run_all
from tests.test_projects import create_channel


def make_video_project(client, monkeypatch):
    """Proyecto hecho por JARVIS hasta el final (incluye visuales con IA simulada)."""
    fake = JarvisAI()
    original = fake.generate_json

    def generate(prompt, schema):
        if schema.__name__ == "ThumbTexts":
            return schema(texts=[
                {"text": "El fin de Enron", "highlight": "fin"},
                {"text": "63.000 millones", "highlight": "63.000"},
                {"text": "Nadie lo vio venir", "highlight": "nadie"},
            ])  # fmt: skip
        return original(prompt, schema)

    fake.generate_json = generate
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    create_channel(client)
    with SessionLocal() as db:
        assistant.handle(
            db, Incoming(chat_id=-1, text=f"hazme un vídeo sobre {TOPIC}"), trusted=True
        )
    run_all()
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=-1, button="pick:1:0"), trusted=True)
    run_all()


def test_split_lines_balances_words():
    assert thumbnail.split_lines("El fin de Nokia") == ["EL FIN", "DE NOKIA"]
    assert thumbnail.split_lines("¿Qué pasó?") == ["¿QUÉ PASÓ?"]


def test_compose_makes_youtube_ready_jpg(tmp_path):
    background = tmp_path / "foto.png"
    Image.new("RGB", (800, 600), (200, 80, 40)).save(background)
    for layout in thumbnail.LAYOUTS:
        out = thumbnail.compose(
            background,
            "El fin de Nokia",
            "fin",
            layout,
            thumbnail.LANDSCAPE,
            tmp_path / f"{layout}.jpg",
        )
        with Image.open(out) as image:
            assert image.size == (1280, 720) and image.format == "JPEG"
        assert out.stat().st_size < 2_000_000
    portrait = thumbnail.compose(
        None, "Hola", "hola", "left", thumbnail.PORTRAIT, tmp_path / "corto.jpg"
    )
    assert Image.open(portrait).size == (1080, 1920)


def test_full_pipeline_ends_with_three_thumbnails(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "thumbnail")
    assert [v["layout"] for v in data["variants"]] == ["left", "bottom", "center"]
    assert data["variants"][1]["text"] == "63.000 millones"
    assert data["variants"][0]["source"] == "IA"  # fondo nuevo creado con IA
    assert data["selected"] is None
    folder = project_dir(1) / "miniaturas"
    assert all((folder / v["file"]).exists() for v in data["variants"])

    page = logged_in.get("/proyectos/1/miniatura").text
    assert "Elegir esta" in page and "63.000 millones" in page

    logged_in.post("/proyectos/1/miniatura/elegir", data={"index": 2})
    page = logged_in.get("/proyectos/1/miniatura").text
    assert "✓ Elegida" in page and "Descargar" in page
    assert "descargar la elegida" in logged_in.get("/proyectos/1/publicacion").text


def test_edit_texts_keeps_backgrounds(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    logged_in.post(
        "/proyectos/1/miniatura/textos",
        data={"text1": "  Adiós   Enron ", "highlight1": "Adiós", "text2": "", "text3": ""},
    )
    run_all()
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "thumbnail")
        latest = jobs.latest_jobs(db, 1)["thumbnail"]
    assert latest.params == {"texts": [{"text": "Adiós Enron", "highlight": "Adiós"}]}
    assert {v["text"] for v in data["variants"]} == {"Adiós Enron"}
    assert all(v["source"] == "vídeo" for v in data["variants"])  # sin fondo nuevo de IA


def test_telegram_gets_the_three_options(logged_in, monkeypatch):
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=42, text=assistant.link_code(db)))
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        replies = assistant.tick(db)
    album = next(r for r in replies if r.photos)
    assert len(album.photos) == 3
    assert album.buttons[0] == [("✅ 1", "thumb:1:0"), ("✅ 2", "thumb:1:1"), ("✅ 3", "thumb:1:2")]
    with SessionLocal() as db:
        reply = assistant.handle(db, Incoming(chat_id=42, button="thumb:1:1"))[0]
        assert "Miniatura 2 elegida" in reply.text
        assert jobs.get_result(db, 1, "thumbnail")["selected"] == 1


def test_telegram_sends_photo_album(tmp_path):
    import httpx

    from app import telegram

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    photo = tmp_path / "m.jpg"
    Image.new("RGB", (10, 10)).save(photo)
    api = telegram.TelegramAPI("1:x", httpx.Client(transport=httpx.MockTransport(handler)))
    api.send(5, assistant.Reply("¿Cuál?", photos=[photo, photo], buttons=[[("✅ 1", "thumb:1:0")]]))
    assert calls[0].url.path.endswith("/sendMediaGroup") and b"attach://foto1" in calls[0].content
    assert calls[1].url.path.endswith("/sendMessage")


def test_project_page_asks_to_pick_the_thumbnail(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        assert jobs.get_result(db, 1, "thumbnail").get("selected") is None
    assert "Elegir la miniatura" in logged_in.get("/proyectos/1").text
    logged_in.post("/proyectos/1/miniatura/elegir", data={"index": 0})
    assert "Elegir la miniatura" not in logged_in.get("/proyectos/1").text


def test_thumbnail_page_shows_youtube_preview(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    page = logged_in.get("/proyectos/1/miniatura").text
    assert "Así se verá en YouTube" in page and 'id="yt-title"' in page
    assert page.count('class="yt-card"') == 3 and "Destacada (color del canal)" in page

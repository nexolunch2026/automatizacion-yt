import imageio_ffmpeg

from app import assistant, jobs
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.pipeline import shorts
from tests.test_thumbnail import make_video_project


def rows(seconds):
    return [
        {"n": i + 1, "id": f"p{i + 1}", "text": "texto", "seconds": s, "kind": ""}
        for i, s in enumerate(seconds)
    ]


def test_fit_keeps_shorts_between_limits():
    table = rows([10, 10, 10, 10, 10, 10, 10])
    assert shorts._fit(table, 1, 1) == (1, 2)  # crece hasta pasar los 15 s
    assert shorts._fit(table, 1, 7) == (1, 3)  # y no pasa de 38 s (+ la frase gancho)
    assert shorts._fit(rows([70]), 1, 1) is None  # un párrafo larguísimo no sirve


def test_shorts_start_with_the_spoken_hook(logged_in, monkeypatch):
    """La voz dice la frase gancho en el primer segundo, con la mejor imagen y el gancho en
    pantalla; el fragmento va después, sin repetir el texto del gancho."""
    seen = []
    real = shorts.render_video

    def spy(scenes, media, takes, *args, **kwargs):
        seen.append((scenes, media, takes))
        return real(scenes, media, takes, *args, **kwargs)

    monkeypatch.setattr(shorts, "render_video", spy)
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        before = jobs.get_result(db, 1, "shorts")["shorts"]
    keep = [{**s, "hook_line": "Esta empresa engañó a todo el mundo durante años"} for s in before]
    with SessionLocal() as db:
        from app.models import Project

        project = db.get(Project, 1)
        voice = jobs.get_result(db, 1, "voice")
        speak = jobs._hook_speaker(db, voice)
        seen.clear()
        data = shorts.run_shorts(
            project,
            jobs.get_result(db, 1, "script"),
            jobs.get_result(db, 1, "storyboard"),
            voice,
            jobs.media_map(project_dir(1), jobs.get_result(db, 1, "visuals")),
            project_dir(1),
            None,
            lambda p, m: None,
            keep=keep,
            speak=speak,
        )
    scenes, media, takes = seen[0]
    assert scenes[0]["paragraph_id"] == "gancho-1" and scenes[0]["number"] == 0
    assert scenes[0]["narration"].startswith("Esta empresa engañó")
    assert scenes[0]["on_screen_text"] == before[0]["hook"].upper()
    assert scenes[0]["text_from_start"] and not scenes[1]["on_screen_text"]
    assert "gancho-1" in media and takes["gancho-1"] > 0
    assert data["shorts"][0]["hook_line"].startswith("Esta empresa")
    assert data["shorts"][0]["seconds"] > before[0]["seconds"]


def test_spoken_hook_is_optional():
    pick = shorts.ShortPick(start=1, end=2, title="t", hook="h", hook_line="Frase gancho")
    assert shorts._hook_audio(pick, None) is None  # sin voz: como antes

    def broken(text):
        raise OSError("sin conexión")

    assert shorts._hook_audio(pick, broken) is None  # si la voz falla, el Short se hace igual
    assert shorts._hook_audio(pick.model_copy(update={"hook_line": " "}), lambda t: b"x") is None


def test_vertical_band_is_big_and_pans(tmp_path):
    from PIL import Image

    from app.pipeline import render

    wide = tmp_path / "ancha.png"
    Image.new("RGB", (1376, 768), (90, 40, 40)).save(wide)
    band = render.blur_fill_height(wide, 1080, 1920)
    assert band == int(1920 * render.SHORTS_FILL) // 2 * 2  # antes: 602 px, un tercio
    assert render.blur_fill_height(wide, 1920, 1080) is None  # vídeo horizontal: nada
    chain = render.pan_band(10, 30, 1080, band, 1, False)
    assert "crop=1080:" in chain and "x='(iw-ow)" in chain


def test_choose_segments_without_ai_prefers_numbers_and_questions():
    table = rows([12] * 12)
    table[6]["text"] = "¿Cómo perdió 63.000 millones en 2001?"
    picks = shorts.choose_segments(None, {}, table, None, 2)
    assert len(picks) == 2
    assert any(p.start <= 7 <= p.end for p in picks)
    spans = [set(range(p.start, p.end + 1)) for p in picks]
    assert not spans[0] & spans[1]


def test_highlight_word():
    assert shorts.highlight_word("Perdió 63.000 millones") == "63.000"
    assert shorts.highlight_word("Nadie lo vio venir") == "Nadie"


def test_how_many():
    assert shorts.how_many(60) == 1 and shorts.how_many(180) == 2 and shorts.how_many(700) == 3


def test_pipeline_makes_vertical_shorts(logged_in, monkeypatch):
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "shorts")
    short = data["shorts"][0]
    assert short["title"] == "Así cayó Enron" and "#shorts" in short["description"]
    path = project_dir(1) / short["file"]
    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)
    reader.close()
    width, height = meta["size"]
    assert height > width  # vertical

    cover = project_dir(1) / short["cover"]
    from PIL import Image

    assert Image.open(cover).size == (1080, 1920)

    page = logged_in.get("/proyectos/1/shorts").text
    assert "Así cayó Enron" in page and "Alta calidad" in page and "Descargar portada" in page

    before = cover.stat().st_mtime_ns
    logged_in.post("/proyectos/1/shorts/1/portada", data={"text": "  El fin   de Enron "})
    with SessionLocal() as db:
        assert jobs.get_result(db, 1, "shorts")["shorts"][0]["hook"] == "El fin de Enron"
    assert cover.stat().st_mtime_ns != before
    assert logged_in.post("/proyectos/1/shorts/9/portada", data={"text": "x"}).status_code == 404

    logged_in.post("/proyectos/1/etapas/shorts", data={"quality": "final"})
    with SessionLocal() as db:
        assert jobs.latest_jobs(db, 1)["shorts"].params == {"quality": "final", "nuevos": False}


def test_shorts_reach_telegram(logged_in, monkeypatch):
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=42, text=assistant.link_code(db)))
    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        replies = assistant.tick(db)
    notice = next(r for r in replies if "Shorts listos" in r.text)
    assert notice.video.name == "video-preview.mp4" and notice.video.exists()
    covers = next(r for r in replies if "portadas" in r.text)
    assert covers.photos and covers.photos[0].name == "portada.jpg"


def test_short_projects_do_not_make_shorts(logged_in, monkeypatch):
    from app.models import Project
    from app.providers.ai import ProviderError

    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:
        project = db.get(Project, 1)
        project.duration = "Short"
        db.commit()
        try:
            jobs.RUNNERS["shorts"](db, project, lambda p, m: None, {})
            raise AssertionError("debería fallar")
        except ProviderError as exc:
            assert "ya es un Short" in str(exc)


def test_old_shorts_get_a_cover_on_request(logged_in, monkeypatch):
    import copy

    from app.models import StageResult

    make_video_project(logged_in, monkeypatch)
    with SessionLocal() as db:  # como si se hubiera hecho con una versión anterior
        row = db.query(StageResult).filter_by(project_id=1, stage="shorts").one()
        data = copy.deepcopy(row.data)
        for short in data["shorts"]:
            short.pop("cover"), short.pop("paragraph_ids")
        row.data = data
        db.commit()
    assert "Crear portada" in logged_in.get("/proyectos/1/shorts").text
    logged_in.post("/proyectos/1/shorts/1/portada", data={"text": "Nadie lo vio"})
    with SessionLocal() as db:
        cover = jobs.get_result(db, 1, "shorts")["shorts"][0]["cover"]
    assert (project_dir(1) / cover).exists()


def test_shorts_end_with_a_call_to_the_long_video(logged_in, monkeypatch):
    seen = []
    real = shorts.render_video

    def spy(scenes, *args, **kwargs):
        seen.append(scenes)
        return real(scenes, *args, **kwargs)

    monkeypatch.setattr(shorts, "render_video", spy)
    make_video_project(logged_in, monkeypatch)
    assert seen and seen[0][-1]["end_text"] == shorts.END_TEXT
    assert seen[0][0]["text_from_start"]

    page = logged_in.get("/proyectos/1/shorts").text
    assert "Vídeo relacionado" in page and "Guardar enlace" in page
    bad = logged_in.post("/proyectos/1/shorts/enlace", data={"url": "hola"})
    assert bad.status_code == 400

    link = "https://www.youtube.com/watch?v=abcdefghijk&t=3"
    logged_in.post("/proyectos/1/shorts/enlace", data={"url": link})
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "shorts")
    assert data["long_url"] == "https://youtu.be/abcdefghijk"
    first = data["shorts"][0]["description"]
    assert "https://youtu.be/abcdefghijk" in first and "#shorts" in first
    page = logged_in.get("/proyectos/1/shorts").text
    assert "Copiar comentario" in page and "Cambiar enlace" in page

    logged_in.post("/proyectos/1/shorts/enlace", data={"url": ""})
    with SessionLocal() as db:
        data = jobs.get_result(db, 1, "shorts")
    assert not data["long_url"] and "youtu.be" not in data["shorts"][0]["description"]


def test_old_shorts_keep_their_hashtags_when_linked():
    old = {
        "shorts": [{"title": "Así cayó", "description": "Así cayó\n\nEn el canal. #enron #shorts"}]
    }
    data = shorts.link_long_video(old, "https://youtu.be/abcdefghijk")
    text = data["shorts"][0]["description"]
    assert text.endswith("#enron #shorts") and "▶ El documental completo" in text
    assert "abcdefghijk" in shorts.pinned_comment("https://youtu.be/abcdefghijk")


def test_end_card_renders(tmp_path):
    from PIL import Image

    from app.pipeline.render import end_overlay

    path = end_overlay(shorts.END_TEXT, (540, 960), tmp_path / "final.png")
    image = Image.open(path)
    assert image.size == (540, 960) and image.getbbox() is not None

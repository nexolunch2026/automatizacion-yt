import shutil

import httpx
import pytest
from PIL import Image

from app import jobs, settings_web
from app.db import SessionLocal
from app.media import project_dir
from app.models import Project
from app.pipeline import visuals as visuals_module
from app.pipeline.render import build_srt, run_ffmpeg
from app.providers.ai import ProviderError
from app.providers.stock import PexelsStock, PixabayStock, StockItem, download
from tests.test_storyboard_voice import ai, result, with_script  # noqa: F401
from tests.test_strategy_script import run_all

# ---------------------------------------------------------------- bancos de imágenes


def pexels_transport(seen):
    def handler(request):
        seen.append(request)
        if request.headers.get("Authorization") != "clave-buena":
            return httpx.Response(401)
        if "/videos/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "videos": [
                        {
                            "id": 1,
                            "url": "https://pexels.com/video/1",
                            "duration": 12,
                            "user": {"name": "Ana"},
                            "video_files": [
                                {
                                    "link": "https://v/4k.mp4",
                                    "file_type": "video/mp4",
                                    "width": 3840,
                                    "height": 2160,
                                },
                                {
                                    "link": "https://v/hd.mp4",
                                    "file_type": "video/mp4",
                                    "width": 1920,
                                    "height": 1080,
                                },
                                {
                                    "link": "https://v/sd.mp4",
                                    "file_type": "video/mp4",
                                    "width": 640,
                                    "height": 360,
                                },
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "photos": [
                    {
                        "id": 7,
                        "url": "https://pexels.com/photo/7",
                        "photographer": "Luis",
                        "width": 4000,
                        "height": 3000,
                        "src": {"large2x": "https://p/7.jpg"},
                    }
                ]
            },
        )

    return httpx.MockTransport(handler)


def test_pexels_parses_videos_and_photos():
    seen = []
    stock = PexelsStock("clave-buena", transport=pexels_transport(seen))
    [video] = stock.search("empty office", "video", portrait=False)
    assert video.url == "https://v/hd.mp4" and video.duration == 12 and video.author == "Ana"
    [photo] = stock.search("empty office", "image", portrait=True)
    assert photo.url == "https://p/7.jpg" and photo.kind == "image"
    assert seen[1].url.params["orientation"] == "portrait"


def test_pexels_invalid_key():
    with pytest.raises(ProviderError) as info:
        PexelsStock("mala", transport=pexels_transport([])).search("x", "image", False)
    assert "no es válida" in str(info.value) and not info.value.transient


def test_pixabay_parses_results():
    def handler(request):
        if "/videos/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "id": 3,
                            "pageURL": "https://pixabay.com/v/3",
                            "duration": 9,
                            "user": "Eva",
                            "videos": {
                                "large": {"url": "", "width": 0},
                                "medium": {"url": "https://x/m.mp4", "width": 1280, "height": 720},
                            },
                        }
                    ]
                },
            )
        assert request.url.params["orientation"] == "horizontal"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 4,
                        "pageURL": "https://pixabay.com/p/4",
                        "user": "Eva",
                        "largeImageURL": "https://x/4.jpg",
                        "imageWidth": 1920,
                        "imageHeight": 1280,
                    }
                ]
            },
        )

    stock = PixabayStock("k", transport=httpx.MockTransport(handler))
    assert stock.search("q", "video", False)[0].url == "https://x/m.mp4"
    assert stock.search("q", "image", False)[0].url == "https://x/4.jpg"


def test_download_is_atomic(tmp_path):
    item = StockItem("pexels", "1", "image", "https://x/a.jpg", "", "", "", 1, 1)
    download(
        item,
        tmp_path / "a.jpg",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"img")),
    )
    assert (tmp_path / "a.jpg").read_bytes() == b"img"
    with pytest.raises(ProviderError):
        download(
            item, tmp_path / "b.jpg", transport=httpx.MockTransport(lambda r: httpx.Response(500))
        )
    assert not list(tmp_path.glob("*.part")) and not (tmp_path / "b.jpg").exists()


# ---------------------------------------------------------------- visuales + montaje real


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=12",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return path


class FakeStock:
    name = "pexels"

    def __init__(self):
        self.counter = 0

    def search(self, query, kind, portrait, limit=8):
        items = []
        for _ in range(3):
            self.counter += 1
            items.append(
                StockItem(
                    "pexels",
                    str(self.counter),
                    kind,
                    f"https://x/{self.counter}",
                    f"https://pexels.com/{self.counter}",
                    "Ana",
                    "Licencia Pexels",
                    1920,
                    1080,
                    duration=30,
                )
            )
        return items


@pytest.fixture
def stock(monkeypatch, sample_video):
    fake = FakeStock()
    monkeypatch.setattr(jobs, "get_stock_providers", lambda db: [fake])

    def fake_download(item, target, transport=None):
        if item.kind == "video":
            shutil.copy(sample_video, target)
        else:
            Image.new("RGB", (320, 180), (int(item.id) * 40 % 255, 60, 90)).save(target, "JPEG")

    monkeypatch.setattr(visuals_module, "download", fake_download)
    return fake


@pytest.fixture
def produced(with_script):  # noqa: F811
    with_script.post("/proyectos/1/etapas/storyboard")
    run_all()
    with_script.post("/proyectos/1/etapas/voice")
    run_all()
    return with_script


def test_visuals_are_downloaded_with_credits(produced, stock):
    produced.post("/proyectos/1/etapas/visuals")
    run_all()
    items = result("visuals")["items"]
    scenes = result("storyboard")["scenes"]
    assert set(items) == {s["paragraph_id"] for s in scenes}
    real = [e for e in items.values() if e.get("provider")]
    assert real and all((project_dir(1) / "visuales" / e["file"]).exists() for e in real)
    assert len({e["id"] for e in real}) == len(real)  # no se repite el mismo visual
    videos = [e for e in real if e["kind"] == "video"]
    assert videos and all((project_dir(1) / "visuales" / e["poster"]).exists() for e in videos)
    page = produced.get("/proyectos/1/visuales").text
    assert "Foto de Ana" in page or "Vídeo de Ana" in page


def test_change_one_visual(produced, stock):
    produced.post("/proyectos/1/etapas/visuals")
    run_all()
    before = result("visuals")["items"]
    pid = next(p for p, e in before.items() if e.get("provider"))
    produced.post(f"/proyectos/1/visuales/cambiar/{pid}")
    run_all()
    after = result("visuals")["items"]
    assert after[pid]["id"] != before[pid]["id"]
    assert all(after[p] == before[p] for p in before if p != pid)  # el resto igual


def test_without_stock_keys_scenes_use_ai_images(produced):
    produced.post("/proyectos/1/etapas/visuals")
    run_all()
    assert all(e.get("ai") for e in result("visuals")["items"].values())
    assert "necesitas una clave gratis de Pixabay" in produced.get("/proyectos/1/visuales").text


def test_full_video_render(produced, stock):
    produced.post("/proyectos/1/etapas/visuals")
    run_all()
    with SessionLocal() as db:
        jobs.enqueue(db, 1, "edit", {"quality": "test"})
    run_all()

    render = result("edit")["renders"]["test"]
    video = project_dir(1) / render["file"]
    assert video.exists() and video.stat().st_size > 1000
    # La duración del vídeo coincide con la de la narración.
    assert render["seconds"] == pytest.approx(result("voice")["seconds"], abs=0.1)
    srt = (project_dir(1) / "video" / "subtitulos.srt").read_text(encoding="utf-8")
    assert "Nadie lo vio venir." in srt and "-->" in srt
    credits = (project_dir(1) / "video" / "creditos.txt").read_text(encoding="utf-8")
    assert "Ana (Pexels)" in credits
    with SessionLocal() as db:
        assert db.get(Project, 1).status == "Edición"
    page = produced.get("/proyectos/1/video").text
    assert "Descargar MP4" not in page or "Vista previa" in page


def test_render_refuses_when_script_changed(produced):
    pid = result("storyboard")["scenes"][0]["paragraph_id"]
    produced.post(f"/proyectos/1/guion/parrafos/{pid}", data={"action": "delete"})
    produced.post("/proyectos/1/etapas/storyboard")
    run_all()
    produced.post("/proyectos/1/etapas/edit", data={"quality": "preview"})
    run_all()
    assert "Las escenas y la voz no coinciden" in produced.get("/proyectos/1/video").text


def test_build_srt_splits_long_paragraphs():
    from app.pipeline.render import srt_problems

    text = (
        "Kodak inventó la cámara digital en 1975, pero la escondió en un cajón durante años "
        "porque temía que acabara con su negocio de carretes. Al final, eso la hundió."
    )
    srt = build_srt([(text, 0.0, 10.0)])
    cues = [block.splitlines() for block in srt.strip().split("\n\n")]
    assert cues[0][1].startswith("00:00:00,000 --> ") and cues[-1][1].endswith("00:00:10,000")
    for cue in cues:
        assert len(cue) <= 4 and all(len(line) <= 42 for line in cue[2:])  # 2 líneas cortas
    assert any(cue[-1].endswith("carretes.") for cue in cues)  # corta en el punto
    assert srt_problems(srt)["hard"] == 0
    assert build_srt([("", 0.0, 1.0)]) == ""


def test_srt_lines_always_fit_and_short_cues_merge():
    from app.pipeline.render import _two_lines, srt_problems

    text = "a" * 39 + " " + "b" * 9 + " " + "c" * 34  # no cabe en 2 líneas de 42
    srt = build_srt([(text, 0.0, 30.0)])
    assert srt_problems(srt)["long"] == 0  # se parte en más trozos
    assert _two_lines("a" * 30 + " " + "b" * 20) == "a" * 30 + "\n" + "b" * 20
    srt = build_srt([("Sí. Kodak dudó durante años antes de decidir nada.", 0.0, 4.0)])
    first = srt.split("\n\n")[0].splitlines()
    assert first[2].startswith("Sí. Kodak")  # «Sí.» solo pasaría en un suspiro
    quoted = build_srt([("Dijo «fin.» Y se fue de la empresa para siempre jamás.", 0.0, 20.0)])
    assert quoted.split("\n\n")[0].splitlines()[2] == "Dijo «fin.»"
    overlapping = build_srt([("Uno dos tres.", 0.0, 2.0), ("Cuatro cinco seis.", 1.0, 3.0)])
    assert srt_problems(overlapping)["broken"] == 0
    assert "00:00:02,000 --> 00:00:03,000" in overlapping  # no empieza antes del anterior


def test_srt_problems_finds_long_and_fast_cues():
    from app.pipeline.render import srt_problems

    old = (
        "1\n00:00:00,000 --> 00:00:01,000\n"
        "Esta línea es demasiado larga para leerla bien en el móvil de un vistazo\n\n"
        "2\n00:00:01,000 --> 00:00:04,000\nCorta\n\nbasura"
    )
    found = srt_problems(old)
    assert (found["cues"], found["long"], found["fast"], found["hard"]) == (3, 1, 1, 2)
    assert found["broken"] == 1  # «basura»: dañado, no «bien»
    assert srt_problems("")["cues"] == 0
    bad_time = "1\n00:00:00 --> nada\nHola\n"
    assert srt_problems(bad_time) == {"cues": 1, "long": 0, "fast": 0, "broken": 1, "hard": 1}


def test_stock_key_settings(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_stock_key", lambda p, k: None)
    r = logged_in.post("/configuracion/stock/pexels", data={"api_key": "clave-pexels-1234"})
    assert "Clave de Pexels guardada" in r.text and "••••1234" in r.text

    def reject(provider, key):
        raise ProviderError("La clave de Pixabay no es válida.")

    monkeypatch.setattr(settings_web, "check_stock_key", reject)
    r = logged_in.post("/configuracion/stock/pixabay", data={"api_key": "mala"})
    assert r.status_code == 400 and "no es válida" in r.text


def test_video_page_says_how_subtitles_read_on_mobile(with_script):  # noqa: F811
    folder = project_dir(1) / "video"
    folder.mkdir(parents=True, exist_ok=True)
    old = "1\n00:00:00,000 --> 00:00:01,000\n" + "palabra " * 12 + "\n"
    (folder / "subtitulos.srt").write_text(old, encoding="utf-8")
    page = with_script.get("/proyectos/1/video").text
    assert "1 de 1 trozos se leen mal en el móvil" in page and "Vuelve a montar" in page
    good = build_srt([("Kodak inventó la cámara digital en 1975.", 0.0, 4.0)])
    (folder / "subtitulos.srt").write_text(good, encoding="utf-8")
    assert "se leen bien en el móvil" in with_script.get("/proyectos/1/video").text

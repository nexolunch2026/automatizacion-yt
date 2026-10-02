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
    srt = build_srt([("uno dos tres cuatro", 0.0, 4.0)], max_words=2)
    assert "00:00:00,000 --> 00:00:02,000\nuno dos" in srt
    assert "00:00:02,000 --> 00:00:04,000\ntres cuatro" in srt


def test_stock_key_settings(logged_in, monkeypatch):
    monkeypatch.setattr(settings_web, "check_stock_key", lambda p, k: None)
    r = logged_in.post("/configuracion/stock/pexels", data={"api_key": "clave-pexels-1234"})
    assert "Clave de Pexels guardada" in r.text and "••••1234" in r.text

    def reject(provider, key):
        raise ProviderError("La clave de Pixabay no es válida.")

    monkeypatch.setattr(settings_web, "check_stock_key", reject)
    r = logged_in.post("/configuracion/stock/pixabay", data={"api_key": "mala"})
    assert r.status_code == 400 and "no es válida" in r.text

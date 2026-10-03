from datetime import datetime, timedelta

import pytest

from app import agenda, analytics, assistant, info, jobs
from app.assistant import Incoming
from app.db import SessionLocal
from app.models import Video, VideoStat
from tests.test_assistant import JarvisAI
from tests.test_projects import create_channel, project_data

NOW = datetime(2026, 10, 9, 23, 0)  # 47 h después de publicar el primer vídeo


@pytest.fixture
def channel(monkeypatch):
    """Canal simulado: el test cambia las visitas entre lecturas."""
    state = {
        "subscribers": 8,
        "latest": [
            {"id": "aaaaaaaaaaa", "title": "Empresas que desaparecieron misteriosamente",
             "views": 80, "likes": 9, "comments": 2, "published": "2026-10-08"},
            {"id": "bbbbbbbbbbb", "title": "El error de Kodak",
             "views": 20, "likes": 1, "comments": 0, "published": "2026-10-01"},
        ],
    }  # fmt: skip
    monkeypatch.setattr(analytics, "fetch_videos", lambda db: state)
    return state


def test_parse_video_id():
    assert analytics.parse_video_id("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert analytics.parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert analytics.parse_video_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert analytics.parse_video_id("hola") is None


def test_refresh_saves_snapshots_links_projects_and_celebrates(logged_in, channel):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data())
    with SessionLocal() as db:
        assert analytics.refresh(db, NOW) == 2
        assert analytics.refresh(db, NOW + timedelta(minutes=10)) == 2  # sin foto repetida
        assert db.query(VideoStat).count() == 2
        assert db.get(Video, "aaaaaaaaaaa").project_id == 1  # enlazado por el título
        assert db.get(Video, "bbbbbbbbbbb").project_id is None

        channel["latest"][0]["views"] = 640
        channel["subscribers"] = 12
        analytics.refresh(db, NOW + timedelta(hours=4))
        alerts = [a["text"] for a in agenda.fire_due(db, NOW + timedelta(hours=4))]
        assert any("pasado las 500 visitas" in a for a in alerts)
        assert not any("100 visitas" in a for a in alerts)  # solo el mayor hito
        assert any("10 suscriptores" in a for a in alerts)
        analytics.refresh(db, NOW + timedelta(hours=8))
        assert len(agenda.fire_due(db, NOW + timedelta(hours=8))) == len(alerts)  # sin repetir

        rows = analytics.video_rows(db, NOW + timedelta(hours=8))
    first = rows[0]
    assert first["title"].startswith("Empresas") and first["views"] == 640
    assert first["views_48h"] == 80  # foto tomada justo a las 48 h
    assert first["like_rate"] is not None and first["history"]
    assert first["vs_average"] > 100


def test_maybe_refresh_waits_and_retries(logged_in, monkeypatch):
    import httpx

    calls = []

    def fail(db):
        calls.append(1)
        raise httpx.ConnectError("sin internet")

    monkeypatch.setattr(analytics, "fetch_videos", fail)
    with SessionLocal() as db:
        assert analytics.maybe_refresh(db, NOW)
        assert not analytics.maybe_refresh(db, NOW + timedelta(minutes=10))
        assert analytics.maybe_refresh(db, NOW + timedelta(minutes=31))  # reintenta
    assert len(calls) == 2


def test_performance_page_and_manual_data(logged_in, channel):
    create_channel(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    assert "Todavía no hay datos" in logged_in.get("/rendimiento").text
    logged_in.post("/rendimiento/actualizar")
    page = logged_in.get("/rendimiento").text
    assert "El error de Kodak" in page and "Analizar ahora" in page

    logged_in.post("/rendimiento/bbbbbbbbbbb", data={"ctr": "6,5 %", "retention": "41",
                                                      "project_id": "1"})  # fmt: skip
    with SessionLocal() as db:
        video = db.get(Video, "bbbbbbbbbbb")
        assert (video.ctr, video.retention, video.project_id) == (6.5, 41.0, 1)

    r = logged_in.post("/proyectos/1/enlace-youtube", data={"url": "https://youtu.be/ccccccccccc"})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.get(Video, "ccccccccccc").project_id == 1


def test_analysis_with_ai_and_jarvis(logged_in, channel, monkeypatch):
    fake = JarvisAI()
    original = fake.generate_json
    prompts = []

    def generate(prompt, schema):
        if schema is analytics.Insight:
            prompts.append(prompt)
            return analytics.Insight(
                summary="Canal muy nuevo: el vídeo de empresas va mejor que la media.",
                worked=["Títulos con misterio"],
                improve=["El inicio puede ser más rápido"],
                next_steps=["Publicar 2 vídeos por semana", "Usar cifras en la miniatura", "x"],
                topic_ideas=["La caída de Nokia"],
            )
        return original(prompt, schema)

    fake.generate_json = generate
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    create_channel(logged_in)
    with SessionLocal() as db:
        say = lambda text: assistant.handle(db, Incoming(chat_id=-1, text=text), trusted=True)  # noqa: E731
        assert "Todavía no tengo cifras" in say("¿cómo va mi vídeo?")[0].text
        analytics.refresh(db, datetime.now())
        text = say("rendimiento")[0].text
        assert "Empresas que desaparecieron" in text and "80 visitas" in text
        assert "Análisis del canal" in say("analiza el canal")[0].text
    assert "«El error de Kodak»" in prompts[0] and "20 visitas" in prompts[0]

    page = logged_in.get("/rendimiento").text
    assert "Títulos con misterio" in page and "La caída de Nokia" in page


def test_feed_gives_video_ids():
    from tests.test_jarvis_skills import CHANNEL_FEED

    videos = info.parse_channel_feed(CHANNEL_FEED, 15)
    assert videos[0]["id"] == "abc" and videos[0]["views"] == 1534

"""Mover un vídeo de canal y leer las cifras de las cuentas de YouTube de los dos canales."""

from datetime import datetime

from app import analytics, info
from app.db import SessionLocal
from app.models import Channel, Project, Video
from app.settings_store import get_setting, set_setting
from tests.test_projects import create_channel, project_data

NOW = datetime(2026, 11, 7, 10, 0)


def test_move_project_to_another_channel(logged_in):
    create_channel(logged_in)
    logged_in.post("/canales", data={"name": "Modo Offside", "niche": "fútbol"})
    logged_in.post("/proyectos/nuevo", data=project_data())
    with SessionLocal() as db:
        offside = db.query(Channel).filter_by(name="Modo Offside").one().id
    page = logged_in.get("/proyectos/1").text
    assert "Mover a este canal" in page and "Modo Offside" in page
    r = logged_in.post("/proyectos/1/canal", data={"channel_id": offside}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Project, 1).channel_id == offside
    assert logged_in.post("/proyectos/1/canal", data={"channel_id": 999}).status_code == 404


def test_link_youtube_account_per_channel(logged_in):
    create_channel(logged_in)
    logged_in.post("/canales/1/youtube", data={"handle": "https://www.youtube.com/@ModoOffside "})
    with SessionLocal() as db:
        assert (
            get_setting(db, "youtube_channel:1").strip() == "https://www.youtube.com/@ModoOffside"
        )
        set_setting(db, "youtube_channel", "@AnatomiaDeUnaMarca")
        assert info.channel_handles(db) == ["@AnatomiaDeUnaMarca", "@ModoOffside"]
    assert "@ModoOffside" in logged_in.get("/canales").text


def test_refresh_reads_every_linked_channel(logged_in, monkeypatch):
    create_channel(logged_in)
    data = {
        "@Anatomia": {"subscribers": 30, "latest": [
            {"id": "aaaaaaaaaaa", "title": "Theranos", "views": 28, "published": "2026-11-05"}]},
        "@ModoOffside": {"subscribers": 12, "latest": [
            {"id": "bbbbbbbbbbb", "title": "Ronaldinho", "views": 50, "published": "2026-11-07"}]},
    }  # fmt: skip

    def fake(db, handle=None):
        if handle == "@Roto":
            raise RuntimeError("canal mal escrito")
        return data[handle]

    monkeypatch.setattr(analytics, "fetch_videos", fake)
    with SessionLocal() as db:
        set_setting(db, "youtube_channel", "@Anatomia")
        set_setting(db, "youtube_channel:1", "@ModoOffside")
        db.add(Channel(name="Otro", created_by=1))
        db.commit()
        set_setting(db, "youtube_channel:2", "@Roto")  # uno mal escrito no tumba los demás
        assert analytics.refresh(db, NOW) == 2
        assert db.get(Video, "bbbbbbbbbbb").title == "Ronaldinho"
        assert get_setting(db, "subs_history")  # el principal, como siempre
        assert get_setting(db, "subs_history:@ModoOffside")

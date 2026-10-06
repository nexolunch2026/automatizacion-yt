from datetime import UTC, datetime, timedelta

from app import info, references
from app.db import SessionLocal
from tests.test_projects import create_channel

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def video(title, views, days_ago):
    published = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M")
    return {"id": title[:11].ljust(11, "x"), "title": title, "views": views,
            "published": published, "url": f"https://youtu.be/{title[:5]}"}  # fmt: skip


def test_analyze_finds_videos_that_beat_the_channel():
    rows = references.analyze(
        [
            video("Normal 1", 1000, 10),  # 100/día
            video("Normal 2", 1200, 10),  # 120/día
            video("Pelotazo", 9000, 10),  # 900/día → ×7,5
            video("Recién salido", 3000, 0.2),  # muy pronto para juzgar
        ],
        NOW,
    )
    assert rows[0]["title"] == "Recién salido" and not rows[0]["outlier"]
    star = next(r for r in rows if r["title"] == "Pelotazo")
    assert star["outlier"] and star["ratio"] >= 2
    assert not next(r for r in rows if r["title"] == "Normal 1")["outlier"]
    assert references.analyze([]) == []


def test_add_accepts_links_and_ignores_repeats(logged_in):
    with SessionLocal() as db:
        assert (
            references.add(db, "https://www.youtube.com/@MagnatesMedia/videos") == "@MagnatesMedia"
        )
        assert references.add(db, "@magnatesmedia") == "@magnatesmedia"
        assert references.handles(db) == ["@MagnatesMedia"]
        assert references.add(db, "hola") is None
        references.remove(db, "@MagnatesMedia")
        assert references.handles(db) == []


def test_page_shows_outliers_and_quick_version(logged_in, monkeypatch):
    create_channel(logged_in)
    info._cache.clear()

    def public(handle, limit=15):
        if handle == "@Roto":
            raise ValueError("no existe")
        return {"name": "Magnates", "subscribers": 1_200_000, "latest": [
            video("Normal", 1000, 10), video("Otro normal", 1100, 10),
            video("Cómo Nokia lo perdió todo", 20000, 10)]}  # fmt: skip

    monkeypatch.setattr(info, "fetch_youtube_public", public)
    page = logged_in.get("/referencias").text
    assert "Añade 3–5 canales" in page
    logged_in.post("/referencias", data={"channel": "@MagnatesMedia"})
    logged_in.post("/referencias", data={"channel": "@Roto"})
    page = logged_in.get("/referencias").text
    assert "Lo que más destaca ahora" in page and "Cómo Nokia lo perdió todo" in page
    assert "Hacer mi versión" in page and "No pude leer este canal" in page
    assert logged_in.post("/referencias", data={"channel": "nada"}).url.query == b"error=1"
    assert "Canales de referencia" in logged_in.get("/rendimiento").text

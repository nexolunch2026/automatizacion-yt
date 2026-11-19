"""Shorts que llevan al vídeo largo: el control de calidad avisa si un Short ya subido de
este vídeo no enlaza al largo en su descripción."""

import json
from datetime import datetime

from app import info
from app.analytics import _store
from app.db import SessionLocal
from app.models import Project, StageResult, Video
from app.pipeline.monetization import project_review
from tests.test_projects import create_channel, project_data

SHORTS = {"shorts": [{"title": "El día que Kodak lo perdió todo"}, {"title": "Kodak y su error"}]}


def test_links_in_descriptions():
    text = (
        "Mira la historia completa: https://youtu.be/AbCdEfGhIj1\n"
        "Otro: https://www.youtube.com/watch?v=ZZZZZZZZZZ2&t=10 y "
        "youtube.com/shorts/SSSSSSSSSS3 · repetido https://youtu.be/AbCdEfGhIj1"
    )
    assert info.video_links(text) == ["AbCdEfGhIj1", "ZZZZZZZZZZ2", "SSSSSSSSSS3"]
    assert info.video_links("") == [] and info.video_links("https://example.com/x") == []


def test_feed_reads_the_description_or_says_it_is_unknown():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
      <entry><yt:videoId>shortkodak1</yt:videoId><title>Kodak y su error</title>
        <published>2026-11-01T10:00:00+00:00</published>
        <media:group><media:description>Completo: https://youtu.be/largokodak1</media:description>
        </media:group></entry>
      <entry><yt:videoId>sinnadaaaa2</yt:videoId><title>Otro</title>
        <published>2026-11-01T10:00:00+00:00</published></entry>
    </feed>"""
    first, second = info.parse_channel_feed(feed)
    assert first["links"] == ["largokodak1"] and second["links"] is None


def setup(client, long_title="Kodak: el error de la cámara digital"):
    create_channel(client)
    client.post("/proyectos/nuevo", data=project_data(topic="Kodak", title="Kodak"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="shorts", data=SHORTS))
        db.add(Video(video_id="largokodak1", title=long_title, published="2026-11-01",
                     project_id=1))  # fmt: skip
        db.commit()


def shorts_check(db):
    checks = project_review(db, db.get(Project, 1))["checks"]
    return next((c for c in checks if c["key"] == "shorts_link"), None)


def store(db, vid, title, links):
    item = {"id": vid, "title": title, "published": "2026-11-02", "views": 5, "links": links}
    _store(db, {"latest": [item]}, datetime.now())
    db.commit()


def test_short_without_the_link_is_warned(logged_in):
    setup(logged_in)
    with SessionLocal() as db:
        assert shorts_check(db) is None  # aún no hay Shorts subidos: no se dice nada
        store(db, "shortkodak1", "El día que Kodak lo perdió todo #shorts", ["otrovideo11"])
        store(db, "shortkodak2", "Kodak y su error", ["largokodak1"])
        check = shorts_check(db)
        assert check["status"] == "warn" and check["title"] == "1 Short sin enlace al vídeo largo"
        assert "«El día que Kodak lo perdió todo #shorts»" in check["detail"]
        assert "Kodak y su error" not in check["detail"]
        store(db, "shortkodak1", "El día que Kodak lo perdió todo #shorts", ["largokodak1"])
        assert shorts_check(db)["status"] == "ok"


def test_unknown_descriptions_and_unpublished_long_say_nothing(logged_in):
    setup(logged_in)
    with SessionLocal() as db:
        store(db, "shortkodak1", "Kodak y su error", None)  # RSS sin descripción
        assert db.get(Video, "shortkodak1").links is None
        assert shorts_check(db) is None
        store(db, "shortkodak1", "Kodak y su error", [])  # ya se sabe: no enlaza nada
        store(db, "shortkodak1", "Kodak y su error", None)  # y no se olvida por un RSS
        assert json.loads(db.get(Video, "shortkodak1").links) == []
        assert shorts_check(db)["status"] == "warn"
        db.get(Video, "largokodak1").project_id = None  # el largo aún no está publicado
        db.commit()
        assert shorts_check(db) is None


def test_long_video_linked_by_mistake_to_a_short_title_is_not_the_long(logged_in):
    setup(logged_in, long_title="Kodak y su error")  # el único «propio» es un Short
    with SessionLocal() as db:
        assert shorts_check(db) is None


def test_short_titles_with_hashtags_and_other_projects(logged_in):
    setup(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak 2", title="Kodak 2"))
    with SessionLocal() as db:
        store(db, "shortkodak2", "Kodak y su error #shorts #kodak", [])  # título corto + «#»
        store(db, "deotroproy", "Kodak y su error", [])
        db.get(Video, "deotroproy").project_id = 2  # es de otro proyecto: no cuenta
        db.commit()
        check = shorts_check(db)
        assert check["title"] == "1 Short sin enlace al vídeo largo"
        assert "#shorts #kodak" in check["detail"]


def test_unknown_shorts_are_said_and_rss_does_not_erase(logged_in):
    setup(logged_in)
    with SessionLocal() as db:
        store(db, "shortkodak1", "Kodak y su error", ["largokodak1"])
        store(db, "shortkodak2", "El día que Kodak lo perdió todo", None)
        check = shorts_check(db)
        assert check["status"] == "ok" and "De 1 más no se pudo leer" in check["detail"]
        store(db, "shortkodak1", "Kodak y su error", [])  # RSS (no «exact»): no borra
        assert json.loads(db.get(Video, "shortkodak1").links) == ["largokodak1"]


def test_broken_rows_and_failures_are_said(logged_in, monkeypatch):
    from app.pipeline import monetization

    setup(logged_in)
    with SessionLocal() as db:
        store(db, "shortkodak1", "Kodak y su error", [])
        db.get(Video, "shortkodak1").links = '[{"a": 1}, ["x"]]'  # JSON raro: no rompe nada
        db.commit()
        assert shorts_check(db)["status"] == "warn"

        def boom(*args):
            raise RuntimeError("fallo")

        monkeypatch.setattr(monetization, "uploaded_shorts", boom)
        assert shorts_check(db)["title"] == "No se pudieron revisar los Shorts subidos"

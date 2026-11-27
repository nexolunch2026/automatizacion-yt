"""«Segunda parte» de los vídeos que despiertan: si JARVIS avisó de que un vídeo viejo
vuelve a tener visitas, el banco de ideas propone primero su segunda parte."""

import json
from datetime import datetime, timedelta

from app import analytics, assistant
from app.assistant import Incoming
from app.db import SessionLocal
from app.models import Project, Video
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401
from tests.test_bank_by_channel import ask, two_channels
from tests.test_niche_bank import fake_bank
from tests.test_projects import brand_channel, create_channel, project_data


def revived(db, video_id, title, project_id=None, days_ago=2):
    db.add(Video(video_id=video_id, title=title, published="2026-01-01", project_id=project_id))
    db.commit()
    when = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    old = json.loads(analytics.get_setting(db, analytics.REVIVAL_KEY) or "{}")
    set_setting(db, analytics.REVIVAL_KEY, json.dumps({**old, video_id: when}))


def test_brand_bank_puts_the_sequel_first_and_it_goes_away_when_done(logged_in, ai):  # noqa: F811
    create_channel(logged_in)
    brand_channel(1)
    logged_in.post("/proyectos/nuevo", data=project_data(topic="Kodak: el error", title="Kodak"))
    with SessionLocal() as db:
        revived(db, "kodakviejoo", "Kodak: el error de la cámara", project_id=1)
        text = ask(db, "banco de ideas")[0].text
        assert "1. <b>Kodak: la segunda parte (lo que pasó después)</b>" in text
        assert "vuelve a tener visitas" in text
        assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)
        assert db.query(Project).filter(Project.topic.like("Kodak: la segunda parte%")).count()
        assert "segunda parte" not in ask(db, "banco de ideas")[0].text  # ya hecha


def test_old_alerts_and_other_channels_are_ignored(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Nokia"))
    with SessionLocal() as db:
        revived(db, "nokiaviejoo", "Nokia: la caída", project_id=1)
        revived(db, "sueltoaaaaa", "Vídeo suelto", days_ago=1)  # 2 canales: sin saber de cuál
        offside = ask(db, "banco de ideas ModoOffside")[0].text
        assert "segunda parte" not in offside  # Nokia es del otro canal
        revived(db, "viejoaaaaaa", "Polaroid", days_ago=40)
        assert [v.video_id for v in analytics.recent_revivals(db)] == ["sueltoaaaaa", "nokiaviejoo"]


def test_niche_bank_also_gets_it(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=2, topic="El caso Bale"))
    with SessionLocal() as db:
        revived(db, "baleviejooo", "El caso Bale", project_id=1)
        text = ask(db, "banco de ideas ModoOffside")[0].text
    assert "1. <b>El caso Bale: la segunda parte (lo que pasó después)</b>" in text
    assert "(Segunda parte)" in text


def test_bad_saved_list_is_harmless(logged_in):
    with SessionLocal() as db:
        for bad in ("no es json", "[1]", '{"x": 5}'):
            set_setting(db, analytics.REVIVAL_KEY, bad)
            assert analytics.recent_revivals(db) == []


def test_a_failure_leaves_the_normal_bank(logged_in, ai, monkeypatch):  # noqa: F811
    create_channel(logged_in)
    brand_channel(1)

    def boom(db, now=None):
        raise RuntimeError("fallo")

    monkeypatch.setattr(analytics, "recent_revivals", boom)
    with SessionLocal() as db:
        text = ask(db, "banco de ideas")[0].text
    assert "Banco de historias" in text and "segunda parte" not in text


def test_unlinked_youtube_title_and_no_repeated_brand(logged_in, ai):  # noqa: F811
    from app import ideas_bank

    create_channel(logged_in)
    brand_channel(1)
    first = ideas_bank.fresh_ideas([])[0]["topic"]  # la primera idea del banco
    brand = first.split(":")[0]
    with SessionLocal() as db:
        revived(db, "conbarraaaa", f"¿{brand}? | La historia completa")
        text = ask(db, "banco de ideas")[0].text
    assert f"1. <b>{brand}: la segunda parte (lo que pasó después)</b>" in text
    assert first not in text  # la idea del banco de esa misma marca no sale justo debajo
    assert text.count("🪝") == 5

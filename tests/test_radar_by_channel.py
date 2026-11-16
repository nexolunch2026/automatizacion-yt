"""«radar ModoOffside»: las noticias de esta semana del nicho de ese canal, y los vídeos que
salen de ellas se crean en ese canal."""

from app import assistant, info, skills
from app.assistant import Incoming, quick_intent
from app.db import SessionLocal
from app.models import Project
from tests.test_assistant import ai  # noqa: F401
from tests.test_jarvis_skills import internet, say  # noqa: F401
from tests.test_projects import brand_channel, create_channel, project_data


def two_channels(client):
    create_channel(client, "Anatomía De Una Marca")
    brand_channel(1)
    create_channel(client, "ModoOffside")  # nicho «casos raros» en las pruebas


def test_intent_reads_the_channel_but_keeps_the_old_phrases():
    assert quick_intent("radar ModoOffside").target == "modooffside"
    assert quick_intent("radar de marcas").action == "radar"
    assert not quick_intent("radar de marcas").target
    assert not quick_intent("radar").target


def test_radar_of_a_channel_uses_its_niche_and_creates_there(logged_in, ai, internet):  # noqa: F811
    two_channels(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    info._cache.clear()
    reply = say("radar ModoOffside")[0]
    assert "Radar de ModoOffside" in reply.text
    searched = [p.get("q", "") for url, p in internet if "news.google.com" in url]
    assert any(q.startswith("casos raros") for q in searched)  # el nicho de ese canal
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=-1, button="radar:0"), trusted=True)
        made = db.query(Project).order_by(Project.id.desc()).first()
        assert made.channel_id == 2


def test_plain_radar_and_unknown_names_use_the_main_channel(logged_in, ai, internet):  # noqa: F811
    two_channels(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=2, topic="Otro"))
    info._cache.clear()
    assert "Radar de tu nicho" in say("radar de noticias")[0].text  # no es un canal
    with SessionLocal() as db:
        assert (skills_setting(db) or "") == ""
        assistant.handle(db, Incoming(chat_id=-1, button="radar:0"), trusted=True)
        made = db.query(Project).order_by(Project.id.desc()).first()
        assert made.channel_id == 2  # sin canal del radar: el de siempre (el último usado)


def skills_setting(db):
    from app.settings_store import get_setting

    return get_setting(db, skills.RADAR_CHANNEL_KEY)


def test_typo_and_empty_niche_are_said(logged_in, ai, internet):  # noqa: F811
    from app.models import Channel

    two_channels(logged_in)
    info._cache.clear()
    typo = say("radar modoofside")[0].text
    assert "No tengo un canal llamado «modoofside»" in typo and "«ModoOffside»" in typo
    assert "No tengo" not in say("radar de noticias")[0].text  # frase genérica: sin aviso
    with SessionLocal() as db:
        db.get(Channel, 2).niche = ""
        db.commit()
    empty = say("radar ModoOffside")[0].text
    assert "no tiene nicho" in empty and "Radar de ModoOffside" not in empty


def test_failed_radar_does_not_change_the_old_buttons(logged_in, ai, internet, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    info._cache.clear()
    say("radar")  # radar de marcas: botones sin canal
    monkeypatch.setattr(info, "brand_radar", lambda db, fetch=True, channel=None: [])
    say("radar ModoOffside")  # sin internet: no hay titulares nuevos
    with SessionLocal() as db:
        assert (skills_setting(db) or "") == ""

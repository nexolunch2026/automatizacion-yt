"""Banco de ideas por canal: «banco de ideas ModoOffside» da el banco de ese canal (fútbol)
y los vídeos que salen de él se crean en ese canal, no en el último usado."""

from app import assistant
from app.assistant import Incoming
from app.db import SessionLocal
from app.models import Project
from tests.test_assistant import ai  # noqa: F401
from tests.test_niche_bank import fake_bank
from tests.test_projects import brand_channel, create_channel, project_data


def ask(db, text):
    return assistant.handle(db, Incoming(chat_id=1, text=text), trusted=True)


def two_channels(client):
    create_channel(client, "Anatomía De Una Marca")
    brand_channel(1)  # 1: marcas (banco fijo)
    create_channel(client, "ModoOffside")  # 2: «casos raros» en las pruebas (no marcas)


def test_bank_of_a_named_channel(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    with SessionLocal() as db:
        reply = ask(db, "banco de ideas ModoOffside")[0]
        assert "Banco de historias — casos raros</b> · ModoOffside" in reply.text
        assert "El caso Dyatlov" in reply.text
        same = ask(db, "banco de ideas modo offside")[0]  # sin mayúsculas ni espacios
        assert "ModoOffside" in same.text
        main = ask(db, "banco de ideas")[0].text
        assert "casos raros" not in main  # el principal sigue siendo el de marcas


def test_ideas_from_the_bank_go_to_that_channel(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)
        made = db.query(Project).filter_by(topic="El caso Dyatlov").one()
        assert made.channel_id == 2  # aunque el último vídeo era del canal 1
        # «ya hecho» cuenta solo en su canal: el banco de marcas no lo da por hecho
        again = ask(db, "banco de ideas ModoOffside")[0].text
        assert "Dyatlov" not in again


def test_other_idea_lists_do_not_inherit_the_bank_channel(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        assistant._save_ideas(db, ["Nokia: la caída"], None)  # p. ej. el radar
        assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)
        made = db.query(Project).filter_by(topic="Nokia: la caída").one()
        assert made.channel_id == 1  # el de siempre (el último usado)


def test_unknown_channel_lists_the_real_ones(logged_in, ai):  # noqa: F811
    two_channels(logged_in)
    with SessionLocal() as db:
        text = ask(db, "banco de ideas Netflix")[0].text
    assert "No tengo ningún canal llamado «netflix»" in text and "«ModoOffside»" in text


def test_regions_and_other_banco_phrases_are_not_channels():
    from app.assistant import quick_intent

    spain = quick_intent("banco de ideas de España")
    assert spain.action == "idea_bank" and spain.topic == "España" and not spain.target
    assert quick_intent("banco de ideas latinoamerica").topic == "Latinoamérica"
    for phrase in ("banco santander", "banco de memoria", "banco de ideas de"):
        found = quick_intent(phrase)
        assert found is None or found.action != "idea_bank" or not found.target


def test_queue_all_keeps_the_bank_channel(logged_in, ai, monkeypatch):  # noqa: F811
    from datetime import datetime

    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        assistant.handle(db, Incoming(chat_id=1, button="idea:all"), trusted=True)
        state = assistant.autopilot_state(db)
        assistant._start_next_in_queue(db, state, datetime.now().strftime("%Y-%m-%d"))
        first = db.query(Project).order_by(Project.id.desc()).first()
        assert first.channel_id == 2 and first.topic == "El caso Dyatlov"


def test_deleted_bank_channel_is_said_not_swapped(logged_in, ai, monkeypatch):  # noqa: F811
    from app.models import Channel

    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        db.delete(db.get(Channel, 2))
        db.commit()
        reply = assistant.handle(db, Incoming(chat_id=1, button="idea:0"), trusted=True)[0]
    assert "ya no existe" in reply.text


def test_channel_without_niche_asks_for_one(logged_in, ai):  # noqa: F811
    from app.models import Channel

    two_channels(logged_in)
    with SessionLocal() as db:
        db.get(Channel, 2).niche = ""
        db.commit()
        text = ask(db, "banco de ideas ModoOffside")[0].text
    assert "no tiene nicho todavía" in text

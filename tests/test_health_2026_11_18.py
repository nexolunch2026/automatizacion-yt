"""Revisión de salud del 18/11/2026: la cola del piloto recordaba el canal de temas que ya
se habían quitado, y un canal borrado hacía perder el tema."""

from datetime import datetime

from app import assistant
from app.assistant import Incoming
from app.db import SessionLocal
from app.models import Channel, Project
from tests.test_assistant import ai  # noqa: F401
from tests.test_bank_by_channel import ask, two_channels
from tests.test_niche_bank import fake_bank
from tests.test_projects import project_data

TODAY = datetime.now().strftime("%Y-%m-%d")


def test_cleared_queue_forgets_the_bank_channel(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        assistant.handle(db, Incoming(chat_id=1, button="idea:all"), trusted=True)
        assistant.handle(db, Incoming(chat_id=1, button="pilot:clear"), trusted=True)
        assistant._queue_add(db, ["El caso Dyatlov"])  # ahora a mano, sin canal
        assistant._start_next_in_queue(db, assistant.autopilot_state(db), TODAY)
        made = db.query(Project).filter_by(topic="El caso Dyatlov").one()
    assert made.channel_id == 1  # el de siempre, no el del banco que se vació


def test_deleted_bank_channel_does_not_lose_the_topic(logged_in, ai, monkeypatch):  # noqa: F811
    two_channels(logged_in)
    fake_bank(monkeypatch, ai)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        ask(db, "banco de ideas ModoOffside")
        assistant.handle(db, Incoming(chat_id=1, button="idea:all"), trusted=True)
        db.delete(db.get(Channel, 2))
        db.commit()
        assistant._start_next_in_queue(db, assistant.autopilot_state(db), TODAY)
        made = db.query(Project).filter_by(topic="El caso Dyatlov").one()
    assert made.channel_id == 1  # sigue con el canal de siempre en vez de perderse

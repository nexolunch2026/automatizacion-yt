from datetime import datetime

import pytest

from app import agenda, assistant, jobs
from app.assistant import Incoming, quick_intent
from app.db import SessionLocal
from app.settings_store import set_setting
from tests.test_assistant import TOPIC, JarvisAI, run_all
from tests.test_projects import create_channel


@pytest.fixture
def ai(monkeypatch):
    fake = JarvisAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    return fake


@pytest.fixture(autouse=True)
def fake_weather(monkeypatch):
    monkeypatch.setattr(
        agenda,
        "fetch_weather",
        lambda city: {
            "city": city,
            "temp": 24,
            "sky": "despejado",
            "max": 27,
            "min": 17,
            "rain": 40,
        },
    )
    agenda._weather_cache.clear()


def say(text):
    with SessionLocal() as db:
        return assistant.handle(db, Incoming(chat_id=-1, text=text), trusted=True)


@pytest.mark.parametrize(
    ("text", "action", "task"),
    [
        ("Jarvis, anota: comprar un micrófono", "task_add", "comprar un micrófono"),
        ("recuérdame llamar a Juan", "task_add", "llamar a Juan"),
        ("ya hice lo del micrófono", "task_done", "lo del micrófono"),
        ("borra la tarea 2", "task_done", "2"),
        ("¿Qué tengo hoy?", "task_list", ""),
        ("jarvis qué hora es", "time", ""),
        ("Buenos días", "briefing", ""),
        ("Jarvis", "briefing", ""),
        ("gracias jarvis", "sleep", ""),
    ],
)
def test_understands_agenda_orders(text, action, task):
    intent = quick_intent(text)
    assert intent.action == action
    assert intent.task == task


def test_wake_word_does_not_break_video_requests():
    intent = quick_intent("Oye Jarvis, hazme un vídeo sobre Kodak")
    assert intent.action == "new_video" and intent.topic == "Kodak"


def test_personal_tasks_by_voice(logged_in):
    assert "Anotado" in say("anota: comprar un micrófono")[0].text
    say("anota: editar la miniatura de Nokia")
    listed = say("tareas")[0].text
    assert "1. comprar un micrófono" in listed and "2. editar la miniatura" in listed

    assert "Hecho: «editar la miniatura de Nokia»" in say("ya hice lo de la miniatura")[0].text
    assert "No encontré" in say("ya hice lo del helicóptero")[0].text
    assert "Te quedan 0" in say("borra la tarea 1")[0].text
    with SessionLocal() as db:
        assert [t for t in agenda.personal_tasks(db) if not t["done"]] == []
    assert "No tienes nada pendiente" in say("tareas")[0].text
    assert "No encontré" in say("ya hice lo del helicóptero")[0].text


def test_done_tasks_disappear_the_next_day(logged_in):
    with SessionLocal() as db:
        task = agenda.add_task(db, "Grabar intro")
        agenda.complete_task(db, task["id"], datetime(2026, 1, 1, 10))
        assert agenda.personal_tasks(db, datetime(2026, 1, 1, 22))[0]["done"]
        assert agenda.personal_tasks(db, datetime(2026, 1, 2, 9)) == []


def test_sleep_order_tells_the_screen(logged_in):
    reply = say("gracias jarvis")[0]
    assert reply.action == "sleep"


def test_studio_tasks_follow_the_projects(logged_in, ai):
    create_channel(logged_in)
    say(f"hazme un vídeo sobre {TOPIC}")
    with SessionLocal() as db:
        assert agenda.studio_tasks(db) == []  # está trabajando: no te pide nada
        assert agenda.production(db)[0]["stage"] == "Investigación"
    run_all()
    with SessionLocal() as db:
        tasks = agenda.studio_tasks(db)
    assert tasks[0]["kind"] == "choice" and tasks[0]["link"] == "/proyectos/1/estrategia"

    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=-1, button="pick:1:0"), trusted=True)
    run_all()
    with SessionLocal() as db:
        assert agenda.studio_tasks(db)[0]["kind"] == "thumb"
        jobs.select_thumbnail(db, 1, 0)
        assert agenda.studio_tasks(db)[0]["kind"] == "review"
        jobs.enqueue(db, 1, "edit", {"quality": "final"})
    run_all()
    with SessionLocal() as db:
        assert agenda.studio_tasks(db)[0]["kind"] == "upload"

    logged_in.post("/proyectos/1/publicado")
    with SessionLocal() as db:
        assert agenda.studio_tasks(db) == []


def test_briefing_speaks_the_day(logged_in, ai):
    create_channel(logged_in)
    with SessionLocal() as db:
        set_setting(db, "jarvis_city", "Medellín")
        agenda.add_task(db, "Comprar café")
        text = agenda.briefing_text(db, datetime(2026, 3, 2, 8, 5), name="jefe")
    assert text.startswith("Buenos días, jefe. Hoy es lunes 2 de marzo y son las 8:05.")
    assert "En Medellín hace 24 grados, despejado" in text
    assert "lluvia: 40 por ciento" in text
    assert "Tienes 1 tarea para hoy. Comprar café." in text


def test_hud_pages(logged_in, ai):
    create_channel(logged_in)
    page = logged_in.get("/jarvis/hud").text
    assert "J.A.R.V.I.S." in page and "jarvis_hud.js" in page

    logged_in.post("/jarvis/preferencias", data={"city": "Medellín", "call_me": "jefe"})
    logged_in.post("/jarvis/tareas", data={"text": "Revisar guion"})
    data = logged_in.get("/jarvis/hud/datos").json()
    assert data["tasks"][0]["text"] == "Revisar guion"
    assert logged_in.get("/jarvis/hud/mundo").json()["weather"]["temp"] == 24
    assert data["system"]["disk_free_gb"] > 0
    assert data["pilot"]["queue"] == []

    task_id = data["tasks"][0]["id"]
    assert logged_in.post(f"/jarvis/tareas/{task_id}/hecha").json()["tasks"][0]["done"]
    assert logged_in.post(f"/jarvis/tareas/{task_id}/borrar").json()["tasks"] == []

    greeting = logged_in.get("/jarvis/hud/saludo").json()["text"]
    assert ", jefe." in greeting and "Medellín" in greeting

    order = logged_in.post("/jarvis/orden", data={"text": "gracias jarvis"}).json()
    assert order["replies"][0]["action"] == "sleep"


def test_hud_needs_login(client):
    r = client.get("/jarvis/hud", follow_redirects=False)
    assert r.status_code == 303

from datetime import datetime

import pytest

from app import assistant, coach
from app.assistant import Incoming, quick_intent
from app.db import SessionLocal
from app.models import StageResult
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project

MONDAY = datetime(2026, 10, 5, 9, 0)
THURSDAY = datetime(2026, 10, 8, 9, 0)


def ask(db, text):
    return assistant.handle(db, Incoming(chat_id=1, text=text), trusted=True)


@pytest.mark.parametrize(
    ("text", "action", "when", "task"),
    [
        ("plan de la semana", "week_plan", "", ""),
        ("¿Qué publico esta semana?", "week_plan", "", ""),
        ("publico los martes a las 19", "publish_day", "martes", "19"),
        ("Publicar los sábados", "publish_day", "sabado", ""),
    ],
)
def test_understands_plan_phrases(text, action, when, task):
    intent = quick_intent(text)
    assert (intent.action, intent.when, intent.task) == (action, when, task)


def _final_video(db, project_id, shorts=()):
    db.add(
        StageResult(
            project_id=project_id,
            stage="edit",
            data={"renders": {"final": {"seconds": 700}}, "last": "final"},
        )
    )
    if shorts:
        data = {"shorts": [{"title": t, "file": f"s{i}.mp4"} for i, t in enumerate(shorts)]}
        db.add(StageResult(project_id=project_id, stage="shorts", data=data))
    db.commit()


def test_plan_without_videos_suggests_starting_one(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        plan = coach.weekly_plan(db, MONDAY)
    assert "empieza uno hoy" in plan["long"] and plan["shorts"] == []
    assert plan["learning"].startswith("una lección")


def test_plan_with_a_ready_video_and_shorts(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1, shorts=["El error de Kodak", "La cámara escondida", "1975"])
        plan = coach.weekly_plan(db, MONDAY)
        assert plan["long"].startswith("Sube «") and "el jueves a las 18:00" in plan["long"]
        assert "mejora lo que marca el Control de calidad" in plan["long"]  # nota baja
        assert plan["shorts"] == [
            ("lunes (hoy)", "El error de Kodak"),
            ("miércoles", "La cámara escondida"),
            ("sábado", "1975"),
        ]
        assert "Hoy toca un Short: «El error de Kodak»" in coach.today_text(db, MONDAY)
        assert "Hoy toca publicar" in coach.today_text(db, THURSDAY)
        text = ask(db, "plan de la semana")[0].text
    assert "Plan de la semana" in text and "Publicas los jueves a las 18:00" in text


def test_change_publish_day(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1)
        reply = ask(db, "publico los martes a las 19")[0]
        assert coach.publish_slot(db) == (1, 19)
        assert "el martes a las 19:00" in reply.text
        set_setting(db, "publish_hour", "no-es-un-número")
        assert coach.publish_slot(db) == (3, 18)  # valores raros: vuelve a lo de siempre


def test_briefing_says_what_to_publish_today(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1)
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        reply = assistant.briefing(db, THURSDAY.replace(hour=10))[0]
    assert "🚀 Hoy toca publicar" in reply.text


def test_uploaded_shorts_leave_the_calendar(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1, shorts=["El error de Kodak", "La cámara escondida", "1975"])
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        reply = assistant.briefing(db, MONDAY.replace(hour=10))[0]
        assert ("✅ Ya subí el Short de hoy", "shortup:1:1") in reply.buttons[0]
        done = assistant.handle(db, Incoming(chat_id=1, button="shortup:1:1"), trusted=True)
        assert "Apuntado" in done[0].text and "La cámara escondida" in done[0].text
        plan = coach.weekly_plan(db, MONDAY)
        assert [t for _, t in plan["shorts"]] == ["La cámara escondida", "1975"]
        bad = assistant.handle(db, Incoming(chat_id=1, button="shortup:9:1"), trusted=True)
        assert "ya no existe" in bad[0].text


def test_shorts_page_marks_and_unmarks(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1, shorts=["El error de Kodak", "La cámara escondida"])
    r = logged_in.post("/proyectos/1/shorts/2/subido", data={"done": "1"}, follow_redirects=False)
    assert r.headers["location"].endswith("/shorts#short-2")
    with SessionLocal() as db:
        assert coach.uploaded_shorts(db) == {"1:2"}
    logged_in.post("/proyectos/1/shorts/2/subido", data={"done": "0"}, follow_redirects=False)
    with SessionLocal() as db:
        assert coach.uploaded_shorts(db) == set()
    assert logged_in.post("/proyectos/1/shorts/5/subido", data={"done": "1"}).status_code == 404


def test_marks_reset_when_shorts_are_made_again_and_bad_data_is_ignored(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        _final_video(db, 1, shorts=["A", "B"])
        coach.mark_short_uploaded(db, 1, 1)
        coach.mark_short_uploaded(db, 7, 1)
        coach.forget_uploaded_shorts(db, 1)
        assert coach.uploaded_shorts(db) == {"7:1"}
        set_setting(db, coach.UPLOADED_KEY, '["1:x", 5, "roto"]')
        assert coach.uploaded_shorts(db) == {"1:x"}
        set_setting(db, coach.UPLOADED_KEY, "{no es json")
        assert coach.uploaded_shorts(db) == set()
    with SessionLocal() as db:
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        stale = assistant.handle(db, Incoming(chat_id=1, button="shortup:1:9"), trusted=True)
        assert "ya no existe" in stale[0].text

from datetime import datetime

from app import coach
from app.db import SessionLocal
from tests.test_projects import create_channel


def test_week_days_mark_long_video_and_shorts(logged_in):
    create_channel(logged_in)
    monday = datetime(2026, 10, 5, 9)
    with SessionLocal() as db:
        coach.set_publish_slot(db, 3, 18)  # jueves
        days = coach.week_days(db, monday)
    assert len(days) == 7 and days[0]["name"] == "lunes (hoy)" and days[0]["today"]
    kinds = {d["name"]: [i["kind"] for i in d["items"]] for d in days}
    assert "long" in kinds["jueves"] and "long" not in kinds["martes"]
    assert "short" in kinds["lunes (hoy)"] and "short" in kinds["miércoles"]
    assert all("learn" in k for k in kinds.values())


def test_week_page_saves_the_slot(logged_in):
    create_channel(logged_in)
    page = logged_in.get("/semana").text
    assert "Tu semana" in page and 'href="/semana" class="active"' in page
    logged_in.post("/semana", data={"day": 5, "hour": 19})
    with SessionLocal() as db:
        assert coach.publish_slot(db) == (5, 19)

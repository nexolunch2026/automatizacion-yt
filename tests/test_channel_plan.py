"""Plan de la semana por canal: con dos canales, el plan dice qué toca en cada uno."""

from app import assistant, coach
from app.db import SessionLocal
from app.models import StageResult
from tests.test_bank_by_channel import two_channels
from tests.test_projects import create_channel, project_data


def test_each_channel_gets_its_line(logged_in):
    two_channels(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic="Kodak"))
    with SessionLocal() as db:
        shorts = {"shorts": [{"title": "Kodak en 60 segundos"}, {"title": "El error"}]}
        db.add(StageResult(project_id=1, stage="shorts", data=shorts))
        db.commit()
        plans = coach.channel_plans(db)
        assert [p["channel"] for p in plans] == ["Anatomía De Una Marca", "ModoOffside"]
        assert plans[0]["shorts"] == 2 and plans[0]["next_short"] == "Kodak en 60 segundos"
        assert "Kodak" in plans[0]["long"]
        assert plans[1] == {
            "channel": "ModoOffside",
            "long": "No hay ningún vídeo en marcha: empieza uno",
            "shorts": 0,
            "next_short": None,
        }
        text = assistant.week_plan_reply(db).text
    assert "📺 <b>Por canal</b>" in text
    assert "<b>ModoOffside</b>: 🎬 No hay ningún vídeo en marcha" in text
    assert "📱 2 Shorts por subir (el próximo: «Kodak en 60 segundos»)" in text


def test_one_channel_keeps_the_old_plan(logged_in):
    create_channel(logged_in)
    with SessionLocal() as db:
        assert coach.channel_plans(db) == []
        assert "Por canal" not in assistant.week_plan_reply(db).text


def test_a_failure_does_not_break_the_plan(logged_in, monkeypatch):
    two_channels(logged_in)

    def boom(db):
        raise RuntimeError("fallo")

    monkeypatch.setattr(coach, "channel_plans", boom)
    with SessionLocal() as db:
        text = assistant.week_plan_reply(db).text
    assert "Plan de la semana" in text and "No pude preparar el plan de cada canal" in text


def test_a_busy_channel_does_not_hide_the_other_ones_shorts(logged_in):
    two_channels(logged_in)
    logged_in.post("/proyectos/nuevo", data=project_data(channel_id=2, topic="Bale"))
    for n in range(11):  # 11 vídeos nuevos en el otro canal
        logged_in.post("/proyectos/nuevo", data=project_data(channel_id=1, topic=f"Marca {n}"))
    with SessionLocal() as db:
        db.add(StageResult(project_id=1, stage="shorts", data={"shorts": [{"title": "Bale"}]}))
        db.commit()
        offside = coach.channel_plans(db)[1]
    assert offside["shorts"] == 1 and "Bale" in offside["long"]

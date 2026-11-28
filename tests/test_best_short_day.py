"""Mejor día para los Shorts: con las visitas de sus primeras 48 h, qué día de la semana
les va mejor (y se dice en el plan de la semana)."""

from app import assistant, best_day
from app.db import SessionLocal
from tests.test_projects import create_channel

DAYS = (0, 2, 4, 5)  # lunes, miércoles, viernes y sábado


def row(weekday, views, title="Kodak en 60 segundos #shorts", **extra):
    base = {"title": title, "weekday": weekday, "views_48h": views, "exact_time": True, "days": 5}
    return {**base, **extra}


def test_tuesday_shorts_win():
    rows = [row(1, 900) for _ in range(4)] + [row(2, 300) for _ in range(4)]
    rows += [row(1, 5000, title="Vídeo largo")]  # no es un Short: no cuenta
    found = best_day.best_short_day(rows, set(), DAYS)
    assert found["status"] == "best" and found["day"] == 1
    assert found["text"].startswith("Tus Shorts que salen en martes consiguen unas 900 visitas")
    assert "Prueba a subir uno de tus Shorts de la semana en martes" in found["text"]
    same_day = best_day.best_short_day(rows, set(), (1, 3))
    assert "Tu plan ya pone Shorts ese día" in same_day["text"]
    # Un vídeo largo (con proyecto) aunque lleve «#shorts», o «#shortstory», no cuenta.
    long_ones = [row(3, 9000, project_id=1, is_short=False) for _ in range(4)]
    long_ones += [row(6, 9000, title="Mi #shortstory") for _ in range(4)]
    assert best_day.best_short_day(rows + long_ones, set(), DAYS)["day"] == 1


def test_program_titles_few_and_similar():
    titles = {"el dia que kodak lo perdio todo"}
    rows = [row(4, 800, title="El día que Kodak lo perdió todo") for _ in range(4)]
    rows += [row(5, 200, title="Otro #shorts") for _ in range(4)]
    assert best_day.best_short_day(rows, titles, DAYS)["day"] == 4  # reconocido por el título
    assert best_day.best_short_day(rows[:5], titles, DAYS)["status"] == "few"
    even = [row(d, 500) for d in (0, 2) for _ in range(4)]
    assert best_day.best_short_day(even, set(), DAYS)["status"] == "same"
    one = [row(0, 500) for _ in range(9)]
    assert best_day.best_short_day(one, set(), DAYS)["status"] == "one_day"


def test_week_plan_shows_it(logged_in, monkeypatch):
    create_channel(logged_in)
    good = {"status": "best", "day": 1, "text": "Tus Shorts que salen en martes van mejor."}
    monkeypatch.setattr(best_day, "short_advice", lambda db: good)
    with SessionLocal() as db:
        assert "📱 Tus Shorts que salen en martes van mejor." in assistant.week_plan_reply(db).text


def test_a_failure_does_not_break_the_plan(logged_in, monkeypatch):
    create_channel(logged_in)

    def boom(*args, **kwargs):
        raise RuntimeError("fallo")

    monkeypatch.setattr(best_day, "best_short_day", boom)
    with SessionLocal() as db:
        assert best_day.short_advice(db) is None
        assert "Plan de la semana" in assistant.week_plan_reply(db).text

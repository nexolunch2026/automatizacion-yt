"""Racha de publicación: cuántas semanas seguidas con vídeo largo (los Shorts no cuentan)."""

from datetime import datetime, timedelta

from app import assistant, coach
from app.db import SessionLocal
from app.models import Video
from tests.test_projects import create_channel

NOW = datetime(2026, 11, 23, 9, 0)  # lunes


def add(db, vid, days_ago, title="Kodak: el error"):
    day = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    db.add(Video(video_id=vid, title=title, published=day))
    db.commit()


def test_streak_counts_weeks_and_skips_shorts(logged_in):
    with SessionLocal() as db:
        assert coach.publishing_streak(db, NOW) is None
        assert coach.streak_text(None) == ""
        add(db, "semana0aaaa", 0)  # esta semana
        add(db, "semana1aaaa", 7)
        add(db, "semana1bbbb", 8)  # dos en la misma semana: cuenta una
        add(db, "semana2aaaa", 14)
        add(db, "semana4aaaa", 28)  # hueco en la semana 3: la racha acaba en la 2
        add(db, "unshortaaaa", 21, "Kodak en 60 segundos #shorts")  # no tapa el hueco
        streak = coach.publishing_streak(db, NOW)
    assert streak == {"weeks": 3, "this_week": True, "weeks_without": 0}
    assert coach.streak_text(streak) == "🔥 Racha: 3 semanas seguidas con vídeo largo."


def test_streak_alive_until_sunday_and_gap(logged_in):
    with SessionLocal() as db:
        add(db, "semana1aaaa", 7)
        streak = coach.publishing_streak(db, NOW)
        assert streak["weeks"] == 1 and not streak["this_week"]
        assert "Esta semana aún no has publicado" in coach.streak_text(streak)
        later = coach.publishing_streak(db, NOW + timedelta(days=14))
    assert later["weeks"] == 0 and later["weeks_without"] == 2  # semanas enteras
    assert coach.streak_text(later).startswith("⚠️ Llevas 2 semanas sin publicar")
    with SessionLocal() as db:
        one = coach.publishing_streak(db, NOW + timedelta(days=7))
    assert coach.streak_text(one).startswith("⚠️ Llevas 1 semana sin publicar")


def test_week_plan_shows_the_streak(logged_in):
    from app.settings_store import set_setting

    create_channel(logged_in)
    with SessionLocal() as db:
        add(db, "hoyaaaaaaaa", 0)
        set_setting(db, "analytics_last", datetime.now().isoformat(timespec="seconds"))
        text = assistant.week_plan_reply(db).text
    assert "🔥 Racha: 1 semana seguida con vídeo largo." in text


def test_old_stats_do_not_claim_a_missing_video(logged_in):
    gap = {"weeks": 0, "this_week": False, "weeks_without": 2}
    alive = {"weeks": 3, "this_week": False, "weeks_without": 0}
    assert coach.streak_text(gap, fresh=False) == ""
    text = coach.streak_text(alive, fresh=False)
    assert text == "🔥 Racha: al menos 3 semanas seguidas con vídeo largo."
    with SessionLocal() as db:
        assert not coach.stats_are_fresh(db)  # nunca se leyeron


def test_a_failure_does_not_break_the_plan(logged_in, monkeypatch):
    create_channel(logged_in)

    def boom(db, now=None):
        raise RuntimeError("fallo")

    monkeypatch.setattr(coach, "publishing_streak", boom)
    with SessionLocal() as db:
        text = assistant.week_plan_reply(db).text
    assert "Plan de la semana" in text and "Racha" not in text


def test_year_boundary_and_short_projects(logged_in):
    from app.models import Project

    create_channel(logged_in)
    monday = datetime(2026, 1, 5, 9, 0)
    with SessionLocal() as db:
        for vid, day in (("a2025w52aaa", "2025-12-22"), ("b2026w01aaa", "2025-12-29")):
            db.add(Video(video_id=vid, title="Kodak", published=day))
        db.add(Project(channel_id=1, title="Short", topic="Short", duration="Short",
                       language="Español", video_type="Documental", automation_mode="manual",
                       created_by=1))  # fmt: skip
        db.commit()
        db.add(Video(video_id="shortproyec", title="Nokia", published="2026-01-05",
                     project_id=1))  # fmt: skip
        db.commit()
        streak = coach.publishing_streak(db, monday)
    assert streak == {"weeks": 2, "this_week": False, "weeks_without": 0}

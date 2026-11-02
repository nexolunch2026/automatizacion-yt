from datetime import datetime, timedelta

from app import analytics, skills
from app.analytics import same_age, video_rows
from app.assistant import Intent
from app.db import SessionLocal
from app.models import Video, VideoStat
from app.skills import same_age_text

NOW = datetime(2026, 11, 2, 12, 0)


def add(db, vid, published, points):
    """points: [(horas tras publicar, visitas)]."""
    db.add(
        Video(video_id=vid, title=f"Vídeo {vid}", published=published.strftime("%Y-%m-%dT%H:%M"))
    )
    for hours, views in points:
        db.add(VideoStat(video_id=vid, taken_at=published + timedelta(hours=hours), views=views))


def rows_for(db):
    return {r["video_id"]: r for r in video_rows(db, NOW)}, video_rows(db, NOW)


def test_compares_with_other_videos_at_the_same_age(logged_in):
    with SessionLocal() as db:
        # Las horas se guardan en UTC; video_rows las pasa a hora local, y la edad se
        # compara en la misma hora local, así que la zona del ordenador no importa.
        add(db, "a", NOW - timedelta(days=30), [(24, 100), (48, 200)])
        add(db, "b", NOW - timedelta(days=20), [(24, 140), (48, 260)])
        add(db, "c", NOW - timedelta(days=10), [(24, 120), (48, 220)])
        add(db, "nuevo", NOW - timedelta(days=1, hours=1), [(24, 400)])
        db.commit()
        by_id, rows = rows_for(db)
        found = same_age(db, rows, by_id["nuevo"])
    assert found["normal"] == 120 and found["count"] == 3 and found["hours"] == 24
    assert round(found["ratio"], 1) == 3.3


def test_not_enough_videos_or_too_early(logged_in):
    with SessionLocal() as db:
        add(db, "a", NOW - timedelta(days=30), [(24, 100), (48, 200)])
        add(db, "b", NOW - timedelta(days=20), [(24, 100), (48, 200)])
        add(db, "nuevo", NOW - timedelta(days=1, hours=1), [(24, 400)])
        add(db, "recien", NOW - timedelta(hours=5), [(4, 50)])
        add(db, "joven", NOW - timedelta(hours=20), [(18, 10)])  # aún no llegó a 24 h
        db.commit()
        by_id, rows = rows_for(db)
        assert same_age(db, rows, by_id["nuevo"]) is None  # 2 vídeos: no basta
        assert same_age(db, rows, by_id["recien"]) is None  # menos de 12 horas


def test_younger_videos_and_tiny_numbers_do_not_count(logged_in):
    with SessionLocal() as db:
        for vid, days in (("a", 30), ("b", 20), ("c", 10)):
            add(db, vid, NOW - timedelta(days=days), [(20, 3), (30, 5)])
        add(db, "nuevo", NOW - timedelta(days=1, hours=1), [(24, 400)])
        db.commit()
        by_id, rows = rows_for(db)
        assert same_age(db, rows, by_id["nuevo"]) is None  # «lo normal» son 4 visitas


def test_advice_text():
    base = {"normal": 100, "count": 3, "hours": 30}
    assert "¡Empújalo!" in same_age_text({**base, "ratio": 2.0})
    assert "×2,0" in same_age_text({**base, "ratio": 2.0}) and "A las 30 h" in same_age_text(
        {**base, "ratio": 2.0}
    )
    assert "en tu media" in same_age_text({**base, "ratio": 1.0})
    assert "en tu media" in same_age_text({**base, "ratio": 1.49})  # sin redondear al límite
    low = same_age_text({**base, "ratio": 0.66})
    assert "por debajo" in low and "Probar y comparar" in low
    assert "cifras de hace 30 h" in same_age_text({**base, "ratio": 1.0}, 30)


def test_jarvis_reply_includes_the_comparison_and_survives_errors(logged_in, monkeypatch):
    with SessionLocal() as db:
        add(db, "a", NOW - timedelta(days=30), [(24, 100), (48, 150)])
        add(db, "b", NOW - timedelta(days=20), [(24, 140), (48, 190)])
        add(db, "c", NOW - timedelta(days=10), [(24, 120), (48, 170)])
        add(db, "nuevo", NOW - timedelta(days=1, hours=1), [(24, 400)])
        db.commit()
        real = analytics.video_rows
        monkeypatch.setattr(analytics, "video_rows", lambda db: real(db, NOW))
        text = skills.act(db, Intent(action="performance"))[0].text
        assert "tus vídeos suelen llevar" in text

        def broken(*args):
            raise RuntimeError("fallo")

        monkeypatch.setattr(analytics, "same_age", broken)
        text = skills.act(db, Intent(action="performance"))[0].text
    assert "Vídeo nuevo" in text and "suelen llevar" not in text

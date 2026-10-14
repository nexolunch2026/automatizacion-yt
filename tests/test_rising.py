from datetime import datetime, timedelta

from app import assistant, rising
from app.db import SessionLocal
from app.models import Video, VideoStat
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401

NOW = datetime(2026, 10, 14, 12, 0)


def row(vid, days, views, views_48h=None, updated=NOW, exact=True):
    return {"video_id": vid, "title": vid, "days": days, "views": views,
            "views_48h": views_48h, "updated": updated, "exact_time": exact}  # fmt: skip


def test_detects_a_video_going_at_double_the_usual():
    rows = [
        row("nuevo", 1.0, 700),  # 24 h: lo normal serían ~283 (400 × raíz de 1/2)
        row("a", 30, 3000, 400),
        row("b", 20, 2000, 400),
        row("joven", 1.5, 50, 50),  # aún no cumplió 48 h: no cuenta para «lo normal»
    ]
    assert rising.rising(rows, NOW) == [
        {"video_id": "nuevo", "title": "nuevo", "views": 700, "hours": 24, "ratio": 2.5}
    ]


def test_normal_too_young_too_old_or_no_history_is_quiet():
    others = [row("a", 30, 3000, 400), row("b", 20, 2000, 400)]
    assert rising.rising([row("normal", 1.0, 400), *others], NOW) == []
    assert rising.rising([row("joven", 0.3, 5000), *others], NOW) == []  # 7 h: aún baila
    assert rising.rising([row("viejo", 5, 9000), *others], NOW) == []  # pasó el arranque
    assert rising.rising([row("solo", 1.0, 900), row("a", 30, 3000, 400)], NOW) == []
    stale = row("parado", 1.0, 900, updated=NOW - timedelta(hours=8))
    assert rising.rising([stale, *others], NOW) == []  # cifras sin actualizar
    assert rising.rising([row("sin hora", 1.0, 900, exact=False), *others], NOW) == []


def local_iso(moment):
    """La hora de publicación como la da YouTube (UTC) para que en local sea `moment`."""
    offset = datetime.now().astimezone().utcoffset() or timedelta()
    return (moment - offset).strftime("%Y-%m-%dT%H:%M")


def add(db, vid, published, shots):
    """`shots`: (horas desde la publicación, visitas)."""
    db.add(Video(video_id=vid, title=f"Vídeo {vid}", published=published))
    start = datetime.fromisoformat(published)
    if "T" in published:  # el programa la pasa a hora local
        start += datetime.now().astimezone().utcoffset() or timedelta()
    for hours, views in shots:
        db.add(VideoStat(video_id=vid, taken_at=start + timedelta(hours=hours), views=views))


def test_jarvis_warns_once_per_video(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        add(db, "a", "2026-09-01T00:00", [(47, 300), (500, 2000)])  # 300 a las 48 h
        add(db, "b", "2026-09-10T00:00", [(47, 500), (400, 1500)])  # 500 a las 48 h
        # Publicado ayer: 900 en ~36 h, más del doble de lo normal (~350).
        add(db, "k", local_iso(NOW - timedelta(hours=36)), [(35.5, 900)])
        db.commit()
        assert assistant.rising_alerts(db, NOW) == []  # sin Telegram
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        set_setting(db, "rising_checked", "")
        reply = assistant.rising_alerts(db, NOW)[0]
        assert "«Vídeo k» está despegando" in reply.text and "900 visitas" in reply.text
        assert ("💡 Ideas parecidas", "ideas") in reply.buttons[0]
        assert assistant.rising_alerts(db, NOW + timedelta(hours=1)) == []  # cada 3 h
        assert assistant.rising_alerts(db, NOW + timedelta(hours=4)) == []  # ya avisado

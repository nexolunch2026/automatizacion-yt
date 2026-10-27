from datetime import datetime, timedelta

from app import assistant, thumb_wins
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.models import StageResult, Video
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project

NOW = datetime(2026, 10, 27, 12, 0)
VARIANTS = [
    {"file": "m1.jpg", "text": "EL FIN DE KODAK", "layout": "left"},
    {"file": "m2.jpg", "text": "1975", "layout": "bottom"},
    {"file": "m3.jpg", "text": "¿POR QUÉ?", "layout": "center"},
]


def setup(db, days_ago=15, vid="kodak"):
    folder = project_dir(1) / "miniaturas"
    folder.mkdir(parents=True, exist_ok=True)
    for v in VARIANTS:
        (folder / v["file"]).write_bytes(b"jpg")
    db.add(StageResult(project_id=1, stage="thumbnail", data={"variants": VARIANTS}))
    published = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    db.add(Video(video_id=vid, title="La caída de Kodak", published=published, project_id=1))
    db.commit()


def press(db, data):
    return assistant.handle(db, Incoming(chat_id=1, button=data), trusted=True)


def test_reminds_two_weeks_after_and_records_the_winner(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db)
        assert assistant.ab_reminders(db, NOW) == []  # sin Telegram
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        reply = assistant.ab_reminders(db, NOW)[0]
        assert "Probar y comparar" in reply.text and "2. «1975»" in reply.text
        assert len(reply.photos) == 3
        assert reply.buttons[0] == [("🏆 La 1", "abwin:kodak:1"), ("🏆 La 2", "abwin:kodak:2"),
                                    ("🏆 La 3", "abwin:kodak:3")]  # fmt: skip
        assert assistant.ab_reminders(db, NOW + timedelta(hours=3)) == []  # una vez
        # Las miniaturas se rehacen antes de contestar: cuenta la que se enseñó.
        row = db.query(StageResult).filter_by(project_id=1, stage="thumbnail").one()
        row.data = {"variants": [{"file": "n.jpg", "text": "OTRA", "layout": "left"}] * 3}
        db.commit()
        done = press(db, "abwin:kodak:2")
        assert "«1975»" in done[0].text
        assert "ganó la 2" in done[0].text and "dos o tres más" in done[0].text
        assert thumb_wins.winners(db)["kodak"]["layout"] == "bottom"
        assert thumb_wins.winners(db)["kodak"]["number"] is True


def test_too_early_too_late_or_one_thumbnail_is_skipped(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, days_ago=5, vid="nuevo")
        db.add(Video(video_id="viejo", title="Viejo", published="2026-09-01", project_id=1))
        db.commit()
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        assert assistant.ab_reminders(db, NOW) == []


def test_bad_buttons_and_not_tested(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db)
        assert "ya no está" in press(db, "abwin:otro:1")[0].text
        assert "ya no existe" in press(db, "abwin:kodak:7")[0].text
        assert "ya no está" in press(db, "abwin:kodak:x")[0].text
        assert "ya no está" in press(db, "abwin:kodak:²")[0].text
        assert "No lo probé" not in press(db, "abwin:kodak:0")[0].text
        assert thumb_wins.winners(db)["kodak"]["n"] == 0
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        assert assistant.ab_reminders(db, NOW) == []  # ya contestado: no se repite


def test_lesson_needs_two_winners_and_finds_the_style(logged_in):
    with SessionLocal() as db:
        assert thumb_wins.lesson(db) == ""
        thumb_wins.record(db, "a", 2, VARIANTS[1])
        assert thumb_wins.lesson(db) == ""
        thumb_wins.record(db, "b", 2, {"text": "63.000 MILLONES", "layout": "bottom"})
        thumb_wins.record(db, "c", 0, None)  # no probado: no cuenta
        text = thumb_wins.lesson(db)
        assert "2 de 2 ganadoras llevan el texto abajo" in text and "llevan una cifra" in text
        thumb_wins.record(db, "d", 1, VARIANTS[0])
        thumb_wins.record(db, "e", 3, VARIANTS[2])
        assert "4 ganadoras apuntadas y aún no se repite" in thumb_wins.lesson(db)  # empate
        set_setting(db, thumb_wins.KEY, "roto")
        assert thumb_wins.winners(db) == {} and thumb_wins.lesson(db) == ""
        thumb_wins.record(db, "f", 1, VARIANTS[0])  # se aparta la copia dañada
        from app.settings_store import get_setting

        assert get_setting(db, thumb_wins.KEY + "_danado") == "roto"
        assert list(thumb_wins.winners(db)) == ["f"]

from datetime import datetime, timedelta

from app import assistant
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.models import StageResult, Video
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project

NOW = datetime(2026, 10, 24, 12, 0)


def add(db, vid, days_ago, ctr, project_id=None):
    published = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    db.add(Video(video_id=vid, title=f"Vídeo {vid}", published=published, ctr=ctr,
                 project_id=project_id))  # fmt: skip


def test_low_ctr_after_a_week_suggests_another_thumbnail(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        folder = project_dir(1) / "miniaturas"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("a.jpg", "b.jpg"):
            (folder / name).write_bytes(b"jpg")
        variants = [{"file": "a.jpg"}, {"file": "b.jpg"}, {"file": "borrada.jpg"}]
        db.add(StageResult(project_id=1, stage="thumbnail", data={"variants": variants}))
        add(db, "flojo", 10, 2.1, project_id=1)  # toca avisar
        add(db, "nuevo", 3, 1.0)  # aún pronto
        add(db, "bueno", 10, 6.5)  # va bien
        add(db, "sincifra", 10, None)  # sin CTR apuntado
        add(db, "suelto", 20, 1.5)  # sin proyecto: aviso sin botón de miniaturas
        db.commit()
        assert assistant.ctr_alerts(db, NOW) == []  # sin Telegram
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        replies = assistant.ctr_alerts(db, NOW)
        texts = {r.text.split("«")[1].split("»")[0]: r for r in replies}
        assert set(texts) == {"Vídeo flojo", "Vídeo suelto"}
        flojo = texts["Vídeo flojo"]
        assert "<b>2,1 %</b>" in flojo.text and "Aquí tienes tus 2" in flojo.text
        assert flojo.buttons == [[("🖼️ Ver mis 2 miniaturas", "thumbs:1")]]
        assert texts["Vídeo suelto"].buttons is None
        assert assistant.ctr_alerts(db, NOW + timedelta(minutes=30)) == []  # cada hora
        assert assistant.ctr_alerts(db, NOW + timedelta(hours=3)) == []  # una vez por vídeo


def test_project_without_thumbnails_offers_new_ones(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        add(db, "flojo", 8, 2.0, project_id=1)
        db.commit()
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        reply = assistant.ctr_alerts(db, NOW)[0]
        assert reply.buttons == [[("🔄 Hacer 3 miniaturas", "rethumb:1")]]
        done = assistant.handle(db, Incoming(chat_id=1, button="rethumb:1"), trusted=True)
        assert "otras 3 miniaturas" in done[0].text


def test_ctr_alerts_run_in_the_tick(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        add(db, "flojo", 9, 2.5)
        db.commit()
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        replies = assistant.tick(db, NOW)
    assert any("<b>2,5 %</b>" in r.text for r in replies)


def test_many_old_videos_arrive_two_per_hour_and_errors_retry(logged_in, ai, monkeypatch):  # noqa: F811
    with SessionLocal() as db:
        for n in range(3):
            add(db, f"v{n}", 30, 1.0)
        db.commit()
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        real = assistant._ctr_reply

        def broken(db, video):
            raise RuntimeError("fallo")

        monkeypatch.setattr(assistant, "_ctr_reply", broken)
        assert assistant.ctr_alerts(db, NOW) == []  # falla: no se apunta como avisado
        monkeypatch.setattr(assistant, "_ctr_reply", real)
        later = NOW + timedelta(hours=2)
        assert len(assistant.ctr_alerts(db, later)) == 2  # como mucho 2 por vuelta
        assert len(assistant.ctr_alerts(db, later + timedelta(hours=2))) == 1  # el que faltaba
        assert assistant.ctr_alerts(db, later + timedelta(hours=4)) == []

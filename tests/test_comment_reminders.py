import json
from datetime import datetime, timedelta

from app import assistant, audience
from app.db import SessionLocal
from app.models import Video
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401

NOW = datetime(2026, 10, 18, 12, 0)


def add(db, vid, hours_ago):
    published = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d")  # solo la fecha
    db.add(Video(video_id=vid, title=f"Vídeo {vid}", published=published))


def test_reminds_once_two_days_after_publishing(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        add(db, "nuevo", 12)  # aún pronto
        add(db, "justo", 60)  # 2,5 días: toca
        add(db, "viejo", 300)  # ya pasó
        db.commit()
        assert assistant.comment_reminders(db, NOW) == []  # sin Telegram
        set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')
        replies = assistant.comment_reminders(db, NOW)
        assert len(replies) == 1 and "«Vídeo justo»" in replies[0].text
        assert replies[0].buttons == [[("💬 Leer comentarios y borradores", "comments:justo")]]
        assert assistant.comment_reminders(db, NOW + timedelta(minutes=30)) == []  # cada hora
        assert assistant.comment_reminders(db, NOW + timedelta(hours=6)) == []  # una vez


def test_button_sends_the_reply_drafts(logged_in, ai, monkeypatch):  # noqa: F811
    report = {
        "summary": "Gusta mucho.",
        "questions": [],
        "requests": [],
        "liked": [],
        "complaints": [],
        "pinned": "",
        "answers": [
            {
                "video": "Vídeo k",
                "text": "¿Y Nokia?",
                "likes": 3,
                "reply": "¡Pronto!",
                "url": "https://www.youtube.com/watch?v=k&lc=c1",
            },
            {"video": "Otro", "text": "De otro vídeo", "likes": 9, "reply": "Gracias"},
        ],
        "comments": 4,
        "date": "18/10/2026 12:00",
    }
    with SessionLocal() as db:
        add(db, "k", 60)
        db.commit()
        set_setting(db, audience.KEY, json.dumps(report))
        monkeypatch.setattr(audience, "analyze", lambda db, ai: report)
        replies = assistant._button(db, "comments:k")
    assert "Lo que pide tu audiencia" in replies[0].text
    assert "Borradores para responder" in replies[1].text and "18/10/2026" in replies[1].text
    assert "«¿Y Nokia?»" in replies[1].text and "👉 ¡Pronto!" in replies[1].text
    assert "De otro vídeo" not in replies[1].text  # solo los de ese vídeo


def test_without_youtube_key_it_says_so(logged_in, ai):  # noqa: F811
    with SessionLocal() as db:
        old = {"summary": "Viejo", "comments": 1, "date": "01/10/2026 10:00", "answers": []}
        set_setting(db, audience.KEY, json.dumps(old))
        replies = assistant._button(db, "comments")
    assert any("Falta la clave gratuita de YouTube" in r.text for r in replies)
    assert any("del 01/10/2026" in r.text for r in replies)

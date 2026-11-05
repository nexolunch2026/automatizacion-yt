"""Short del día con sus textos: el «buenos días» trae el vídeo del Short y su título,
descripción (con el enlace al vídeo largo) y hashtags listos para copiar desde el móvil."""

from app import assistant
from app.assistant import Incoming
from app.db import SessionLocal
from app.media import project_dir
from app.models import StageResult, Video
from app.settings_store import set_setting
from tests.test_assistant import ai  # noqa: F401
from tests.test_strategy_script import make_project
from tests.test_week_plan import MONDAY, _final_video

SHORT = {
    "title": "El error de Kodak",
    "file": "shorts/short-1/short.mp4",
    "tags": "#kodak #marcas #shorts",
    "description": "El error de Kodak\n\nEl documental completo, en el canal.\n\n#kodak",
}


def setup(db, short=None, long_url="", video_file=True):
    _final_video(db, 1)
    data = {"shorts": [short or SHORT, {"title": "La cámara escondida"}]}
    if long_url:
        data["long_url"] = long_url
    db.add(StageResult(project_id=1, stage="shorts", data=data))
    db.commit()
    path = project_dir(1) / SHORT["file"]
    if video_file:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mp4")
    else:
        path.unlink(missing_ok=True)
    set_setting(db, "telegram_chats", '[{"id": 1, "name": "Simón"}]')


def test_briefing_brings_the_short_and_its_texts(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, long_url="https://youtu.be/aaaaaaaaaaa")
        summary, video, texts = assistant.briefing(db, MONDAY.replace(hour=10))
    assert "Buenos días" in summary.text
    assert not any("shortup" in d for row in summary.buttons for _, d in row)  # va abajo
    assert video.video == project_dir(1) / SHORT["file"]
    assert "Short de hoy: «El error de Kodak»" in texts.text
    assert "<code>El error de Kodak</code>" in texts.text
    assert "▶ El documental completo: https://youtu.be/aaaaaaaaaaa" in texts.text
    assert "<code>#kodak #marcas #shorts</code>" in texts.text
    assert "Comentario fijado" in texts.text and "Vídeo relacionado" in texts.text
    assert texts.buttons == [[("✅ Ya subí el Short de hoy", "shortup:1:1")]]


def test_link_from_the_published_video_when_not_pasted(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db)
        db.add(Video(video_id="shortaaaaaa", title="Kodak #shorts", published="2026-10-20",
                     project_id=1))  # fmt: skip
        db.add(Video(video_id="largobbbbbb", title="Kodak", published="2026-10-15",
                     project_id=1))  # fmt: skip
        db.commit()
        texts = assistant.short_texts(db, "1:1")[-1]
    assert "https://youtu.be/largobbbbbb" in texts.text


def test_without_link_says_where_to_paste_it(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, video_file=False)
        replies = assistant.short_texts(db, "1:1")
    assert len(replies) == 1  # sin archivo del vídeo, solo los textos
    assert "El vídeo del Short no lo encuentro" in replies[0].text
    assert "Aún no tengo el enlace del vídeo largo" in replies[0].text
    assert "Comentario fijado" not in replies[0].text
    assert "El documental completo, en el canal." in replies[0].text


def test_texts_are_escaped_and_old_shorts_keep_their_hashtags(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    old = {"title": "<Nokia> & Apple", "description": "x\n\n#nokia #shorts"}  # sin «tags»
    with SessionLocal() as db:
        setup(db, short=old, video_file=False)
        [texts] = assistant.short_texts(db, "1:1")
    assert "<code>&lt;Nokia&gt; &amp; Apple</code>" in texts.text
    assert "<code>#nokia #shorts</code>" in texts.text


def test_button_and_week_plan(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, video_file=False)
        replies = assistant.handle(db, Incoming(chat_id=1, button="shorttxt:1:2"), trusted=True)
        assert "La cámara escondida" in replies[-1].text
        for bad in ("shorttxt:1:9", "shorttxt:9:1", "shorttxt:x"):
            replies = assistant.handle(db, Incoming(chat_id=1, button=bad), trusted=True)
            assert "ya no existe" in replies[0].text


def test_week_plan_offers_the_texts_on_short_days(logged_in, ai, monkeypatch):  # noqa: F811
    from app import coach

    make_project(logged_in, "manual")
    real = coach.weekly_plan
    monkeypatch.setattr(coach, "weekly_plan", lambda db, now=None: real(db, MONDAY))
    with SessionLocal() as db:
        setup(db, video_file=False)
        reply = assistant.week_plan_reply(db)
    assert ("📋 Textos del Short de hoy", "shorttxt:1:1") in reply.buttons[0]


def test_briefing_still_goes_out_if_the_texts_fail(logged_in, ai, monkeypatch):  # noqa: F811
    def broken(db, key):
        raise KeyError("dato raro")

    make_project(logged_in, "manual")
    monkeypatch.setattr(assistant, "short_texts", broken)
    with SessionLocal() as db:
        setup(db)
        [summary] = assistant.briefing(db, MONDAY.replace(hour=10))
    assert ("✅ Ya subí el Short de hoy", "shortup:1:1") in summary.buttons[0]


def test_old_short_without_description_or_title(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, short={"description": None}, video_file=False)
        [texts] = assistant.short_texts(db, "1:1")
    assert "Short de hoy" in texts.text


def test_video_too_big_for_telegram_is_explained(logged_in, ai, monkeypatch):  # noqa: F811
    make_project(logged_in, "manual")
    monkeypatch.setattr(assistant, "MAX_VIDEO_BYTES", 2)
    with SessionLocal() as db:
        setup(db)  # el vídeo de prueba pesa 3 bytes
        [texts] = assistant.short_texts(db, "1:1")
    assert "pesa más de 49 MB" in texts.text


def test_uploaded_short_is_not_taken_as_the_long_video(logged_in, ai):  # noqa: F811
    make_project(logged_in, "manual")
    with SessionLocal() as db:
        setup(db, video_file=False)
        db.add(Video(video_id="shortaaaaaa", title="Kodak #Shorts", published="2026-10-01",
                     project_id=1))  # fmt: skip
        db.add(Video(video_id="largobbbbbb", title="Kodak", published="2026-10-15",
                     project_id=1))  # fmt: skip
        db.commit()
        [texts] = assistant.short_texts(db, "1:1")
    assert "largobbbbbb" in texts.text and "shortaaaaaa" not in texts.text


class FlakyAPI:
    """Telegram simulado: mandar el vídeo falla; lo demás llega."""

    def __init__(self, error):
        self.error, self.sent = error, []

    def answer_button(self, callback_id):
        pass

    def typing(self, chat_id):
        pass

    def send(self, chat_id, reply):
        if reply.video:
            raise self.error
        self.sent.append(reply.text)


def test_texts_still_arrive_when_the_video_fails(logged_in, ai):  # noqa: F811
    from app import telegram
    from app.providers.ai import ProviderError

    make_project(logged_in, "manual")
    update = {"callback_query": {"id": "q", "data": "shorttxt:1:1", "from": {},
                                 "message": {"chat": {"id": 1}}}}  # fmt: skip
    for error in (ProviderError("413 demasiado grande"), PermissionError("bloqueado")):
        api = FlakyAPI(error)
        with SessionLocal() as db:
            if not db.get(StageResult, 1):
                setup(db)
            telegram.process_update(db, api, update)
        assert any("No pude mandarte el vídeo" in t for t in api.sent)
        assert any("<code>El error de Kodak</code>" in t for t in api.sent)
        api = FlakyAPI(error)
        with SessionLocal() as db:
            telegram.broadcast(db, api, assistant.short_texts(db, "1:1"))
        assert any("<code>El error de Kodak</code>" in t for t in api.sent)

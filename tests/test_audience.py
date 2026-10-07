import httpx

from app import assistant, audience
from app.db import SessionLocal
from app.models import Video
from app.settings_store import save_api_key
from tests.test_assistant import ai, studio, talk  # noqa: F401

REAL_DOWNLOAD = audience._download  # las pruebas lo cambian por uno sin internet

REPORT = audience.Report(
    summary="Os encanta la historia de las marcas que caen.",
    questions=["¿Haréis la historia de Nokia?"],
    requests=["La caída de Nokia", "Cómo Zara se hizo gigante"],
    liked=["La narración"],
    complaints=["El audio de la intro está bajo"],
    pinned="¡Nokia llega la semana que viene! ¿Qué marca queréis después?",
)


def thread(text, likes=0):
    return {"snippet": {"topLevelComment": {"snippet": {"textDisplay": text, "likeCount": likes}}}}


def fake_comments(monkeypatch, calls=None):
    def download(video_id, key, limit=50):
        if calls is not None:
            calls.append((video_id, key))
        if video_id == "roto":
            raise httpx.ConnectError("falla")
        return {"items": [thread("Haced  Nokia por favor", 12), thread("Buen vídeo"), thread("")]}

    monkeypatch.setattr(audience, "_download", download)


def add_videos():
    with SessionLocal() as db:
        db.add(Video(video_id="abc", title="Kodak", published="2026-09-01"))
        db.add(Video(video_id="roto", title="Roto", published="2026-09-02"))
        save_api_key(db, "youtube", "clave-yt")
        db.commit()


def test_comments_are_read_and_summarized(studio, ai, monkeypatch):  # noqa: F811
    calls, prompts = [], []
    fake_comments(monkeypatch, calls)
    add_videos()
    monkeypatch.setattr(
        ai, "generate_json", lambda prompt, schema: prompts.append(prompt) or REPORT
    )
    page = studio.get("/rendimiento").text
    assert "Lo que pide tu audiencia" in page and "Leer comentarios" in page
    studio.post("/rendimiento/audiencia")
    assert ("abc", "clave-yt") in calls
    assert "[Kodak] (12 me gusta) Haced Nokia por favor" in prompts[0]
    page = studio.get("/rendimiento").text
    assert "La caída de Nokia" in page and "Hacer este vídeo" in page
    assert "¿Qué marca queréis después?" in page and "2 comentarios leídos" in page
    with SessionLocal() as db:
        assert "La caída de Nokia" in assistant._audience_hint(db)


def test_without_youtube_key_it_explains(studio, ai):  # noqa: F811
    page = studio.get("/rendimiento").text
    assert "hace falta la clave gratuita de YouTube" in page
    add_videos()
    with SessionLocal() as db:
        db.query(Video).delete()
        db.commit()
    reply = studio.post("/rendimiento/audiencia", follow_redirects=False)
    assert "comentarios" in reply.headers["location"]


def test_jarvis_tells_what_the_audience_asks(studio, ai, monkeypatch):  # noqa: F811
    fake_comments(monkeypatch)
    add_videos()
    monkeypatch.setattr(ai, "generate_json", lambda prompt, schema: REPORT)
    reply = talk("¿Qué pide mi audiencia?")[0]
    assert "Lo que pide tu audiencia" in reply.text and "1. La caída de Nokia" in reply.text
    assert reply.buttons and reply.buttons[0][0][1] == "idea:0"


def test_jarvis_keeps_the_last_report_if_youtube_fails(studio, ai, monkeypatch):  # noqa: F811
    fake_comments(monkeypatch)
    add_videos()
    monkeypatch.setattr(ai, "generate_json", lambda prompt, schema: REPORT)
    talk("lee mis comentarios")
    monkeypatch.setattr(
        audience, "_download", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x"))
    )
    reply = talk("comentarios")[0]
    assert "La caída de Nokia" in reply.text  # sin internet: el último informe


def test_jarvis_without_key_says_how(studio, ai):  # noqa: F811
    assert "clave gratuita de YouTube" in talk("qué dicen los comentarios")[0].text


def test_reply_drafts_for_unanswered_comments(studio, ai, monkeypatch):  # noqa: F811
    def download(video_id, key, limit=50):
        items = [thread("¿Haréis Nokia?", 30), thread("Ya respondido", 50), thread("Spam", 1)]
        items[0]["id"], items[1]["id"], items[2]["id"] = "c1", "c2", "c3"
        items[1]["snippet"]["totalReplyCount"] = 2
        return {"items": items if video_id == "abc" else []}

    monkeypatch.setattr(audience, "_download", download)
    add_videos()
    prompts = []
    replies = [  # desordenadas, una vacía y un número que no existe
        audience.Reply(n=2, reply=" "),
        audience.Reply(n=9, reply="No existe"),
        audience.Reply(n=1, reply="¡Sí! Nokia llega pronto."),
    ]
    report = REPORT.model_copy(update={"replies": replies})
    monkeypatch.setattr(
        ai, "generate_json", lambda prompt, schema: prompts.append(prompt) or report
    )
    studio.post("/rendimiento/audiencia")

    assert "SIN RESPONDER" in prompts[0]
    assert "1. [Kodak] ¿Haréis Nokia?" in prompts[0] and "2. [Kodak] Spam" in prompts[0]
    assert "Ya respondido" not in prompts[0].split("SIN RESPONDER")[1]  # ya tiene respuestas
    with SessionLocal() as db:
        saved = audience.last_report(db)
    assert "replies" not in saved
    assert saved["unanswered"] == 2
    assert saved["answers"] == [  # cada borrador con su comentario; el vacío no se guarda
        {
            "video": "Kodak",
            "text": "¿Haréis Nokia?",
            "likes": 30,
            "reply": "¡Sí! Nokia llega pronto.",
            "url": "https://www.youtube.com/watch?v=abc&lc=c1",
        }
    ]
    page = studio.get("/rendimiento").text
    assert "Comentarios por responder" in page and "¡Sí! Nokia llega pronto." in page
    assert "Copiar" in page and "watch?v=abc&amp;lc=c1" in page


def test_old_reports_without_answers_still_show(studio, ai, monkeypatch):  # noqa: F811
    fake_comments(monkeypatch)
    add_videos()
    monkeypatch.setattr(ai, "generate_json", lambda prompt, schema: REPORT)
    studio.post("/rendimiento/audiencia")
    page = studio.get("/rendimiento").text
    assert "La caída de Nokia" in page and "Comentarios por responder" not in page


def test_a_broken_youtube_key_is_not_reported_as_no_comments(studio, ai, monkeypatch):  # noqa: F811
    real_client = httpx.Client

    def respond(reason):
        body = {"error": {"errors": [{"reason": reason}]}}
        transport = httpx.MockTransport(lambda request: httpx.Response(403, json=body))
        return lambda **kw: real_client(transport=transport, **kw)

    monkeypatch.setattr(audience, "_download", REAL_DOWNLOAD)
    monkeypatch.setattr(audience.httpx, "Client", respond("commentsDisabled"))
    assert audience._download("abc", "clave") == {"items": []}  # comentarios desactivados

    monkeypatch.setattr(audience.httpx, "Client", respond("quotaExceeded"))
    add_videos()
    reply = studio.post("/rendimiento/audiencia", follow_redirects=False)
    assert "quotaExceeded" in reply.headers["location"]
    assert "comentarios%20en%20tus" not in reply.headers["location"]

import httpx
import pytest

from app import assistant, jobs, learning, yt_research
from app.assistant import Incoming
from app.db import SessionLocal
from app.providers.ai import GroundedText, ProviderError
from app.settings_store import save_api_key
from tests.test_learning import LESSON

PAGE = (
    'var ytInitialData = {"contents":[{"videoRenderer":{"videoId":"aaaaaaaaaaa",'
    '"title":{"runs":[{"text":"C\\u00f3mo crear un canal \\"faceless\\""}]},'
    '"ownerText":{"runs":[{"text":"Canal Uno"}]},'
    '"lengthText":{"accessibility":{},"simpleText":"12:04"}}},'
    '{"videoRenderer":{"videoId":"bbbbbbbbbbb","title":{"runs":[{"text":"Monetizar"}]}}},'
    '{"videoRenderer":{"videoId":"aaaaaaaaaaa"}},'
    '{"videoRenderer":{"videoId":"ccccccccccc","title":{"runs":[{"text":"Tercero"}]}}}]}'
)
REPORT = yt_research.Report(
    summary="Los canales faceless que funcionan cuentan historias con análisis propio.",
    top_tips=["Gancho en los primeros 15 segundos", "Un nicho claro"],
    apply=["Publica un documental por semana"],
    careful=["Nada de vídeos en serie sin aportar nada"],
    ideas=["La caída de Blockbuster"],
)


class FakeAI:
    def __init__(self, fail=()):
        self.watched, self.prompts, self.fail = [], [], set(fail)

    def watch_video(self, url, prompt, schema):
        self.watched.append(url)
        if url in self.fail:
            raise ProviderError("Vídeo privado")
        return LESSON.model_copy(update={"title": f"Vídeo {len(self.watched)}"})

    def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        assert schema is yt_research.Report
        return REPORT

    def grounded_research(self, prompt, think=True):
        return GroundedText(
            "https://www.youtube.com/watch?v=ddddddddddd\nhttps://youtu.be/eeeeeeeeeee", []
        )


def test_parse_search_page_reads_ids_titles_and_skips_repeats():
    found = yt_research.parse_search_page(PAGE, 5)
    assert [v["id"] for v in found] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    assert found[0]["title"] == 'Cómo crear un canal "faceless"'
    assert found[0]["channel"] == "Canal Uno" and found[0]["length"] == "12:04"
    assert yt_research.parse_search_page(PAGE, 2)[-1]["id"] == "bbbbbbbbbbb"


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("investiga en youtube canales faceless", "canales faceless"),
        ("busca videos de youtube sobre monetizar un canal", "monetizar un canal"),
        ("mira unos videos sobre edicion faceless", "edicion faceless"),
        ("investiga canales faceless en youtube", "canales faceless"),
        ("aprende en youtube sobre guiones", "guiones"),
        ("busca restaurantes cerca", ""),
        ("busca en youtube musica lofi", ""),
        ("mira videos de gatos", ""),
        ("investiga en youtube", ""),
    ],
)
def test_research_topic(text, topic):
    assert assistant.research_topic(text) == topic


def test_quick_intent_starts_research():
    intent = assistant.quick_intent("Jarvis, investiga en YouTube canales faceless")
    assert intent.action == "yt_research" and intent.topic == "canales faceless"


def test_research_runs_in_background_and_reports(logged_in, monkeypatch):
    monkeypatch.setattr(yt_research, "search_page", lambda topic, limit: [
        {"id": "aaaaaaaaaaa", "title": "Uno", "channel": "C1", "length": "10:00"},
        {"id": "bbbbbbbbbbb", "title": "Dos", "channel": "C2", "length": ""},
        {"id": "ccccccccccc", "title": "Tres", "channel": "C3", "length": ""},
    ][:limit])  # fmt: skip
    ai = FakeAI(fail={"https://www.youtube.com/watch?v=bbbbbbbbbbb"})
    with SessionLocal() as db:
        known = learning.learn(db, "https://www.youtube.com/watch?v=ccccccccccc", ai)
        ai.watched.clear()
        item = yt_research.queue(db, "  canales   faceless ", count=9)
        assert item["count"] == yt_research.MAX_COUNT and item["topic"] == "canales faceless"
        assert yt_research.busy(db)
        assert yt_research.process_next(db, lambda db: ai) is True
        assert yt_research.process_next(db, lambda db: ai) is False  # nada más en cola

        report = yt_research.reports(db)[0]
    assert report["status"] == "done" and report["summary"] == REPORT.summary
    # El vídeo ya aprendido no se vuelve a ver; el privado se salta.
    assert ai.watched == [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    ]
    by_id = {v["id"]: v for v in report["videos"]}
    assert by_id["ccccccccccc"]["lesson_id"] == known["id"]
    assert by_id["bbbbbbbbbbb"]["lesson_id"] is None
    assert "canales faceless" in ai.prompts[0] and "Vídeo 1" in ai.prompts[0]

    page = logged_in.get("/aprender").text
    assert "Informe listo" in page and REPORT.top_tips[0] in page and "ver lección" in page


def test_failed_research_is_saved_not_retried(logged_in, monkeypatch):
    monkeypatch.setattr(yt_research, "find_videos", lambda db, topic, ai, limit: [])
    with SessionLocal() as db:
        yt_research.queue(db, "nada de nada")
        yt_research.process_next(db, lambda db: FakeAI())
        report = yt_research.reports(db)[0]
        assert report["status"] == "failed" and "No encontré" in report["message"]
        assert not yt_research.busy(db)
        assert yt_research.process_next(db, lambda db: FakeAI()) is False


def test_search_falls_back_to_google_and_checks_links(logged_in, monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(yt_research, "search_page", offline)
    real = {"ddddddddddd"}  # el otro enlace «no existe»
    monkeypatch.setattr(
        yt_research,
        "oembed",
        lambda vid: {"id": vid, "title": "Real", "channel": "C"} if vid in real else None,
    )
    with SessionLocal() as db:
        found = yt_research.find_videos(db, "faceless", FakeAI(), 3)
    assert [v["id"] for v in found] == ["ddddddddddd"]


def test_search_uses_youtube_key_when_saved(logged_in, monkeypatch):
    calls = []

    def api(topic, key, limit):
        calls.append(key)
        return [{"id": "fffffffffff", "title": "API", "channel": "C", "length": ""}]

    monkeypatch.setattr(yt_research, "search_api", api)
    with SessionLocal() as db:
        save_api_key(db, "youtube", "clave-yt")
        found = yt_research.find_videos(db, "faceless", FakeAI(), 3)
    assert calls == ["clave-yt"] and found[0]["title"] == "API"


def test_web_queue_and_delete(logged_in):
    logged_in.post("/aprender/investigar", data={"topic": "guiones que retienen", "count": "2"})
    with SessionLocal() as db:
        report = yt_research.reports(db)[0]
    assert report["count"] == 2 and report["status"] == "queued"
    page = logged_in.get("/aprender").text
    assert "guiones que retienen" in page and "location.reload" in page
    logged_in.post(f"/aprender/investigacion/{report['id']}/borrar")
    with SessionLocal() as db:
        assert yt_research.reports(db) == []


def test_interrupted_research_restarts(logged_in):
    with SessionLocal() as db:
        item = yt_research.queue(db, "faceless")
        yt_research._update(db, item["id"], status="working")
    jobs.recover_interrupted()
    with SessionLocal() as db:
        assert yt_research.reports(db)[0]["status"] == "queued"


def test_jarvis_queues_and_announces(logged_in):
    with SessionLocal() as db:
        save_api_key(db, "gemini", "clave")
        assistant.handle(db, Incoming(chat_id=42, text=assistant.link_code(db)))
        replies = assistant.handle(
            db, Incoming(chat_id=42, text="investiga en YouTube canales faceless")
        )
        assert "Busco en YouTube" in replies[0].text
        item = yt_research.reports(db)[0]
        yt_research._update(db, item["id"], status="done", **REPORT.model_dump(), videos=[])
        notices = assistant.research_notices(db)
        assert len(notices) == 1 and "Gancho en los primeros 15 segundos" in notices[0].text
        assert assistant.research_notices(db) == []  # solo se avisa una vez

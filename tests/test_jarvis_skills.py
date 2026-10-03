from datetime import datetime, timedelta

import httpx
import pytest

from app import agenda, assistant, info, jobs, skills
from app.assistant import Incoming, quick_intent
from app.db import SessionLocal
from app.settings_store import set_setting
from tests.test_assistant import JarvisAI
from tests.test_projects import create_channel

NEWS_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Tiendas X cierra 40 locales - El Tiempo</title><link>https://n/1</link>
<pubDate>Sat, 03 Oct 2026 10:00:00 GMT</pubDate><source url="https://e">El Tiempo</source></item>
<item><title>La marca Y entra en quiebra - Portafolio</title><link>https://n/2</link>
<pubDate>Sat, 03 Oct 2026 09:00:00 GMT</pubDate><source url="https://p">Portafolio</source></item>
</channel></rss>"""

CHANNEL_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>abc</yt:videoId><title>La caída de Nokia</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
  <published>2026-09-30T12:00:00+00:00</published>
  <media:group><media:community><media:statistics views="1534"/></media:community></media:group>
 </entry>
</feed>"""

CHANNEL_PAGE = (
    '<meta property="og:title" content="Anatomía De Una Marca">'
    '..."externalId":"UCabcdefghijklmnopqrstuv"...'
    '"subscriberCountText":{"accessibility":{},"simpleText":"1,2 mil suscriptores"}'
)


class Response:
    def __init__(self, text="", data=None):
        self.text = text
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def internet(monkeypatch):
    """Internet simulado: noticias, YouTube, dólar y clima."""
    calls = []

    def get(url, **params):
        calls.append((url, params))
        if "news.google.com" in url:
            return Response(NEWS_RSS)
        if "feeds/videos.xml" in url:
            return Response(CHANNEL_FEED)
        if "youtube.com/@" in url:
            return Response(CHANNEL_PAGE)
        if "googleapis.com/youtube/v3/channels" in url:
            return Response(data={"items": [{
                "snippet": {"title": "Anatomía De Una Marca"},
                "statistics": {"subscriberCount": "345", "viewCount": "56789", "videoCount": "12"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}},
            }]})  # fmt: skip
        if "playlistItems" in url:
            return Response(data={"items": [{"contentDetails": {"videoId": "abc"}}]})
        if "youtube/v3/videos" in url:
            return Response(data={"items": [{
                "id": "abc", "snippet": {"title": "Kodak", "publishedAt": "2026-09-01T00:00:00Z"},
                "statistics": {"viewCount": "900", "likeCount": "40"},
            }]})  # fmt: skip
        if "er-api.com" in url:
            return Response(data={"result": "success", "rates": {"COP": 4123.456, "EUR": 0.9}})
        if "geocoding" in url:
            return Response(data={"results": [{"latitude": 6.2, "longitude": -75.5}]})
        if "open-meteo.com/v1/forecast" in url:
            return Response(data={"daily": {
                "time": ["2026-10-03", "2026-10-04", "2026-10-05"],
                "weather_code": [1, 61, 3], "temperature_2m_max": [27.2, 25, 26],
                "temperature_2m_min": [16.8, 16, 15], "precipitation_probability_max": [10, 80, 20],
            }})  # fmt: skip
        raise httpx.ConnectError("no simulado: " + url)

    monkeypatch.setattr(info, "_get", get)
    info._cache.clear()
    return calls


@pytest.fixture
def ai(monkeypatch):
    fake = JarvisAI()
    monkeypatch.setattr(jobs, "get_ai_provider", lambda db: fake)
    return fake


def say(text):
    with SessionLocal() as db:
        return assistant.handle(db, Incoming(chat_id=-1, text=text), trusted=True)


# ---------------------------------------------------------------- entender


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Jarvis, recuérdame a las 5 llamar a Juan", "reminder"),
        ("temporizador de 10 minutos", "timer"),
        ("pon un temporizador de cinco minutos", "timer"),
        ("noticias", "news"),
        ("radar de marcas", "radar"),
        ("¿cómo va el canal?", "channel"),
        ("cuántos suscriptores tengo", "channel"),
        ("¿a cómo está el dólar?", "dollar"),
        ("¿va a llover?", "forecast"),
        ("dato curioso", "fact"),
        ("abre YouTube Studio", "open"),
        ("busca la historia de Kodak", "open"),
        ("ponme música lofi", "open"),
        ("estadísticas", "stats"),
        ("mis recordatorios", "reminder_list"),
    ],
)
def test_understands_new_skills(text, action):
    assert quick_intent(text).action == action


def test_reminder_without_time_is_a_task():
    assert quick_intent("recuérdame comprar café").action == "task_add"


def test_parse_when():
    now = datetime(2026, 10, 3, 9, 30)
    cases = {
        "llamar a Juan a las 5": (datetime(2026, 10, 3, 17, 0), "llamar a Juan"),
        "en 20 minutos sacar el pollo": (now + timedelta(minutes=20), "sacar el pollo"),
        "a las 5:30 de la tarde revisar": (datetime(2026, 10, 3, 17, 30), "revisar"),
        "mañana a las 8 subir el vídeo": (datetime(2026, 10, 4, 8, 0), "subir el vídeo"),
        "a las 8 de la mañana correr": (datetime(2026, 10, 4, 8, 0), "correr"),
        "en una hora descansar": (now + timedelta(hours=1), "descansar"),
        "a las 3 y media pagar": (datetime(2026, 10, 3, 15, 30), "pagar"),
        "a mediodía almorzar": (datetime(2026, 10, 3, 12, 0), "almorzar"),
    }
    for text, expected in cases.items():
        assert agenda.parse_when(text, now) == expected, text
    assert agenda.parse_when("sin hora", now) == (None, "sin hora")


# ---------------------------------------------------------------- recordatorios


def test_reminders_fire_on_screen_and_telegram(logged_in, ai):
    create_channel(logged_in)
    reply = say("recuérdame en 10 minutos sacar el pollo")[0]
    assert "sacar el pollo" in reply.text and "en 10 minutos" in reply.text
    assert reply.buttons[0][0][1].startswith("unremind:")
    say("temporizador de 5 minutos")
    assert "Recordatorios" in say("mis recordatorios")[0].text

    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=42, text=assistant.link_code(db)))
        later = datetime.now() + timedelta(minutes=11)
        assert assistant.reminder_alerts(db, datetime.now()) == []
        alerts = assistant.reminder_alerts(db, later)
        texts = [a.text for a in alerts]
        assert any("Recordatorio:</b> sacar el pollo" in t for t in texts)
        assert any("Temporizador de 5 minutos terminado" in t for t in texts)
        assert assistant.reminder_alerts(db, later) == []  # una sola vez por Telegram
        # La pantalla los sigue viendo un rato para anunciarlos
        assert len(agenda.fire_due(db, later)) == 2

    data = logged_in.get("/jarvis/hud/datos").json()
    assert data["reminders"] == []  # (ya sonaron con la hora simulada)


def test_cancel_reminder(logged_in):
    reply = say("recuérdame a las 11 de la noche apagar el horno")[0]
    reminder_id = int(reply.buttons[0][0][1].split(":")[1])
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=-1, button=f"unremind:{reminder_id}"), trusted=True)
        assert agenda.reminders(db) == []


# ---------------------------------------------------------------- información


def test_news_and_radar_to_video(logged_in, ai, internet):
    create_channel(logged_in)
    news = say("noticias")[0].text
    assert "Tiendas X cierra 40 locales" in news and "El Tiempo" in news
    assert " - El Tiempo" not in news  # la fuente no se repite en el título

    radar = say("radar")[0]
    assert radar.buttons[0][0] == ("🎬 1", "radar:0")
    with SessionLocal() as db:
        assistant.handle(db, Incoming(chat_id=-1, button="radar:1"), trusted=True)
        assert db.get(assistant.Project, 1).topic == "La marca Y entra en quiebra"


def test_channel_without_key_reads_public_page(logged_in, internet):
    text = say("¿cómo va el canal?")[0].text
    assert "1.200 suscriptores" in text and "120 % de los 1.000" not in text
    assert "La caída de Nokia" in text and "1.534 visitas" in text
    assert "Datos aproximados" in text


def test_channel_with_youtube_key(logged_in, internet):
    with SessionLocal() as db:
        from app.settings_store import save_api_key

        save_api_key(db, "youtube", "AIzaYT")
    text = say("suscriptores")[0].text
    assert "345 suscriptores — 34 % de los 1.000" in text
    assert "12 vídeos" in text and "56.789 visitas" in text and "«Kodak» — 900" in text
    assert "aproximados" not in text


def test_dollar_forecast_and_fact(logged_in, ai, internet):
    assert "4.123,46 pesos colombianos" in say("dólar")[0].text
    assert "Dime tu ciudad" in say("clima")[0].text
    with SessionLocal() as db:
        set_setting(db, "jarvis_city", "Medellín")
    forecast = say("pronóstico")[0].text
    assert "Hoy: casi despejado, entre 17° y 27°" in forecast
    assert "Mañana: con lluvia ligera, entre 16° y 25°, lluvia 80 %" in forecast


def test_fact_of_the_day_once_a_day(logged_in, ai, monkeypatch):
    calls = []
    original = ai.generate_json

    def generate(prompt, schema):
        if schema.__name__ == "Fact":
            calls.append(prompt)
            return schema(fact="Nokia empezó fabricando papel en 1865.")
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", generate)
    assert "fabricando papel" in say("dato curioso")[0].text
    assert "fabricando papel" in say("dato del día")[0].text
    assert len(calls) == 1
    with SessionLocal() as db:
        assert info.fact_of_day(db, datetime(2099, 1, 1), generate=False) == ""


def test_open_pages(logged_in, ai):
    create_channel(logged_in)
    reply = say("abre YouTube Studio")[0]
    assert reply.action == "open:https://studio.youtube.com"
    assert say("busca historia de Kodak")[0].action == (
        "open:https://www.google.com/search?q=historia+de+Kodak"
    )
    assert say("pon música lofi")[0].action.startswith(
        "open:https://www.youtube.com/results?search_query=lofi"
    )
    assert say("abre mi canal")[0].action == "open:https://www.youtube.com/@AnatomiaDeUnaMarca"
    say("hazme un vídeo sobre la caída de Nokia")
    assert say("abre el proyecto de Nokia")[0].action == "open:/proyectos/1"


def test_stats(logged_in):
    text = say("estadísticas")[0].text
    assert "Vídeos montados esta semana: 0" in text


def test_conversation_memory_goes_to_the_ai(logged_in, ai, monkeypatch):
    prompts = []
    original = ai.generate_json

    def spy(prompt, schema):
        prompts.append(prompt)
        return original(prompt, schema)

    monkeypatch.setattr(ai, "generate_json", spy)
    say("háblame de Nokia")
    say("y de su fundador")
    assert "Creador: háblame de Nokia" in prompts[-1]
    assert "JARVIS: A sus órdenes, señor." in prompts[-1]


def test_hud_world(logged_in, internet):
    with SessionLocal() as db:
        set_setting(db, "jarvis_city", "Medellín")
    world = logged_in.get("/jarvis/hud/mundo").json()
    assert world["youtube"]["subscribers"] == 1200
    assert world["news"][0]["source"] == "El Tiempo"
    assert world["radar"] and world["dollar"]["rate"] == 4123.46
    assert world["forecast"][1]["day"] == "Mañana"
    assert world["stats"]["projects"] == 0


def test_offline_world_does_not_break(logged_in):
    world = logged_in.get("/jarvis/hud/mundo").json()
    assert world["youtube"] is None and world["news"] == [] and world["dollar"] is None


def test_count_parser():
    assert skills.number(1234567) == "1.234.567"
    assert info._count("1,2 mil") == 1200
    assert info._count("3.456") == 3456
    assert info._count("1.5M") == 1_500_000
    assert info._count("12 K") == 12000


def test_channel_page_prefers_its_own_id_and_survives_rss_errors(monkeypatch):
    page = (
        '"channelId":"UCotroCanalRecomendado00x"'
        '<link rel="canonical" href="https://www.youtube.com/channel/UCelCanalDeVerdad0000000">'
        '<meta property="og:title" content="Anatomía De Una Marca">'
        '"subscriberCountText":{"simpleText":"312 suscriptores"}'
    )
    assert info.parse_channel_page(page)["id"] == "UCelCanalDeVerdad0000000"

    def get(url, **params):
        if "feeds" in url:
            raise httpx.HTTPStatusError("404", request=None, response=None)
        return Response(page)

    monkeypatch.setattr(info, "_get", get)
    data = info.fetch_youtube_public("@AnatomiaDeUnaMarca")
    assert data["subscribers"] == 312 and data["latest"] == []
